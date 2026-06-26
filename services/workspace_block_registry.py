from copy import deepcopy

BLOCK_CATEGORIES = {
    "Core": ["personal_info", "contact_info", "status_summary", "appointments"],
    "Documents": ["documents", "document_viewer", "missing_documents", "document_checklist"],
    "Workflow": ["workflow", "workflow_next_steps", "open_tasks", "task_board", "quick_actions"],
    "Content": ["notes", "notes_editor", "recent_activity", "link_list", "residency_timeline", "web_viewer"],
}

_BLOCKS = {
    "personal_info": {"label": "Personal Information", "i18n_key": "workspace_block_personal_info", "icon": "👤", "default_size": (6, 2), "min_size": (3, 1), "default_settings": {"fields": ["full_name", "nationality", "passport_number", "carnet_number"]}, "inspector_fields": ["title", "fields"]},
    "documents": {"label": "Documents", "i18n_key": "workspace_block_documents", "icon": "📄", "default_size": (6, 2), "min_size": (3, 1)},
    "document_viewer": {"label": "Document Viewer", "i18n_key": "workspace_block_document_viewer", "icon": "🔎", "default_size": (12, 3), "min_size": (4, 2), "default_settings": {"document_type": ""}, "inspector_fields": ["title", "document_type"]},
    "web_viewer": {"label": "Web Viewer", "i18n_key": "workspace_block_web_viewer", "icon": "🌐", "default_size": (12, 3), "min_size": (4, 2), "default_settings": {"web_url": "https://", "settings": {"open_external": True}}, "inspector_fields": ["title", "web_url"]},
    "missing_documents": {"label": "Missing Documents", "i18n_key": "workspace_block_missing_documents", "icon": "⚠️", "default_size": (6, 2), "min_size": (3, 1)},
    "workflow": {"label": "Workflow", "i18n_key": "workspace_block_workflow", "icon": "🧭", "default_size": (6, 2), "min_size": (3, 1), "supports_actions": True},
    "open_tasks": {"label": "Open Tasks", "i18n_key": "workspace_block_open_tasks", "icon": "✅", "default_size": (6, 2), "min_size": (3, 1), "supports_actions": True},
    "notes": {"label": "Notes", "i18n_key": "workspace_block_notes", "icon": "📝", "default_size": (6, 2), "min_size": (3, 1)},
    "residency_timeline": {"label": "Residency Timeline", "i18n_key": "workspace_block_residency_timeline", "icon": "📅", "default_size": (6, 2), "min_size": (3, 1)},
    "quick_actions": {"label": "Quick Actions", "i18n_key": "workspace_block_quick_actions", "icon": "⚡", "default_size": (6, 1), "min_size": (3, 1), "supports_actions": True, "default_settings": {"settings": {"actions": ["upload_document", "add_task", "open_folder", "update_workflow"]}}},
    "appointments": {"label": "Appointments", "i18n_key": "workspace_block_appointments", "icon": "🗓️", "default_size": (6, 2), "min_size": (3, 1)},
    "status_summary": {"label": "Status Summary", "i18n_key": "workspace_block_status_summary", "icon": "📊", "default_size": (6, 2), "min_size": (3, 1)},
    "document_checklist": {"label": "Document Checklist", "i18n_key": "workspace_block_document_checklist", "icon": "☑️", "default_size": (6, 2), "min_size": (3, 1)},
    "task_board": {"label": "Task Board", "i18n_key": "workspace_block_task_board", "icon": "📌", "default_size": (6, 2), "min_size": (3, 1)},
    "notes_editor": {"label": "Notes Editor", "i18n_key": "workspace_block_notes_editor", "icon": "✍️", "default_size": (6, 2), "min_size": (3, 1), "supports_actions": True},
    "contact_info": {"label": "Contact Info", "i18n_key": "workspace_block_contact_info", "icon": "☎️", "default_size": (6, 2), "min_size": (3, 1)},
    "workflow_next_steps": {"label": "Workflow Next Steps", "i18n_key": "workspace_block_workflow_next_steps", "icon": "➡️", "default_size": (6, 2), "min_size": (3, 1)},
    "recent_activity": {"label": "Recent Activity", "i18n_key": "workspace_block_recent_activity", "icon": "🕘", "default_size": (6, 2), "min_size": (3, 1)},
    "link_list": {"label": "Link List", "i18n_key": "workspace_block_link_list", "icon": "🔗", "default_size": (6, 2), "min_size": (3, 1), "default_settings": {"settings": {"links": []}}, "inspector_fields": ["title", "links"]},
}

BLOCK_LABELS = {key: value["i18n_key"] for key, value in _BLOCKS.items()}


def block_types():
    return list(_BLOCKS.keys())


def block_definition(block_type):
    return deepcopy(_BLOCKS.get(block_type, {"label": str(block_type), "i18n_key": "workspace_block_unsupported", "icon": "□", "default_size": (6, 2), "min_size": (1, 1)}))


def default_block_payload(block_type):
    definition = block_definition(block_type)
    col_span, row_span = definition.get("default_size", (6, 2))
    payload = deepcopy(definition.get("default_settings", {}))
    payload.update({
        "type": block_type,
        "title": definition.get("label", str(block_type)),
        "width": "full" if col_span >= 12 else "half",
        "height": "compact" if row_span <= 1 else "tall" if row_span >= 3 else "normal",
        "layout": {"row": 0, "col": 0, "row_span": row_span, "col_span": col_span},
    })
    return payload
