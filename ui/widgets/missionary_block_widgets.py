from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout

from ui.foundation import (
    app_icon,
    create_button,
    create_card,
    create_info_badge,
)
from utils.constants import DOCUMENTS
from utils.language_helper import ui_text as tr


STAGE_TRANSLATION_KEYS = {
    "INTERPOL": "missionary_detail_stage_interpol",
    "CARNET DE EXTRANJERIA": "missionary_detail_stage_carnet_de_extranjeria",
    "PRORROGA": "missionary_detail_stage_prorroga",
    "CANCELACION": "missionary_detail_stage_cancelacion",
}

WORKFLOW_STATUS_TRANSLATION_KEYS = {
    "NOT STARTED": "missionary_detail_status_not_started",
    "IN PROGRESS": "missionary_detail_status_in_progress",
    "WAITING": "missionary_detail_status_waiting",
    "COMPLETED": "missionary_detail_status_completed",
    "BLOCKED": "missionary_detail_status_blocked",
}

DOCUMENT_TRANSLATION_KEYS = {
    "PHOTO": "missionary_detail_doc_photo",
    "PASSPORT": "missionary_detail_doc_passport",
    "FBI": "missionary_detail_doc_fbi",
    "TAM": "missionary_detail_doc_tam",
    "PAGO_INTERPOL": "missionary_detail_doc_pago_interpol",
    "CONSTANCIA_DE_CITA_INTERPOL": "missionary_detail_doc_constancia_de_cita_interpol",
    "FICHA_DE_CANJE_INTERNACIONAL": "missionary_detail_doc_ficha_de_canje_internacional",
    "PAGO_CARNE_DE_EXTRANJERIA": "missionary_detail_doc_pago_carne_de_extranjeria",
    "CONSTANCIA_DE_CITA_BIOMETRICO": "missionary_detail_doc_constancia_de_cita_biometrico",
    "CONSTANCIA_DE_TRAMITE_CARNE_DE_EXTRANJERIA": "missionary_detail_doc_constancia_de_tramite_carne_de_extranjeria",
    "CITA_RECOJO": "missionary_detail_doc_cita_recojo",
    "CARNE_DE_EXTRANJERIA": "missionary_detail_doc_carne_de_extranjeria",
    "PAGO_PRORROGA": "missionary_detail_doc_pago_prorroga",
    "CARTA_MINJUS": "missionary_detail_doc_carta_minjus",
    "DECLARACION_JURADA": "missionary_detail_doc_declaracion_jurada",
    "CONSTANCIA_DE_PRORROGA": "missionary_detail_doc_constancia_de_prorroga",
    "APROBACION_DE_PRORROGA": "missionary_detail_doc_aprobacion_de_prorroga",
    "PAGO_CANCELACION_DE_RESIDENCIA": "missionary_detail_doc_pago_cancelacion_de_residencia",
    "CONSTANCIA_CANCELACION": "missionary_detail_doc_constancia_cancelacion",
    "OTHER": "missionary_detail_doc_other",
}


def stage_display_name(stage):
    if not stage:
        return tr("missionary_detail_not_assigned")
    return tr(STAGE_TRANSLATION_KEYS.get(stage, stage))


def document_label(document_type):
    key = DOCUMENT_TRANSLATION_KEYS.get(document_type)
    if key:
        return tr(key)
    return DOCUMENTS.get(document_type, {}).get("label", document_type or "")


def workflow_status_label(status):
    return tr(WORKFLOW_STATUS_TRANSLATION_KEYS.get(status, status or ""))


def format_value(value):
    if value is None or value == "":
        return tr("missionary_detail_not_set")
    if hasattr(value, "strftime"):
        return value.strftime("%b %d, %Y")
    return str(value)


def build_empty_state_card(title, text, *, min_height=80, tone="muted"):
    card = create_card()
    card.setMinimumHeight(min_height)
    card.setProperty("tone", tone)
    layout = QVBoxLayout()
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(4)
    card.setLayout(layout)

    title_lbl = QLabel(title)
    title_lbl.setObjectName("StrongText")
    title_lbl.setWordWrap(True)

    text_lbl = QLabel(text)
    text_lbl.setObjectName("MutedText")
    text_lbl.setWordWrap(True)

    layout.addWidget(title_lbl)
    layout.addWidget(text_lbl)
    return card


