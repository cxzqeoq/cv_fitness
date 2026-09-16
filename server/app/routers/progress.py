from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..auth import csrf_token
from ..config import BASE_DIR
from ..db import get_db
from ..models import Student
from ..progress import build_progress_report


router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


def _filters(period: str, exercise: str) -> tuple[str, str]:
    return period.strip()[:20], exercise.strip()[:200]


@router.get("/students/{student_id}/progress")
def trainer_progress(
    student_id: int,
    request: Request,
    period: str = "180",
    exercise: str = "",
    db: Session = Depends(get_db),
) -> Response:
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(404, "student not found")
    clean_period, clean_exercise = _filters(period, exercise)
    return templates.TemplateResponse(
        "admin/student_progress.html",
        {
            "request": request,
            "active": "students",
            "student": student,
            "report": build_progress_report(
                db,
                student_id=student.id,
                period=clean_period,
                exercise=clean_exercise,
            ),
        },
    )


@router.get("/student/progress")
def student_progress(
    request: Request,
    period: str = "180",
    exercise: str = "",
    db: Session = Depends(get_db),
) -> Response:
    principal = request.state.principal
    student = db.get(Student, principal["student_id"])
    if student is None:
        raise HTTPException(404, "student not found")
    clean_period, clean_exercise = _filters(period, exercise)
    return templates.TemplateResponse(
        "student/progress.html",
        {
            "request": request,
            "principal": principal,
            "student": student,
            "report": build_progress_report(
                db,
                student_id=student.id,
                period=clean_period,
                exercise=clean_exercise,
            ),
            "csrf_token": csrf_token(request),
        },
    )
