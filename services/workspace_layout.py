from copy import deepcopy


WORKSPACE_GRID_COLUMNS = 12


def _as_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def legacy_col_span(block, columns=WORKSPACE_GRID_COLUMNS):
    return columns if block.get("width") == "full" else max(1, columns // 2)


def legacy_row_span(block):
    return {
        "compact": 1,
        "normal": 2,
        "tall": 3,
    }.get(block.get("height"), 2)


def validate_block_layout(block, columns=WORKSPACE_GRID_COLUMNS):
    layout = block.get("layout") if isinstance(block.get("layout"), dict) else {}
    col_span = _as_int(layout.get("col_span"), legacy_col_span(block, columns))
    row_span = _as_int(layout.get("row_span"), legacy_row_span(block))
    col_span = max(1, min(columns, col_span))
    row_span = max(1, min(8, row_span))
    row = max(0, _as_int(layout.get("row"), 0))
    col = max(0, _as_int(layout.get("col"), 0))
    if col + col_span > columns:
        col = max(0, columns - col_span)
    return {
        "row": row,
        "col": col,
        "row_span": row_span,
        "col_span": col_span,
    }


def layouts_overlap(left, right):
    return not (
        left["col"] + left["col_span"] <= right["col"]
        or right["col"] + right["col_span"] <= left["col"]
        or left["row"] + left["row_span"] <= right["row"]
        or right["row"] + right["row_span"] <= left["row"]
    )


def _occupied_layouts(blocks, exclude_id=None, columns=WORKSPACE_GRID_COLUMNS):
    layouts = []
    for block in blocks:
        if block.get("id") == exclude_id:
            continue
        layout = validate_block_layout(block, columns)
        layouts.append(layout)
    return layouts


def first_available_layout(
    blocks,
    desired,
    block_id=None,
    columns=WORKSPACE_GRID_COLUMNS,
):
    desired = validate_block_layout({"layout": desired}, columns)
    occupied = _occupied_layouts(blocks, exclude_id=block_id, columns=columns)
    row = desired["row"]
    col = min(desired["col"], max(0, columns - desired["col_span"]))
    for _ in range(400):
        candidate = dict(desired, row=row, col=col)
        if not any(layouts_overlap(candidate, other) for other in occupied):
            return candidate
        col += 1
        if col + desired["col_span"] > columns:
            col = 0
            row += 1
    return dict(desired, row=row + 1, col=0)


def pack_blocks_to_grid(blocks, columns=WORKSPACE_GRID_COLUMNS):
    packed = []
    for block in blocks or []:
        next_block = deepcopy(block)
        desired = validate_block_layout(next_block, columns)
        next_block["layout"] = first_available_layout(
            packed,
            desired,
            block_id=next_block.get("id"),
            columns=columns,
        )
        packed.append(next_block)
    return packed


def normalize_workspace_layout(workspace, columns=WORKSPACE_GRID_COLUMNS):
    normalized = deepcopy(workspace or {})
    normalized["blocks"] = pack_blocks_to_grid(
        normalized.get("blocks", []),
        columns=columns,
    )
    return normalized


def update_block_layout(blocks, block_id, layout, columns=WORKSPACE_GRID_COLUMNS):
    updated = []
    for block in blocks or []:
        next_block = deepcopy(block)
        if next_block.get("id") == block_id:
            next_block["layout"] = validate_block_layout(
                {"layout": layout, "width": next_block.get("width"), "height": next_block.get("height")},
                columns,
            )
        updated.append(next_block)
    return pack_blocks_to_grid(updated, columns=columns)
