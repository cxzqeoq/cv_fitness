import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = Path(os.environ.get("STORAGE_DIR", BASE_DIR / "storage"))
VIDEOS_DIR = STORAGE_DIR / "videos"
TRACKS_DIR = STORAGE_DIR / "tracks"
THUMBS_DIR = STORAGE_DIR / "thumbs"

VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
TRACKS_DIR.mkdir(parents=True, exist_ok=True)
THUMBS_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://cvfit:cvfit@db:5432/cvfit"
)
