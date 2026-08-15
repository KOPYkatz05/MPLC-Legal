from datetime import datetime

from sqlalchemy.exc import IntegrityError

from database.db import SessionLocal
from services.remote_service import RemoteServiceMixin
from database.models.missionary import Missionary
from database.models.residency_event import ResidencyEvent
from services.expiration_rules import add_years
from utils.logger import logger


INITIAL_RESIDENCY = "INITIAL_RESIDENCY"
PRORROGA = "PRORROGA"
APPROVED = "APPROVED"
MAX_PRORROGAS = 2


def calculate_residency_expiration(
    arrival_date,
    approved_prorroga_count,
):
    years = 1 + int(approved_prorroga_count or 0)
    return add_years(arrival_date, years)


class ResidencyService(RemoteServiceMixin):
    REMOTE_SERVICE = "residency"
    REMOTE_METHODS = frozenset({
        "get_approved_prorroga_count",
        "approve_initial_residency",
        "approve_next_prorroga",
        "sync_residency_expiration",
        "get_residency_timeline",
    })
    def get_approved_prorroga_count(self, missionary_id):
        session = SessionLocal()
        try:
            return (
                session.query(ResidencyEvent)
                .filter_by(
                    missionary_id=missionary_id,
                    event_type=PRORROGA,
                    status=APPROVED,
                )
                .count()
            )
        finally:
            session.close()

    def approve_initial_residency(
        self,
        missionary_id,
        document_id=None,
    ):
        session = SessionLocal()
        try:
            missionary = (
                session.query(Missionary)
                .filter_by(id=missionary_id)
                .first()
            )
            if not missionary:
                return None

            event = self.approve_initial_residency_in_session(
                session,
                missionary,
                document_id=document_id,
            )
            session.commit()
            session.refresh(event)
            return event
        except Exception:
            session.rollback()
            logger.exception(
                "Failed to approve initial residency for missionary %s",
                missionary_id,
            )
            return None
        finally:
            session.close()

    def approve_next_prorroga(
        self,
        missionary_id,
        document_id=None,
    ):
        session = SessionLocal()
        try:
            missionary = (
                session.query(Missionary)
                .filter_by(id=missionary_id)
                .first()
            )
            if not missionary:
                return None

            event = self.approve_next_prorroga_in_session(
                session,
                missionary,
                document_id=document_id,
            )
            session.commit()
            if event:
                session.refresh(event)
            return event
        except Exception:
            session.rollback()
            logger.exception(
                "Failed to approve prorroga for missionary %s",
                missionary_id,
            )
            return None
        finally:
            session.close()

    def sync_residency_expiration(self, missionary_id):
        session = SessionLocal()
        try:
            missionary = (
                session.query(Missionary)
                .filter_by(id=missionary_id)
                .first()
            )
            if not missionary:
                return None
            expiration = self._sync_missionary_expiration(
                session,
                missionary,
            )
            session.commit()
            return expiration
        except Exception:
            session.rollback()
            logger.exception(
                "Failed to sync residency expiration for missionary %s",
                missionary_id,
            )
            return None
        finally:
            session.close()

    def get_residency_timeline(self, missionary_id):
        session = SessionLocal()
        try:
            missionary = (
                session.query(Missionary)
                .filter_by(id=missionary_id)
                .first()
            )
            if not missionary:
                return []

            events = (
                session.query(ResidencyEvent)
                .filter_by(missionary_id=missionary_id)
                .all()
            )
            event_map = {
                (event.event_type, event.sequence_number): event
                for event in events
            }

            rows = []
            for event_type, sequence, label, years in [
                (INITIAL_RESIDENCY, 0, "Initial residency", 1),
                (PRORROGA, 1, "Prorroga 1", 2),
                (PRORROGA, 2, "Prorroga 2", 3),
            ]:
                event = event_map.get((event_type, sequence))
                rows.append({
                    "event_type": event_type,
                    "sequence_number": sequence,
                    "label": label,
                    "status": (
                        event.status
                        if event
                        else "PENDING"
                    ),
                    "target_expiration": add_years(
                        missionary.arrival_date,
                        years,
                    ),
                    "document_id": (
                        event.document_id
                        if event
                        else None
                    ),
                    "approved_at": (
                        event.approved_at
                        if event
                        else None
                    ),
                })

            return rows
        finally:
            session.close()

    def approve_initial_residency_in_session(
        self,
        session,
        missionary,
        document_id=None,
    ):
        event = self._get_or_create_identity_event(
            session,
            missionary_id=missionary.id,
            event_type=INITIAL_RESIDENCY,
            sequence_number=0,
            document_id=document_id,
        )
        event.status = APPROVED
        if document_id is not None:
            event.document_id = document_id
        if event.approved_at is None:
            event.approved_at = datetime.now()

        session.flush()
        self._sync_missionary_expiration(session, missionary)
        return event

    def approve_next_prorroga_in_session(
        self,
        session,
        missionary,
        document_id=None,
    ):
        if document_id is not None:
            existing_for_document = (
                session.query(ResidencyEvent)
                .filter_by(
                    missionary_id=missionary.id,
                    event_type=PRORROGA,
                    document_id=document_id,
                )
                .first()
            )
            if existing_for_document:
                self._sync_missionary_expiration(session, missionary)
                return existing_for_document

        for sequence in range(1, MAX_PRORROGAS + 1):
            event = self._identity_event(
                session,
                missionary_id=missionary.id,
                event_type=PRORROGA,
                sequence_number=sequence,
            )
            if event is None:
                event = self._get_or_create_identity_event(
                    session,
                    missionary_id=missionary.id,
                    event_type=PRORROGA,
                    sequence_number=sequence,
                    document_id=document_id,
                )

            # A concurrent request may have claimed this sequence between the
            # read and insert. The same document is an idempotent replay; a
            # different document retries at the next allowed sequence.
            if document_id is None or event.document_id == document_id:
                event.status = APPROVED
                if event.approved_at is None:
                    event.approved_at = datetime.now()
                session.flush()
                self._sync_missionary_expiration(session, missionary)
                return event

        logger.warning(
            "Missionary %s already has %s residency prorroga slots; "
            "not creating another residency event.",
            missionary.id,
            MAX_PRORROGAS,
        )
        self._sync_missionary_expiration(session, missionary)
        return None

    @staticmethod
    def _identity_event(
        session,
        missionary_id,
        event_type,
        sequence_number,
    ):
        return (
            session.query(ResidencyEvent)
            .filter_by(
                missionary_id=missionary_id,
                event_type=event_type,
                sequence_number=sequence_number,
            )
            .first()
        )

    def _get_or_create_identity_event(
        self,
        session,
        missionary_id,
        event_type,
        sequence_number,
        document_id=None,
    ):
        existing = self._identity_event(
            session,
            missionary_id,
            event_type,
            sequence_number,
        )
        if existing is not None:
            return existing

        event = ResidencyEvent(
            missionary_id=missionary_id,
            event_type=event_type,
            sequence_number=sequence_number,
            status=APPROVED,
            document_id=document_id,
            approved_at=datetime.now(),
        )
        try:
            # Keep a concurrent unique-key collision inside a savepoint so the
            # caller's missionary-field transaction remains usable.
            with session.begin_nested():
                session.add(event)
                session.flush()
            return event
        except IntegrityError:
            logger.info(
                "Residency event identity was concurrently claimed: "
                "missionary=%s type=%s sequence=%s",
                missionary_id,
                event_type,
                sequence_number,
            )
            winner = self._identity_event(
                session,
                missionary_id,
                event_type,
                sequence_number,
            )
            if winner is None:
                # Do not pretend the event exists if the competing transaction
                # is not visible. The durable document remains saved and the
                # post-processing caller can retry safely.
                raise
            return winner

    def _sync_missionary_expiration(
        self,
        session,
        missionary,
    ):
        approved_prorrogas = (
            session.query(ResidencyEvent)
            .filter_by(
                missionary_id=missionary.id,
                event_type=PRORROGA,
                status=APPROVED,
            )
            .count()
        )
        expiration = calculate_residency_expiration(
            missionary.arrival_date,
            approved_prorrogas,
        )
        if expiration is None:
            logger.warning(
                "Could not sync residency expiration for missionary %s: "
                "missing arrival date.",
                missionary.id,
            )
            return None

        missionary.residency_expiration = expiration
        return expiration
