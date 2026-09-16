import json
import subprocess
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from .config import ALLOWED_VIDEO_EXTENSIONS, UPLOAD_CHUNK_BYTES, VIDEOS_DIR


def _validate_video(path: Path) -> None:
    """Reject files that ffprobe cannot identify as video."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        streams = json.loads(result.stdout).get("streams", [])
    except (json.JSONDecodeError, subprocess.TimeoutExpired):
        raise HTTPException(422, "Не удалось проверить видео.") from None
    if result.returncode != 0 or not streams:
        raise HTTPException(422, "Файл не содержит поддерживаемого видеопотока.")


def format_size_limit(size: int) -> str:
    if size >= 1024**3:
        return f"{size / 1024**3:g} ГБ"
    return f"{size / 1024**2:g} МБ"


async def save_video_upload(file: UploadFile, max_upload_bytes: int) -> tuple[Path, str]:
    original_name = Path(file.filename or "").name
    if not original_name:
        raise HTTPException(400, "Выберите видеофайл.")
    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(415, "Поддерживаются MP4, MOV, M4V и WebM.")

    destination = VIDEOS_DIR / f"{uuid.uuid4().hex}{ext}"
    size = 0
    try:
        with destination.open("xb") as output:
            while chunk := await file.read(UPLOAD_CHUNK_BYTES):
                size += len(chunk)
                if size > max_upload_bytes:
                    limit = format_size_limit(max_upload_bytes)
                    raise HTTPException(413, f"Размер видео превышает {limit}.")
                output.write(chunk)
        if size == 0:
            raise HTTPException(400, "Нельзя загрузить пустой файл.")
        _validate_video(destination)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    return destination, original_name
