import secrets
import uuid

from authlib.integrations.starlette_client import OAuthError
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import (
    clear_session,
    csrf_token,
    dev_staff_bypass_enabled,
    oauth,
    oidc_configured,
    start_session,
)
from ..assignment_workflow import (
    latest_submission,
    next_attempt,
    start_assignment,
    submit_assignment,
)
from ..notification_service import notify_reviewers
from ..config import BASE_DIR, OIDC_REDIRECT_URI
from ..db import get_db, set_tenant
from ..models import (
    AssessmentStatus,
    Assignment,
    AssignmentStatus,
    Enrollment,
    EnrollmentStatus,
    NotificationEvent,
    Student,
    Submission,
    SubmissionStatus,
    TeamMember,
    Video,
    VideoAssessment,
    VideoStatus,
)
from ..settings_store import get_app_settings
from ..program_workflow import refresh_enrollment

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


from ..video_upload import save_video_upload
from ..workers.pipeline import process_video
def _auth_context(request: Request, **values) -> dict:
    return {"request": request, "csrf_token": csrf_token(request), **values}


def _login_redirect(path: str, error: str) -> RedirectResponse:
    from urllib.parse import urlencode

    return RedirectResponse(f"{path}?{urlencode({'error': error})}", status_code=303)


def _student_assignment_redirect(
    assignment_id: int,
    *,
    error: str | None = None,
    notice: str | None = None,
) -> RedirectResponse:
    from urllib.parse import urlencode

    params = {}
    if error:
        params["error"] = error
    if notice:
        params["notice"] = notice
    suffix = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(f"/student/assignments/{assignment_id}{suffix}", status_code=303)


@router.get("/auth/login")
def staff_login_page(
    request: Request,
    error: str = "",
    db: Session = Depends(get_db),
) -> Response:
    if getattr(request.state, "principal", None) and request.state.principal["kind"] == "staff":
        return RedirectResponse("/app", status_code=303)
    dev_members = []
    if dev_staff_bypass_enabled():
        dev_members = (
            db.query(TeamMember)
            .filter(TeamMember.is_active.is_(True))
            .order_by(TeamMember.name, TeamMember.id)
            .all()
        )
    return templates.TemplateResponse(
        "auth/staff_login.html",
        _auth_context(
            request,
            error=error[:500],
            oidc_configured=oidc_configured(),
            dev_members=dev_members,
        ),
    )


@router.get("/auth/start")
async def staff_login_start(request: Request):
    if not oidc_configured():
        return _login_redirect("/auth/login", "Вход через omra.is ещё не настроен.")
    request.session["oidc_login_kind"] = "staff"
    return await _oidc_redirect(request)


@router.get("/student/auth/start")
async def student_login_start(request: Request):
    if not oidc_configured():
        return _login_redirect("/student/login", "Вход через omra.is ещё не настроен.")
    request.session["oidc_login_kind"] = "student"
    return await _oidc_redirect(request)


async def _oidc_redirect(request: Request):
    nonce = secrets.token_urlsafe(32)
    return await oauth.omra_is.authorize_redirect(
        request,
        OIDC_REDIRECT_URI,
        nonce=nonce,
    )


def _oidc_identity(claims: dict) -> tuple[str, str, uuid.UUID] | None:
    subject = str(claims.get("sub") or "")
    email = str(claims.get("email") or "").strip().lower()
    email_verified = claims.get("email_verified") is True
    org_role = str(claims.get("org_role") or "")
    try:
        org_id = uuid.UUID(str(claims.get("org_id") or ""))
    except ValueError:
        return None
    if (
        not subject
        or not email
        or not email_verified
        or org_role not in {"owner", "admin", "member"}
    ):
        return None
    return subject, email, org_id


@router.get("/auth/callback")
async def login_callback(request: Request, db: Session = Depends(get_db)):
    login_kind = request.session.pop("oidc_login_kind", "staff")
    login_path = "/student/login" if login_kind == "student" else "/auth/login"
    try:
        token = await oauth.omra_is.authorize_access_token(request)
    except OAuthError:
        return _login_redirect(login_path, "Сессия входа истекла. Попробуйте снова.")
    claims = dict(token.get("userinfo") or {})
    if not claims.get("sub") or not claims.get("email"):
        try:
            claims.update(dict(await oauth.omra_is.userinfo(token=token) or {}))
        except Exception:
            return _login_redirect(login_path, "omra.is не вернул данные пользователя.")

    identity = _oidc_identity(claims)
    if identity is None:
        return _login_redirect(login_path, "omra.is не вернул организацию пользователя.")
    subject, email, org_id = identity
    set_tenant(db, org_id)

    if login_kind == "student":
        student = db.query(Student).filter(Student.oidc_sub == subject).first()
        if student is None:
            student = db.query(Student).filter(func.lower(Student.email) == email).first()
            if student is not None and student.oidc_sub not in {None, subject}:
                student = None
        if student is None or student.status.value != "active":
            db.rollback()
            return templates.TemplateResponse(
                "auth/student_denied.html",
                _auth_context(request, email=email),
                status_code=403,
            )
        if student.oidc_sub is None:
            student.oidc_sub = subject
        db.commit()
        start_session(
            request,
            kind="student",
            account_id=student.id,
            org_id=org_id,
        )
        return RedirectResponse("/student", status_code=303)

    member = db.query(TeamMember).filter(TeamMember.oidc_sub == subject).first()
    if member is None:
        member = db.query(TeamMember).filter(func.lower(TeamMember.email) == email).first()
        if member is not None and member.oidc_sub not in {None, subject}:
            member = None
    if member is None or not member.is_active:
        db.rollback()
        return templates.TemplateResponse(
            "auth/staff_denied.html",
            _auth_context(request, email=email),
            status_code=403,
        )
    if member.oidc_sub is None:
        member.oidc_sub = subject
    db.commit()
    start_session(request, kind="staff", account_id=member.id, org_id=org_id)
    return RedirectResponse("/app", status_code=303)


