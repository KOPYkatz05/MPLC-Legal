"""Identity/details persistence for Missionary Detail."""

import json
import sys
from datetime import date

from PySide6.QtCore import QDate

from services.expiration_rules import add_years
from utils.language_helper import ui_text as tr
from utils.logger import logger
from ui.foundation import show_message


DATE_PLACEHOLDER = QDate(1900, 1, 1)
AUTO_DERIVED_VISA_SOURCE_LABEL = "Auto-derived from arrival date"


def _parse_field_sources(field_sources):
    if not field_sources:
        return {}
    if isinstance(field_sources, dict):
        return dict(field_sources)
    try:
        parsed = json.loads(field_sources)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


class IdentityDetailsSection:
    """Collect and persist editable identity/date controls from its host page."""

    def __init__(self, host):
        self.host = host

    def updates_for_field(self, field_key):
        """Build the minimal authoritative update for one visible editor."""
        host = self.host
        missionary = getattr(host, "current_missionary", None)
        if missionary is None:
            return {}

        if field_key in host._text_edits:
            value = host._text_edits[field_key].text().strip()
            current = (getattr(missionary, field_key, None) or "").strip()
            return {field_key: value} if value != current else {}

        date_edit = host._date_edits.get(field_key)
        if date_edit is None:
            return {}
        qd = (
            date_edit.getDate()
            if hasattr(date_edit, "getDate")
            else date_edit.date()
        )
        if not qd.isValid() or qd == DATE_PLACEHOLDER:
            return {}
        value = date(qd.year(), qd.month(), qd.day())
        current = (
            host._displayed_date_for_field(field_key)
            if hasattr(host, "_displayed_date_for_field")
            else getattr(missionary, field_key, None)
        )
        if value == current:
            return {}

        updates = {field_key: value}
        sources = _parse_field_sources(
            getattr(missionary, "field_sources", None)
        )
        original_sources = dict(sources)

        if field_key == "arrival_date":
            current_arrival = getattr(missionary, "arrival_date", None)
            current_visa = getattr(missionary, "visa_expiration", None)
            visa_source = sources.get("visa_expiration", {})
            old_derived = add_years(current_arrival, 1) if current_arrival else None
            visa_is_auto = (
                visa_source.get("label") == AUTO_DERIVED_VISA_SOURCE_LABEL
                or visa_source.get("document_type") == "TAM"
                or current_visa is None
                or (old_derived is not None and current_visa == old_derived)
            )
            if visa_is_auto:
                derived_visa = add_years(value, 1)
                if derived_visa is not None:
                    updates["visa_expiration"] = derived_visa
                    sources["visa_expiration"] = {
                        "label": AUTO_DERIVED_VISA_SOURCE_LABEL,
                    }
        elif field_key == "visa_expiration":
            arrival = getattr(missionary, "arrival_date", None)
            derived_visa = add_years(arrival, 1) if arrival else None
            if derived_visa is not None and value == derived_visa:
                sources["visa_expiration"] = {
                    "label": AUTO_DERIVED_VISA_SOURCE_LABEL,
                }
            else:
                sources.pop("visa_expiration", None)

        if sources != original_sources:
            updates["field_sources"] = json.dumps(sources)
        return updates

    def apply_saved_updates(self, updates):
        missionary = getattr(self.host, "current_missionary", None)
        if missionary is None:
            return
        for field_key, value in updates.items():
            if hasattr(missionary, field_key):
                setattr(missionary, field_key, value)

    def save(self):
        host = self.host
        if not hasattr(host, "current_missionary"):
            return

        updates = {}
        sources = _parse_field_sources(
            getattr(host.current_missionary, "field_sources", None)
        )
        current_arrival = getattr(
            host.current_missionary,
            "arrival_date",
            None,
        )
        current_visa = getattr(
            host.current_missionary,
            "visa_expiration",
            None,
        )
        current_visa_source = sources.get("visa_expiration", {})
        current_visa_is_auto = (
            current_visa_source.get("label")
            == AUTO_DERIVED_VISA_SOURCE_LABEL
            or current_visa_source.get("document_type") == "TAM"
        )

        for field_key, date_edit in host._date_edits.items():
            qd = (
                date_edit.getDate()
                if hasattr(date_edit, "getDate")
                else date_edit.date()
            )
            if (
                field_key in host._date_empty_on_load
                and qd == DATE_PLACEHOLDER
            ):
                continue
            if qd == DATE_PLACEHOLDER:
                continue
            updates[field_key] = date(qd.year(), qd.month(), qd.day())

        for field_key, text_edit in host._text_edits.items():
            value = text_edit.text().strip()
            current_value = (
                getattr(host.current_missionary, field_key, None) or ""
            ).strip()
            if value != current_value:
                updates[field_key] = value

        arrival_date = updates.get("arrival_date", current_arrival)
        visa_date = updates.get("visa_expiration", current_visa)
        if arrival_date:
            derived_visa = add_years(arrival_date, 1)
            if derived_visa:
                old_derived_visa = (
                    add_years(current_arrival, 1)
                    if current_arrival
                    else None
                )
                current_visa_was_auto = (
                    current_visa_is_auto
                    or (
                        current_visa is not None
                        and old_derived_visa is not None
                        and current_visa == old_derived_visa
                    )
                    or current_visa is None
                )
                if arrival_date != current_arrival:
                    if current_visa_was_auto:
                        if visa_date in {None, current_visa, old_derived_visa}:
                            updates["visa_expiration"] = derived_visa
                            sources["visa_expiration"] = {
                                "label": AUTO_DERIVED_VISA_SOURCE_LABEL,
                            }
                        else:
                            updates["visa_expiration"] = visa_date
                            if visa_date == derived_visa:
                                sources["visa_expiration"] = {
                                    "label": AUTO_DERIVED_VISA_SOURCE_LABEL,
                                }
                            else:
                                sources.pop("visa_expiration", None)
                    else:
                        updates["visa_expiration"] = visa_date
                        if visa_date == derived_visa:
                            sources["visa_expiration"] = {
                                "label": AUTO_DERIVED_VISA_SOURCE_LABEL,
                            }
                        else:
                            sources.pop("visa_expiration", None)
                elif visa_date == derived_visa:
                    sources["visa_expiration"] = {
                        "label": AUTO_DERIVED_VISA_SOURCE_LABEL,
                    }
                elif visa_date != current_visa:
                    sources.pop("visa_expiration", None)

        if sources:
            updates["field_sources"] = json.dumps(sources)
        if not updates:
            return

        try:
            host.missionary_service.update_fields(
                host.current_missionary.id,
                updates,
            )
            # The remote detail refresh is asynchronous.  Advance the local
            # comparison baseline as soon as the write succeeds so that the
            # refresh is not mistaken for an attempt to overwrite unsaved
            # edits (and Back does not warn about values that were just saved).
            for field_key, value in updates.items():
                if hasattr(host.current_missionary, field_key):
                    setattr(host.current_missionary, field_key, value)
            self._show_message(host, tr("save_details"), tr("details_saved"))
            host._reload_missionary()
            host._refresh_missionaries_table()
        except Exception:
            logger.exception("Failed to save dates")
            self._show_message(
                host,
                tr("save_details"),
                tr("details_save_failed"),
                kind="critical",
            )

    @staticmethod
    def _show_message(*args, **kwargs):
        facade = sys.modules.get("ui.pages.missionary_detail_page")
        callback = getattr(facade, "show_message", show_message)
        return callback(*args, **kwargs)
