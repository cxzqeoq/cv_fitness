import unittest
from datetime import date

from app.progress import ProgressRecord, filter_progress_records, summarize_progress


def record(video_id, day, exercise, scores):
    fields = ("technique", "range_of_motion", "stability", "tempo", "symmetry")
    return ProgressRecord(
        video_id=video_id,
        date=day,
        exercise=exercise,
        scores=dict(zip(fields, scores, strict=True)),
    )


class ProgressAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.records = [
            record(1, date(2026, 1, 10), "Приседания", (2, 2, 2, 2, 2)),
            record(2, date(2026, 2, 10), "Планка", (3, 3, 3, 3, 3)),
            record(3, date(2026, 3, 10), "Приседания", (4, 5, 4, 4, 4)),
        ]

    def test_summary_reports_trend_criteria_and_exercises(self):
        report = summarize_progress(self.records)

        self.assertEqual(report["count"], 3)
        self.assertEqual(report["average"], 3.1)
        self.assertEqual(report["latest_average"], 4.2)
        self.assertEqual(report["trend_delta"], 2.2)
        self.assertEqual(report["best_criterion"]["label"], "Амплитуда")
        self.assertEqual(report["focus_criterion"]["label"], "Техника")
        self.assertEqual(report["exercises"][0]["name"], "Приседания")
        self.assertEqual(report["exercises"][0]["count"], 2)
        self.assertEqual(report["points"][0]["x"], 0)
        self.assertEqual(report["points"][-1]["x"], 100)

    def test_filters_by_period_and_exact_exercise(self):
        filtered, period = filter_progress_records(
            self.records,
            period="90",
            exercise="Приседания",
            today=date(2026, 3, 15),
        )

        self.assertEqual(period, "90")
        self.assertEqual([item.video_id for item in filtered], [1, 3])

    def test_invalid_period_uses_six_month_default(self):
        filtered, period = filter_progress_records(
            self.records,
            period="unexpected",
            exercise="",
            today=date(2026, 3, 15),
        )

        self.assertEqual(period, "180")
        self.assertEqual(len(filtered), 3)

    def test_single_point_is_centered_in_chart(self):
        report = summarize_progress([self.records[0]])

        self.assertEqual(report["points"][0]["x"], 50)
        self.assertIsNone(report["trend_delta"])


if __name__ == "__main__":
    unittest.main()
