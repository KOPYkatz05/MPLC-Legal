import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch

from database.db import Base
from database.models.missionary import Missionary
from services.missionary_service import (
    MissionaryCodeError,
    MissionaryService,
)


class FakeOneDriveService:
    def __init__(self):
        self.created = []

    def create_missionary_folders(self, full_name):
        self.created.append(full_name)
        return Path("fake") / full_name


class FakeWorkflowService:
    def __init__(self):
        self.initialized = []

    def initialize_workflows(self, missionary_id):
        self.initialized.append(missionary_id)


class MissionaryServiceTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        self.session_factory = sessionmaker(bind=engine)
        self.service = MissionaryService.__new__(
            MissionaryService
        )
        self.service.onedrive_service = FakeOneDriveService()
        self.service.workflow_service = FakeWorkflowService()
        self.session_patch = patch(
            "services.missionary_service.SessionLocal",
            self.session_factory,
        )
        self.session_patch.start()

    def tearDown(self):
        self.session_patch.stop()

    def test_create_missionary_with_numeric_code(self):
        missionary = self.service.create_missionary(
            full_name="Jane Missionary",
            missionary_code="00123",
            nationality="USA",
        )

        self.assertEqual(missionary.missionary_code, "00123")
        self.assertEqual(
            self.service.onedrive_service.created,
            ["Jane Missionary"],
        )
        self.assertEqual(
            self.service.workflow_service.initialized,
            [missionary.id],
        )

    def test_create_missionary_rejects_blank_code(self):
        with self.assertRaises(MissionaryCodeError):
            self.service.create_missionary(
                full_name="Jane Missionary",
                missionary_code=" ",
            )

        self.assertEqual(
            self.service.onedrive_service.created,
            [],
        )

    def test_create_missionary_rejects_non_numeric_code(self):
        with self.assertRaises(MissionaryCodeError):
            self.service.create_missionary(
                full_name="Jane Missionary",
                missionary_code="ABC-123",
            )

        self.assertEqual(
            self.service.onedrive_service.created,
            [],
        )

    def test_create_missionary_rejects_duplicate_code(self):
        session = self.session_factory()
        try:
            session.add(
                Missionary(
                    full_name="Existing Missionary",
                    missionary_code="123",
                    status="ACTIVE",
                )
            )
            session.commit()
        finally:
            session.close()

        with self.assertRaises(MissionaryCodeError):
            self.service.create_missionary(
                full_name="Jane Missionary",
                missionary_code="123",
            )

        self.assertEqual(
            self.service.onedrive_service.created,
            [],
        )


if __name__ == "__main__":
    unittest.main()
