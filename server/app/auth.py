import hmac
import secrets
import uuid
from datetime import datetime, timezone
from urllib.parse import parse_qs

from authlib.integrations.starlette_client import OAuth
from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import (
    DEV_STAFF_BYPASS,
    ENVIRONMENT,
    OIDC_CLIENT_ID,
    OIDC_CLIENT_SECRET,
    OIDC_REDIRECT_URI,
    OMRA_IS_INTERNAL_URL,
    OMRA_IS_ISSUER,
)
from .db import SessionLocal, set_tenant
from .models import (
    AuditEvent,
    NotificationRecipient,
    Student,
    TeamMember,
    TeamRole,
)
from .notification_service import unread_count

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
STAFF_ROLES = frozenset(role.value for role in TeamRole)


def _oidc_metadata(issuer: str, internal: str) -> dict:
    public = issuer.rstrip("/")
    server = (internal or issuer).rstrip("/")
    return {
        "issuer": public,
        "authorization_endpoint": f"{public}/oauth/authorize",
        "token_endpoint": f"{server}/oauth/token",
        "jwks_uri": f"{server}/jwks.json",
        "userinfo_endpoint": f"{server}/oauth/userinfo",
        "id_token_signing_alg_values_supported": ["EdDSA"],
    }


oauth = OAuth()
oauth.register(
    name="omra_is",
    client_id=OIDC_CLIENT_ID,
    client_secret=OIDC_CLIENT_SECRET,
    client_kwargs={"scope": "openid profile email", "code_challenge_method": "S256"},
    **_oidc_metadata(OMRA_IS_ISSUER, OMRA_IS_INTERNAL_URL),
)




def csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def start_session(
    request: Request,
    *,
    kind: str,
    account_id: int,
    org_id: uuid.UUID | str,
) -> None:
    request.session.clear()
    request.session["principal"] = {
        "kind": kind,
        "account_id": account_id,
        "org_id": str(org_id),
    }
    request.session["csrf_token"] = secrets.token_urlsafe(32)


def clear_session(request: Request) -> None:
    request.session.clear()


def oidc_configured() -> bool:
    return bool(OIDC_CLIENT_ID and OIDC_CLIENT_SECRET and OIDC_REDIRECT_URI)


def dev_staff_bypass_enabled() -> bool:
    return ENVIRONMENT == "dev" and DEV_STAFF_BYPASS


def _required_roles(path: str, method: str) -> frozenset[str]:
    if path.startswith("/team") or path.startswith("/settings"):
        return frozenset({TeamRole.owner.value})
    if path.startswith("/students") or path.startswith("/assessments"):
        return frozenset({TeamRole.owner.value, TeamRole.manager.value})
    if path.startswith("/programs") and method not in SAFE_METHODS and (
        path.endswith("/enroll") or path.endswith("/archive")
    ):
        return frozenset({TeamRole.owner.value, TeamRole.manager.value})
    if method not in SAFE_METHODS and (
        path.endswith("/delete") or path.endswith("/publish") or path.endswith("/unpublish")
    ):
        if path.endswith("/delete"):
            return frozenset({TeamRole.owner.value})
        return frozenset({TeamRole.owner.value, TeamRole.manager.value})
    return STAFF_ROLES


def staff_access_allowed(path: str, method: str, role: str) -> bool:
    return role in _required_roles(path, method)


def _is_public(path: str) -> bool:
    return (
        path == "/auth/login"
        or path == "/auth/start"
        or path == "/auth/callback"
        or path == "/auth/dev"
        or path == "/student/login"
        or path == "/student/auth/start"
        or path.startswith("/watch/")
        or path.startswith("/api/public/")
        or path.startswith("/static/")
    )


def _is_student_area(path: str) -> bool:
    return path == "/student" or path.startswith("/student/") or path.startswith("/api/student/")


def _unauthorized(path: str, login_path: str):
    if path.startswith("/api/"):
        return JSONResponse({"detail": "authentication required"}, status_code=401)
    return RedirectResponse(login_path, status_code=303)


def _forbidden(path: str):
    if path.startswith("/api/"):
        return JSONResponse({"detail": "forbidden"}, status_code=403)
    return HTMLResponse(
        "<h1>Недостаточно прав</h1><p>Обратитесь к владельцу команды.</p>",
        status_code=403,
    )


