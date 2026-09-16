import os
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..config import BASE_DIR, STORAGE_DIR
from ..db import get_db
from ..models import Video, VideoPublication
from ..settings_store import get_app_settings

router = APIRouter(prefix="/settings")
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


def _redirect(*, error: str | None = None, notice: str | None = None) -> RedirectResponse:
    params = {}
    if error:
        params["error"] = error
    if notice:
        params["notice"] = notice
    suffix = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(url=f"/settings{suffix}", status_code=303)


def _storage_bytes(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return total


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if value < 1024 or unit == "ТБ":
            return f"{value:.1f} {unit}" if unit != "Б" else f"{int(value)} {unit}"
        value /= 1024
    return f"{size} Б"


def _openrouter_model() -> str | None:
    dsn = os.environ.get("OPENROUTER_DSN", "")
    if not dsn.startswith("openai://") or "@openrouter.ai/api/v1/" not in dsn:
        return None
    return dsn.split("@openrouter.ai/api/v1/", 1)[1]


@router.get("")
def settings_page(
    request: Request,
    error: str = "",
    notice: str = "",
    db: Session = Depends(get_db),
) -> Response:
    settings = get_app_settings(db)
    return templates.TemplateResponse(
        "admin/settings.html",
        {
            "request": request,
            "active": "settings",
            "settings": settings,
            "max_upload_gb": settings.max_upload_bytes / 1024**3,
            "storage_size": _human_size(_storage_bytes(STORAGE_DIR)),
            "video_count": db.query(Video).count(),
            "publication_count": db.query(VideoPublication).count(),
            "ai_model": _openrouter_model(),
            "error": error[:500],
            "notice": notice[:500],
        },
    )


@router.post("")
def update_settings(
    max_upload_gb: float = Form(...),
    target_sample_fps: int = Form(...),
    pose_model_complexity: int = Form(...),
    ai_prompt: str = Form(""),
    show_skeleton: str | None = Form(None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    prompt = ai_prompt.strip()
    if not 0.1 <= max_upload_gb <= 50:
        return _redirect(error="Лимит загрузки должен быть от 0,1 до 50 ГБ.")
    if not 4 <= target_sample_fps <= 30:
        return _redirect(error="Частота анализа должна быть от 4 до 30 кадров в секунду.")
    if pose_model_complexity not in (0, 1, 2):
        return _redirect(error="Выберите допустимую точность модели.")
    if not 20 <= len(prompt) <= 2000:
        return _redirect(error="Инструкция для AI должна содержать от 20 до 2000 символов.")

    settings = get_app_settings(db)
    settings.max_upload_bytes = round(max_upload_gb * 1024**3)
    settings.target_sample_fps = target_sample_fps
    settings.pose_model_complexity = pose_model_complexity
    settings.ai_prompt = prompt
    settings.show_skeleton = show_skeleton == "on"
    db.commit()
    return _redirect(notice="Настройки сохранены.")
