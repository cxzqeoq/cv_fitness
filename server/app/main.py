from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import BASE_DIR
from .db import Base, engine
from . import models  # noqa: F401 - register models on Base
from .routers import admin, api

Base.metadata.create_all(bind=engine)

app = FastAPI(title="CV Fitness Admin")
# No global GZipMiddleware: it would also compress the video Range/streaming
# response, corrupting Content-Range vs. the (now-gzipped) body length and
# breaking playback entirely. Gzip is applied per-route in api.py instead,
# only for the JSON track/segments endpoints.

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")
app.include_router(api.router)
app.include_router(admin.router)
