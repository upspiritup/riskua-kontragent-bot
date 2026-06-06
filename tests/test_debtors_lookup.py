from pathlib import Path
import unittest


FIXTURES = Path(__file__).parent / "fixtures"


class DebtorsLookupTests(unittest.TestCase):
    def fixture(self, name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    def test_build_debtors_result_url_returns_source_url(self):
        from app.services.debtors_lookup import build_debtors_result_url

        self.assertEqual(
            build_debtors_result_url(),
            "https://erb.minjust.gov.ua/#/search-debtors",
        )

    def test_fetch_debtors_registry_uses_mock_fetcher_and_parses_results(self):
        from app.services.debtors_lookup import fetch_debtors_registry

        calls: list[str] = []

        def fake_fetcher(edrpou: str) -> str:
            calls.append(edrpou)
            return self.fixture("debtors_registry_results.html")

        result = fetch_debtors_registry("05747991", fetcher=fake_fetcher)

        self.assertEqual(calls, ["05747991"])
        self.assertTrue(result["checked"])
        self.assertTrue(result["found"])
        self.assertEqual(result["items_count"], 5)
        self.assertEqual(result["searched_edrpou"], "05747991")
        self.assertEqual(result["items"][0]["edrpou"], "05747991")
        self.assertEqual(result["items"][0]["enforcement_proceeding_number"], "73477103")
        self.assertEqual(result["items"][0]["collection_category"], "стягнення судового збору")
        self.assertTrue(result["items"][0]["executor_details_available"])
        self.assertIn("стягнення заборгованості із заробітної плати", result["unique_categories"])
        self.assertEqual(
            result["proceeding_numbers"],
            ["73477103", "76936018", "69992338", "78788009", "77563164"],
        )
        self.assertIn("debtor_registry_found", result["risk_flags"])
        self.assertIn("multiple_debtor_records", result["risk_flags"])
        self.assertIn("salary_debt_enforcement_found", result["risk_flags"])
        self.assertIn("court_fee_enforcement_found", result["risk_flags"])
        self.assertIsNone(result["error"])

    def test_parse_debtors_results_returns_not_found_without_error(self):
        from app.services.debtors_lookup import parse_debtors_results

        result = parse_debtors_results(self.fixture("debtors_registry_empty.html"), "05747991")

        self.assertTrue(result["checked"])
        self.assertFalse(result["found"])
        self.assertEqual(result["items_count"], 0)
        self.assertEqual(result["items"], [])
        self.assertEqual(result["signals"], [])
        self.assertEqual(result["risk_flags"], [])
        self.assertIsNone(result["error"])

    def test_parse_debtors_results_returns_source_unavailable_for_captcha_page(self):
        from app.services.debtors_lookup import parse_debtors_results

        result = parse_debtors_results(self.fixture("debtors_registry_unavailable.html"), "05747991")

        self.assertFalse(result["checked"])
        self.assertFalse(result["found"])
        self.assertEqual(result["items_count"], 0)
        self.assertEqual(result["risk_flags"], ["source_unavailable"])
        self.assertEqual(result["error"], "source_unavailable")

    def test_fetch_debtors_registry_returns_clean_fallback_on_fetch_error(self):
        from app.services.debtors_lookup import fetch_debtors_registry

        def failing_fetcher(edrpou: str) -> str:
            raise TimeoutError("slow registry")

        result = fetch_debtors_registry("05747991", fetcher=failing_fetcher)

        self.assertFalse(result["checked"])
        self.assertFalse(result["found"])
        self.assertEqual(result["risk_flags"], ["source_unavailable"])
        self.assertEqual(result["error"], "source_unavailable")

    def test_build_debtors_risk_flags_classifies_categories_without_duplicates(self):
        from app.services.debtors_lookup import build_debtors_risk_flags, classify_debt_category

        items = [
            {"collection_category": "стягнення судового збору"},
            {"collection_category": "стягнення заборгованості із заробітної плати"},
            {"collection_category": "стягнення заборгованості із заробітної плати"},
            {"collection_category": "податковий борг"},
        ]

        self.assertEqual(
            build_debtors_risk_flags(items),
            [
                "debtor_registry_found",
                "multiple_debtor_records",
                "court_fee_enforcement_found",
                "salary_debt_enforcement_found",
                "tax_debt_enforcement_found",
            ],
        )
        self.assertEqual(
            classify_debt_category("штраф")["risk_flags"],
            ["fine_or_penalty_enforcement_found"],
        )

    def test_build_debtors_risk_flags_classifies_tax_creditor_and_state_budget_collection(self):
        from app.services.debtors_lookup import build_debtors_risk_flags

        flags = build_debtors_risk_flags(
            [
                {
                    "document_issuer": "ГУ ДПС у м. Києві",
                    "collection_category": "стягнення коштів до державного бюджету",
                }
            ]
        )

        self.assertIn("tax_debt_enforcement_found", flags)
        self.assertIn("debt_collection_found", flags)


if __name__ == "__main__":
    unittest.main()
