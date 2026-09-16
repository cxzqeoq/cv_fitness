import hashlib
import hmac
import time
from datetime import datetime, timedelta, timezone
from threading import Event

import httpx
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .config import CRM_BASE_URL, CRM_WEBHOOK_SECRET, PUBLIC_BASE_URL
from .db import SessionLocal, set_tenant
from .models import (
    Assignment,
    AssignmentStatus,
    CrmOrganizationBinding,
    CrmOutboxEvent,
    CrmOutboxStatus,
    Student,
    Submission,
    SubmissionStatus,
)


OUTBOX_POLL_SECONDS = 5


def valid_webhook_signature(body: bytes, supplied: str) -> bool:
    if not CRM_WEBHOOK_SECRET or not supplied:
        return False
    expected = hmac.new(
        CRM_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    value = supplied.removeprefix("sha256=")
    return hmac.compare_digest(expected, value)


def enqueue_crm_message(
    db: Session,
    *,
    org_id,
    crm_lead_id: int | None,
    student_id: int | None,
    event_type: str,
    event_key: str,
    text: str,
) -> CrmOutboxEvent | None:
    if crm_lead_id is None:
        return None
    idempotency_key = f"fitness:{org_id}:{event_key}"
    existing = (
        db.query(CrmOutboxEvent)
        .filter(CrmOutboxEvent.idempotency_key == idempotency_key)
        .first()
    )
    if existing is not None:
        return existing
    event = CrmOutboxEvent(
        org_id=org_id,
        student_id=student_id,
        crm_lead_id=crm_lead_id,
        event_type=event_type,
        idempotency_key=idempotency_key,
        text=text,
        status=CrmOutboxStatus.pending,
        attempts=0,
    )
    db.add(event)
    return event


def enqueue_assignment_message(db: Session, assignment: Assignment) -> CrmOutboxEvent | None:
    student = db.get(Student, assignment.student_id)
    if student is None:
        return None
    url = f"{PUBLIC_BASE_URL}/student/assignments/{assignment.id}"
    return enqueue_crm_message(
        db,
        org_id=assignment.org_id,
        crm_lead_id=student.crm_lead_id,
        student_id=student.id,
        event_type="assignment.created",
        event_key=f"assignment.created:{assignment.id}",
        text=f"Новая тренировка: «{assignment.title}». Открыть задание: {url}",
    )


def expected_video_assignments(db: Session, student_id: int) -> list[Assignment]:
    assignments = (
        db.query(Assignment)
        .filter(
            Assignment.student_id == student_id,
            Assignment.status.in_([
                AssignmentStatus.assigned,
                AssignmentStatus.in_progress,
                AssignmentStatus.revision_requested,
            ]),
        )
        .order_by(Assignment.due_at.asc().nullslast(), Assignment.id)
        .all()
    )
    expected = []
    for assignment in assignments:
        latest = (
            db.query(Submission)
            .filter(Submission.assignment_id == assignment.id)
            .order_by(Submission.attempt.desc())
            .first()
        )
        if latest is None or (
            assignment.status == AssignmentStatus.revision_requested
            and latest.status == SubmissionStatus.revision_requested
        ):
            expected.append(assignment)
    return expected


def _deliver_outbox_event(db: Session, event: CrmOutboxEvent) -> None:
    binding = (
        db.query(CrmOrganizationBinding)
        .filter(CrmOrganizationBinding.org_id == event.org_id)
        .first()
    )
    if binding is None:
        raise RuntimeError("CRM organization binding is missing")
    if not CRM_BASE_URL:
        raise RuntimeError("CRM_BASE_URL is not configured")
    response = httpx.post(
        f"{CRM_BASE_URL}/api/v1/external/leads/{event.crm_lead_id}/messages",
        json={"text": event.text},
        headers={
            "X-Api-Key": binding.api_key,
            "Idempotency-Key": event.idempotency_key,
        },
        timeout=20,
    )
    response.raise_for_status()


def drain_crm_outbox_once(*, limit: int = 20) -> int:
    db = SessionLocal()
    delivered = 0
    try:
        now = datetime.now(timezone.utc)
        events = (
            db.query(CrmOutboxEvent)
            .filter(
                CrmOutboxEvent.status == CrmOutboxStatus.pending,
                or_(
                    CrmOutboxEvent.next_attempt_at.is_(None),
                    CrmOutboxEvent.next_attempt_at <= now,
                ),
            )
            .order_by(CrmOutboxEvent.created_at, CrmOutboxEvent.id)
            .limit(limit)
            .all()
        )
        for event in events:
            set_tenant(db, event.org_id)
            event.attempts += 1
            try:
                _deliver_outbox_event(db, event)
            except Exception as exc:  # noqa: BLE001 - persist transport failures for retry
                event.last_error = str(exc)[:2000]
                delay = min(300, 5 * (2 ** min(event.attempts - 1, 6)))
                event.next_attempt_at = now + timedelta(seconds=delay)
            else:
                event.status = CrmOutboxStatus.delivered
                event.delivered_at = now
                event.next_attempt_at = None
                event.last_error = None
                delivered += 1
            db.commit()
            db.info.pop("org_id", None)
        return delivered
    finally:
        db.close()


def run_crm_outbox_worker(stop: Event | None = None) -> None:
    stop = stop or Event()
    while not stop.is_set():
        try:
            drain_crm_outbox_once()
        except Exception:  # noqa: BLE001 - one broken row must not stop future delivery
            time.sleep(OUTBOX_POLL_SECONDS)
            continue
        stop.wait(OUTBOX_POLL_SECONDS)
