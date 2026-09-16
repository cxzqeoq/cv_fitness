from collections.abc import Iterable
from typing import Any

from .models import Segment, Video


def _srt_timestamp(seconds: float) -> str:
    total_ms = max(0, round(seconds * 1000))
    total_seconds, milliseconds = divmod(total_ms, 1000)
    total_minutes, seconds_part = divmod(total_seconds, 60)
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds_part:02d},{milliseconds:03d}"


def build_srt(segments: Iterable[Segment]) -> str:
    """Build subtitle cues, preferring explicit subtitle text over descriptions."""
    cues = []
    for segment in segments:
        text = (segment.subtitle or segment.description or segment.label or "").strip()
        if not text:
            continue
        cue_number = len(cues) + 1
        cues.append(
            f"{cue_number}\r\n"
            f"{_srt_timestamp(segment.start_sec)} --> {_srt_timestamp(segment.end_sec)}\r\n"
            f"{text}"
        )
    return "\r\n\r\n".join(cues) + ("\r\n" if cues else "")


def build_json_export(video: Video, segments: Iterable[Segment]) -> dict[str, Any]:
    return {
        "version": 1,
        "video": {
            "id": video.id,
            "name": video.original_name,
            "duration_sec": video.duration_sec,
            "fps": video.fps,
            "created_at": video.created_at.isoformat() if video.created_at else None,
        },
        "segments": [
            {
                "id": segment.id,
                "index": index,
                "start_sec": segment.start_sec,
                "end_sec": segment.end_sec,
                "label": segment.label,
                "description": segment.description,
                "subtitle": segment.subtitle,
            }
            for index, segment in enumerate(segments, start=1)
        ],
    }
