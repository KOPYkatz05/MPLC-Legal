from PySide6.QtCore import Qt

from ui.foundation import GuidanceButton, create_guidance_button


def test_guidance_factory_uses_the_question_mark_icon(qapp):
    button = create_guidance_button(
        "Use the first arrival date.",
        title="Original entry date",
    )

    assert isinstance(button, GuidanceButton)
    assert button.objectName() == "GuidanceButton"
    assert button.guidance_text == "Use the first arrival date."
    assert button.guidance_title == "Original entry date"
    assert button.accessibleName() == "Help: Original entry date"
    assert not button.icon().isNull()
    assert button.toolTip() == ""
    assert button._show_timer.isSingleShot()
    assert button._popup.objectName() == "GuidancePopup"
    assert button._popup.testAttribute(Qt.WA_TranslucentBackground)
    assert button._popup._animation.duration() == 250


def test_guidance_popup_uses_one_reversible_fade_animation(qapp):
    button = create_guidance_button("Helpful context", title="Help")

    button._popup.show_at(button)
    assert button._popup.isVisible()
    assert button._popup._animation.endValue() == 1.0

    button._popup.fade_out()
    assert button._popup._hiding
    assert button._popup._animation.endValue() == 0.0


def test_guidance_factory_has_a_text_fallback_for_missing_icons(monkeypatch, qapp):
    monkeypatch.setattr("ui.foundation.guidance.lucide_icon", lambda *args, **kwargs: None)

    button = create_guidance_button("Helpful context")

    assert button.text() == "?"