@router.post("/auth/dev")
def staff_dev_login(
    request: Request,
    member_id: int = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if not dev_staff_bypass_enabled():
        raise HTTPException(404, "not found")
    member = db.get(TeamMember, member_id)
    if member is None or not member.is_active:
        return _login_redirect("/auth/login", "Участник команды недоступен.")
    start_session(
        request,
        kind="staff",
        account_id=member.id,
        org_id=member.org_id,
    )
    return RedirectResponse("/app", status_code=303)


@router.post("/auth/logout")
def staff_logout(request: Request) -> RedirectResponse:
    clear_session(request)
    return RedirectResponse("/auth/login", status_code=303)


@router.get("/student/login")
def student_login_page(request: Request, error: str = "") -> Response:
    if getattr(request.state, "principal", None) and request.state.principal["kind"] == "student":
        return RedirectResponse("/student", status_code=303)
    return templates.TemplateResponse(
        "auth/student_login.html",
        _auth_context(
            request,
            error=error[:500],
            oidc_configured=oidc_configured(),
        ),
    )


@router.post("/student/logout")
def student_logout(request: Request) -> RedirectResponse:
    clear_session(request)
    return RedirectResponse("/student/login", status_code=303)


def _owned_assignment(
    request: Request,
    db: Session,
    assignment_id: int,
) -> tuple[Assignment, Submission | None, Video | None]:
    principal = request.state.principal
    assignment = db.get(Assignment, assignment_id)
    if (
        assignment is not None
        and assignment.status == AssignmentStatus.locked
        and assignment.enrollment is not None
    ):
        refresh_enrollment(db, assignment.enrollment)
    if (
        assignment is None
        or assignment.student_id != principal["student_id"]
        or assignment.status == AssignmentStatus.locked
    ):
        raise HTTPException(404, "assignment not found")
    submission = latest_submission(db, assignment.id)
    video = db.get(Video, submission.video_id) if submission is not None else None
    return assignment, submission, video


@router.post("/student/assignments/{assignment_id}/start")
def student_start_assignment(
    assignment_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    assignment, _, _ = _owned_assignment(request, db, assignment_id)
    try:
        start_assignment(assignment)
    except ValueError as exc:
        return _student_assignment_redirect(assignment_id, error=str(exc))
    db.commit()
    return _student_assignment_redirect(assignment_id, notice="Тренировка начата.")


@router.post("/student/assignments/{assignment_id}/upload")
async def student_upload_submission(
    assignment_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    assignment, latest, latest_video = _owned_assignment(request, db, assignment_id)
    if assignment.status in (AssignmentStatus.submitted, AssignmentStatus.completed):
        return _student_assignment_redirect(
            assignment_id,
            error="Текущая попытка уже отправлена тренеру.",
        )
    if latest is not None and latest.status == SubmissionStatus.draft:
        if latest_video is None or latest_video.status != VideoStatus.failed:
            return _student_assignment_redirect(
                assignment_id,
                error="Сначала отправьте уже загруженную попытку.",
            )
        latest.status = SubmissionStatus.revision_requested

    settings = get_app_settings(db)
    destination, original_name = await save_video_upload(file, settings.max_upload_bytes)
    video = Video(filename=str(destination), original_name=original_name)
    try:
        db.add(video)
        db.flush()
        db.add(
            Submission(
                assignment_id=assignment.id,
                video_id=video.id,
                attempt=next_attempt(db, assignment.id),
                status=SubmissionStatus.draft,
            )
        )
        start_assignment(assignment)
        db.commit()
        db.refresh(video)
    except Exception:
        db.rollback()
        destination.unlink(missing_ok=True)
        raise
    background_tasks.add_task(process_video, video.id)
    return _student_assignment_redirect(
        assignment.id,
        notice="Видео загружено и поставлено в очередь на обработку.",
    )


@router.post("/student/assignments/{assignment_id}/submit")
def student_submit_assignment(
    assignment_id: int,
    request: Request,
    student_comment: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    assignment, submission, video = _owned_assignment(request, db, assignment_id)
    if submission is None or video is None or video.status != VideoStatus.done:
        return _student_assignment_redirect(
            assignment_id,
            error="Сначала загрузите и дождитесь обработки видео.",
        )
    try:
        submit_assignment(assignment, submission, student_comment)
    except ValueError as exc:
        return _student_assignment_redirect(assignment_id, error=str(exc))
    principal = request.state.principal
    notify_reviewers(
        db,
        event=NotificationEvent.assignment_submitted,
        title=f"{principal['name']} отправил тренировку",
        body=f"«{assignment.title}» готова к проверке.",
        url=f"/students/{assignment.student_id}",
    )
    db.commit()
    return _student_assignment_redirect(assignment_id, notice="Результат отправлен тренеру.")


@router.get("/student")
def student_dashboard(request: Request, db: Session = Depends(get_db)) -> Response:
    principal = request.state.principal
    student = db.get(Student, principal["student_id"])
    active_enrollments = (
        db.query(Enrollment)
        .filter(
            Enrollment.student_id == student.id,
            Enrollment.status == EnrollmentStatus.active,
        )
        .all()
    )
    for enrollment in active_enrollments:
        refresh_enrollment(db, enrollment)
    if active_enrollments:
        db.commit()
    assignments = (
        db.query(Assignment)
        .filter(Assignment.student_id == student.id)
        .order_by(Assignment.available_at.asc().nullsfirst(), Assignment.created_at, Assignment.id)
        .all()
    )
    history = []
    for assignment in assignments:
        submission = latest_submission(db, assignment.id)
        video = db.get(Video, submission.video_id) if submission is not None else None
        assessment = db.get(VideoAssessment, video.id) if video is not None else None
        final = assessment if assessment and assessment.status == AssessmentStatus.final else None
        scores = []
        if final is not None:
            scores = [
                value
                for value in (
                    final.technique,
                    final.range_of_motion,
                    final.stability,
                    final.tempo,
                    final.symmetry,
                )
                if value is not None
            ]
        history.append(
            {
                "assignment": assignment,
                "submission": submission,
                "video": video,
                "assessment": final,
                "average": round(sum(scores) / len(scores), 1) if scores else None,
                "lesson": assignment.lesson_exercise.lesson
                if assignment.lesson_exercise is not None
                else None,
                "program": assignment.lesson_exercise.lesson.program
                if assignment.lesson_exercise is not None
                else None,
            }
        )
    return templates.TemplateResponse(
        "student/dashboard.html",
        {
            "request": request,
            "student": student,
            "principal": principal,
            "history": history,
            "today_history": [
                item
                for item in history
                if item["assignment"].status
                not in (AssignmentStatus.locked, AssignmentStatus.completed)
            ],
            "next_history": [
                item
                for item in history
                if item["assignment"].status == AssignmentStatus.locked
            ],
            "completed_history": [
                item
                for item in history
                if item["assignment"].status == AssignmentStatus.completed
            ],
            "submitted_count": sum(
                item["assignment"].status.value == "submitted" for item in history
            ),
            "csrf_token": csrf_token(request),
        },
    )


@router.get("/student/assignments/{assignment_id}")
def student_assignment(
    assignment_id: int,
    request: Request,
    error: str = "",
    notice: str = "",
    db: Session = Depends(get_db),
) -> Response:
    assignment, submission, video = _owned_assignment(request, db, assignment_id)
    if (
        assignment.status == AssignmentStatus.revision_requested
        or video is None
        or video.status != VideoStatus.done
    ):
        return templates.TemplateResponse(
            "student/assignment.html",
            {
                "request": request,
                "assignment": assignment,
                "submission": submission,
                "video": video,
                "csrf_token": csrf_token(request),
                "error": error[:500],
                "notice": notice[:500],
            },
        )
    assessment = db.get(VideoAssessment, video.id)
    final = assessment if assessment and assessment.status == AssessmentStatus.final else None
    scores = []
    if final is not None:
        scores = [
            value
            for value in (
                final.technique,
                final.range_of_motion,
                final.stability,
                final.tempo,
                final.symmetry,
            )
            if value is not None
        ]
    return templates.TemplateResponse(
        "watch.html",
        {
            "request": request,
            "video": video,
            "assignment": assignment,
            "submission": submission,
            "api_base": f"/api/student/videos/{video.id}",
            "is_preview": False,
            "student_portal": True,
            "public_url": None,
            "show_skeleton": get_app_settings(db).show_skeleton,
            "coach_assessment": final,
            "assessment_average": round(sum(scores) / len(scores), 1) if scores else None,
            "csrf_token": csrf_token(request),
            "error": error[:500],
            "notice": notice[:500],
        },
    )
