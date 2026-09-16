import unittest
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, TenantSession, set_tenant
from app.models import Exercise, Student, TeamMember, TeamRole, Video


class TenantScopeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, class_=TenantSession)
        self.org_a = uuid.uuid4()
        self.org_b = uuid.uuid4()

        db = self.sessions()
        db.add_all(
            [
                Student(org_id=self.org_a, name="A", email="same@example.com"),
                Student(org_id=self.org_b, name="B", email="same@example.com"),
                TeamMember(
                    org_id=self.org_a,
                    name="Owner A",
                    email="owner@example.com",
                    role=TeamRole.owner,
                ),
                TeamMember(
                    org_id=self.org_b,
                    name="Owner B",
                    email="owner@example.com",
                    role=TeamRole.owner,
                ),
                Exercise(org_id=self.org_a, name="Squat"),
                Exercise(org_id=self.org_b, name="Squat"),
                Video(org_id=self.org_a, filename="a.mp4", original_name="a.mp4"),
                Video(org_id=self.org_b, filename="b.mp4", original_name="b.mp4"),
            ]
        )
        db.commit()
        db.close()

    def tearDown(self):
        self.engine.dispose()

    def test_reads_only_current_organization(self):
        db = self.sessions()
        set_tenant(db, self.org_a)

        self.assertEqual([student.name for student in db.query(Student).all()], ["A"])
        self.assertEqual([member.name for member in db.query(TeamMember).all()], ["Owner A"])
        self.assertEqual([video.original_name for video in db.query(Video).all()], ["a.mp4"])
        self.assertEqual([exercise.name for exercise in db.query(Exercise).all()], ["Squat"])
        self.assertIsNone(db.get(Student, 2))
        db.close()

    def test_new_roots_inherit_tenant_and_cross_tenant_insert_is_rejected(self):
        db = self.sessions()
        set_tenant(db, self.org_a)
        student = Student(name="C", email="c@example.com")
        db.add(student)
        db.flush()
        self.assertEqual(student.org_id, self.org_a)

        db.add(Student(org_id=self.org_b, name="Wrong org"))
        with self.assertRaisesRegex(ValueError, "cross-tenant insert rejected"):
            db.flush()
        db.rollback()
        db.close()


if __name__ == "__main__":
    unittest.main()
