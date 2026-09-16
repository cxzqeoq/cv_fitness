import os
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = Path(os.environ.get("STORAGE_DIR", BASE_DIR / "storage"))
VIDEOS_DIR = STORAGE_DIR / "videos"
TRACKS_DIR = STORAGE_DIR / "tracks"
THUMBS_DIR = STORAGE_DIR / "thumbs"

ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev").strip().lower()
SESSION_SECRET = os.environ.get("SESSION_SECRET", "change-me")
OMRA_IS_ISSUER = os.environ.get("OMRA_IS_ISSUER", "https://omra.is").rstrip("/")
OMRA_IS_INTERNAL_URL = os.environ.get("OMRA_IS_INTERNAL_URL", "").rstrip("/")
OIDC_CLIENT_ID = os.environ.get("OIDC_CLIENT_ID", "")
OIDC_CLIENT_SECRET = os.environ.get("OIDC_CLIENT_SECRET", "")
OIDC_REDIRECT_URI = os.environ.get(
    "OIDC_REDIRECT_URI", "http://localhost:8000/auth/callback"
)
DEV_STAFF_BYPASS = os.environ.get("DEV_STAFF_BYPASS", "false").lower() == "true"
BOOTSTRAP_ORG_ID = uuid.UUID(
    os.environ.get("BOOTSTRAP_ORG_ID", "00000000-0000-0000-0000-000000000001")
)
ALLOWED_VIDEO_EXTENSIONS = frozenset({".m4v", ".mov", ".mp4", ".webm"})
UPLOAD_CHUNK_BYTES = 1024 * 1024

VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
TRACKS_DIR.mkdir(parents=True, exist_ok=True)
THUMBS_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://cvfit:cvfit@db:5432/cvfit"
)
