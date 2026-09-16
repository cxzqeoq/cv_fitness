import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from app.assignment_workflow import review_submission, start_assignment, submit_assignment
from app.models import AssignmentStatus, SubmissionStatus


def assignment(status: AssignmentStatus = AssignmentStatus.assigned) -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        started_at=None,
        completed_at=None,
    )


def submission(status: SubmissionStatus = SubmissionStatus.draft) -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        student_comment=None,
        coach_comment=None,
        submitted_at=None,
        reviewed_at=None,
    )


class AssignmentWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)

    def test_student_submits_one_attempt_for_review(self):
        item = assignment()
        attempt = submission()

        start_assignment(item, now=self.now)
        submit_assignment(item, attempt, "  Колено уходит внутрь  ", now=self.now)

        self.assertEqual(item.status, AssignmentStatus.submitted)
        self.assertEqual(attempt.status, SubmissionStatus.submitted)
        self.assertEqual(attempt.student_comment, "Колено уходит внутрь")
        self.assertEqual(item.started_at, self.now)
        self.assertEqual(attempt.submitted_at, self.now)

    def test_trainer_accepts_or_requests_new_attempt(self):
        item = assignment(AssignmentStatus.submitted)
        attempt = submission(SubmissionStatus.submitted)

        review_submission(item, attempt, "complete", "  Техника стабильнее  ", now=self.now)
        self.assertEqual(item.status, AssignmentStatus.completed)
        self.assertEqual(attempt.status, SubmissionStatus.accepted)
        self.assertEqual(attempt.coach_comment, "Техника стабильнее")
        self.assertEqual(item.completed_at, self.now)

        review_submission(item, attempt, "reopen", attempt.coach_comment, now=self.now)
        self.assertEqual(item.status, AssignmentStatus.revision_requested)
        self.assertEqual(attempt.status, SubmissionStatus.revision_requested)
        self.assertIsNone(item.completed_at)

    def test_invalid_transitions_do_not_skip_student_submission(self):
        item = assignment()
        attempt = submission()

        with self.assertRaisesRegex(ValueError, "отправленную учеником"):
            review_submission(item, attempt, "complete", "", now=self.now)

        item.status = AssignmentStatus.completed
        with self.assertRaisesRegex(ValueError, "нельзя изменить"):
            submit_assignment(item, attempt, "повтор", now=self.now)

    def test_submitted_attempt_cannot_be_changed(self):
        item = assignment(AssignmentStatus.submitted)
        attempt = submission(SubmissionStatus.submitted)

        with self.assertRaisesRegex(ValueError, "уже отправлена"):
            submit_assignment(item, attempt, "изменить", now=self.now)


if __name__ == "__main__":
    unittest.main()
