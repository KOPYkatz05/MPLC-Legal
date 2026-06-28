from pathlib import Path

import fitz

from PySide6.QtCore import (
    Qt,
    QSize,
)

from PySide6.QtGui import (
    QPixmap,
    QImage,
    QTransform,
)

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QWidget,
    QListWidgetItem,
    QGraphicsScene,
    QGraphicsPixmapItem,
)

from ui.widgets.crop_graphics_view import (
    CropGraphicsView,
)
from ui.foundation import (
    DialogFooter,
    create_button,
    create_list_widget,
    create_slider,
    setup_dialog_shell,
)


class DocumentEditorDialog(QDialog):

    def __init__(
        self,
        file_path,
        parent=None,
    ):
        super().__init__(parent)

        self.file_path = Path(file_path)

        self.document = None

        self.current_page = 0

        self.rotation_angle = 0

        self.current_pixmap = None

        self.setWindowTitle(
            "Document Editor"
        )

        self.surface = setup_dialog_shell(
            self,
            surface_min_width=1200,
            surface_min_height=800,
            use_masked_shell=False,
        )

        self.resize(
            1200,
            800,
        )

        self.setup_ui()

        self.load_document()

    def setup_ui(self):

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.surface.setLayout(
            main_layout
        )

        header = QFrame()
        header.setObjectName("DocumentEditorDialogHeader")
        header.setAttribute(Qt.WA_StyledBackground, True)
        header_layout = QVBoxLayout()
        header_layout.setContentsMargins(18, 16, 18, 12)
        header_layout.setSpacing(4)
        header.setLayout(header_layout)

        title = QLabel("Document Editor")
        title.setObjectName("DocumentEditorDialogTitle")
        subtitle = QLabel(
            "Review the selected page, rotation, and crop area before export."
        )
        subtitle.setObjectName("DocumentEditorDialogSubtitle")
        subtitle.setWordWrap(True)
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)

        main_layout.addWidget(
            header
        )

        body = QWidget()
        body.setObjectName("DocumentEditorDialogBody")
        body.setAttribute(
            Qt.WA_StyledBackground,
            True,
        )

        body_layout = QVBoxLayout()
        body_layout.setContentsMargins(18, 16, 18, 16)
        body_layout.setSpacing(12)
        body.setLayout(body_layout)

        # =====================================
        # Main Editor Area
        # =====================================

        editor_layout = QHBoxLayout()
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(12)

        body_layout.addLayout(
            editor_layout,
            stretch=1,
        )

        # =====================================
        # PDF Page List
        # =====================================

        self.page_list = create_list_widget()
        self.page_list.setObjectName("DocumentEditorPageList")

        self.page_list.setFixedWidth(
            180
        )

        editor_layout.addWidget(
            self.page_list
        )

        # =====================================
        # Graphics Scene
        # =====================================

        self.scene = QGraphicsScene()

        self.graphics_view = (
            CropGraphicsView()
        )
        self.graphics_view.setObjectName("DocumentEditorGraphicsView")

        self.graphics_view.setScene(
            self.scene
        )

        editor_layout.addWidget(
            self.graphics_view,
            stretch=1,
        )

        # =====================================
        # Rotation Slider
        # =====================================

        self.rotation_slider = create_slider(
            Qt.Horizontal
        )
        self.rotation_slider.setObjectName("DocumentEditorRotationSlider")

        self.rotation_slider.setRange(
            -180,
            180,
        )

        self.rotation_slider.setValue(
            0
        )

        body_layout.addWidget(
            self.rotation_slider
        )

        main_layout.addWidget(
            body,
            stretch=1,
        )

        # =====================================
        # Buttons
        # =====================================

        self.cancel_button = create_button("Cancel", "secondary")

        self.confirm_button = create_button("Confirm", "primary")

        footer = DialogFooter()
        footer.setObjectName("DocumentEditorDialogFooter")
        footer.add_action(
            self.cancel_button
        )
        footer.add_action(
            self.confirm_button
        )

        main_layout.addWidget(
            footer
        )

        # =====================================
        # Signals
        # =====================================

        self.cancel_button.clicked.connect(
            self.reject
        )

        self.confirm_button.clicked.connect(
            self.accept
        )

        self.page_list.currentRowChanged.connect(
            self.change_page
        )

        self.rotation_slider.valueChanged.connect(
            self.rotation_changed
        )

    def load_document(self):

        suffix = (
            self.file_path.suffix.lower()
        )

        if suffix == ".pdf":
            self.load_pdf()

        else:
            self.load_image()

    def load_pdf(self):

        self.document = fitz.open(
            str(self.file_path)
        )

        self.page_list.clear()

        for page_index in range(
            len(self.document)
        ):

            item = QListWidgetItem(
                f"Page {page_index + 1}"
            )

            item.setSizeHint(
                QSize(
                    140,
                    40,
                )
            )

            self.page_list.addItem(
                item
            )

        self.page_list.setCurrentRow(
            0
        )

    def load_image(self):

        self.page_list.hide()

        self.current_pixmap = QPixmap(
            str(self.file_path)
        )

        self.update_preview()

    def change_page(
        self,
        index,
    ):

        if (
            self.document is None
            or index < 0
        ):
            return

        self.current_page = index

        page = self.document.load_page(
            index
        )

        pix = page.get_pixmap(
            dpi=250
        )

        image = QImage(
            pix.samples,
            pix.width,
            pix.height,
            pix.stride,
            QImage.Format_RGB888,
        )

        self.current_pixmap = (
            QPixmap.fromImage(
                image.copy()
            )
        )

        self.update_preview()

    def rotation_changed(
        self,
        value,
    ):

        self.rotation_angle = value

        self.update_preview()

    def update_preview(self):

        if self.current_pixmap is None:
            return

        rotated = (
            self.current_pixmap.transformed(
                QTransform().rotate(
                    self.rotation_angle
                ),
                Qt.SmoothTransformation,
            )
        )

        self.scene.clear()

        pix_item = QGraphicsPixmapItem(
            rotated
        )

        self.scene.addItem(
            pix_item
        )

        self.scene.setSceneRect(
            pix_item.boundingRect()
        )

        self.graphics_view.fitInView(
            pix_item,
            Qt.KeepAspectRatio,
        )

    def get_rotation_angle(
        self,
    ):
        return self.rotation_angle

    def get_selected_page(
        self,
    ):
        return self.current_page

    def get_crop_rect(
        self,
    ):
        return (
            self.graphics_view
            .get_crop_rect()
        )

    def get_export_settings(
        self,
    ):
        return {
            "page": self.get_selected_page(),
            "rotation": self.get_rotation_angle(),
            "crop_rect": self.get_crop_rect(),
        }

    def closeEvent(
        self,
        event,
    ):

        if self.document:
            self.document.close()

        super().closeEvent(
            event
        )
