from types import SimpleNamespace

from ui.pages import missionary_detail_page as detail_module
from ui.pages.missionaries_page import MissionariesPage


class VisibilityProbe:
    def __init__(self):
        self.visible = None

    def setVisible(self, visible):
        self.visible = visible


def _page(profile):
    page = detail_module.MissionaryDetailPage.__new__(
        detail_module.MissionaryDetailPage
    )
    page.current_missionary = SimpleNamespace(
        id=7,
        tracking_profile=profile,
    )
    page.advance_button = VisibilityProbe()
    page.advance_banner = VisibilityProbe()
    return page


def test_peruvian_detail_hides_advance_controls():
    page = _page("PERUVIAN_DNI")
    page._set_advance_banner_tone = lambda **kwargs: None
    page.banner_now_btn = VisibilityProbe()
    page.banner_text = SimpleNamespace(setText=lambda text: None)

    page._update_tracking_profile_controls(page.current_missionary)
    page._update_advance_banner(documents=[])

    assert page.advance_button.visible is False
    assert page.advance_banner.visible is True
    assert page.banner_now_btn.visible is False


def test_peruvian_detail_hides_alert_after_dni_upload():
    page = _page("PERUVIAN_DNI")
    page._set_advance_banner_tone = lambda **kwargs: None
    page.banner_now_btn = VisibilityProbe()
    page.banner_text = SimpleNamespace(setText=lambda text: None)

    page._update_advance_banner(
        documents=[SimpleNamespace(document_type="DNI", status="ACTIVE")]
    )

    assert page.advance_banner.visible is False


def test_legal_detail_restores_advance_button():
    page = _page("LEGAL")

    page._update_tracking_profile_controls(page.current_missionary)

    assert page.advance_button.visible is True


def test_peruvian_detail_does_not_open_advance_dialog(monkeypatch):
    page = _page("PERUVIAN_DNI")
    opened = []

    monkeypatch.setattr(
        detail_module,
        "StageAdvanceDialog",
        lambda *args, **kwargs: opened.append((args, kwargs)),
    )

    page._advance_stage()

    assert opened == []


def test_batch_advance_excludes_peruvian_dni_records():
    page = MissionariesPage.__new__(MissionariesPage)
    page._all_missionaries = [
        SimpleNamespace(id=1, tracking_profile="PERUVIAN_DNI"),
        SimpleNamespace(id=2, tracking_profile="LEGAL"),
    ]

    assert page._advanceable_missionary_ids([1, 2]) == [2]
    assert page._advanceable_missionary_ids([1]) == []