def build_task_card(task, *, on_done=None, on_edit=None):
    card = create_card()
    layout = QHBoxLayout()
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(10)
    card.setLayout(layout)

    if task.get("is_group_task"):
        accent = QFrame()
        accent.setObjectName("TaskGroupAccent")
        accent.setFixedWidth(4)
        layout.addWidget(accent)

    copy = QVBoxLayout()
    copy.setContentsMargins(0, 0, 0, 0)
    copy.setSpacing(4)
    title = QLabel(task.get("title", tr("missionary_detail_untitled_task")))
    title.setObjectName("StrongText")
    copy.addWidget(title)

    status_labels = {
        "READY": "Ready",
        "WAITING": tr("missionary_detail_task_waiting"),
    }
    status_label = status_labels.get(
        task.get("status"),
        tr("missionary_detail_task_to_do"),
    )
    meta_parts = [task.get("priority", "NORMAL").title(), status_label]
    if task.get("due_date"):
        meta_parts.append(task["due_date"].strftime("%b %d, %Y"))
    else:
        meta_parts.append(tr("missionary_detail_no_due_date"))
    if task.get("waiting_reason_label"):
        meta_parts.append(task["waiting_reason_label"])
    if task.get("is_group_task"):
        shared_label = tr(
            "missionary_detail_shared_with",
            count=task.get("missionary_count", 0),
        )
        if task.get("group_scope_label"):
            shared_label = f"{shared_label} - {task['group_scope_label']}"
        meta_parts.append(shared_label)
    meta = QLabel("  |  ".join(meta_parts))
    meta.setObjectName("MutedText")
    meta.setWordWrap(True)
    copy.addWidget(meta)
    layout.addLayout(copy, stretch=1)

    if on_done is not None:
        done_btn = create_button(tr("missionary_detail_done"), "success", fixed_height=28)
        done_btn.clicked.connect(lambda checked=False: on_done(task))
        layout.addWidget(done_btn)
    if on_edit is not None:
        edit_btn = create_button(tr("missionary_detail_edit"), "secondary", fixed_height=28)
        edit_btn.clicked.connect(lambda checked=False: on_edit(task))
        layout.addWidget(edit_btn)
    return card


