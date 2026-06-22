"""
Small UI language helper for labels, buttons, and short help text.

Edit text in utils/i18n.py. Use ui_text("some_key") from widgets, dialogs,
and pages instead of hard-coded strings when the label should follow the
current app language.
"""

from utils.i18n import tr


def ui_text(key, **kwargs):
    return tr(key, **kwargs)


def button_text(key, **kwargs):
    return ui_text(key, **kwargs)


def tab_text(key, **kwargs):
    return ui_text(key, **kwargs)


def help_text(key, **kwargs):
    return ui_text(key, **kwargs)
