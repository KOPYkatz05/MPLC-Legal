"""Notes persistence for Missionary Detail."""

import sys

from ui.foundation import show_message
from utils.language_helper import ui_text as tr
from utils.logger import logger


class NotesSection:
    def __init__(self, host):
        self.host = host

    def save(self):
        host = self.host
        if not hasattr(host, "current_missionary"):
            return
        notes = host.notes_text.toPlainText()
        try:
            host.missionary_service.update_fields(
                host.current_missionary.id,
                {"notes": notes},
            )
            logger.info("Saved notes for %s", host.current_missionary.full_name)
            self._show_message(
                host,
                tr("missionary_detail_saved_title"),
                tr("missionary_detail_notes_saved"),
            )
        except Exception:
            logger.exception("Failed to save notes")
            self._show_message(
                host,
                tr("missionary_detail_error_title"),
                tr("missionary_detail_notes_save_failed"),
                kind="critical",
            )

    @staticmethod
    def _show_message(*args, **kwargs):
        facade = sys.modules.get("ui.pages.missionary_detail_page")
        callback = getattr(facade, "show_message", show_message)
        return callback(*args, **kwargs)