def build_document_card(
    doc,
    *,
    label=None,
    pixmap=None,
    on_view=None,
    on_notes=None,
    on_open=None,
    on_delete=None,
    show_thumbnail=True,
    pill_actions=False,
):
    card = create_card()
    card.setMinimumHeight(104)
    layout = QHBoxLayout()
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(10)
    card.setLayout(layout)

    if show_thumbnail:
        thumb = QLabel()
        thumb.setObjectName("DocumentThumb")
        thumb.setFixedSize(54, 64)
        thumb.setAlignment(Qt.AlignCenter)
        thumb.setProperty("document_thumbnail", True)
        if pixmap and not pixmap.isNull():
            thumb.setPixmap(pixmap.scaled(48, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            thumb.setText("DOC")
        layout.addWidget(thumb)

    copy = QVBoxLayout()
    copy.setContentsMargins(0, 0, 0, 0)
    copy.setSpacing(4)
    title_row = QHBoxLayout()
    title_row.setContentsMargins(0, 0, 0, 0)
    title_row.setSpacing(8)
    title = QLabel(label or document_label(getattr(doc, "document_type", None)))
    title.setObjectName("StrongText")
    status = QLabel(tr("missionary_detail_uploaded_status"))
    status.setObjectName("MutedText")
    status.setProperty("document_card_status", True)
    title_row.addWidget(title)
    title_row.addWidget(status)
    title_row.addStretch()
    copy.addLayout(title_row)

    file_name = QLabel(getattr(doc, "file_name", "") or "")
    file_name.setWordWrap(True)
    copy.addWidget(file_name)

    meta_text = []
    uploaded_at = getattr(doc, "uploaded_at", None)
    if uploaded_at:
        meta_text.append(tr("missionary_detail_uploaded_date", date=uploaded_at.strftime("%b %d, %Y")))
    workflow_stage = getattr(doc, "workflow_stage", None)
    if workflow_stage:
        meta_text.append(tr("missionary_detail_document_stage", stage=stage_display_name(workflow_stage)))
    if not meta_text:
        meta_text.append(tr("missionary_detail_added_to_record"))
    meta = QLabel("  *  ".join(meta_text))
    meta.setObjectName("MutedText")
    meta.setWordWrap(True)
    copy.addWidget(meta)
    layout.addLayout(copy, stretch=1)

    actions = QHBoxLayout()
    actions.setContentsMargins(0, 0, 0, 0)
    actions.setSpacing(8)
    actions.addStretch()
    for text_key, tone, icon_slot, fallback_icons, callback in (
        ("missionary_detail_view", "primary", "document.view", ("eye",), on_view),
        (
            "missionary_detail_notes",
            "secondary",
            "document.notes",
            ("notebook-pen", "notebook-text"),
            on_notes,
        ),
        (
            "missionary_detail_open",
            "subtle",
            "document.open",
            ("external-link",),
            on_open,
        ),
        (
            "delete_document",
            "danger",
            "document.delete",
            ("trash-2", "trash"),
            on_delete,
        ),
    ):
        if callback is None:
            continue
        if pill_actions:
            tooltip = tr(text_key)
            button = QToolButton()
            button.setObjectName("PillActionIconButton")
            button.setProperty("detailTone", tone)
            button.setCursor(Qt.PointingHandCursor)
            button.setFixedSize(26, 26)
            button.setToolTip(tooltip)
            button.setAccessibleName(tooltip)
            button.setAutoRaise(True)
            icon = app_icon(
                icon_slot,
                fallback_names=fallback_icons,
                size=18,
                color="#6B7280",
            )
            if icon is not None and not icon.isNull():
                button.setIcon(icon)
                button.setIconSize(QSize(18, 18))
            else:
                button.setText(tooltip[:1])
        else:
            button = create_button(tr(text_key), tone, fixed_height=28)
        button.clicked.connect(lambda checked=False, cb=callback: cb(doc))
        actions.addWidget(button)
    layout.addLayout(actions)
    return card


def build_workflow_stage_card(workflow, *, hint="", is_current=False, on_update=None):
    card = create_card()
    card.setMinimumHeight(84)
    layout = QHBoxLayout()
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(10)
    card.setLayout(layout)

    indicator = QLabel("*")
    indicator.setFixedWidth(16)
    indicator.setAlignment(Qt.AlignTop | Qt.AlignHCenter)

    copy = QVBoxLayout()
    copy.setContentsMargins(0, 0, 0, 0)
    copy.setSpacing(4)
    title_row = QHBoxLayout()
    title_row.setContentsMargins(0, 0, 0, 0)
    title_row.setSpacing(8)
    title = QLabel(stage_display_name(workflow.stage_name))
    title.setObjectName("StrongText")
    status = QLabel(workflow_status_label(workflow.status))
    status.setObjectName("MutedText")
    title_row.addWidget(title)
    title_row.addWidget(status)
    title_row.addStretch()
    copy.addLayout(title_row)

    hint_label = QLabel(hint or tr("missionary_detail_workflow_update_hint"))
    hint_label.setObjectName("MutedText")
    hint_label.setWordWrap(True)
    copy.addWidget(hint_label)
    layout.addWidget(indicator)
    layout.addLayout(copy, stretch=1)

    if is_current:
        badge = create_info_badge(tr("missionary_detail_workflow_active_hint"))
        layout.addWidget(badge)
    if on_update is not None:
        button = create_button(tr("missionary_detail_update_status"), "subtle", fixed_height=28)
        button.clicked.connect(lambda checked=False: on_update(workflow))
        layout.addWidget(button)
    return card


def build_missing_stage_card(
    stage_name,
    missing_docs,
    *,
    is_current=False,
    summary_text="",
    reason_for_doc=None,
):
    card = create_card()
    card.setMinimumHeight(84)
    layout = QVBoxLayout()
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(6)
    card.setLayout(layout)

    title_text = (
        tr("missionary_detail_always_required")
        if stage_name == "Always required"
        else tr("missionary_detail_required_for_stage", stage=stage_display_name(stage_name))
    )
    badge_text = (
        tr("missionary_detail_highest_priority")
        if stage_name == "Always required"
        else tr("missionary_detail_current_priority")
        if is_current
        else tr("missionary_detail_upcoming")
    )
    header = QHBoxLayout()
    header.setContentsMargins(0, 0, 0, 0)
    header.setSpacing(6)
    title = QLabel(title_text)
    title.setObjectName("MissingStageTitle")
    badge = QLabel(badge_text)
    badge.setObjectName("WarningBadge")
    header.addWidget(title)
    header.addWidget(badge)
    header.addStretch()
    layout.addLayout(header)

    summary = QLabel(summary_text or ", ".join(document_label(doc_key) for doc_key in missing_docs))
    summary.setObjectName("MutedText")
    summary.setWordWrap(True)
    layout.addWidget(summary)

    if reason_for_doc is not None:
        for doc_key in missing_docs:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            icon = QLabel("x")
            icon.setObjectName("DangerText")
            icon.setFixedWidth(18)
            copy = QVBoxLayout()
            copy.setContentsMargins(0, 0, 0, 0)
            copy.setSpacing(2)
            label = QLabel(document_label(doc_key))
            label.setWordWrap(True)
            hint = QLabel(reason_for_doc(doc_key, stage_name))
            hint.setObjectName("MutedText")
            hint.setWordWrap(True)
            copy.addWidget(label)
            copy.addWidget(hint)
            row.addWidget(icon)
            row.addLayout(copy, stretch=1)
            layout.addLayout(row)
    return card
