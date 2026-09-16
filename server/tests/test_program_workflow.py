import unittest
import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, TenantSession, set_tenant
from app.models import (
    Assignment,
    AssignmentStatus,
    EnrollmentStatus,
    Exercise,
    Lesson,
    LessonExercise,
    Program,
    ProgramStatus,
    Student,
)
from app.program_workflow import clone_program, enroll_student, publish_program, refresh_enrollment


class ProgramWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, class_=TenantSession, expire_on_commit=False)
        self.db = self.sessions()
        self.org_id = uuid.uuid4()
        set_tenant(self.db, self.org_id)
        self.student = Student(name="Student", email="student@example.com")
        exercises = [Exercise(name=f"Exercise {index}") for index in range(1, 4)]
        self.db.add_all([self.student, *exercises])
        self.db.flush()
        self.program = Program(title="Starter")
        first = Lesson(position=1, title="Foundation", unlock_offset_days=0)
        first.exercises = [
            LessonExercise(position=1, exercise_id=exercises[0].id),
            LessonExercise(position=2, exercise_id=exercises[1].id),
        ]
        second = Lesson(position=2, title="Progression", unlock_offset_days=2)
        second.exercises = [LessonExercise(position=1, exercise_id=exercises[2].id)]
        self.program.lessons = [first, second]
        self.db.add(self.program)
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_previous_lesson_and_date_both_gate_the_next_lesson(self):
        starts_at = datetime(2026, 9, 17, 9, 0, tzinfo=timezone.utc)
        publish_program(self.program, now=starts_at)
        enrollment = enroll_student(
            self.db,
            self.program,
            self.student,
            starts_at,
            now=starts_at,
        )
        assignments = (
            self.db.query(Assignment)
            .filter(Assignment.enrollment_id == enrollment.id)
            .order_by(Assignment.id)
            .all()
        )

        self.assertEqual(
            [assignment.status for assignment in assignments],
            [AssignmentStatus.assigned, AssignmentStatus.assigned, AssignmentStatus.locked],
        )

        assignments[0].status = AssignmentStatus.completed
        assignments[1].status = AssignmentStatus.completed
        refresh_enrollment(self.db, enrollment, now=starts_at)
        self.assertEqual(assignments[2].status, AssignmentStatus.locked)

        unlock_time = datetime(2026, 9, 19, 9, 0, tzinfo=timezone.utc)
        refresh_enrollment(self.db, enrollment, now=unlock_time)
        self.assertEqual(assignments[2].status, AssignmentStatus.assigned)

        assignments[2].status = AssignmentStatus.completed
        refresh_enrollment(self.db, enrollment, now=unlock_time)
        self.assertEqual(enrollment.status, EnrollmentStatus.completed)
        self.assertEqual(enrollment.completed_at, unlock_time)

    def test_clone_is_independent_from_published_program_and_enrollment(self):
        now = datetime(2026, 9, 17, 9, 0, tzinfo=timezone.utc)
        publish_program(self.program, now=now)
        enrollment = enroll_student(self.db, self.program, self.student, now, now=now)
        copied = clone_program(self.db, self.program)

        copied.title = "Changed copy"
        copied.lessons[0].title = "Changed lesson"
        copied.lessons[0].exercises[0].instructions = "Changed instructions"
        self.db.flush()

        self.assertEqual(copied.status, ProgramStatus.draft)
        self.assertEqual(self.program.title, "Starter")
        self.assertEqual(self.program.lessons[0].title, "Foundation")
        self.assertIsNone(self.program.lessons[0].exercises[0].instructions)
        self.assertEqual(
            self.db.query(Assignment).filter(Assignment.enrollment_id == enrollment.id).count(),
            3,
        )

    def test_publish_rejects_incomplete_program(self):
        empty = Program(title="Empty")
        self.db.add(empty)
        self.db.flush()
        with self.assertRaisesRegex(ValueError, "хотя бы один урок"):
            publish_program(empty)

        empty.lessons.append(Lesson(position=1, title="No exercises"))
        with self.assertRaisesRegex(ValueError, "каждом уроке"):
            publish_program(empty)


if __name__ == "__main__":
    unittest.main()
