import re
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Form, Request
from fastapi.responses import PlainTextResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from ..config import (
    BASE_DIR,
    CRM_BASE_URL,
    CRM_PILOT_API_KEY,
    PUBLIC_BASE_URL,
)


router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _landing_redirect(*, sent: bool = False, error: str | None = None) -> RedirectResponse:
    params = {}
    if sent:
        params["pilot"] = "sent"
    if error:
        params["error"] = error
    suffix = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(url=f"/{suffix}#pilot", status_code=303)


@router.get("/")
def landing(
    request: Request,
    pilot: str = "",
    error: str = "",
) -> Response:
    return templates.TemplateResponse(
        "landing.html",
        {
            "request": request,
            "canonical_url": f"{PUBLIC_BASE_URL}/",
            "pilot_sent": pilot == "sent",
            "error": error[:500],
        },
    )


@router.post("/pilot")
async def request_pilot(
    name: str = Form(""),
    school: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    messenger: str = Form("telegram"),
    consent: str | None = Form(None),
) -> RedirectResponse:
    clean_name = name.strip()
    clean_school = school.strip()
    clean_phone = phone.strip()
    clean_email = email.strip().lower()
    if not clean_name or len(clean_name) > 120:
        return _landing_redirect(error="Укажите имя до 120 символов.")
    if len(clean_school) > 200:
        return _landing_redirect(error="Название школы должно быть короче 200 символов.")
    if not clean_phone and not clean_email:
        return _landing_redirect(error="Укажите телефон или email для связи.")
    if clean_email and (len(clean_email) > 320 or not _EMAIL_RE.fullmatch(clean_email)):
        return _landing_redirect(error="Проверьте email.")
    if len(clean_phone) > 50:
        return _landing_redirect(error="Телефон должен быть короче 50 символов.")
    if messenger not in {"telegram", "whatsapp"}:
        return _landing_redirect(error="Выберите Telegram или WhatsApp.")
    if consent != "on":
        return _landing_redirect(error="Нужно согласие на обработку заявки.")
    if not CRM_BASE_URL or not CRM_PILOT_API_KEY:
        return _landing_redirect(error="Приём заявок временно недоступен. Напишите нам позже.")

    note_parts = ["Заявка на пилот OMRA Fitness", f"Предпочтительный канал: {messenger}"]
    if clean_school:
        note_parts.append(f"Школа или команда: {clean_school}")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{CRM_BASE_URL}/api/v1/external/order",
                headers={"X-Api-Key": CRM_PILOT_API_KEY},
                json={
                    "contact": {
                        "name": clean_name,
                        "phone": clean_phone or None,
                        "email": clean_email or None,
                    },
                    "title": "Пилот OMRA Fitness",
                    "source": "omra.fitness",
                    "note": "\n".join(note_parts),
                },
            )
            response.raise_for_status()
    except httpx.HTTPError:
        return _landing_redirect(error="Не удалось отправить заявку. Попробуйте ещё раз позже.")
    return _landing_redirect(sent=True)


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots() -> str:
    return f"User-agent: *\nAllow: /\nDisallow: /app\nSitemap: {PUBLIC_BASE_URL}/sitemap.xml\n"


@router.get("/sitemap.xml")
def sitemap() -> Response:
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{PUBLIC_BASE_URL}/</loc></url>"
        "</urlset>"
    )
    return Response(body, media_type="application/xml")
