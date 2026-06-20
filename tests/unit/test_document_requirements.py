from types import SimpleNamespace

from utils.constants import (
    required_documents_for_missionary,
    requires_fbi_document,
    visible_document_keys_for_missionary,
)


def _missionary(nationality):
    return SimpleNamespace(nationality=nationality)


def test_canadian_missionaries_require_fbi_for_interpol():
    missionary = _missionary("CAN")

    assert requires_fbi_document(missionary)
    assert "FBI" in visible_document_keys_for_missionary(missionary)
    assert "FBI" in required_documents_for_missionary("INTERPOL", missionary)


def test_non_fbi_country_does_not_require_fbi_for_interpol():
    missionary = _missionary("PER")

    assert not requires_fbi_document(missionary)
    assert "FBI" not in visible_document_keys_for_missionary(missionary)
    assert "FBI" not in required_documents_for_missionary("INTERPOL", missionary)
