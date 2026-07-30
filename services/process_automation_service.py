from datetime import date, timedelta

from database.db import SessionLocal
from services.remote_service import RemoteServiceMixin
from database.models.document import Document
from database.models.missionary import Missionary
from database.models.secretary_work import SecretaryTask
from services.secretary_work_service import SecretaryWorkService
from services.secretary_work_service import VISIBLE_TASK_STATUSES
from services.settings_service import SettingsService
from utils.logger import logger


ACTIVE_STATUS = "ACTIVE"
DOCUMENT_ACTIVE = "ACTIVE"
AUTOMATION_SOURCE = "process_automation"
VISIBLE_RESULTS = ("created", "updated", "skipped")


def _iso(value):
    return value.isoformat()


def _week_key(value):
    year, week, _weekday = value.isocalendar()
    return f"{year}-W{week:02d}"


class ProcessAutomationService(RemoteServiceMixin):
    REMOTE_SERVICE = "automation"
    REMOTE_METHODS = frozenset({"run"})
    def __init__(self, settings_service=None, secretary_work_service=None):
        self.settings_service = settings_service or SettingsService()
        self.secretary_work_service = (
            secretary_work_service or SecretaryWorkService()
        )

    def run(self, today=None):
        today = today or date.today()
        summary = {
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "archived_obsolete": 0,
            "errors": 0,
        }

        payloads = self._task_payloads(today)
        active_keys = {
            payload.get("automation_key")
            for payload in payloads
            if payload.get("automation_key")
        }

        for payload in payloads:
            try:
                task = self.secretary_work_service.create_or_update_automatic_task(
                    **payload
                )
                result = task.get("automation_result", "updated")
                if result in VISIBLE_RESULTS:
                    summary[result] += 1
            except Exception:
                summary["errors"] += 1
                logger.exception(
                    "Failed to apply automation task %s",
                    payload.get("automation_key"),
                )

        try:
            summary["archived_obsolete"] = (
                self.secretary_work_service.archive_obsolete_automatic_tasks(
                    active_keys=active_keys,
                    source=AUTOMATION_SOURCE,
                    prefixes=(
                        "prorroga:",
                        "after-interpol:",
                        "after-biometric:",
                        "cancelacion:",
                    ),
                    reason="No longer needed based on current documents or process state.",
                )
            )
        except Exception:
            summary["errors"] += 1

        logger.info(
            "Process automation complete: %s created, %s updated, "
            "%s skipped, %s obsolete archived, %s errors",
            summary["created"],
            summary["updated"],
            summary["skipped"],
            summary["archived_obsolete"],
            summary["errors"],
        )
        return summary

    def _task_payloads(self, today):
        payloads = []
        payloads.extend(self._transfer_payloads(today))
        payloads.extend(self._missionary_payloads(today))
        return payloads

    def _transfer_payloads(self, today):
        payloads = []
        transfers = self.settings_service.get_upcoming_transfer_wednesdays(
            today=today,
            count=8,
        )
        for transfer_date in transfers:
            payloads.append({
                "automation_key": f"transfer:fbi:{_iso(transfer_date)}",
                "automation_source": AUTOMATION_SOURCE,
                "title": "Request/check FBIs for incoming North American missionaries",
                "description": (
                    "Two weeks before transfers, check with the Area for "
                    "FBIs needed by incoming North American missionaries."
                ),
                "priority": "IMPORTANT",
                "work_date": transfer_date - timedelta(days=14),
                "due_date": transfer_date - timedelta(days=14),
                "task_type": "DOCUMENT",
                "related_document_type": "FBI",
            })
            payloads.append({
                "automation_key": f"transfer:flights:{_iso(transfer_date)}",
                "automation_source": AUTOMATION_SOURCE,
                "title": "Begin flight purchase/planning for missionaries leaving next transfer",
                "description": (
                    "Generic transfer-cycle reminder only. Do not track "
                    "individual itineraries in this app."
                ),
                "priority": "IMPORTANT",
                "work_date": transfer_date - timedelta(days=90),
                "due_date": transfer_date - timedelta(days=90),
                "task_type": "FOLLOW_UP",
            })
            payloads.append({
                "automation_key": f"transfer:arrivals:{_iso(transfer_date)}",
                "automation_source": AUTOMATION_SOURCE,
                "title": "Collect and scan passports/TAMs for new arrivals",
                "description": (
                    "Transfer-week reminder: collect passports, scan passport/"
                    "visa documents, and verify TAM quality for new arrivals."
                ),
                "priority": "NORMAL",
                "work_date": transfer_date,
                "due_date": transfer_date,
                "task_type": "DOCUMENT",
                "related_document_type": "PASSPORT",
            })
        return payloads

    def _missionary_payloads(self, today):
        session = SessionLocal()
        try:
            missionaries = (
                session.query(Missionary)
                .filter_by(status=ACTIVE_STATUS)
                .all()
            )
            docs_by_missionary = self._active_docs_by_missionary(session)
        finally:
            session.close()

        payloads = []
        prorroga_payloads = []
        for missionary in missionaries:
            docs = docs_by_missionary.get(missionary.id, set())
            if (getattr(missionary, "dynamics_status", "In-field") or "In-field") != "In-field":
                continue
            if getattr(missionary, "tracking_profile", "LEGAL") == "PERUVIAN_DNI":
                continue
            prorroga_payloads.extend(
                self._prorroga_payloads(missionary, docs, today)
            )
            payloads.extend(self._gvm_payloads(missionary, docs, today))
            payloads.extend(self._after_event_payloads(missionary, docs, today))
            payloads.extend(self._cancelacion_payloads(missionary, today))
        payloads.extend(self._group_prorroga_payloads(prorroga_payloads))
        return payloads

    @staticmethod
    def _cancelacion_payloads(missionary, today):
        release = getattr(missionary, "release_date", None)
        if release is None:
            return []
        work_date = release - timedelta(days=21)
        if work_date > today:
            return []
        return [{
            "automation_key": f"cancelacion:{missionary.id}:{_iso(release)}",
            "automation_source": AUTOMATION_SOURCE,
            "title": "Prepare Cancelacion documents",
            "description": f"{missionary.full_name}: release date is {_iso(release)}.",
            "priority": "IMPORTANT" if work_date >= today else "CRITICAL",
            "work_date": work_date, "due_date": work_date,
            "missionary_id": missionary.id, "task_type": "DOCUMENT",
            "related_stage": "CANCELACION",
        }]

    @staticmethod
    def _active_docs_by_missionary(session):
        rows = (
            session.query(Document.missionary_id, Document.document_type)
            .filter_by(status=DOCUMENT_ACTIVE)
            .all()
        )
        docs = {}
        for missionary_id, document_type in rows:
            docs.setdefault(missionary_id, set()).add(document_type)
        return docs

    def _prorroga_payloads(self, missionary, docs, today):
        expiration = missionary.residency_expiration
        if expiration is None:
            return []
        if "APROBACION_DE_PRORROGA" in docs:
            return []

        windows = [
            (
                60,
                "Prorroga submission window is open",
                "Submit Prorroga only inside the 60-day window before "
                "residency expiration.",
                "IMPORTANT",
            ),
            (
                30,
                "Critical Prorroga follow-up needed",
                "Residency expires soon and no Prorroga approval document is "
                "uploaded yet.",
                "CRITICAL",
            ),
        ]

        eligible = []
        for offset, title, description, priority in windows:
            work_date = expiration - timedelta(days=offset)
            if work_date > today:
                continue
            eligible.append({
                "offset": offset,
                "automation_key": (
                    f"prorroga:{missionary.id}:{offset}:{_iso(expiration)}"
                ),
                "group_batch_key": f"prorroga:group:{offset}",
                "automation_source": AUTOMATION_SOURCE,
                "title": title,
                "missionary_name": missionary.full_name,
                "description": (
                    f"{missionary.full_name}: {description} "
                    f"Residency expiration: {_iso(expiration)}."
                ),
                "priority": priority,
                "work_date": work_date,
                "due_date": work_date,
                "missionary_id": missionary.id,
                "task_type": (
                    "SUBMISSION" if offset <= 60 else "DOCUMENT"
                ),
                "related_stage": "PRORROGA",
            })
        if not eligible:
            return []
        strongest = min(eligible, key=lambda item: item["offset"])
        strongest.pop("offset", None)
        return [strongest]

    def _group_prorroga_payloads(self, payloads):
        grouped = {}
        singles = []
        for payload in payloads:
            group_key = payload.get("group_batch_key")
            if not group_key:
                singles.append(payload)
                continue
            grouped.setdefault(group_key, []).append(payload)

        result = []
        for group_key, items in grouped.items():
            for cluster in self._cluster_weekly_items(items):
                if len(cluster) == 1:
                    item = dict(cluster[0])
                    item.pop("group_batch_key", None)
                    item.pop("missionary_name", None)
                    result.append(item)
                    continue

                cluster_key = (
                    f"{group_key}:{_iso(min(item['work_date'] for item in cluster))}"
                )
                result.append(self._combined_payload(cluster_key, cluster))
                self._archive_replaced_prorroga_tasks(cluster_key, cluster)

        return result + singles

    @staticmethod
    def _cluster_weekly_items(items):
        clusters = []
        for item in sorted(items, key=lambda payload: payload["work_date"]):
            if (
                not clusters
                or item["work_date"] > clusters[-1][0]["work_date"] + timedelta(days=6)
            ):
                clusters.append([item])
            else:
                clusters[-1].append(item)
        return clusters

    @staticmethod
    def _combined_payload(group_key, items):
        sorted_items = sorted(items, key=lambda item: item["missionary_id"])
        first = sorted_items[0]
        missionary_ids = [
            item["missionary_id"]
            for item in sorted_items
        ]
        names = [item.get("missionary_name") or "" for item in sorted_items]
        due_date = min(item["due_date"] for item in sorted_items)
        work_date = min(item["work_date"] for item in sorted_items)
        priority = (
            "CRITICAL"
            if any(item["priority"] == "CRITICAL" for item in sorted_items)
            else "IMPORTANT"
            if any(item["priority"] == "IMPORTANT" for item in sorted_items)
            else "NORMAL"
        )
        description = (
            f"{len(missionary_ids)} missionaries need this prorroga step "
            "within the same week. Complete this as one batch:\n"
            + "\n".join(f"- {name}" for name in names)
        )
        return {
            "automation_key": group_key,
            "automation_source": AUTOMATION_SOURCE,
            "title": first["title"],
            "description": description,
            "priority": priority,
            "work_date": work_date,
            "due_date": due_date,
            "missionary_ids": missionary_ids,
            "task_type": first.get("task_type"),
            "related_stage": first.get("related_stage"),
            "related_document_type": first.get("related_document_type"),
        }

    @staticmethod
    def _archive_replaced_prorroga_tasks(group_key, items):
        _ = group_key
        individual_keys = [
            item["automation_key"]
            for item in items
            if item.get("automation_key")
        ]
        if not individual_keys:
            return

        session = SessionLocal()
        try:
            (
                session.query(SecretaryTask)
                .filter(
                    SecretaryTask.automation_key.in_(individual_keys),
                    SecretaryTask.automation_source == AUTOMATION_SOURCE,
                    SecretaryTask.status.in_(VISIBLE_TASK_STATUSES),
                )
                .update(
                    {SecretaryTask.status: "ARCHIVED"},
                    synchronize_session=False,
                )
            )
            session.commit()
        except Exception:
            session.rollback()
            logger.exception("Failed to archive replaced prorroga tasks")
        finally:
            session.close()

    @staticmethod
    def _gvm_payloads(missionary, docs, today):
        rules = [
            (
                "CARNE_DE_EXTRANJERIA",
                "gvm:carne",
                "Update Travel Connect/GVM with Carne and inactivate Religious Visa",
                "Upload/register the Carne information in Travel Connect/GVM, "
                "then inactivate the old Religious Visa document.",
                "IMPORTANT",
            ),
            (
                "APROBACION_DE_PRORROGA",
                "gvm:prorroga",
                "Update Travel Connect/GVM with Prorroga and inactivate old Carne document",
                "Register the Prorroga in Travel Connect/GVM and inactivate "
                "the previous Carne document.",
                "IMPORTANT",
            ),
            (
                "CONSTANCIA_CANCELACION",
                "gvm:cancelacion",
                "Update Travel Connect/GVM with Salida/Cancelacion",
                "Register Salida/Cancelacion in Travel Connect/GVM after "
                "the cancellation constancia is uploaded.",
                "IMPORTANT",
            ),
        ]
        payloads = []
        for document_type, key_prefix, title, description, priority in rules:
            if document_type not in docs:
                continue
            payloads.append({
                "automation_key": f"{key_prefix}:{missionary.id}",
                "automation_source": AUTOMATION_SOURCE,
                "title": title,
                "description": f"{missionary.full_name}: {description}",
                "priority": priority,
                "work_date": today,
                "due_date": today,
                "missionary_id": missionary.id,
                "task_type": "GVM_UPDATE",
                "related_document_type": document_type,
            })
        return payloads

    @staticmethod
    def _after_event_payloads(missionary, docs, today):
        payloads = []

        interpol_date = missionary.interpol_appointment_date
        if (
            interpol_date is not None
            and interpol_date < today
            and "FICHA_DE_CANJE_INTERNACIONAL" not in docs
        ):
            payloads.append({
                "automation_key": (
                    f"after-interpol:ficha:{missionary.id}:{_iso(interpol_date)}"
                ),
                "automation_source": AUTOMATION_SOURCE,
                "title": "Scan/upload Ficha de Canje Internacional",
                "description": (
                    f"{missionary.full_name}: Interpol appointment has "
                    "passed; scan and upload the Ficha de Canje Internacional."
                ),
                "priority": "IMPORTANT",
                "work_date": today,
                "due_date": today,
                "missionary_id": missionary.id,
                "appointment_field": "interpol_appointment_date",
                "task_type": "DOCUMENT",
                "related_stage": "INTERPOL",
                "related_document_type": "FICHA_DE_CANJE_INTERNACIONAL",
            })

        biometric_date = missionary.biometric_appointment_date
        waiting_for_pickup = (
            "CITA_RECOJO" not in docs
            and "CARNE_DE_EXTRANJERIA" not in docs
        )
        if (
            biometric_date is not None
            and biometric_date < today
            and waiting_for_pickup
        ):
            payloads.append({
                "automation_key": (
                    "after-biometric:buzon:"
                    f"{missionary.id}:{_week_key(today)}"
                ),
                "automation_source": AUTOMATION_SOURCE,
                "title": "Check Migraciones buzon and schedule pickup if approved",
                "description": (
                    f"{missionary.full_name}: biometric appointment has "
                    "passed. Check the electronic buzon and schedule pickup "
                    "if the Carne is approved."
                ),
                "priority": "NORMAL",
                "work_date": today,
                "due_date": today,
                "missionary_id": missionary.id,
                "appointment_field": "biometric_appointment_date",
                "task_type": "APPOINTMENT",
                "related_stage": "CARNET DE EXTRANJERIA",
                "related_document_type": "CITA_RECOJO",
            })

        return payloads
