from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..assignment_workflow import submission_for_video
from ..db import get_db
from ..models import (
    AssessmentStatus,
    Segment,
    SegmentAssessment,
    Video,
    VideoAssessment,
    VideoStatus,
)

router = APIRouter(prefix="/assessments")

_SCORE_FIELDS = ("technique", "range_of_motion", "stability", "tempo", "symmetry")


def _redirect(
    video_id: int,
    *,
    segment_id: int | None = None,
    error: str | None = None,
    notice: str | None = None,
) -> RedirectResponse:
    params = {}
    if error:
        params["error"] = error
    if notice:
        params["notice"] = notice
    suffix = f"?{urlencode(params)}" if params else ""
    anchor = f"#segment-{segment_id}" if segment_id is not None else "#assessment"
    return RedirectResponse(url=f"/{video_id}{suffix}{anchor}", status_code=303)


def _validated_scores(**scores: int | None) -> dict[str, int | None] | str:
    for field in _SCORE_FIELDS:
        value = scores[field]
        if value is not None and value not in range(1, 6):
            return "Каждая оценка должна быть от 1 до 5."
    return scores


def _assignment_video(db: Session, video_id: int) -> Video | None:
    video = db.get(Video, video_id)
    submission = submission_for_video(db, video_id)
    if video is None or submission is None:
        return None
    return video


@router.post("/videos/{video_id}")
def save_video_assessment(
    video_id: int,
    status: str = Form("draft"),
    technique: int | None = Form(None),
    range_of_motion: int | None = Form(None),
    stability: int | None = Form(None),
    tempo: int | None = Form(None),
    symmetry: int | None = Form(None),
    summary: str = Form(""),
    recommendations: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    video = _assignment_video(db, video_id)
    if video is None:
        return _redirect(video_id, error="Сначала привяжите видео к ученику.")
    if video.status != VideoStatus.done:
        return _redirect(video_id, error="Оценивать можно только обработанное видео.")
    try:
        clean_status = AssessmentStatus(status)
    except ValueError:
        return _redirect(video_id, error="Выберите допустимый статус оценки.")
    scores = _validated_scores(
        technique=technique,
        range_of_motion=range_of_motion,
        stability=stability,
        tempo=tempo,
        symmetry=symmetry,
    )
    if isinstance(scores, str):
        return _redirect(video_id, error=scores)
    clean_summary = summary.strip()
    clean_recommendations = recommendations.strip()
    if len(clean_summary) > 5000 or len(clean_recommendations) > 5000:
        return _redirect(video_id, error="Текст оценки должен быть короче 5000 символов.")
    if clean_status == AssessmentStatus.final:
        if any(scores[field] is None for field in _SCORE_FIELDS):
            return _redirect(video_id, error="Для итоговой оценки заполните все пять критериев.")
        if not clean_summary:
            return _redirect(video_id, error="Для итоговой оценки добавьте заключение тренера.")

    assessment = db.get(VideoAssessment, video_id)
    if assessment is None:
        assessment = VideoAssessment(video_id=video_id)
        db.add(assessment)
    assessment.status = clean_status
    for field, value in scores.items():
        setattr(assessment, field, value)
    assessment.summary = clean_summary or None
    assessment.recommendations = clean_recommendations or None
    db.commit()
    notice = "Итоговая оценка опубликована." if clean_status == AssessmentStatus.final else "Черновик оценки сохранён."
    return _redirect(video_id, notice=notice)


@router.post("/segments/{segment_id}")
def save_segment_assessment(
    segment_id: int,
    technique: int | None = Form(None),
    range_of_motion: int | None = Form(None),
    stability: int | None = Form(None),
    tempo: int | None = Form(None),
    symmetry: int | None = Form(None),
    comment: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    segment = db.get(Segment, segment_id)
    if segment is None:
        raise HTTPException(404, "segment not found")
    video = _assignment_video(db, segment.video_id)
    if video is None:
        return _redirect(segment.video_id, segment_id=segment_id, error="Сначала привяжите видео к ученику.")
    if video.status != VideoStatus.done:
        return _redirect(segment.video_id, segment_id=segment_id, error="Оценивать можно только обработанное видео.")
    scores = _validated_scores(
        technique=technique,
        range_of_motion=range_of_motion,
        stability=stability,
        tempo=tempo,
        symmetry=symmetry,
    )
    if isinstance(scores, str):
        return _redirect(segment.video_id, segment_id=segment_id, error=scores)
    clean_comment = comment.strip()
    if len(clean_comment) > 3000:
        return _redirect(segment.video_id, segment_id=segment_id, error="Комментарий должен быть короче 3000 символов.")

    assessment = db.get(SegmentAssessment, segment_id)
    if not clean_comment and all(value is None for value in scores.values()):
        if assessment is not None:
            db.delete(assessment)
            db.commit()
        return _redirect(segment.video_id, segment_id=segment_id, notice="Оценка сегмента очищена.")
    if assessment is None:
        assessment = SegmentAssessment(segment_id=segment_id)
        db.add(assessment)
    for field, value in scores.items():
        setattr(assessment, field, value)
    assessment.comment = clean_comment or None
    db.commit()
    return _redirect(segment.video_id, segment_id=segment_id, notice="Оценка сегмента сохранена.")
