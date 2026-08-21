"""Interactive approval editor for a portrait cropped from a passport scan."""

from pathlib import Path
import os
import tempfile

from PIL import Image, ImageOps
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsScene,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from ui.file_dialogs import downloads_folder

from ui.foundation import AppDialog, create_button, lucide_icon
from services.passport_photo_service import PassportPhotoService
from ui.widgets.crop_graphics_view import CropGraphicsView
from ui.widgets.infinite_rotation_ruler import InfiniteRotationRuler


class PassportPhotoReviewDialog(AppDialog):
    PHOTO_ASPECT_RATIO = 4 / 5
    OUTPUT_SIZE = (600, 750)

    def __init__(self, photo_path=None, parent=None):
        has_photo = bool(photo_path)
        super().__init__(
            parent,
            title="Approve Missionary Photo" if has_photo else "Add Missionary Photo",
            subtitle=(
                "Choose the photo from the full passport page."
                if has_photo
                else "No photo found, select a photo to start."
            ),
            width=620,
            min_height=700,
            max_height=860,
        )
        self.photo_path = Path(photo_path) if photo_path else None
        self._owns_photo_path = False
        self.original_pixmap = QPixmap()
        self.preview_pixmap = QPixmap()
        self.rotation_angle = 0
        self._preview_rotated_size = None
        self._rotation_preview_timer = QTimer(self)
        self._rotation_preview_timer.setSingleShot(True)
        self._rotation_preview_timer.setInterval(8)
        self._rotation_preview_timer.timeout.connect(self._update_preview)

        self.scene = QGraphicsScene(self)
        self.graphics_view = CropGraphicsView(
            aspect_ratio=self.PHOTO_ASPECT_RATIO,
            enable_zoom=True,
        )
        self.graphics_view.setObjectName("PassportPhotoReviewPreview")
        self.graphics_view.setScene(self.scene)
        self.graphics_view.setAlignment(Qt.AlignCenter)
        self.graphics_view.setMinimumSize(440, 470)
        self.body_layout.addWidget(self.graphics_view, stretch=1)
        self.graphics_view.crop_changed.connect(self._crop_changed)
        self.pixmap_item = None

        self.empty_state = QWidget(self.graphics_view)
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.setContentsMargins(24, 20, 24, 20)
        empty_layout.setSpacing(12)
        empty_message = QLabel("No photo found, select a photo to start.")
        empty_message.setObjectName("MutedText")
        empty_message.setAlignment(Qt.AlignCenter)
        empty_message.setWordWrap(True)
        choose_photo = QToolButton()
        choose_photo.setObjectName("MissionaryPhotoFolderButton")
        choose_photo.setIcon(lucide_icon("folder-open", size=24, color="#0F5F64"))
        choose_photo.setIconSize(QSize(24, 24))
        choose_photo.setFixedSize(48, 42)
        choose_photo.setCursor(Qt.PointingHandCursor)
        choose_photo.setToolTip("Select a photo")
        choose_photo.setAccessibleName("Select a photo")
        choose_photo.clicked.connect(self._pick_photo)
        empty_layout.addStretch()
        empty_layout.addWidget(empty_message)
        empty_layout.addWidget(choose_photo, alignment=Qt.AlignCenter)
        empty_layout.addStretch()
        self.empty_message = empty_message
        self.choose_photo_button = choose_photo

        self.rotation_ruler = InfiniteRotationRuler(
            self.graphics_view
        )
        self.rotation_ruler.setObjectName("PassportPhotoRotationRuler")
        self.rotation_ruler.angleChanged.connect(self._rotation_changed)
        self.rotation_ruler.show()
        self.rotation_ruler.raise_()

        rotation_row = QHBoxLayout()
        rotate_left = create_button("Rotate Left", "secondary")
        rotate_right = create_button("Rotate Right", "secondary")
        reset_crop = create_button("Reset Crop", "secondary")
        zoom_out = create_button("Zoom Out", "secondary")
        zoom_in = create_button("Zoom In", "secondary")
        fit_view = create_button("Fit", "secondary")
        rotate_left.clicked.connect(lambda: self._nudge_rotation(-90))
        rotate_right.clicked.connect(lambda: self._nudge_rotation(90))
        reset_crop.clicked.connect(self._reset_crop)
        zoom_out.clicked.connect(lambda: self.graphics_view.zoom_by(0.8))
        zoom_in.clicked.connect(lambda: self.graphics_view.zoom_by(1.25))
        fit_view.clicked.connect(self.graphics_view.fit_scene)

        rotation_row.addWidget(rotate_left)
        rotation_row.addWidget(rotate_right)
        rotation_row.addStretch()
        rotation_row.addWidget(zoom_out)
        rotation_row.addWidget(zoom_in)
        rotation_row.addWidget(fit_view)
        rotation_row.addWidget(reset_crop)
        self.body_layout.addLayout(rotation_row)

        explanation = QLabel(
            "Drag the angle ruler left or right without endpoints. Use the "
            "mouse wheel to zoom and the middle mouse button to pan. Then "
            "drag over whichever passport photo you want; the 4:5 outlined "
            "area is what will upload."
        )
        explanation.setObjectName("MutedText")
        explanation.setWordWrap(True)
        self.body_layout.addWidget(explanation)

        reject_button = create_button("Cancel", "secondary")
        approve_button = create_button("Approve Photo", "success")
        reject_button.clicked.connect(self.reject)
        approve_button.clicked.connect(self._approve)
        self.footer.add_action(reject_button)
        self.footer.add_action(approve_button)
        approve_button.setDefault(True)
        self.approve_button = approve_button
        self.approve_button.setEnabled(False)
        self.reject_button = reject_button
        self.rotate_left_button = rotate_left
        self.rotate_right_button = rotate_right
        self.reset_crop_button = reset_crop
        self.zoom_out_button = zoom_out
        self.zoom_in_button = zoom_in
        self.fit_view_button = fit_view

        if self.photo_path is not None:
            self._load_photo(self.photo_path)
        else:
            self._show_empty_state()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._position_rotation_ruler)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._position_rotation_ruler)

    def _position_rotation_ruler(self):
        graphics_view = getattr(self, "graphics_view", None)
        rotation_ruler = getattr(self, "rotation_ruler", None)
        if graphics_view is None or rotation_ruler is None:
            return
        viewport_geometry = graphics_view.viewport().geometry()
        width = max(260, min(500, viewport_geometry.width() - 36))
        x = viewport_geometry.x() + max(
            0, (viewport_geometry.width() - width) // 2
        )
        y = viewport_geometry.y() + max(
            0, viewport_geometry.height() - rotation_ruler.height() - 16
        )
        rotation_ruler.setGeometry(x, y, width, rotation_ruler.height())
        rotation_ruler.raise_()
        empty_state = getattr(self, "empty_state", None)
        if empty_state is not None and empty_state.isVisible():
            empty_state.setGeometry(graphics_view.viewport().geometry())
            empty_state.raise_()

    def _show_empty_state(self):
        self.graphics_view.clear_crop()
        self.approve_button.setEnabled(False)
        self.rotation_ruler.hide()
        self.empty_state.setGeometry(self.graphics_view.viewport().geometry())
        self.empty_state.show()
        self.empty_state.raise_()

    def _pick_photo(self):
        selected_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Photo or Passport PDF",
            downloads_folder(),
            (
                "Photos and Passport PDFs "
                "(*.pdf *.jpg *.jpeg *.jfif *.png *.bmp *.tif *.tiff *.webp)"
            ),
        )
        if not selected_path:
            return
        if Path(selected_path).suffix.lower() == ".pdf":
            try:
                candidate = PassportPhotoService().extract(selected_path)
            except (OSError, ValueError):
                candidate = None
            if candidate is None:
                self.empty_message.setText(
                    "That PDF could not be opened. Choose another file."
                )
                return
            self._discard_owned_photo()
            self.photo_path = Path(candidate.path)
            self._owns_photo_path = True
            self._load_photo(self.photo_path)
            return
        try:
            with Image.open(selected_path) as opened:
                image = ImageOps.exif_transpose(opened).convert("RGB")
                descriptor, temporary_name = tempfile.mkstemp(
                    prefix="missionary-photo-",
                    suffix=".jpg",
                )
                os.close(descriptor)
                image.save(temporary_name, "JPEG", quality=95)
        except (OSError, ValueError):
            self.empty_message.setText("That photo could not be opened. Choose another file.")
            return
        self._discard_owned_photo()
        self.photo_path = Path(temporary_name)
        self._owns_photo_path = True
        self._load_photo(self.photo_path)

    def _load_photo(self, path):
        self.original_pixmap = QPixmap(str(path))
        if self.original_pixmap.isNull():
            self._show_empty_state()
            return
        self.preview_pixmap = self.original_pixmap.scaled(
            1200,
            1200,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.scene.clear()
        self.graphics_view.crop_item = None
        self.pixmap_item = QGraphicsPixmapItem(self.preview_pixmap)
        self.pixmap_item.setTransformationMode(Qt.SmoothTransformation)
        self.pixmap_item.setTransformOriginPoint(self.pixmap_item.boundingRect().center())
        self.scene.addItem(self.pixmap_item)
        self.rotation_angle = 0.0
        self.rotation_ruler.set_angle(0.0)
        self.empty_state.hide()
        self.rotation_ruler.show()
        self._update_preview(fit_view=True)

    def _discard_owned_photo(self):
        if self._owns_photo_path and self.photo_path is not None:
            try:
                self.photo_path.unlink(missing_ok=True)
            except OSError:
                pass
        self._owns_photo_path = False

    def _nudge_rotation(self, amount):
        self.rotation_ruler.set_angle(self.rotation_angle + amount)

    def _rotation_changed(self, value):
        self.rotation_angle = float(value)
        self._rotation_preview_timer.start()

    def _reset_crop(self):
        self.graphics_view.clear_crop()
        self.approve_button.setEnabled(False)

    def _crop_changed(self, rect):
        self.approve_button.setEnabled(rect is not None and not rect.isEmpty())

    def _update_preview(self, *, fit_view=False):
        if self.preview_pixmap.isNull() or self.pixmap_item is None:
            self.scene.clear()
            self.scene.addText("Photo preview unavailable")
            return

        self.pixmap_item.setPos(0, 0)
        self.pixmap_item.setRotation(self.rotation_angle)
        raw_bounds = self.pixmap_item.sceneBoundingRect()
        self.pixmap_item.setPos(-raw_bounds.left(), -raw_bounds.top())
        bounds = self.pixmap_item.sceneBoundingRect()
        self._preview_rotated_size = bounds.size().toSize()
        self.scene.setSceneRect(bounds)
        if fit_view:
            self.graphics_view.fit_scene()
        self._position_rotation_ruler()

    def _approve(self):
        if self._rotation_preview_timer.isActive():
            self._rotation_preview_timer.stop()
            self._update_preview()
        if self._save_edited_photo():
            self.accept()

    def reject(self):
        self._discard_owned_photo()
        super().reject()

    def _save_edited_photo(self):
        crop_rect = self.graphics_view.get_crop_rect()
        try:
            with Image.open(self.photo_path) as opened:
                image = ImageOps.exif_transpose(opened).convert("RGB")
                rotated = image.rotate(
                    -self.rotation_angle,
                    expand=True,
                    resample=Image.Resampling.BICUBIC,
                )
                if crop_rect is not None:
                    preview_size = self._preview_rotated_size
                    scale_x = (
                        rotated.width / preview_size.width()
                        if preview_size is not None and preview_size.width()
                        else 1.0
                    )
                    scale_y = (
                        rotated.height / preview_size.height()
                        if preview_size is not None and preview_size.height()
                        else 1.0
                    )
                    left = max(0, int(round(crop_rect.left() * scale_x)))
                    top = max(0, int(round(crop_rect.top() * scale_y)))
                    right = min(
                        rotated.width,
                        int(round(crop_rect.right() * scale_x)),
                    )
                    bottom = min(
                        rotated.height,
                        int(round(crop_rect.bottom() * scale_y)),
                    )
                    if right > left and bottom > top:
                        rotated = rotated.crop((left, top, right, bottom))
                output = ImageOps.fit(
                    rotated,
                    self.OUTPUT_SIZE,
                    method=Image.Resampling.LANCZOS,
                )
                edited_path = self.photo_path.with_name(
                    f"{self.photo_path.stem}-edited.jpg"
                )
                output.save(edited_path, "JPEG", quality=92, optimize=True)
            edited_path.replace(self.photo_path)
            return True
        except (OSError, ValueError):
            self.scene.clear()
            self.scene.addText("The edited photo could not be saved.")
            return False
