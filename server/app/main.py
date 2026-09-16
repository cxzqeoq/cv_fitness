from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from threading import Thread

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .auth import AuthMiddleware
from .config import BASE_DIR, ENVIRONMENT, SESSION_SECRET
from .crm_integration import run_crm_outbox_worker
from .routers import (
    admin,
    api,
    assessments,
    crm,
    auth,
    exercises,
    notifications,
    programs,
    progress,
    settings,
    students,
    team,
)
from .workers.pipeline import resume_interrupted_processing

if ENVIRONMENT != "dev" and SESSION_SECRET == "change-me":
    raise RuntimeError("SESSION_SECRET must be configured outside development")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    recovery = Thread(
        target=resume_interrupted_processing,
        name="video-processing-recovery",
        daemon=True,
    )
    recovery.start()
    outbox = Thread(
        target=run_crm_outbox_worker,
        name="crm-outbox",
        daemon=True,
    )
    outbox.start()
    yield

app = FastAPI(title="CV Fitness Admin", lifespan=lifespan)
# No global GZipMiddleware: it would also compress the video Range/streaming
# response, corrupting Content-Range vs. the (now-gzipped) body length and
# breaking playback entirely. Gzip is applied per-route in api.py instead,
# only for the JSON track/segments endpoints.
app.add_middleware(AuthMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="cv_fitness_session",
    same_site="lax",
    https_only=ENVIRONMENT != "dev",
    max_age=60 * 60 * 24 * 14,
)

app.include_router(auth.router)
app.include_router(crm.router)
app.include_router(assessments.router)
app.include_router(exercises.router)
app.include_router(programs.router)
app.include_router(students.router)
app.include_router(notifications.router)
app.include_router(progress.router)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")
app.include_router(api.router)
app.include_router(team.router)
app.include_router(settings.router)
app.include_router(admin.router)
