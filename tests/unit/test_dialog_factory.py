import inspect

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtWidgets import QDialog, QFrame, QWidget

from ui.foundation import dialog_factory
from ui.foundation.dialog_factory import AppDialog, DialogBackdrop


def _dialog(qapp):
    host = QWidget()
    host.resize(800, 600)
    host.show()
    qapp.processEvents()
    dialog = AppDialog(
        host,
        title="Factory test",
        subtitle="Reusable dialog lifecycle coverage.",
        width=420,
        min_height=240,
    )
    return host, dialog


def _flush_deletes(qapp):
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()


def _close_dialog(host, dialog, qapp):
    dialog.close()
    dialog.deleteLater()
    _flush_deletes(qapp)
    host.close()
    _flush_deletes(qapp)


def test_app_dialog_uses_generic_surface_slots(qapp):
    host, dialog = _dialog(qapp)
    try:
        assert dialog.surface.objectName() == "AppDialogSurface"
        assert dialog.findChild(QFrame, "AppDialogHeader") is not None
        assert dialog.findChild(QFrame, "AppDialogFooter") is not None
        assert dialog.surface.width() == 420
        assert dialog.surface.minimumHeight() == 240
    finally:
        _close_dialog(host, dialog, qapp)


@pytest.mark.parametrize(
    ("width", "min_height", "max_height"),
    [
        (320, 180, 280),
        (520, 420, 620),
        (1600, 1400, None),
    ],
)
def test_app_dialog_constrains_compact_standard_and_tall_sizes(
    qapp,
    width,
    min_height,
    max_height,
):
    host = QWidget()
    host.resize(800, 600)
    host.show()
    qapp.processEvents()
    dialog = AppDialog(
        host,
        title="Sizing",
        width=width,
        min_height=min_height,
        max_height=max_height,
    )
    try:
        available = host.screen().availableGeometry()
        assert dialog.surface.width() == min(width, available.width() - 64)
        assert dialog.surface.minimumHeight() <= available.height() - 64
        assert dialog.surface.maximumHeight() <= available.height() - 64
        assert dialog.surface.minimumHeight() <= dialog.surface.maximumHeight()
    finally:
        _close_dialog(host, dialog, qapp)


def test_app_dialog_factory_has_no_fluent_or_painter_dependency():
    source = inspect.getsource(dialog_factory).casefold()
    assert "qpainter" not in source
    assert "paintevent" not in source
    assert "ui.foundation.widgets" not in source
    assert "qfluent" not in source


def test_show_and_open_install_then_remove_backdrop(qapp):
    host, dialog = _dialog(qapp)
    try:
        dialog.show()
        qapp.processEvents()
        assert isinstance(dialog._backdrop, DialogBackdrop)

        dialog.hide()
        qapp.processEvents()
        assert dialog._backdrop is None
        assert not host.findChildren(DialogBackdrop)

        dialog.open()
        qapp.processEvents()
        assert isinstance(dialog._backdrop, DialogBackdrop)

        dialog.reject()
        qapp.processEvents()
        assert dialog._backdrop is None
        assert not host.findChildren(DialogBackdrop)
    finally:
        _close_dialog(host, dialog, qapp)


def test_exec_and_resize_keep_backdrop_in_sync(qapp):
    host, dialog = _dialog(qapp)
    try:
        dialog.show()
        qapp.processEvents()
        backdrop = dialog._backdrop
        assert backdrop is not None

        host.resize(960, 700)
        qapp.processEvents()
        assert backdrop.size() == host.size()
        assert backdrop.snapshot.pixmap().deviceIndependentSize().toSize() == host.size()

        dialog.hide()
        QTimer.singleShot(0, dialog.accept)
        assert dialog.exec() == QDialog.Accepted
        assert dialog._backdrop is None
        assert not host.findChildren(DialogBackdrop)
    finally:
        _close_dialog(host, dialog, qapp)


def test_repeated_open_close_leaves_no_backdrop(qapp):
    host, dialog = _dialog(qapp)
    try:
        for _ in range(3):
            dialog.open()
            qapp.processEvents()
            dialog.close()
            _flush_deletes(qapp)
            assert dialog._backdrop is None
            assert not host.findChildren(DialogBackdrop)
    finally:
        dialog.close()
        dialog.deleteLater()
        _flush_deletes(qapp)
        assert not host.findChildren(DialogBackdrop)
        host.close()
