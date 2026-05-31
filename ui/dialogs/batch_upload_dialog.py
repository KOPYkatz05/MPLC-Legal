import shutil

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QTableWidget,
    QTableWidgetItem,
    QComboBox,
    QFileDialog,
    QHeaderView,
    QAbstractItemView,
    QProgressBar,
)

from PySide6.QtCore import Qt, QThread, Signal

from database.db import SessionLocal

from database.models.document import Document

from utils.constants import DOCUMENTS

from utils.logger import logger


# Column indices in the table
COL_FILENAME = 0
COL_TYPE = 1
COL_STAGE = 2
COL_STATUS = 3


class BatchUploadDialog(QDialog):

    def __init__(self, missionary, parent=None):
        super().__init__(parent)

        self.missionary = missionary

        self.setWindowTitle("Batch Upload Documents")

        self.setMinimumWidth(760)

        self.setMinimumHeight(520)

        self._file_paths = []

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()

        layout.setContentsMargins(0, 0, 0, 0)

        layout.setSpacing(0)

        self.setLayout(layout)

        # ==========================================
        # Header
        # ==========================================

        header = QFrame()

        header.setObjectName("PageHeader")

        header_layout = QHBoxLayout()

        header_layout.setContentsMargins(
            24, 16, 24, 16
        )

        header.setLayout(header_layout)

        title = QLabel("Batch Upload Documents")

        title.setObjectName("PageTitle")

        add_files_btn = QPushButton(
            "+ Add Files"
        )

        add_files_btn.setObjectName("PrimaryButton")

        add_files_btn.setFixedHeight(32)

        add_files_btn.clicked.connect(
            self._pick_files
        )

        header_layout.addWidget(title)

        header_layout.addStretch()

        header_layout.addWidget(add_files_btn)

        layout.addWidget(header)

        divider = QFrame()

        divider.setObjectName("HeaderDivider")

        divider.setFixedHeight(1)

        layout.addWidget(divider)

        # ==========================================
        # Instruction label
        # ==========================================

        info = QLabel(
            "  Select files, assign document types, "
            "then click Upload All. "
            "Files are uploaded without cropping or "
            "OCR review for speed."
        )

        info.setStyleSheet(
            "background-color: #F4F4F5; "
            "color: #71717A; "
            "font-size: 12px; "
            "padding: 10px 24px;"
        )

        layout.addWidget(info)

        # ==========================================
        # Table
        # ==========================================

        self.table = QTableWidget()

        self.table.setObjectName("MissionaryTable")

        self.table.setColumnCount(4)

        self.table.setHorizontalHeaderLabels([
            "File Name",
            "Document Type",
            "Stage",
            "Status",
        ])

        self.table.setSelectionBehavior(
            QAbstractItemView.SelectRows
        )

        self.table.setEditTriggers(
            QAbstractItemView.NoEditTriggers
        )

        self.table.setAlternatingRowColors(True)

        self.table.verticalHeader().setVisible(False)

        self.table.setShowGrid(False)

        header_view = self.table.horizontalHeader()

        header_view.setSectionResizeMode(
            COL_FILENAME, QHeaderView.Stretch
        )

        header_view.setSectionResizeMode(
            COL_TYPE, QHeaderView.ResizeToContents
        )

        header_view.setSectionResizeMode(
            COL_STAGE, QHeaderView.ResizeToContents
        )

        header_view.setSectionResizeMode(
            COL_STATUS, QHeaderView.ResizeToContents
        )

        layout.addWidget(self.table, stretch=1)

        # ==========================================
        # Progress bar
        # ==========================================

        self.progress_bar = QProgressBar()

        self.progress_bar.setVisible(False)

        self.progress_bar.setFixedHeight(4)

        self.progress_bar.setStyleSheet(
            "QProgressBar { "
            "border: none; "
            "background: #E4E4E7; "
            "} "
            "QProgressBar::chunk { "
            "background-color: #3B82F6; "
            "}"
        )

        self.progress_bar.setTextVisible(False)

        layout.addWidget(self.progress_bar)

        # ==========================================
        # Footer
        # ==========================================

        footer_divider = QFrame()

        footer_divider.setObjectName(
            "HeaderDivider"
        )

        footer_divider.setFixedHeight(1)

        layout.addWidget(footer_divider)

        footer = QFrame()

        footer.setObjectName("PageHeader")

        footer_layout = QHBoxLayout()

        footer_layout.setContentsMargins(
            24, 12, 24, 12
        )

        footer.setLayout(footer_layout)

        self.status_label = QLabel(
            "No files selected."
        )

        self.status_label.setStyleSheet(
            "color: #A1A1AA; "
            "font-size: 12px; "
            "background: transparent;"
        )

        cancel_btn = QPushButton("Cancel")

        cancel_btn.clicked.connect(self.reject)

        self.upload_btn = QPushButton(
            "Upload All"
        )

        self.upload_btn.setObjectName(
            "PrimaryButton"
        )

        self.upload_btn.setFixedHeight(34)

        self.upload_btn.setEnabled(False)

        self.upload_btn.clicked.connect(
            self._upload_all
        )

        footer_layout.addWidget(self.status_label)

        footer_layout.addStretch()

        footer_layout.addWidget(cancel_btn)

        footer_layout.addWidget(self.upload_btn)

        layout.addWidget(footer)

    # ==========================================
    # FILE PICKING
    # ==========================================

    def _pick_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Documents",
            "",
            "Documents ("
            "*.pdf *.png *.jpg *.jpeg "
            "*.bmp *.tiff *.tif"
            ")",
        )

        if not files:
            return

        for f in files:
            if f not in self._file_paths:
                self._file_paths.append(f)

        self._populate_table()

    def _populate_table(self):
        self.table.setRowCount(
            len(self._file_paths)
        )

        type_keys = list(DOCUMENTS.keys())

        type_labels = [
            DOCUMENTS[k]["label"]
            for k in type_keys
        ]

        for row, fp in enumerate(self._file_paths):
            self.table.setRowHeight(row, 38)

            # Filename
            fn_item = QTableWidgetItem(
                Path(fp).name
            )

            fn_item.setData(
                Qt.UserRole, fp
            )

            self.table.setItem(
                row, COL_FILENAME, fn_item
            )

            # Document type combo
            combo = QComboBox()

            combo.setStyleSheet(
                "border: 1px solid #D4D4D8; "
                "border-radius: 4px; "
                "padding: 2px 6px; "
                "background: white;"
            )

            for label in type_labels:
                combo.addItem(label)

            combo.currentIndexChanged.connect(
                lambda idx, r=row: self._update_stage(r)
            )

            self.table.setCellWidget(
                row, COL_TYPE, combo
            )

            # Stage (auto-fill)
            stage_item = QTableWidgetItem("")

            self.table.setItem(
                row, COL_STAGE, stage_item
            )

            self._update_stage(row)

            # Status
            status_item = QTableWidgetItem("Pending")

            status_item.setForeground(
                Qt.gray
            )

            self.table.setItem(
                row, COL_STATUS, status_item
            )

        count = len(self._file_paths)

        self.status_label.setText(
            f"{count} file(s) ready to upload."
        )

        self.upload_btn.setEnabled(count > 0)

    def _update_stage(self, row):
        combo = self.table.cellWidget(
            row, COL_TYPE
        )

        if not combo:
            return

        label = combo.currentText()

        type_key = next(
            (
                k for k, v in DOCUMENTS.items()
                if v["label"] == label
            ),
            "OTHER",
        )

        stage = (
            DOCUMENTS.get(type_key, {})
            .get("stage", "")
            or ""
        )

        stage_item = self.table.item(
            row, COL_STAGE
        )

        if stage_item:
            stage_item.setText(stage)

    # ==========================================
    # UPLOAD
    # ==========================================

    def _get_row_data(self, row):
        fn_item = self.table.item(
            row, COL_FILENAME
        )

        if not fn_item:
            return None

        file_path = fn_item.data(Qt.UserRole)

        combo = self.table.cellWidget(
            row, COL_TYPE
        )

        label = (
            combo.currentText() if combo else ""
        )

        type_key = next(
            (
                k for k, v in DOCUMENTS.items()
                if v["label"] == label
            ),
            "OTHER",
        )

        stage = (
            DOCUMENTS.get(type_key, {})
            .get("stage", "")
            or "GENERAL"
        )

        return {
            "file_path": file_path,
            "type_key": type_key,
            "stage": stage,
        }

    def _set_status(self, row, text, color):
        item = self.table.item(row, COL_STATUS)

        if item:
            item.setText(text)

            from PySide6.QtGui import QColor

            item.setForeground(QColor(color))

    def _upload_all(self):
        self.upload_btn.setEnabled(False)

        total = self.table.rowCount()

        self.progress_bar.setVisible(True)

        self.progress_bar.setMaximum(total)

        self.progress_bar.setValue(0)

        uploaded = 0

        failed = 0

        for row in range(total):
            data = self._get_row_data(row)

            if not data:
                continue

            try:
                self._save_document(
                    data["file_path"],
                    data["type_key"],
                    data["stage"],
                )

                self._set_status(
                    row, "✓ Uploaded", "#059669"
                )

                uploaded += 1

            except Exception as e:
                logger.exception(
                    f"Batch upload failed row {row}"
                )

                self._set_status(
                    row,
                    f"✗ Failed: {str(e)[:40]}",
                    "#DC2626",
                )

                failed += 1

            self.progress_bar.setValue(row + 1)

        self.status_label.setText(
            f"Done: {uploaded} uploaded"
            + (
                f", {failed} failed"
                if failed
                else ""
            )
        )

        self.upload_btn.setText("Close")

        self.upload_btn.setEnabled(True)

        self.upload_btn.clicked.disconnect()

        self.upload_btn.clicked.connect(
            self.accept
        )

    def _save_document(
        self,
        source_file,
        document_type,
        workflow_stage,
    ):
        source_path = Path(source_file)

        if not source_path.exists():
            raise FileNotFoundError(
                f"File not found: {source_file}"
            )

        missionary = self.missionary

        folder = Path(missionary.folder_path)

        dest_folder = folder / (
            workflow_stage or "GENERAL"
        )

        dest_folder.mkdir(
            parents=True, exist_ok=True
        )

        ext = source_path.suffix

        new_name = f"{document_type}{ext}"

        dest_path = dest_folder / new_name

        counter = 1

        while dest_path.exists():
            new_name = (
                f"{document_type}_{counter}{ext}"
            )

            dest_path = dest_folder / new_name

            counter += 1

        shutil.copy2(
            str(source_path),
            str(dest_path),
        )

        session = SessionLocal()

        try:
            doc = Document(
                missionary_id=missionary.id,
                document_type=document_type,
                workflow_stage=workflow_stage,
                file_name=new_name,
                file_path=str(dest_path),
            )

            session.add(doc)

            session.commit()

            logger.info(
                f"Batch uploaded {new_name} "
                f"for {missionary.full_name}"
            )

        except Exception:
            session.rollback()

            raise

        finally:
            session.close()
