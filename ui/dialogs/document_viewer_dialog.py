from ui.dialogs.document_rendering import (
    get_document_viewer_render_hints,
    get_pdf_page_count,
    render_document_pixmap,
)
from ui.foundation import create_button, setup_dialog_shell
from utils.logger import logger
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsPixmapItem,
    QFrame,
    QSizePolicy,
    QScrollBar,
)

from PySide6.QtCore import Qt, QRectF


class DocumentViewerDialog(QDialog):
    def __init__(self, file_path, parent=None):
        super().__init__(parent)

        self.file_path = file_path

        self.setWindowTitle("Document Viewer")

        self.surface = setup_dialog_shell(
            self,
            surface_min_width=900,
            surface_min_height=700,
            use_masked_shell=False,
        )

        self._scale = 1.0

        self._pixmap = None

        self._scene = QGraphicsScene()

        self._item = None

        self.setup_ui()

        self._load_document()

    def setup_ui(self):
        layout = QVBoxLayout()

        layout.setContentsMargins(0, 0, 0, 0)

        layout.setSpacing(0)

        self.surface.setLayout(layout)

        # Header
        header = QFrame()

        header.setObjectName("PageHeader")

        header_layout = QHBoxLayout()

        header_layout.setContentsMargins(16, 10, 16, 10)

        header.setLayout(header_layout)

        self.title_label = QLabel("Document Viewer")

        self.title_label.setObjectName("PanelTitle")

        header_layout.addWidget(self.title_label)

        header_layout.addStretch()

        # Zoom controls
        zoom_out = create_button("Zoom Out", "secondary", fixed_height=28)

        zoom_out.clicked.connect(self._zoom_out)

        self.zoom_label = QLabel("100%")

        self.zoom_label.setObjectName("MutedText")

        self.zoom_label.setFixedWidth(50)

        self.zoom_label.setAlignment(
            Qt.AlignCenter
        )

        zoom_in = create_button("Zoom In", "secondary", fixed_height=28)

        zoom_in.clicked.connect(self._zoom_in)

        reset_btn = create_button("Fit", "secondary", fixed_height=28)

        reset_btn.clicked.connect(self._fit_to_window)

        close_btn = create_button("Close", "secondary", fixed_height=28)

        close_btn.clicked.connect(self.accept)

        header_layout.addWidget(zoom_out)

        header_layout.addWidget(self.zoom_label)

        header_layout.addWidget(zoom_in)

        header_layout.addWidget(reset_btn)

        header_layout.addWidget(close_btn)

        layout.addWidget(header)

        divider = QFrame()

        divider.setFixedHeight(1)

        divider.setObjectName("HeaderDivider")

        layout.addWidget(divider)

        # Graphics view
        self.view = QGraphicsView()

        self.view.setScene(self._scene)

        self.view.setAlignment(Qt.AlignCenter)

        self.view.setRenderHints(
            self.view.renderHints()
            | get_document_viewer_render_hints()
        )

        self.view.setBackgroundBrush(
            Qt.GlobalColor.lightGray
        )

        self.view.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Expanding,
        )

        layout.addWidget(self.view, stretch=1)

    def _load_document(self):
        try:
            path = self.file_path.lower()

            if path.endswith(".pdf"):
                self._load_pdf()

            elif path.endswith((
                ".png", ".jpg", ".jpeg",
                ".bmp", ".tiff", ".tif",
                ".webp",
            )):
                self._load_image()

            else:
                self._show_error(
                    "Unsupported file format."
                )

                return

        except Exception:
            logger.exception("Document load failed")

            self._show_error(
                "Failed to load document."
            )

    def _load_pdf(self):
        self._pixmap = render_document_pixmap(self.file_path, 0)

        self._show_pixmap()

        self.title_label.setText(
            f"Document Viewer - "
            f"Page 1 of {get_pdf_page_count(self.file_path)}"
        )

    def _load_image(self):
        self._pixmap = render_document_pixmap(self.file_path)

        self._show_pixmap()

        self.title_label.setText("Document Viewer")

    def _show_pixmap(self):
        if self._pixmap is None:
            return

        self._scene.clear()

        self._item = QGraphicsPixmapItem(
            self._pixmap
        )

        self._scene.addItem(self._item)

        self._scene.setSceneRect(
            QRectF(self._pixmap.rect())
        )

        self._scale = 1.0

        self._update_zoom()

    def _zoom_in(self):
        self._scale *= 1.25

        self._update_zoom()

    def _zoom_out(self):
        self._scale *= 0.8

        self._update_zoom()

    def _fit_to_window(self):
        if self._pixmap is None:
            return

        view_rect = self.view.viewport().rect()

        pix_rect = self._pixmap.rect()

        scale_w = (
            view_rect.width() - 40
        ) / pix_rect.width()

        scale_h = (
            view_rect.height() - 40
        ) / pix_rect.height()

        self._scale = min(scale_w, scale_h, 1.0)

        self._update_zoom()

    def _update_zoom(self):
        if self._item is None:
            return

        self._item.setScale(self._scale)

        self.zoom_label.setText(
            f"{int(self._scale * 100)}%"
        )

    def _show_error(self, message):
        self._scene.clear()

        label = QLabel(message)

        label.setObjectName("DangerText")

        self._scene.addWidget(label)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Plus:
            self._zoom_in()

        elif event.key() == Qt.Key_Minus:
            self._zoom_out()

        elif event.key() == Qt.Key_0:
            self._fit_to_window()

        elif event.key() == Qt.Key_Escape:
            self.accept()

        else:
            super().keyPressEvent(event)
