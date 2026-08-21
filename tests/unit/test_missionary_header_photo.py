from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

from ui.pages.missionary_detail_page import (
    MissionaryDetailPage,
    MissionaryPortraitLabel,
)


def test_header_portrait_uses_initials_and_responsive_sizes(qtbot):
    portrait = MissionaryPortraitLabel()
    qtbot.addWidget(portrait)

    portrait.set_initials("Ada Lovelace")
    assert portrait._initials == "AL"
    assert portrait.size().width() == 96
    assert portrait.size().height() == 120

    portrait.set_portrait_size(compact=True)
    assert portrait.size().width() == 80
    assert portrait.size().height() == 100


def test_header_portrait_click_opens_with_or_without_a_loaded_photo(qtbot):
    portrait = MissionaryPortraitLabel()
    qtbot.addWidget(portrait)
    clicks = []
    portrait.clicked.connect(lambda: clicks.append(True))

    qtbot.mouseClick(portrait, Qt.LeftButton)
    assert clicks == [True]

    portrait.set_photo(QPixmap(20, 25))
    portrait.show()
    assert not portrait.grab().isNull()
    qtbot.mouseClick(portrait, Qt.LeftButton)
    assert clicks == [True, True]


def test_latest_active_photo_uses_newest_active_photo_document():
    documents = [
        SimpleNamespace(id=2, document_type="PHOTO", status="ACTIVE"),
        SimpleNamespace(id=7, document_type="PHOTO", status="INVALIDATED"),
        SimpleNamespace(id=6, document_type="PHOTO", status="ACTIVE"),
        SimpleNamespace(id=9, document_type="PASSPORT", status="ACTIVE"),
    ]

    selected = MissionaryDetailPage._latest_active_photo(documents)

    assert selected.id == 6
