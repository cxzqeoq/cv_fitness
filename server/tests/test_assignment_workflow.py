import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from app.assignment_workflow import (
    reset_assignment,
    review_assignment,
    start_assignment,
    submit_assignment,
)
from app.models import AssignmentStatus


def assignment(status: AssignmentStatus = AssignmentStatus.assigned) -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        student_comment=None,
        coach_comment=None,
        started_at=None,
        submitted_at=None,
        completed_at=None,
    )


class AssignmentWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)

    def test_student_progresses_from_assignment_to_review(self):
        item = assignment()

        start_assignment(item, now=self.now)
        submit_assignment(item, "  Колено уходит внутрь  ", now=self.now)

        self.assertEqual(item.status, AssignmentStatus.submitted)
        self.assertEqual(item.student_comment, "Колено уходит внутрь")
        self.assertEqual(item.started_at, self.now)
        self.assertEqual(item.submitted_at, self.now)

    def test_trainer_can_complete_and_reopen_submitted_work(self):
        item = assignment(AssignmentStatus.submitted)
        item.started_at = self.now
        item.submitted_at = self.now

        review_assignment(item, "complete", "  Техника стала стабильнее  ", now=self.now)
        self.assertEqual(item.status, AssignmentStatus.completed)
        self.assertEqual(item.coach_comment, "Техника стала стабильнее")
        self.assertEqual(item.completed_at, self.now)

        review_assignment(item, "reopen", item.coach_comment, now=self.now)
        self.assertEqual(item.status, AssignmentStatus.in_progress)
        self.assertIsNone(item.completed_at)

    def test_invalid_transitions_do_not_skip_student_submission(self):
        item = assignment()

        with self.assertRaisesRegex(ValueError, "отправленную учеником"):
            review_assignment(item, "complete", "", now=self.now)

        item.status = AssignmentStatus.completed
        with self.assertRaisesRegex(ValueError, "нельзя изменить"):
            submit_assignment(item, "повтор", now=self.now)

    def test_transfer_to_another_student_clears_workflow_data(self):
        item = assignment(AssignmentStatus.completed)
        item.student_comment = "Было сложно"
        item.coach_comment = "Повторить"
        item.started_at = self.now
        item.submitted_at = self.now
        item.completed_at = self.now

        reset_assignment(item)

        self.assertEqual(item.status, AssignmentStatus.assigned)
        self.assertIsNone(item.student_comment)
        self.assertIsNone(item.coach_comment)
        self.assertIsNone(item.started_at)
        self.assertIsNone(item.submitted_at)
        self.assertIsNone(item.completed_at)


if __name__ == "__main__":
    unittest.main()
