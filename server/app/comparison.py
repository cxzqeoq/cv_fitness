import json
import math
from pathlib import Path

VISIBILITY_THRESHOLD = 0.15
MAX_SAMPLES = 240

_FEATURES = {
    "left_elbow": (1, 3, 5),
    "right_elbow": (2, 4, 6),
    "left_knee": (7, 9, 11),
    "right_knee": (8, 10, 12),
    "left_hip": (1, 7, 9),
    "right_hip": (2, 8, 10),
}


def _point(frame: list[float], index: int) -> tuple[float, float, float]:
    offset = 1 + index * 3
    return frame[offset], frame[offset + 1], frame[offset + 2]


def _angle(
    first: tuple[float, float, float],
    center: tuple[float, float, float],
    last: tuple[float, float, float],
) -> float | None:
    if min(first[2], center[2], last[2]) < VISIBILITY_THRESHOLD:
        return None
    left = (first[0] - center[0], first[1] - center[1])
    right = (last[0] - center[0], last[1] - center[1])
    magnitude = math.hypot(*left) * math.hypot(*right)
    if not magnitude:
        return None
    cosine = max(-1.0, min(1.0, (left[0] * right[0] + left[1] * right[1]) / magnitude))
    return math.degrees(math.acos(cosine))


def _frame_features(frame: list[float]) -> dict[str, float | None]:
    if len(frame) != 40:
        return {}
    points = [_point(frame, index) for index in range(13)]
    values = {
        name: _angle(points[first], points[center], points[last])
        for name, (first, center, last) in _FEATURES.items()
    }
    shoulders = (
        (points[1][0] + points[2][0]) / 2,
        (points[1][1] + points[2][1]) / 2,
        min(points[1][2], points[2][2]),
    )
    hips = (
        (points[7][0] + points[8][0]) / 2,
        (points[7][1] + points[8][1]) / 2,
        min(points[7][2], points[8][2]),
    )
    if min(shoulders[2], hips[2]) >= VISIBILITY_THRESHOLD:
        dx = shoulders[0] - hips[0]
        dy = shoulders[1] - hips[1]
        magnitude = math.hypot(dx, dy)
        values["torso_tilt"] = (
            math.degrees(math.acos(max(-1.0, min(1.0, -dy / magnitude))))
            if magnitude
            else None
        )
    else:
        values["torso_tilt"] = None
    values["arm_spread"] = _angle(points[5], shoulders, points[6])
    return values


def _feature_series(path: Path, start: float, end: float) -> dict[str, list[float]]:
    try:
        frames = json.loads(path.read_text())["frames"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Не удалось прочитать трек скелета.") from exc
    series = {name: [] for name in (*_FEATURES, "torso_tilt", "arm_spread")}
    for frame in frames:
        if not frame or not start <= frame[0] <= end:
            continue
        values = _frame_features(frame)
        for name, value in values.items():
            if value is not None:
                series[name].append(value)
    return series


def _resample(values: list[float], count: int) -> list[float]:
    if len(values) == count:
        return values
    if count == 1:
        return [values[0]]
    result = []
    scale = (len(values) - 1) / (count - 1)
    for index in range(count):
        position = index * scale
        left = int(position)
        right = min(left + 1, len(values) - 1)
        fraction = position - left
        result.append(values[left] * (1 - fraction) + values[right] * fraction)
    return result


def _dtw_mean_abs(reference: list[float], target: list[float]) -> float:
    size = len(reference)
    band = max(4, round(size * 0.12))
    infinity = float("inf")
    previous = [infinity] * size
    previous_length = [0] * size
    for row, ref_value in enumerate(reference):
        current = [infinity] * size
        current_length = [0] * size
        start = max(0, row - band)
        end = min(size - 1, row + band)
        for column in range(start, end + 1):
            cost = abs(ref_value - target[column])
            if row == 0 and column == 0:
                current[column] = cost
                current_length[column] = 1
                continue
            candidates = []
            if row > 0 and previous[column] < infinity:
                candidates.append((previous[column], previous_length[column]))
            if column > 0 and current[column - 1] < infinity:
                candidates.append((current[column - 1], current_length[column - 1]))
            if row > 0 and column > 0 and previous[column - 1] < infinity:
                candidates.append((previous[column - 1], previous_length[column - 1]))
            if candidates:
                best_cost, best_length = min(candidates, key=lambda item: item[0])
                current[column] = best_cost + cost
                current_length[column] = best_length + 1
        previous, previous_length = current, current_length
    if previous[-1] == infinity or not previous_length[-1]:
        raise ValueError("Не удалось выровнять движения по времени.")
    return previous[-1] / previous_length[-1]


def _soft_similarity(delta: float, tolerance: int) -> float:
    if delta <= tolerance:
        return 1.0
    cap = tolerance * 2.2
    if delta >= cap:
        return 0.0
    return (cap - delta) / (cap - tolerance)


def compare_tracks(
    reference_path: Path,
    reference_start: float,
    reference_end: float,
    target_path: Path,
    target_start: float,
    target_end: float,
    tolerance: int,
) -> dict[str, object]:
    """Compare normalized 2D angle trajectories using the browser DTW semantics."""
    reference = _feature_series(reference_path, reference_start, reference_end)
    target = _feature_series(target_path, target_start, target_end)
    usable = {
        name: (reference[name], target[name])
        for name in reference
        if len(reference[name]) >= 8 and len(target[name]) >= 8
    }
    if len(usable) < 3:
        raise ValueError("Недостаточно видимых точек тела для сравнения.")

    sample_count = min(
        MAX_SAMPLES,
        max(24, min(min(len(first), len(second)) for first, second in usable.values())),
    )
    ranges = {name: max(values[0]) - min(values[0]) for name, values in usable.items()}
    max_range = max(ranges.values()) or 1.0
    feature_scores = {}
    weighted_score = 0.0
    total_weight = 0.0
    for name, (reference_values, target_values) in usable.items():
        ref = _resample(reference_values, sample_count)
        candidate = _resample(target_values, sample_count)
        mean_abs = _dtw_mean_abs(ref, candidate)
        score = _soft_similarity(mean_abs, tolerance) * 100
        weight = max(0.15, ranges[name] / max_range)
        weighted_score += score * weight
        total_weight += weight
        feature_scores[name] = {
            "score": round(score, 1),
            "mean_abs": round(mean_abs, 1),
        }

    reference_duration = reference_end - reference_start
    target_duration = target_end - target_start
    tempo_score = min(reference_duration, target_duration) / max(reference_duration, target_duration) * 100
    return {
        "score": round(weighted_score / total_weight, 1),
        "tempo_score": round(tempo_score, 1),
        "feature_scores": feature_scores,
        "sample_count": sample_count,
    }
