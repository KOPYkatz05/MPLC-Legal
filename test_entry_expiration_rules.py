import inspect
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import services.upload_pipeline as upload_pipeline
import services.workflow_service as workflow_service
from database.models.missionary import Missionary
from database.models.workflow import WorkflowStage
from services.workflow_service import WorkflowService
from services.expiration_rules import (
    add_years,
    apply_stage_completion_expiration,
)
from ui.dialogs.batch_stage_advance_dialog import BatchStageAdvanceDialog
from ui.dialogs.stage_advance_dialog import StageAdvanceDialog


class FakeQuery:
    def __init__(self, result):
        self.result = result

    def filter_by(self, **kwargs):
        return self

    def first(self):
        if isinstance(self.result, list):
            return self.result[0] if self.result else None
        return self.result

    def all(self):
        if isinstance(self.result, list):
            return self.result
        return [self.result] if self.result is not None else []


class FakeSession:
    def __init__(self, missionary=None, workflow=None):
        self.missionary = missionary
        self.workflow = workflow
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def query(self, model):
        if model is Missionary:
            return FakeQuery(self.missionary)
        if model is WorkflowStage:
            return FakeQuery(self.workflow)
        return FakeQuery(None)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class EntryExpirationRuleTests(unittest.TestCase):

    def test_add_years_uses_feb_28_for_leap_day(self):
        self.assertEqual(
            add_years(date(2024, 2, 29), 1),
            date(2025, 2, 28),
        )
        self.assertEqual(
            add_years(date(2024, 2, 29), 2),
            date(2026, 2, 28),
        )

    def test_tam_sets_visa_expiration_from_arrival_date(self):
        missionary = SimpleNamespace(
            id=1,
            arrival_date=None,
            visa_expiration=None,
            field_sources=None,
        )
        session = FakeSession(missionary=missionary)

        with patch.object(
            upload_pipeline,
            "SessionLocal",
            return_value=session,
        ):
            updated = upload_pipeline.apply_missionary_updates(
                missionary_id=1,
                document_type="TAM",
                document_id=10,
                confirmed_data={
                    "arrival_date": "2026-04-01",
                    "visa_expiration": "2026-06-30",
                },
                auto_update_fields=[
                    "arrival_date",
                    "visa_expiration",
                ],
            )

        self.assertIn("arrival_date", updated)
        self.assertIn("visa_expiration", updated)
        self.assertEqual(missionary.arrival_date, date(2026, 4, 1))
        self.assertEqual(missionary.visa_expiration, date(2027, 4, 1))
        self.assertTrue(session.committed)

    def test_carne_sets_residency_expiration_from_arrival_date(self):
        missionary = SimpleNamespace(
            id=1,
            arrival_date=date(2026, 4, 1),
            residency_expiration=None,
            field_sources=None,
        )
        session = FakeSession(missionary=missionary)

        with patch.object(
            upload_pipeline,
            "SessionLocal",
            return_value=session,
        ):
            updated = upload_pipeline.apply_missionary_updates(
                missionary_id=1,
                document_type="CARNE_DE_EXTRANJERIA",
                document_id=11,
                confirmed_data={
                    "residency_expiration": "2026-06-30",
                },
                auto_update_fields=["residency_expiration"],
            )

        self.assertIn("residency_expiration", updated)
        self.assertEqual(
            missionary.residency_expiration,
            date(2027, 4, 1),
        )
        self.assertTrue(session.committed)

    def test_prorroga_completion_sets_residency_expiration(self):
        missionary = SimpleNamespace(
            id=1,
            arrival_date=date(2026, 4, 1),
            residency_expiration=None,
            field_sources=None,
        )

        changed = apply_stage_completion_expiration(
            missionary,
            "PRORROGA",
        )

        self.assertTrue(changed)
        self.assertEqual(
            missionary.residency_expiration,
            date(2028, 4, 1),
        )

    def test_workflow_service_applies_prorroga_completion_rule(self):
        missionary = SimpleNamespace(
            id=1,
            arrival_date=date(2026, 4, 1),
            residency_expiration=None,
            field_sources=None,
        )
        workflow = SimpleNamespace(
            id=7,
            missionary_id=1,
            stage_name="PRORROGA",
            status="WAITING",
        )
        session = FakeSession(
            missionary=missionary,
            workflow=workflow,
        )
        service = WorkflowService.__new__(WorkflowService)
        service.update_missionary_stage = lambda missionary_id: None
        service.check_for_archive = lambda missionary_id: None

        with patch.object(
            workflow_service,
            "SessionLocal",
            return_value=session,
        ):
            service.update_workflow_status(7, "COMPLETED")

        self.assertEqual(workflow.status, "COMPLETED")
        self.assertEqual(
            missionary.residency_expiration,
            date(2028, 4, 1),
        )
        self.assertTrue(session.committed)

    def test_dialog_completion_paths_call_shared_expiration_hook(self):
        self.assertIn(
            "apply_stage_completion_expiration",
            inspect.getsource(StageAdvanceDialog._do_advance),
        )
        self.assertIn(
            "apply_stage_completion_expiration",
            inspect.getsource(BatchStageAdvanceDialog._do_batch_advance),
        )


if __name__ == "__main__":
    unittest.main()
