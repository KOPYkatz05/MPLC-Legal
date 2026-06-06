import unittest
from types import SimpleNamespace

from utils.constants import (
    required_documents_for_missionary,
    visible_document_keys_for_missionary,
)


class DocumentRuleTests(unittest.TestCase):
    def missionary(self, nationality):
        return SimpleNamespace(nationality=nationality)

    def test_fbi_visible_only_for_exact_usa(self):
        self.assertIn(
            "FBI",
            visible_document_keys_for_missionary(self.missionary("USA")),
        )

        for nationality in (
            "US",
            "U.S.A.",
            "United States",
            "American",
            "",
            None,
        ):
            with self.subTest(nationality=nationality):
                self.assertNotIn(
                    "FBI",
                    visible_document_keys_for_missionary(
                        self.missionary(nationality)
                    ),
                )

    def test_fbi_required_only_for_usa_interpol(self):
        self.assertIn(
            "FBI",
            required_documents_for_missionary(
                "INTERPOL",
                self.missionary("USA"),
            ),
        )
        self.assertNotIn(
            "FBI",
            required_documents_for_missionary(
                "INTERPOL",
                self.missionary("US"),
            ),
        )
        self.assertNotIn(
            "FBI",
            required_documents_for_missionary(
                "CARNET DE EXTRANJERIA",
                self.missionary("USA"),
            ),
        )


if __name__ == "__main__":
    unittest.main()
