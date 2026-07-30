import json
from datetime import date

from utils.logger import logger


def add_years(base_date, years):
    if not isinstance(base_date, date):
        return None

    try:
        return base_date.replace(year=base_date.year + years)
    except ValueError:
        return base_date.replace(
            year=base_date.year + years,
            day=28,
        )


def set_field_source(
    missionary,
    field,
    *,
    document_id=None,
    document_type=None,
    label=None,
):
    sources = {}
    if getattr(missionary, "field_sources", None):
        try:
            sources = json.loads(missionary.field_sources)
        except (json.JSONDecodeError, TypeError):
            sources = {}

    source = {}
    if document_id is not None:
        source["document_id"] = document_id
    if document_type:
        source["document_type"] = document_type
    if label:
        source["label"] = label

    sources[field] = source
    missionary.field_sources = json.dumps(sources)


def set_entry_based_expiration(
    missionary,
    field,
    years,
    *,
    document_id=None,
    document_type=None,
    label=None,
):
    arrival_date = getattr(missionary, "arrival_date", None)
    expiration = add_years(arrival_date, years)
    if not expiration:
        logger.warning(
            "Could not derive %s for missionary %s: missing arrival_date",
            field,
            getattr(missionary, "id", None),
        )
        return False

    setattr(missionary, field, expiration)
    set_field_source(
        missionary,
        field,
        document_id=document_id,
        document_type=document_type,
        label=label,
    )
    return True


def should_track_expiration_field(missionary, field):
    if (
        (getattr(missionary, "dynamics_status", "In-field") or "In-field")
        != "In-field"
    ):
        return False
    if (
        getattr(missionary, "tracking_profile", "LEGAL") or "LEGAL"
    ) == "PERUVIAN_DNI":
        return False
    if field == "visa_expiration" and getattr(
        missionary,
        "residency_expiration",
        None,
    ):
        return False

    return True


def apply_prorroga_completion_expiration(missionary):
    logger.info(
        "Skipping residency expiration update for missionary %s: "
        "prorroga approval is tracked from approval documents.",
        getattr(missionary, "id", None),
    )
    return False


def apply_stage_completion_expiration(missionary, stage_name):
    if stage_name == "PRORROGA":
        return apply_prorroga_completion_expiration(missionary)
    return False
