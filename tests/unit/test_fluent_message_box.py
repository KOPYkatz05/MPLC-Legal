import inspect

from utils.i18n import get_i18n
import ui.foundation.fluent as fluent


class _FakeStyle:
    def unpolish(self, widget):
        pass

    def polish(self, widget):
        pass


class _FakeButton:
    def __init__(self):
        self.text = ""
        self.object_name = ""
        self.fixed_height = None

    def setText(self, text):
        self.text = text

    def setObjectName(self, object_name):
        self.object_name = object_name

    def setFixedHeight(self, height):
        self.fixed_height = height

    def style(self):
        return _FakeStyle()

    def update(self):
        pass


class _FakeMessageBox:
    last_instance = None

    def __init__(self, title, content, parent):
        self.title = title
        self.content = content
        self.parent = parent
        self.yesButton = _FakeButton()
        self.cancelButton = _FakeButton()
        _FakeMessageBox.last_instance = self

    def setObjectName(self, object_name):
        self.object_name = object_name

    def hideCancelButton(self):
        self.cancel_hidden = True

    def style(self):
        return _FakeStyle()

    def update(self):
        pass

    def exec(self):
        return 1


def test_yes_no_message_buttons_follow_active_language(monkeypatch):
    i18n = get_i18n()
    original_language = i18n.get_language()
    i18n.set_language("es")

    monkeypatch.setattr(fluent, "FLUENT_AVAILABLE", True)
    monkeypatch.setattr(fluent, "MessageBox", _FakeMessageBox)

    try:
        fluent.show_message(
            parent=object(),
            title="Confirmar",
            content="Continuar?",
            buttons="yes_no",
        )
    finally:
        i18n.set_language(original_language)

    box = _FakeMessageBox.last_instance
    assert box.yesButton.text == "Sí"
    assert box.cancelButton.text == "No"


def test_dialog_surfaces_do_not_use_hard_widget_masks():
    source = inspect.getsource(fluent)

    assert ".setMask(" not in source
    assert "QRegion" not in source
    assert "_RoundedSurfaceEffect" in source
