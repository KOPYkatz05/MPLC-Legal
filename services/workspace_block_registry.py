from copy import deepcopy


DEFAULT_VARIANTS = ("summary", "list", "detail")
DEFAULT_DENSITIES = ("compact", "comfortable", "spacious")

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

_PRESENTATION_MANIFESTS = {
    "personal_info": {"default_variant": "summary", "allowed_variants": ["summary", "detail"], "max_items_by_size": {"compact": 3, "normal": 4, "large": 8}},
    "documents": {"default_variant": "summary", "allowed_variants": ["summary", "list"], "max_items_by_size": {"compact": 2, "normal": 4, "large": 8}},
    "document_viewer": {"default_variant": "detail", "allowed_variants": ["summary", "detail"], "max_items_by_size": {"compact": 1, "normal": 1, "large": 1}},
    "web_viewer": {"default_variant": "detail", "allowed_variants": ["summary", "detail"], "max_items_by_size": {"compact": 1, "normal": 1, "large": 1}},
    "missing_documents": {"default_variant": "summary", "allowed_variants": ["summary", "list"], "max_items_by_size": {"compact": 1, "normal": 2, "large": 5}},
    "workflow": {"default_variant": "summary", "allowed_variants": ["summary", "list"], "max_items_by_size": {"compact": 1, "normal": 2, "large": 5}},
    "open_tasks": {"default_variant": "summary", "allowed_variants": ["summary", "list"], "max_items_by_size": {"compact": 2, "normal": 3, "large": 8}},
    "notes": {"default_variant": "summary", "allowed_variants": ["summary", "detail"], "max_items_by_size": {"compact": 1, "normal": 1, "large": 1}},
    "residency_timeline": {"default_variant": "summary", "allowed_variants": ["summary", "timeline"], "max_items_by_size": {"compact": 2, "normal": 4, "large": 8}},
    "quick_actions": {"default_variant": "action_panel", "allowed_variants": ["action_panel", "summary"], "max_items_by_size": {"compact": 2, "normal": 4, "large": 6}},
    "appointments": {"default_variant": "summary", "allowed_variants": ["summary", "list"], "max_items_by_size": {"compact": 1, "normal": 3, "large": 7}},
    "status_summary": {"default_variant": "compact_metric", "allowed_variants": ["compact_metric", "summary"], "max_items_by_size": {"compact": 2, "normal": 4, "large": 5}},
    "document_checklist": {"default_variant": "summary", "allowed_variants": ["summary", "list"], "max_items_by_size": {"compact": 2, "normal": 4, "large": 8}},
    "task_board": {"default_variant": "summary", "allowed_variants": ["summary", "list"], "max_items_by_size": {"compact": 2, "normal": 3, "large": 8}},
    "notes_editor": {"default_variant": "detail", "allowed_variants": ["summary", "detail"], "max_items_by_size": {"compact": 1, "normal": 1, "large": 1}},
    "contact_info": {"default_variant": "summary", "allowed_variants": ["summary", "detail"], "max_items_by_size": {"compact": 2, "normal": 4, "large": 6}},
    "workflow_next_steps": {"default_variant": "summary", "allowed_variants": ["summary", "list"], "max_items_by_size": {"compact": 1, "normal": 3, "large": 5}},
    "recent_activity": {"default_variant": "summary", "allowed_variants": ["summary", "list"], "max_items_by_size": {"compact": 2, "normal": 3, "large": 6}},
    "link_list": {"default_variant": "summary", "allowed_variants": ["summary", "list"], "max_items_by_size": {"compact": 2, "normal": 4, "large": 8}},
}

BLOCK_LABELS = {key: value["i18n_key"] for key, value in _BLOCKS.items()}


def block_types():
    return list(_BLOCKS.keys())


def block_definition(block_type):
    definition = deepcopy(
        _BLOCKS.get(
            block_type,
            {
                "label": str(block_type),
                "i18n_key": "workspace_block_unsupported",
                "icon": "?",
                "default_size": (6, 2),
                "min_size": (1, 1),
            },
        )
    )
    definition.update(
        deepcopy(
            _PRESENTATION_MANIFESTS.get(
                block_type,
                {
                    "default_variant": "summary",
                    "allowed_variants": ["summary"],
                    "max_items_by_size": {"compact": 1, "normal": 3, "large": 6},
                },
            )
        )
    )
    return definition


def block_size_bucket(block):
    layout = block.get("layout") if isinstance(block.get("layout"), dict) else {}
    try:
        row_span = int(layout.get("row_span") or 2)
        col_span = int(layout.get("col_span") or 6)
    except (TypeError, ValueError):
        row_span = 2
        col_span = 6
    area = row_span * col_span
    if row_span <= 1 or area <= 8:
        return "compact"
    if row_span >= 4 or area >= 28:
        return "large"
    return "normal"


def block_presentation(block):
    definition = block_definition(block.get("type"))
    allowed = definition.get("allowed_variants") or list(DEFAULT_VARIANTS)
    variant = block.get("variant") or definition.get("default_variant") or allowed[0]
    if variant not in allowed:
        variant = allowed[0]
    density = block.get("density") or "comfortable"
    if density not in DEFAULT_DENSITIES:
        density = "comfortable"
    bucket = block_size_bucket(block)
    max_items = definition.get("max_items_by_size", {}).get(bucket, 3)
    try:
        content_limit = int(block.get("content_limit") or max_items)
    except (TypeError, ValueError):
        content_limit = max_items
    return {
        "variant": variant,
        "density": density,
        "size_bucket": bucket,
        "content_limit": max(1, min(content_limit, max_items)),
        "overflow": block.get("overflow") or definition.get("overflow") or "view_all",
        "allowed_variants": list(allowed),
    }


def default_block_payload(block_type):
    definition = block_definition(block_type)
    col_span, row_span = definition.get("default_size", (6, 2))
    payload = deepcopy(definition.get("default_settings", {}))
    payload.update({
        "type": block_type,
        "title": definition.get("label", str(block_type)),
        "variant": definition.get("default_variant", "summary"),
        "density": "comfortable",
        "overflow": definition.get("overflow", "view_all"),
        "width": "full" if col_span >= 12 else "half",
        "height": "compact" if row_span <= 1 else "tall" if row_span >= 3 else "normal",
        "layout": {"row": 0, "col": 0, "row_span": row_span, "col_span": col_span},
    })
    return payload