def _csrf_from_body(body: bytes, content_type: str) -> str:
    if content_type.startswith("application/x-www-form-urlencoded"):
        values = parse_qs(body.decode("utf-8", errors="replace")).get("csrf_token", [])
        return values[0] if values else ""
    if content_type.startswith("multipart/form-data"):
        marker = b'name="csrf_token"'
        start = body.find(marker)
        if start < 0:
            return ""
        value_start = body.find(b"\r\n\r\n", start)
        if value_start < 0:
            return ""
        value_end = body.find(b"\r\n", value_start + 4)
        if value_end < 0:
            return ""
        return body[value_start + 4 : value_end].decode("ascii", errors="ignore")
    return ""

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        token = csrf_token(request)
        request.state.csrf_token = token
        path = request.url.path
        principal = (
            self._resolve_principal(request)
            if request.session.get("principal")
            else None
        )

        if not _is_public(path):
            if _is_student_area(path):
                if principal is None or principal["kind"] != "student":
                    return _unauthorized(path, "/student/login")
            else:
                if principal is None or principal["kind"] != "staff":
                    return _unauthorized(path, "/auth/login")
                if not staff_access_allowed(path, request.method, principal["role"]):
                    return _forbidden(path)
        request.state.principal = principal

        if request.method not in SAFE_METHODS:
            submitted = request.headers.get("X-CSRF-Token", "")
            if not submitted:
                body = await request.body()
                submitted = _csrf_from_body(body, request.headers.get("content-type", ""))
            if not submitted or not hmac.compare_digest(token, submitted):
                return JSONResponse({"detail": "invalid CSRF token"}, status_code=403)

        response = await call_next(request)
        if not response.headers.get("Cache-Control") and not path.startswith("/static/"):
            response.headers["Cache-Control"] = "private, no-store"
        audit_principal = (
            self._resolve_principal(request)
            if request.session.get("principal")
            else principal
        )
        if audit_principal is not None and request.method not in SAFE_METHODS:
            self._audit(audit_principal, request, response.status_code)
        return response

    @staticmethod
    def _resolve_principal(request: Request) -> dict | None:
        stored = request.session.get("principal")
        if not isinstance(stored, dict):
            return None
        kind = stored.get("kind")
        account_id = stored.get("account_id")
        try:
            org_id = uuid.UUID(str(stored.get("org_id") or ""))
        except ValueError:
            request.session.pop("principal", None)
            return None
        if not isinstance(account_id, int):
            request.session.pop("principal", None)
            return None
        db = SessionLocal()
        set_tenant(db, org_id)
        try:
            if kind == "staff":
                member = db.get(TeamMember, account_id)
                if member is None or not member.is_active:
                    request.session.pop("principal", None)
                    return None
                return {
                    "kind": "staff",
                    "id": member.id,
                    "org_id": str(member.org_id),
                    "name": member.name,
                    "email": member.email,
                    "role": member.role.value,
                    "unread_notifications": unread_count(
                        db,
                        recipient_kind=NotificationRecipient.staff,
                        recipient_id=member.id,
                    ),
                }
            if kind == "student":
                student = db.get(Student, account_id)
                if student is None or student.status.value != "active":
                    request.session.pop("principal", None)
                    return None
                return {
                    "kind": "student",
                    "id": student.id,
                    "student_id": student.id,
                    "org_id": str(student.org_id),
                    "name": student.name,
                    "email": student.email,
                    "role": "student",
                    "unread_notifications": unread_count(
                        db,
                        recipient_kind=NotificationRecipient.student,
                        recipient_id=student.id,
                    ),
                }
        finally:
            db.close()
        request.session.pop("principal", None)
        return None

    @staticmethod
    def _audit(principal: dict, request: Request, status_code: int) -> None:
        db = SessionLocal()
        set_tenant(db, principal["org_id"])
        try:
            db.add(
                AuditEvent(
                    actor_kind=principal["kind"],
                    actor_id=str(principal["id"]),
                    action=request.method,
                    path=request.url.path,
                    status_code=status_code,
                    details={"role": principal["role"]},
                    created_at=datetime.now(timezone.utc),
                )
            )
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
