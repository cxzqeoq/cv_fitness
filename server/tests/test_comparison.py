import json
import tempfile
import unittest
from pathlib import Path

from app.comparison import compare_tracks


STRAIGHT_POSE = (
    (0.50, 0.10),
    (0.40, 0.30),
    (0.60, 0.30),
    (0.35, 0.45),
    (0.65, 0.45),
    (0.30, 0.60),
    (0.70, 0.60),
    (0.43, 0.55),
    (0.57, 0.55),
    (0.43, 0.75),
    (0.57, 0.75),
    (0.43, 0.95),
    (0.57, 0.95),
)

BENT_POSE = (
    (0.50, 0.10),
    (0.40, 0.30),
    (0.60, 0.30),
    (0.34, 0.45),
    (0.66, 0.45),
    (0.48, 0.45),
    (0.52, 0.45),
    (0.43, 0.55),
    (0.57, 0.55),
    (0.32, 0.72),
    (0.68, 0.72),
    (0.43, 0.95),
    (0.57, 0.95),
)


def _track(pose, duration: float, frame_count: int = 16) -> list[list[float]]:
    frames = []
    for index in range(frame_count):
        timestamp = duration * index / (frame_count - 1)
        frame = [timestamp]
        for x, y in pose:
            frame.extend((x, y, 0.99))
        frames.append(frame)
    return frames


class MotionComparisonTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def _write_track(self, name: str, frames: list[list[float]]) -> Path:
        path = self.root / name
        path.write_text(json.dumps({"frames": frames}))
        return path

    def test_identical_motion_has_full_similarity(self):
        reference = self._write_track("reference.json", _track(STRAIGHT_POSE, 2.0))
        target = self._write_track("target.json", _track(STRAIGHT_POSE, 2.0))

        result = compare_tracks(reference, 0.0, 2.0, target, 0.0, 2.0, 15)

        self.assertEqual(result["score"], 100.0)
        self.assertEqual(result["tempo_score"], 100.0)
        self.assertTrue(
            all(item["score"] == 100.0 for item in result["feature_scores"].values())
        )

    def test_pose_similarity_is_separate_from_tempo(self):
        reference = self._write_track("reference.json", _track(STRAIGHT_POSE, 2.0))
        target = self._write_track("target.json", _track(STRAIGHT_POSE, 4.0, 24))

        result = compare_tracks(reference, 0.0, 2.0, target, 0.0, 4.0, 15)

        self.assertEqual(result["score"], 100.0)
        self.assertEqual(result["tempo_score"], 50.0)

    def test_changed_joint_geometry_reduces_similarity(self):
        reference = self._write_track("reference.json", _track(STRAIGHT_POSE, 2.0))
        target = self._write_track("target.json", _track(BENT_POSE, 2.0))

        result = compare_tracks(reference, 0.0, 2.0, target, 0.0, 2.0, 15)

        self.assertLess(result["score"], 80.0)
        self.assertLess(result["feature_scores"]["left_knee"]["score"], 100.0)
        self.assertLess(result["feature_scores"]["right_elbow"]["score"], 100.0)


if __name__ == "__main__":
    unittest.main()
