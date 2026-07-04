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
    create_button,
    create_card,
    create_scroll_area,
    show_message,
)
from utils.i18n import tr


PRIORITY_COLORS = {
    "LOW": "#71717A",
    "NORMAL": "#0EA5AC",
    "IMPORTANT": "#D97706",
    "CRITICAL": "#DC2626",
}
TONE_COLORS = {
    "#DC2626": "danger",
    "#D97706": "warning",
    "#0EA5AC": "info",
    "#059669": "success",
    "#71717A": "neutral",
    "#52525B": "neutral",
    "#18181B": "strong",
}


def _tone_from_color(color):
    return TONE_COLORS.get(str(color or "").upper(), "strong")

STATUS_LABELS = {
    "OPEN": "alert_workspace_status_open",
    "READY": "alert_workspace_status_ready",
    "WAITING": "alert_workspace_status_waiting",
    "DONE": "alert_workspace_status_done",
    "ARCHIVED": "alert_workspace_status_archived",
}


class _HeaderCompat:
    def __init__(self, title_label, subtitle_label):
        self.title_label = title_label
        self.subtitle_label = subtitle_label

    def set_title(self, title):
        self.title_label.setText(title)

    def set_subtitle(self, subtitle):
        self.subtitle_label.setText(subtitle)


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

        self.back_btn = create_button(tr("common_back"), "secondary")
        self.back_btn.clicked.connect(self._go_back)
        self.edit_btn = create_button(tr("alert_workspace_edit_task"), "secondary")
        self.edit_btn.clicked.connect(self._edit_task)
        self.follow_up_btn = create_button(
            tr("alert_workspace_set_follow_up"),
            "secondary",
        )
        self.follow_up_btn.clicked.connect(self._edit_task)
        self.ready_btn = create_button(tr("alert_workspace_mark_ready"), "secondary")
        self.ready_btn.clicked.connect(self._mark_ready)
        self.needs_work_btn = create_button(
            tr("alert_workspace_needs_work"),
            "secondary",
        )
        self.needs_work_btn.clicked.connect(self._mark_needs_work)
        self.done_btn = create_button(tr("alert_workspace_mark_done"), "primary")
        self.done_btn.clicked.connect(self._mark_done)

        outer.addWidget(self._build_top_bar())

        scroll = create_scroll_area(single_direction=True)
        scroll.setObjectName("AlertWorkspaceScroll")
        self.content = QWidget()
        self.content.setObjectName("AlertWorkspaceContent")
        self.content_layout = QVBoxLayout()
        self.content_layout.setContentsMargins(12, 12, 24, 24)
        self.content_layout.setSpacing(12)
        self.content.setLayout(self.content_layout)
        scroll.setWidget(self.content)
        outer.addWidget(scroll, stretch=1)

    def _build_top_bar(self):
        top_bar = QFrame()
        top_bar.setObjectName("AlertWorkspaceTopBar")
        top_bar.setAttribute(Qt.WA_StyledBackground, True)

        layout = QVBoxLayout()
        layout.setContentsMargins(12, 10, 16, 12)
        layout.setSpacing(8)
        top_bar.setLayout(layout)

        tabs = QFrame()
        tabs.setObjectName("AlertWorkspaceTabStrip")
        tabs.setAttribute(Qt.WA_StyledBackground, True)
        tabs_layout = QHBoxLayout()
        tabs_layout.setContentsMargins(0, 0, 0, 0)
        tabs_layout.setSpacing(0)
        tabs.setLayout(tabs_layout)

        for text, active in [
            (tr("alert_workspace_tab_brief"), True),
            (tr("alert_workspace_tab_people"), False),
            (tr("alert_workspace_tab_evidence"), False),
        ]:
            label = QLabel(text)
            label.setObjectName("AlertWorkspaceTopTab")
            label.setProperty("active", active)
            label.setFixedHeight(30)
            label.setAlignment(Qt.AlignCenter)
            tabs_layout.addWidget(label)
        tabs_layout.addStretch()
        layout.addWidget(tabs)

        command_row = QHBoxLayout()
        command_row.setContentsMargins(0, 0, 0, 0)
        command_row.setSpacing(12)

        title_stack = QVBoxLayout()
        title_stack.setContentsMargins(0, 0, 0, 0)
        title_stack.setSpacing(3)

        self.title_label = QLabel(tr("alert_workspace_title"))
        self.title_label.setObjectName("AlertWorkspaceTitle")
        self.subtitle_label = QLabel(
            tr("alert_workspace_breadcrumb_mission_control")
        )
        self.subtitle_label.setObjectName("AlertWorkspaceSubtitle")
        self.header = _HeaderCompat(self.title_label, self.subtitle_label)

        title_stack.addWidget(self.title_label)
        title_stack.addWidget(self.subtitle_label)

        command_row.addLayout(title_stack)
        command_row.addStretch()
        command_row.addWidget(self.back_btn)
        command_row.addWidget(self.edit_btn)
        command_row.addWidget(self.follow_up_btn)
        command_row.addWidget(self.ready_btn)
        command_row.addWidget(self.needs_work_btn)
        command_row.addWidget(self.done_btn)

        layout.addLayout(command_row)
        return top_bar

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

        title = self.workspace.get("title", tr("alert_workspace_title"))
        self.title_label.setText(title)
        self.subtitle_label.setText(self._breadcrumb_text())

        status = self.workspace.get("status", "")
        self.done_btn.setVisible(status not in {"DONE", "ARCHIVED"})
        self.edit_btn.setVisible(status != "ARCHIVED")
        self.follow_up_btn.setVisible(
            status == "WAITING"
            and self.workspace.get("waiting_follow_up_date") is None
        )
        self.ready_btn.setVisible(status in {"OPEN", "WAITING"})
        self.needs_work_btn.setVisible(status == "READY")

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
        self.title_label.setText(tr("alert_workspace_title"))
        self.subtitle_label.setText(self._breadcrumb_text())
        self.done_btn.setVisible(False)
        self.edit_btn.setVisible(False)
        self.follow_up_btn.setVisible(False)
        self.ready_btn.setVisible(False)
        self.needs_work_btn.setVisible(False)

        card = create_card(object_name="AlertWorkspaceErrorCard")
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(8)
        card.setLayout(layout)

        title = QLabel(tr("alert_workspace_task_not_found"))
        title.setObjectName("PanelTitle")
        detail = QLabel(message or tr("alert_workspace_task_unavailable"))
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

        eyebrow = QLabel(tr("alert_workspace_at_a_glance"))
        eyebrow.setObjectName("SectionHeader")
        layout.addWidget(eyebrow)

        brief = QLabel(
            self.workspace.get("brief_text")
            or tr("alert_workspace_needs_review")
        )
        brief.setObjectName("PanelTitle")
        brief.setWordWrap(True)
        layout.addWidget(brief)

        facts = QHBoxLayout()
        facts.setContentsMargins(0, 0, 0, 0)
        facts.setSpacing(10)

        for fact in self.workspace.get("key_facts") or []:
            facts.addWidget(self._fact_tile(fact))
        facts.addStretch()

        office_btn = create_button(
            tr("alert_workspace_open_office_work"),
            "subtle",
            fixed_height=28,
        )
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

        title = QLabel(tr("alert_workspace_why_title"))
        title.setObjectName("PanelTitle")
        text = QLabel(
            self.workspace.get("why_text")
            or tr("alert_workspace_review_task")
        )
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

        title = QLabel(tr("alert_workspace_steps_title"))
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        for index, step in enumerate(self.workspace.get("recommended_steps") or [], 1):
            row = QFrame()
            row.setObjectName("AlertStepRow")
            row.setAttribute(Qt.WA_StyledBackground, True)
            row_layout = QHBoxLayout()
            row_layout.setContentsMargins(10, 8, 10, 8)
            row_layout.setSpacing(10)
            row.setLayout(row_layout)

            number = QLabel(str(index))
            number.setObjectName("AlertStepNumber")
            number.setAlignment(Qt.AlignCenter)
            number.setFixedWidth(24)
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

        title = QLabel(tr("alert_workspace_source_title"))
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        evidence = self.workspace.get("evidence") or []
        if not evidence:
            empty = QLabel(tr("alert_workspace_no_source_details"))
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

        history = self.workspace.get("status_history") or []
        if history:
            history_title = QLabel(tr("alert_workspace_status_history_title"))
            history_title.setObjectName("PanelTitle")
            layout.addWidget(history_title)
            for item in history[:4]:
                layout.addWidget(self._history_row(item))
        return card

    @staticmethod
    def _history_row(item):
        row = QFrame()
        row.setObjectName("AlertStepRow")
        row.setAttribute(Qt.WA_StyledBackground, True)
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(3)
        row.setLayout(layout)

        summary = QLabel(item.get("summary", ""))
        summary.setObjectName("StrongText")
        summary.setWordWrap(True)
        timestamp = QLabel(item.get("created_at_text", ""))
        timestamp.setObjectName("MiniMutedText")
        timestamp.setWordWrap(True)

        layout.addWidget(summary)
        if timestamp.text():
            layout.addWidget(timestamp)
        return row

    def _build_missionaries_card(self):
        card = create_card()
        layout = QVBoxLayout()
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        card.setLayout(layout)

        missionaries = self.workspace.get("affected_missionaries") or []

        title = QLabel(
            tr("alert_workspace_affected_missionaries", count=len(missionaries))
        )
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        if not missionaries:
            empty = QLabel(tr("alert_workspace_no_missionaries"))
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
        layout = QHBoxLayout()
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)
        row.setLayout(layout)

        text_stack = QVBoxLayout()
        text_stack.setContentsMargins(0, 0, 0, 0)
        text_stack.setSpacing(3)

        name = QLabel(missionary.get("name", tr("missionary_label")))
        name.setObjectName("StrongText")
        name.setWordWrap(True)

        meta = QLabel(
            missionary.get("issue_summary")
            or tr("alert_workspace_review_record")
        )
        meta.setObjectName("MutedText")
        meta.setWordWrap(True)
        dates = QLabel(
            "  |  ".join([
                tr(
                    "alert_workspace_stage_meta",
                    value=missionary.get("current_stage")
                    or tr("alert_workspace_no_stage"),
                ),
                tr(
                    "alert_workspace_residency_meta",
                    value=missionary.get("residency_expiration_text"),
                ),
                tr(
                    "alert_workspace_prorroga_meta",
                    value=missionary.get("prorroga_expiration_text"),
                ),
            ])
        )
        dates.setObjectName("MiniMutedText")
        dates.setWordWrap(True)

        text_stack.addWidget(name)
        text_stack.addWidget(meta)
        text_stack.addWidget(dates)

        open_btn = create_button(tr("dashboard_action_open"), "subtle", fixed_height=28)
        open_btn.clicked.connect(
            lambda _=None, missionary_id=missionary.get("id"):
            self._open_missionary(missionary_id)
        )

        layout.addLayout(text_stack, stretch=1)
        layout.addWidget(open_btn)
        return row

    def _breadcrumb_text(self):
        if self.return_key == "office_work":
            return tr("alert_workspace_breadcrumb_office_work")
        return tr("alert_workspace_breadcrumb_mission_control")

    @staticmethod
    def _fact_tile(fact):
        tile = QFrame()
        tile.setObjectName("AlertFactTile")
        tile.setAttribute(Qt.WA_StyledBackground, True)
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)
        tile.setLayout(layout)

        value = QLabel(str(fact.get("value", "")))
        value.setObjectName("AlertFactValue")
        value.setProperty(
            "tone", _tone_from_color(fact.get("color", "#18181B"))
        )
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
        chip.setProperty("tone", _tone_from_color(color))
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
            tr("alert_workspace_mark_done_title"),
            tr("alert_workspace_mark_done_message"),
            kind="question",
            buttons="yes_no",
        )
        if response not in {1, 16384}:
            return

        self.service.complete_task(self.task_id)
        self._refresh_related_pages()
        self.load_task(self.task_id, self.return_key)

    def _mark_ready(self):
        if self.task_id is None:
            return
        self.service.mark_task_ready(self.task_id)
        self._refresh_related_pages()
        self.load_task(self.task_id, self.return_key)

    def _mark_needs_work(self):
        if self.task_id is None:
            return
        self.service.reopen_task(self.task_id)
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
