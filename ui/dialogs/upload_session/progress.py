"""Progress surface for sequential document saves."""

from shiboken6 import isValid as shiboken_is_valid

from PySide6.QtCore import QEasingCurve, QEvent, QPropertyAnimation, QRect, Qt, QTimer
from PySide6.QtWidgets import QFrame, QVBoxLayout

from ui.foundation import BodyLabel, MaskDialogBase, SubtitleLabel, setup_dialog_shell


def _widget_alive(widget):
    try:
        return widget is not None and shiboken_is_valid(widget)
    except Exception:
        return False


class UploadSaveProgressDialog(MaskDialogBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Saving Documents")
        self.setModal(True)
        self.setWindowModality(Qt.WindowModal)
        self.surface = setup_dialog_shell(
            self,
            surface_width=420,
            surface_min_width=360,
            surface_min_height=170,
            shell_object_name="UploadSaveProgressDialog",
            surface_object_name="FluentLoadingSurface",
            use_masked_shell=True,
        )
        layout = QVBoxLayout()
        layout.setContentsMargins(22, 20, 22, 22)
        layout.setSpacing(14)
        self.surface.setLayout(layout)
        self.title_label = SubtitleLabel("Saving Documents")
        self.title_label.setObjectName("FluentLoadingTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.title_label)
        self.message_label = BodyLabel("Preparing documents...")
        self.message_label.setObjectName("FluentLoadingMessage")
        self.message_label.setAlignment(Qt.AlignCenter)
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label)
        self.progress_track = QFrame(self.surface)
        self.progress_track.setObjectName("UploadSaveProgressTrack")
        self.progress_track.setFixedHeight(8)
        self.progress_track.setAttribute(Qt.WA_StyledBackground, True)
        self.progress_track.installEventFilter(self)
        self.progress_fill = QFrame(self.progress_track)
        self.progress_fill.setObjectName("UploadSaveProgressFill")
        self.progress_fill.setAttribute(Qt.WA_StyledBackground, True)
        self.progress_fill.setGeometry(0, 0, 0, 8)
        self.progress_fill.show()
        self._progress_fraction = 0.0
        self._progress_animation = QPropertyAnimation(
            self.progress_fill,
            b"geometry",
            self,
        )
        self._progress_animation.setDuration(180)
        self._progress_animation.setEasingCurve(QEasingCurve.OutCubic)
        layout.addWidget(self.progress_track)

    def eventFilter(self, watched, event):
        if watched is getattr(self, "progress_track", None) and event.type() in {
            QEvent.Show,
            QEvent.Resize,
        }:
            QTimer.singleShot(0, self._set_progress_fill_width)
        return super().eventFilter(watched, event)

    def set_progress(
        self,
        completed,
        total,
        file_name=None,
        saved=0,
        failed=0,
        skipped=0,
        warnings=0,
    ):
        total = max(int(total or 0), 1)
        completed = min(max(int(completed or 0), 0), total)
        self._progress_fraction = completed / total
        QTimer.singleShot(0, self._animate_progress_fill)
        if file_name and completed < total:
            message = f"Processing {completed + 1} of {total}: {file_name}"
        else:
            message = (
                f"Processed {completed} of {total} | "
                f"{saved} saved | {failed} failed | {skipped} skipped"
            )
            if warnings:
                message += f" | {warnings} warning(s)"
        self.message_label.setText(message)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._set_progress_fill_width(animated=False)

    def _animate_progress_fill(self):
        if not _widget_alive(getattr(self, "progress_fill", None)):
            return
        target = self._progress_fill_geometry()
        if self._progress_animation.state() == QPropertyAnimation.Running:
            self._progress_animation.stop()
        self._progress_animation.setStartValue(self.progress_fill.geometry())
        self._progress_animation.setEndValue(target)
        self._progress_animation.start()

    def _set_progress_fill_width(self, animated=True):
        target = self._progress_fill_geometry()
        if animated:
            self._animate_progress_fill()
        else:
            self.progress_fill.setGeometry(target)

    def _progress_fill_geometry(self):
        track_width = max(self.progress_track.width(), 0)
        fill_width = int(track_width * self._progress_fraction)
        if self._progress_fraction > 0 and track_width > 0:
            fill_width = max(fill_width, 2)
        width = min(fill_width, track_width)
        height = max(self.progress_track.height(), 8)
        return QRect(0, 0, width, height)
