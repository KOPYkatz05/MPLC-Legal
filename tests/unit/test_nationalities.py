from types import SimpleNamespace

from utils.constants import is_usa_missionary, requires_fbi_document
from utils.nationalities import country_code, normalize_nationality


def test_passport_codes_are_normalized_to_country_names():
    assert normalize_nationality("USA") == "United States"
    assert normalize_nationality("per") == "Peru"


def test_country_names_are_idempotent_and_resolve_back_to_codes():
    assert normalize_nationality("United States") == "United States"
    assert country_code("united states") == "USA"


def test_country_name_storage_preserves_nationality_rules():
    missionary = SimpleNamespace(nationality="United States")
    assert is_usa_missionary(missionary)
    assert requires_fbi_document(missionary)
