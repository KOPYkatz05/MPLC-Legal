from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from services.secretary_work_service import SecretaryWorkError, SecretaryWorkService
from ui.dialogs.office_work_dialogs import TaskDialog
from ui.foundation import (
    PageHeader,
    create_button,
    create_card,
    create_scroll_area,
    divider,
    show_message,
)


PRIORITY_COLORS = {
    "LOW": "#71717A",
    "NORMAL": "#2563EB",
    "IMPORTANT": "#D97706",
    "CRITICAL": "#DC2626",
}

STATUS_LABELS = {
    "OPEN": "To Do",
    "WAITING": "Waiting",
    "DONE": "Done",
    "ARCHIVED": "Archived",
}


class AlertWorkspacePage(QWidget):
    def __init__(self, main_window=None, service=None):
        super().__init__()
        self.setObjectName("AlertWorkspacePage")
        self.main_window = main_window
        self.service = service or SecretaryWorkService()
        self.task_id = None
        self.return_key = "dashboard"
        self.workspace = {}

        self.setup_ui()

    def setup_ui(self):
        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setLayout(outer)

        self.back_btn = create_button("Back", "secondary")
        self.back_btn.clicked.connect(self._go_back)
        self.edit_btn = create_button("Edit Task", "secondary")
        self.edit_btn.clicked.connect(self._edit_task)
        self.done_btn = create_button("Mark Done", "primary")
        self.done_btn.clicked.connect(self._mark_done)

        self.header = PageHeader(
            "Alert Workspace",
            "Mission Control / Alert Workspace",
            [self.back_btn, self.edit_btn, self.done_btn],
        )
        outer.addWidget(self.header)
        outer.addWidget(divider())

        scroll = create_scroll_area(single_direction=True)
        scroll.setObjectName("PageSurface")
        self.content = QWidget()
        self.content.setObjectName("PageSurface")
        self.content_layout = QVBoxLayout()
        self.content_layout.setContentsMargins(32, 24, 32, 32)
        self.content_layout.setSpacing(16)
        self.content.setLayout(self.content_layout)
        scroll.setWidget(self.content)
        outer.addWidget(scroll, stretch=1)

    def load_task(self, task_id, return_key="dashboard"):
        self.task_id = task_id
        self.return_key = return_key or "dashboard"
        try:
            self.workspace = self.service.get_task_workspace(task_id)
        except SecretaryWorkError as exc:
            self.workspace = {}
            self._render_error(str(exc))
            return

        self._render_workspace()

    def _render_workspace(self):
        self._clear_layout(self.content_layout)

        title = self.workspace.get("title", "Alert Workspace")
        self.header.set_title(title)
        self.header.set_subtitle(self._breadcrumb_text())

        status = self.workspace.get("status", "")
        self.done_btn.setVisible(status not in {"DONE", "ARCHIVED"})
        self.edit_btn.setVisible(status != "ARCHIVED")

        self.content_layout.addWidget(self._build_summary_card())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(16)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(16)
        left.addWidget(self._build_reason_card())
        left.addWidget(self._build_steps_card())
        left.addWidget(self._build_evidence_card())
        left.addStretch()

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(16)
        right.addWidget(self._build_missionaries_card())
        right.addStretch()

        body.addLayout(left, stretch=5)
        body.addLayout(right, stretch=4)
        self.content_layout.addLayout(body)
        self.content_layout.addStretch()

    def _render_error(self, message):
        self._clear_layout(self.content_layout)
        self.header.set_title("Alert Workspace")
        self.header.set_subtitle(self._breadcrumb_text())
        self.done_btn.setVisible(False)
        self.edit_btn.setVisible(False)

        card = create_card()
        layout = QVBoxLayout()
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(8)
        card.setLayout(layout)

        title = QLabel("Task not found")
        title.setObjectName("PanelTitle")
        detail = QLabel(message or "This task is no longer available.")
        detail.setObjectName("MutedText")
        detail.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(detail)
        self.content_layout.addWidget(card)
        self.content_layout.addStretch()

    def _build_summary_card(self):
        card = create_card()
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)
        card.setLayout(layout)

        eyebrow = QLabel("At a glance")
        eyebrow.setObjectName("SectionHeader")
        layout.addWidget(eyebrow)

        brief = QLabel(self.workspace.get("brief_text") or "This task needs review.")
        brief.setObjectName("PanelTitle")
        brief.setWordWrap(True)
        layout.addWidget(brief)

        facts = QHBoxLayout()
        facts.setContentsMargins(0, 0, 0, 0)
        facts.setSpacing(10)

        for fact in self.workspace.get("key_facts") or []:
            facts.addWidget(self._fact_tile(fact))
        facts.addStretch()

        office_btn = create_button("Open in Office Work", "subtle", fixed_height=28)
        office_btn.clicked.connect(self._open_in_office_work)
        facts.addWidget(office_btn)

        layout.addLayout(facts)
        return card

    def _build_reason_card(self):
        card = create_card()
        layout = QVBoxLayout()
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)
        card.setLayout(layout)

        title = QLabel("Why this alert is showing")
        title.setObjectName("PanelTitle")
        text = QLabel(self.workspace.get("why_text", "Review this task."))
        text.setObjectName("RowText")
        text.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(text)

        points = self.workspace.get("why_points") or []
        if points:
            point_row = QHBoxLayout()
            point_row.setContentsMargins(0, 4, 0, 0)
            point_row.setSpacing(8)
            for point in points[:4]:
                point_row.addWidget(self._chip(point, "#71717A"))
            point_row.addStretch()
            layout.addLayout(point_row)
        return card

    def _build_steps_card(self):
        card = create_card()
        layout = QVBoxLayout()
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)
        card.setLayout(layout)

        title = QLabel("Recommended next steps")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        for index, step in enumerate(self.workspace.get("recommended_steps") or [], 1):
            row = QFrame()
            row.setObjectName("AlertStepRow")
            row.setAttribute(Qt.WA_StyledBackground, True)
            row.setStyleSheet(
                "QFrame#AlertStepRow {"
                "background: #FAFAFA;"
                "border: 1px solid #F4F4F5;"
                "border-radius: 8px;"
                "}"
            )
            row_layout = QHBoxLayout()
            row_layout.setContentsMargins(10, 8, 10, 8)
            row_layout.setSpacing(10)
            row.setLayout(row_layout)

            number = QLabel(str(index))
            number.setObjectName("AlertStepNumber")
            number.setAlignment(Qt.AlignCenter)
            number.setFixedWidth(24)
            number.setStyleSheet(
                "QLabel#AlertStepNumber {"
                "color: #0F766E;"
                "border: 1px solid #99F6E4;"
                "border-radius: 8px;"
                "background: #F0FDFA;"
                "font-weight: 700;"
                "}"
            )
            label = QLabel(step)
            label.setObjectName("RowText")
            label.setWordWrap(True)

            row_layout.addWidget(number)
            row_layout.addWidget(label, stretch=1)
            layout.addWidget(row)

        return card

    def _build_evidence_card(self):
        card = create_card()
        layout = QVBoxLayout()
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        card.setLayout(layout)

        title = QLabel("Source details")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        evidence = self.workspace.get("evidence") or []
        if not evidence:
            empty = QLabel("No automation source details are attached.")
            empty.setObjectName("MutedText")
            layout.addWidget(empty)
            return card

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(6)
        for row, item in enumerate(evidence):
            key = QLabel(item.get("label", ""))
            key.setObjectName("MutedText")
            value = QLabel(item.get("value", ""))
            value.setObjectName("StrongText")
            value.setWordWrap(True)
            grid.addWidget(key, row, 0)
            grid.addWidget(value, row, 1)
        layout.addLayout(grid)
        return card

    def _build_missionaries_card(self):
        card = create_card()
        layout = QVBoxLayout()
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        card.setLayout(layout)

        missionaries = self.workspace.get("affected_missionaries") or []

        title = QLabel(f"Affected missionaries ({len(missionaries)})")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        if not missionaries:
            empty = QLabel("No missionaries are linked to this task.")
            empty.setObjectName("MutedText")
            empty.setWordWrap(True)
            layout.addWidget(empty)
            return card

        for missionary in missionaries:
            layout.addWidget(self._missionary_row(missionary))

        return card

    def _missionary_row(self, missionary):
        row = QFrame()
        row.setObjectName("AlertMissionaryRow")
        row.setAttribute(Qt.WA_StyledBackground, True)
        row.setStyleSheet(
            "QFrame#AlertMissionaryRow {"
            "background: #FAFAFA;"
            "border: 1px solid #E5E7EB;"
            "border-radius: 8px;"
            "}"
        )
        layout = QHBoxLayout()
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)
        row.setLayout(layout)

        text_stack = QVBoxLayout()
        text_stack.setContentsMargins(0, 0, 0, 0)
        text_stack.setSpacing(3)

        name = QLabel(missionary.get("name", "Missionary"))
        name.setObjectName("StrongText")
        name.setWordWrap(True)

        meta = QLabel(missionary.get("issue_summary") or "Review record")
        meta.setObjectName("MutedText")
        meta.setWordWrap(True)
        dates = QLabel(
            "  |  ".join([
                f"Stage: {missionary.get('current_stage') or 'No stage'}",
                f"Residency: {missionary.get('residency_expiration_text')}",
                f"Prorroga: {missionary.get('prorroga_expiration_text')}",
            ])
        )
        dates.setObjectName("MiniMutedText")
        dates.setWordWrap(True)

        text_stack.addWidget(name)
        text_stack.addWidget(meta)
        text_stack.addWidget(dates)

        open_btn = create_button("Open", "subtle", fixed_height=28)
        open_btn.clicked.connect(
            lambda _=None, missionary_id=missionary.get("id"):
            self._open_missionary(missionary_id)
        )

        layout.addLayout(text_stack, stretch=1)
        layout.addWidget(open_btn)
        return row

    def _breadcrumb_text(self):
        prefix = "Office Work" if self.return_key == "office_work" else "Mission Control"
        return f"{prefix} / Alert Workspace"

    @staticmethod
    def _fact_tile(fact):
        tile = QFrame()
        tile.setObjectName("AlertFactTile")
        tile.setAttribute(Qt.WA_StyledBackground, True)
        tile.setStyleSheet(
            "QFrame#AlertFactTile {"
            "background: #FFFFFF;"
            "border: 1px solid #E5E7EB;"
            "border-radius: 8px;"
            "}"
        )
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)
        tile.setLayout(layout)

        value = QLabel(str(fact.get("value", "")))
        value.setObjectName("StrongText")
        value.setStyleSheet(f"color: {fact.get('color', '#18181B')};")
        value.setWordWrap(True)
        label = QLabel(str(fact.get("label", "")))
        label.setObjectName("MiniMutedText")

        layout.addWidget(value)
        layout.addWidget(label)
        return tile

    @staticmethod
    def _chip(text, color):
        chip = QLabel(str(text or ""))
        chip.setObjectName("AlertWorkspaceChip")
        chip.setAlignment(Qt.AlignCenter)
        chip.setStyleSheet(
            "QLabel#AlertWorkspaceChip {"
            f"color: {color};"
            f"border: 1px solid {color};"
            "border-radius: 8px;"
            "padding: 3px 8px;"
            "background: #FFFFFF;"
            "font-size: 11px;"
            "font-weight: 600;"
            "}"
        )
        return chip

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                AlertWorkspacePage._clear_layout(item.layout())

    def _go_back(self):
        if self.main_window is not None and hasattr(self.main_window, "set_current_key"):
            self.main_window.set_current_key(self.return_key)

    def _mark_done(self):
        if self.task_id is None:
            return
        response = show_message(
            self,
            "Mark Task Done?",
            "Mark this alert task done once the records are resolved?",
            kind="question",
            buttons="yes_no",
        )
        if response not in {1, 16384}:
            return

        self.service.complete_task(self.task_id)
        self._refresh_related_pages()
        self.load_task(self.task_id, self.return_key)

    def _edit_task(self):
        if not self.workspace:
            return
        dialog = TaskDialog(self.service, task=self.workspace, parent=self)
        if dialog.exec():
            self._refresh_related_pages()
            self.load_task(self.task_id, self.return_key)

    def _open_missionary(self, missionary_id):
        if missionary_id is None or self.main_window is None:
            return
        opener = getattr(self.main_window, "open_missionary_detail", None)
        if callable(opener):
            opener(missionary_id)

    def _open_in_office_work(self):
        if self.main_window is None:
            return
        office_page = getattr(self.main_window, "office_work_page", None)
        if office_page is not None and hasattr(office_page, "focus_task_context"):
            office_page.focus_task_context(
                task_id=self.task_id,
                title=self.workspace.get("title", ""),
            )
        if hasattr(self.main_window, "set_current_key"):
            self.main_window.set_current_key("office_work")

    def _refresh_related_pages(self):
        if self.main_window is None:
            return
        for attr in ("dashboard_page", "office_work_page", "calendar_page"):
            page = getattr(self.main_window, attr, None)
            if page is not None and hasattr(page, "load_data"):
                page.load_data()
