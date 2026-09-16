from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from .models import Assignment, AssessmentStatus, Submission, Video, VideoAssessment


CRITERIA: tuple[tuple[str, str], ...] = (
    ("technique", "Техника"),
    ("range_of_motion", "Амплитуда"),
    ("stability", "Стабильность"),
    ("tempo", "Темп"),
    ("symmetry", "Симметрия"),
)
PERIODS: dict[str, tuple[str, int | None]] = {
    "30": ("30 дней", 30),
    "90": ("3 месяца", 90),
    "180": ("6 месяцев", 180),
    "365": ("Год", 365),
    "all": ("Всё время", None),
}


@dataclass(frozen=True)
class ProgressRecord:
    assignment_id: int
    video_id: int
    date: date
    exercise: str
    scores: dict[str, int | None]

    @property
    def average(self) -> float | None:
        values = [value for value in self.scores.values() if value is not None]
        return round(sum(values) / len(values), 2) if values else None


def _record_date(assignment: Assignment, video: Video) -> date:
    if assignment.due_at is not None:
        return assignment.due_at.date()
    created_at: datetime = video.created_at or assignment.created_at
    return created_at.date()


def load_progress_records(db: Session, student_id: int) -> list[ProgressRecord]:
    rows = (
        db.query(Assignment, Submission, Video, VideoAssessment)
        .join(Submission, Submission.assignment_id == Assignment.id)
        .join(Video, Video.id == Submission.video_id)
        .join(VideoAssessment, VideoAssessment.video_id == Video.id)
        .filter(
            Assignment.student_id == student_id,
            VideoAssessment.status == AssessmentStatus.final,
        )
        .all()
    )
    records = [
        ProgressRecord(
            assignment_id=assignment.id,
            video_id=video.id,
            date=_record_date(assignment, video),
            exercise=assignment.title.strip(),
            scores={field: getattr(assessment, field) for field, _ in CRITERIA},
        )
        for assignment, _submission, video, assessment in rows
    ]
    return sorted(records, key=lambda item: (item.date, item.video_id))


def filter_progress_records(
    records: list[ProgressRecord],
    *,
    period: str,
    exercise: str,
    today: date | None = None,
) -> tuple[list[ProgressRecord], str]:
    selected_period = period if period in PERIODS else "180"
    _, days = PERIODS[selected_period]
    cutoff = (today or date.today()) - timedelta(days=days) if days is not None else None
    filtered = [
        record
        for record in records
        if (cutoff is None or record.date >= cutoff)
        and (not exercise or record.exercise == exercise)
    ]
    return filtered, selected_period


def _delta(first: float | None, last: float | None) -> float | None:
    if first is None or last is None:
        return None
    return round(last - first, 1)


def summarize_progress(records: list[ProgressRecord]) -> dict:
    points = []
    usable_records = [record for record in records if record.average is not None]
    for index, record in enumerate(usable_records):
        x = 50.0 if len(usable_records) == 1 else index / (len(usable_records) - 1) * 100
        average = record.average
        assert average is not None
        y = (5 - average) / 4 * 100
        points.append(
            {
                "x": round(x, 2),
                "y": round(y, 2),
                "average": round(average, 1),
                "date": record.date,
                "exercise": record.exercise,
                "video_id": record.video_id,
            }
        )

    criteria = []
    for field, label in CRITERIA:
        values = [record.scores[field] for record in records if record.scores[field] is not None]
        criteria.append(
            {
                "field": field,
                "label": label,
                "average": round(sum(values) / len(values), 1) if values else None,
                "delta": _delta(values[0], values[-1]) if len(values) >= 2 else None,
            }
        )

    grouped: dict[str, list[float]] = defaultdict(list)
    for record in usable_records:
        average = record.average
        assert average is not None
        grouped[record.exercise].append(average)
    exercises = [
        {
            "name": name,
            "count": len(values),
            "average": round(sum(values) / len(values), 1),
            "delta": _delta(values[0], values[-1]) if len(values) >= 2 else None,
        }
        for name, values in grouped.items()
    ]
    exercises.sort(key=lambda item: (-item["count"], item["name"]))

    available_criteria = [item for item in criteria if item["average"] is not None]
    first_average = usable_records[0].average if usable_records else None
    last_average = usable_records[-1].average if usable_records else None
    return {
        "count": len(records),
        "average": (
            round(sum(point["average"] for point in points) / len(points), 1)
            if points
            else None
        ),
        "latest_average": round(last_average, 1) if last_average is not None else None,
        "trend_delta": _delta(first_average, last_average) if len(usable_records) >= 2 else None,
        "points": points,
        "polyline": " ".join(f'{point["x"]},{point["y"]}' for point in points),
        "criteria": criteria,
        "best_criterion": max(available_criteria, key=lambda item: item["average"])
        if available_criteria
        else None,
        "focus_criterion": min(available_criteria, key=lambda item: item["average"])
        if available_criteria
        else None,
        "exercises": exercises,
        "records": list(reversed(records)),
    }


def build_progress_report(
    db: Session,
    *,
    student_id: int,
    period: str,
    exercise: str,
    today: date | None = None,
) -> dict:
    all_records = load_progress_records(db, student_id)
    exercise_options = sorted({record.exercise for record in all_records})
    records, selected_period = filter_progress_records(
        all_records,
        period=period,
        exercise=exercise,
        today=today,
    )
    return {
        **summarize_progress(records),
        "period": selected_period,
        "period_label": PERIODS[selected_period][0],
        "periods": PERIODS,
        "exercise": exercise,
        "exercise_options": exercise_options,
    }
