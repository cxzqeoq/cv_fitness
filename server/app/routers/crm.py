import json
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from sqlalchemy.exc import IntegrityError

from ..assignment_workflow import next_attempt
from ..config import CRM_BASE_URL
from ..crm_integration import (
    enqueue_crm_message,
    expected_video_assignments,
    valid_webhook_signature,
)
from ..db import SessionLocal, set_tenant
from ..models import (
    AssignmentStatus,
    CrmInboundEvent,
    CrmInboxStatus,
    CrmOrganizationBinding,
    Student,
    Submission,
    SubmissionStatus,
    Video,
)
from ..settings_store import get_app_settings
from ..video_upload import save_video_chunks
from ..workers.pipeline import process_video


router = APIRouter(prefix="/api/integrations/crm", tags=["crm-integration"])


def _video_name(message_id: str, content_type: str) -> str:
    extensions = {
        "video/mp4": ".mp4",
        "video/quicktime": ".mov",
        "video/webm": ".webm",
        "video/x-m4v": ".m4v",
    }
    return f"crm-{message_id}{extensions.get(content_type.split(';', 1)[0].lower(), '.mp4')}"


@router.post("/webhook")
async def receive_crm_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_webhook_signature: str = Header(default="", alias="X-Webhook-Signature"),
):
    body = await request.body()
    if not valid_webhook_signature(body, x_webhook_signature):
        raise HTTPException(401, "Invalid webhook signature")
    try:
        envelope = json.loads(body)
        event_type = str(envelope["event"])
        crm_company_id = int(envelope["company_id"])
        data = envelope["data"]
        message_id = str(data["message_id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise HTTPException(422, "Invalid CRM event") from None
    if not isinstance(data, dict):
        raise HTTPException(422, "Invalid CRM event data")

    db = SessionLocal()
    destination = None
    try:
        binding = (
            db.query(CrmOrganizationBinding)
            .filter(CrmOrganizationBinding.crm_company_id == crm_company_id)
            .first()
        )
        if binding is None:
            raise HTTPException(404, "CRM organization binding not found")
        set_tenant(db, binding.org_id)

        source_event_key = f"{event_type}:{message_id}"
        inbound = CrmInboundEvent(
            source_event_key=source_event_key,
            event_type=event_type,
            crm_lead_id=None,
            payload=envelope,
            status=CrmInboxStatus.ignored,
        )
        db.add(inbound)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            return {"ok": True, "duplicate": True}

        if event_type != "message.in":
            db.commit()
            return {"ok": True, "ignored": True}

        try:
            crm_lead_id = int(data["lead_id"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(422, "message.in requires lead_id") from None
        inbound.crm_lead_id = crm_lead_id
        attachment = data.get("attachment")
        if not isinstance(attachment, dict) or attachment.get("kind") != "video":
            db.commit()
            return {"ok": True, "ignored": True}

        student = (
            db.query(Student)
            .filter(Student.crm_lead_id == crm_lead_id)
            .one_or_none()
        )
        if student is None:
            enqueue_crm_message(
                db,
                org_id=binding.org_id,
                crm_lead_id=crm_lead_id,
                student_id=None,
                event_type="inbound.unmatched_student",
                event_key=f"inbound.unmatched_student:{message_id}",
                text="Профиль ученика не связан с этим чатом. Обратитесь к тренеру.",
            )
            db.commit()
            return {"ok": True, "matched": False}

        assignments = expected_video_assignments(db, student.id)
        if len(assignments) != 1:
            if assignments:
                choices = ", ".join(
                    f"#{assignment.id} «{assignment.title}»"
                    for assignment in assignments
                )
                text = (
                    "Ожидается видео по нескольким заданиям: "
                    f"{choices}. Откройте нужное задание и загрузите видео там."
                )
            else:
                text = "Сейчас нет задания, которое ожидает видео. Обратитесь к тренеру."
            enqueue_crm_message(
                db,
                org_id=binding.org_id,
                crm_lead_id=crm_lead_id,
                student_id=student.id,
                event_type="inbound.assignment_ambiguous",
                event_key=f"inbound.assignment_ambiguous:{message_id}",
                text=text,
            )
            db.commit()
            return {"ok": True, "matched": False, "assignments": len(assignments)}

        expected_ref = f"message:{message_id}"
        expected_download_url = f"/api/v1/external/attachments/{message_id}"
        if (
            attachment.get("ref") != expected_ref
            or attachment.get("download_url") != expected_download_url
        ):
            raise HTTPException(422, "Invalid attachment reference")
        download_url = expected_download_url
        if not CRM_BASE_URL:
            raise HTTPException(503, "CRM_BASE_URL is not configured")
        settings = get_app_settings(db)
        async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
            async with client.stream(
                "GET",
                f"{CRM_BASE_URL}{download_url}",
                headers={"X-Api-Key": binding.api_key},
            ) as response:
                response.raise_for_status()
                original_name = _video_name(
                    message_id,
                    response.headers.get("content-type", "video/mp4"),
                )
                destination, original_name = await save_video_chunks(
                    response.aiter_bytes(),
                    original_name,
                    settings.max_upload_bytes,
                )

        assignment = assignments[0]
        attempt = next_attempt(db, assignment.id)
        moment = datetime.now(timezone.utc)
        video = Video(filename=str(destination), original_name=original_name)
        db.add(video)
        db.flush()
        db.add(
            Submission(
                assignment_id=assignment.id,
                video_id=video.id,
                attempt=attempt,
                status=SubmissionStatus.submitted,
                submitted_at=moment,
            )
        )
        assignment.status = AssignmentStatus.submitted
        assignment.started_at = assignment.started_at or moment
        inbound.status = CrmInboxStatus.processed
        db.commit()
        background_tasks.add_task(process_video, video.id)
        return {
            "ok": True,
            "assignment_id": assignment.id,
            "video_id": video.id,
        }
    except HTTPException:
        db.rollback()
        if destination is not None:
            destination.unlink(missing_ok=True)
        raise
    except httpx.HTTPError as exc:
        db.rollback()
        if destination is not None:
            destination.unlink(missing_ok=True)
        raise HTTPException(502, "Unable to fetch CRM attachment") from exc
    except Exception:
        db.rollback()
        if destination is not None:
            destination.unlink(missing_ok=True)
        raise
    finally:
        db.close()
