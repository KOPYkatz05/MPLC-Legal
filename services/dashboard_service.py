from datetime import date

from database.db import SessionLocal

from database.models.missionary import Missionary

from database.models.document import Document

from utils.constants import (
    WORKFLOW_STAGES,
    DOCUMENTS,
    required_documents_for_missionary,
)

from utils.logger import logger


EXPIRY_FIELDS = [
    ("visa_expiration", "Visa Expiration"),
    ("residency_expiration", "Residency Expiration"),
]

EXPIRY_WINDOW_DAYS = 60


class DashboardService:

    def get_summary(self):
        session = SessionLocal()

        try:
            missionaries = (
                session.query(Missionary)
                .filter_by(status="ACTIVE")
                .all()
            )

            total = len(missionaries)

            # ======================================
            # Stage counts
            # ======================================

            stage_counts = {
                stage: 0
                for stage in WORKFLOW_STAGES
            }

            for missionary in missionaries:
                stage = missionary.current_stage

                if stage in stage_counts:
                    stage_counts[stage] += 1

            # ======================================
            # Expiring documents
            # ======================================

            today = date.today()

            expiring = []

            for missionary in missionaries:
                for field, label in EXPIRY_FIELDS:
                    val = getattr(
                        missionary,
                        field,
                        None,
                    )

                    if val is None:
                        continue

                    days_left = (val - today).days

                    if days_left <= EXPIRY_WINDOW_DAYS:
                        expiring.append({
                            "name": missionary.full_name,
                            "field_label": label,
                            "date": val,
                            "days_left": days_left,
                        })

            expiring.sort(
                key=lambda x: x["days_left"]
            )

            # ======================================
            # Missing required documents
            # ======================================

            all_docs = (
                session.query(Document)
                .all()
            )

            uploaded_by_missionary = {}

            for doc in all_docs:
                uploaded_by_missionary.setdefault(
                    doc.missionary_id,
                    set(),
                ).add(doc.document_type)

            missing_docs = []

            for missionary in missionaries:
                uploaded = uploaded_by_missionary.get(
                    missionary.id,
                    set(),
                )

                # Only check CURRENT stage
                stage = missionary.current_stage

                required = required_documents_for_missionary(
                    stage,
                    missionary,
                )

                missionary_missing = []

                for doc_type in required:
                    if doc_type not in uploaded:
                        label = (
                            DOCUMENTS
                            .get(doc_type, {})
                            .get("label", doc_type)
                        )

                        missionary_missing.append({
                            "stage": stage,
                            "label": label,
                        })

                if missionary_missing:
                    missing_docs.append({
                        "name": missionary.full_name,
                        "missing": missionary_missing,
                    })

            return {
                "total": total,
                "stage_counts": stage_counts,
                "expiring": expiring,
                "missing_docs": missing_docs,
            }

        except Exception:
            logger.exception(
                "Failed to load dashboard data"
            )

            return {
                "total": 0,
                "stage_counts": {
                    s: 0 for s in WORKFLOW_STAGES
                },
                "expiring": [],
                "missing_docs": [],
            }

        finally:
            session.close()
