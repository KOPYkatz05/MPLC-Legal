"""Canonical whitespace handling for person names."""


def normalize_person_name(value):
    """Trim a name and collapse every run of whitespace to one space."""
    if value is None:
        return None
    return " ".join(str(value).split())
