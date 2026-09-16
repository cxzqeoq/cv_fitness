import hashlib
import hmac
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.crm_integration import (
    drain_crm_outbox_once,
    enqueue_crm_message,
    valid_webhook_signature,
)
from app.db import Base, TenantSession, set_tenant
from app.models import (
    Assignment,
    AssignmentStatus,
    CrmInboundEvent,
    CrmOrganizationBinding,
    CrmOutboxEvent,
    CrmOutboxStatus,
    Student,
    Submission,
)
from app.routers.crm import router


class _StreamResponse:
    headers = {"content-type": "video/mp4"}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def raise_for_status(self):
        return None

    async def aiter_bytes(self):
        yield b"video"

class _HttpClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def stream(self, *_args, **_kwargs):
        return _StreamResponse()


class CrmIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, class_=TenantSession)
        self.org_id = uuid.uuid4()

    def tearDown(self):
        self.engine.dispose()

    def test_signature_covers_raw_body(self):
        body = b'{"event":"message.in"}'
        secret = "webhook-secret"
        signature = "sha256=" + hmac.new(
            secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()

        with patch("app.crm_integration.CRM_WEBHOOK_SECRET", secret):
            self.assertTrue(valid_webhook_signature(body, signature))
            self.assertFalse(valid_webhook_signature(body + b" ", signature))

    def test_repeated_video_webhook_creates_one_submission(self):
        db = self.sessions()
        set_tenant(db, self.org_id)
        binding = CrmOrganizationBinding(crm_company_id=71, api_key="company-key")
        student = Student(name="Messenger Student", crm_lead_id=501)
        db.add_all([binding, student])
        db.flush()
        assignment = Assignment(
            student_id=student.id,
            title="Приседания",
            status=AssignmentStatus.assigned,
        )
        db.add(assignment)
        db.flush()
        assignment_id = assignment.id
        db.commit()
        db.close()

        app = FastAPI()
        app.include_router(router)
        payload = {
            "event": "message.in",
            "company_id": 71,
            "data": {
                "message_id": "mongo-message-1",
                "lead_id": 501,
                "attachment": {
                    "ref": "message:mongo-message-1",
                    "kind": "video",
                    "download_url": "/api/v1/external/attachments/mongo-message-1",
                },
            },
        }
        destination = Path(tempfile.mkstemp(suffix=".mp4")[1])
        try:
            with (
                patch("app.routers.crm.SessionLocal", self.sessions),
                patch("app.routers.crm.valid_webhook_signature", return_value=True),
                patch("app.routers.crm.CRM_BASE_URL", "http://crm"),
                patch("app.routers.crm.httpx.AsyncClient", return_value=_HttpClient()),
                patch(
                    "app.routers.crm.save_video_chunks",
                    new=AsyncMock(return_value=(destination, "attempt.mp4")),
                ),
                patch("app.routers.crm.process_video") as process_video,
            ):
                client = TestClient(app)
                first = client.post(
                    "/api/integrations/crm/webhook",
                    json=payload,
                    headers={"X-Webhook-Signature": "valid"},
                )
                second = client.post(
                    "/api/integrations/crm/webhook",
                    json=payload,
                    headers={"X-Webhook-Signature": "valid"},
                )

            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.json(), {"ok": True, "duplicate": True})
            db = self.sessions()
            set_tenant(db, self.org_id)
            self.assertEqual(db.query(CrmInboundEvent).count(), 1)
            self.assertEqual(db.query(Submission).count(), 1)
            self.assertEqual(
                db.get(Assignment, assignment_id).status,
                AssignmentStatus.submitted,
            )
            db.close()
            process_video.assert_called_once()
        finally:
            destination.unlink(missing_ok=True)

    def test_outbox_retries_without_losing_event(self):
        db = self.sessions()
        set_tenant(db, self.org_id)
        binding = CrmOrganizationBinding(crm_company_id=71, api_key="company-key")
        student = Student(name="Messenger Student", crm_lead_id=501)
        db.add_all([binding, student])
        db.flush()
        enqueue_crm_message(
            db,
            org_id=self.org_id,
            crm_lead_id=student.crm_lead_id,
            student_id=student.id,
            event_type="assignment.created",
            event_key="assignment.created:1",
            text="Новая тренировка",
        )
        db.commit()
        db.close()

        failed = Mock(side_effect=RuntimeError("CRM unavailable"))
        with (
            patch("app.crm_integration.SessionLocal", self.sessions),
            patch("app.crm_integration.CRM_BASE_URL", "http://crm"),
            patch("app.crm_integration.httpx.post", failed),
        ):
            self.assertEqual(drain_crm_outbox_once(), 0)

        db = self.sessions()
        set_tenant(db, self.org_id)
        event = db.query(CrmOutboxEvent).one()
        self.assertEqual(event.status, CrmOutboxStatus.pending)
        self.assertEqual(event.attempts, 1)
        event.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
        db.close()

        response = Mock()
        response.raise_for_status.return_value = None
        with (
            patch("app.crm_integration.SessionLocal", self.sessions),
            patch("app.crm_integration.CRM_BASE_URL", "http://crm"),
            patch("app.crm_integration.httpx.post", return_value=response) as post,
        ):
            self.assertEqual(drain_crm_outbox_once(), 1)

        db = self.sessions()
        set_tenant(db, self.org_id)
        event = db.query(CrmOutboxEvent).one()
        self.assertEqual(event.status, CrmOutboxStatus.delivered)
        self.assertEqual(event.attempts, 2)
        db.close()
        self.assertEqual(
            post.call_args.kwargs["headers"]["Idempotency-Key"],
            f"fitness:{self.org_id}:assignment.created:1",
        )


if __name__ == "__main__":
    unittest.main()
