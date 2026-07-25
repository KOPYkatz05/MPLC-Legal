"""Helpers for keeping passport identifiers in their machine-readable form."""


def normalize_passport_number(value):
    """Remove all whitespace from a passport number without altering its characters."""
    if value is None:
        return None
    return "".join(str(value).split())
