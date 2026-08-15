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
