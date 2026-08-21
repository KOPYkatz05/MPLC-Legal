"""Page transformations used by printable packets."""

import fitz


def interpol_annotation_lines(missionary, document_service):
    api_client = getattr(document_service, "api_client", None)
    if api_client is not None:
        details = api_client.get("/v1/server/configuration")
    else:
        from server.configuration import load_server_configuration

        details = load_server_configuration()

    def first_name(value, override):
        override = str(override or "").strip()
        if override:
            return override
        tokens = str(value or "").strip().split()
        return tokens[0] if tokens else ""

    values = {
        "Area Office address": str(
            details.get("interpol_area_office_address") or ""
        ).strip(),
        "home address": str(getattr(missionary, "home_address", "") or "").strip(),
        "father name": first_name(
            getattr(missionary, "father_name", ""),
            getattr(missionary, "father_first_name_override", ""),
        ),
        "mother name": first_name(
            getattr(missionary, "mother_name", ""),
            getattr(missionary, "mother_first_name_override", ""),
        ),
        "secretary phone": str(
            details.get("interpol_secretary_phone") or ""
        ).strip(),
    }
    missing = [label for label, value in values.items() if not value]
    if missing:
        raise ValueError(
            "Add the following before generating the official copy: "
            + ", ".join(missing)
            + "."
        )
    return [
        f"Dirección Actual: {values['Area Office address']}",
        f"Dirección en País de Origen: {values['home address']}",
        f"Nombre de Padre: {values['father name']}",
        f"Nombre de Madre: {values['mother name']}",
        f"Teléfono: {values['secretary phone']}",
    ]


def annotate_interpol_passport(page, *, context):
    lines = context["interpol_annotation_lines"]
    rect = page.rect
    point = fitz.Point(rect.width * 0.14, rect.height * 0.72)
    page.insert_textbox(
        fitz.Rect(point.x, point.y, rect.width * 0.9, rect.height * 0.95),
        "\n".join(lines),
        fontsize=10,
        fontname="helv",
        color=(0, 0, 0),
        lineheight=1.45,
    )


PRINT_TRANSFORMS = {
    "interpol_passport": annotate_interpol_passport,
}

