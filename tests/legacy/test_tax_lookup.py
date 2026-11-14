from pathlib import Path
import unittest


FIXTURES = Path(__file__).parent / "fixtures"


class TaxLookupTests(unittest.TestCase):
    def fixture(self, name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    def test_build_tax_debt_dataset_url_returns_official_open_data_url(self):
        from app.services.tax_lookup import build_tax_debt_dataset_url

        self.assertIn("data.gov.ua", build_tax_debt_dataset_url())

    def test_fetch_tax_status_returns_tax_debt_found_if_edrpou_in_debt_fixture(self):
        from app.services.tax_lookup import fetch_tax_status

        calls: list[str] = []

        def fake_fetcher(edrpou: str) -> dict[str, str]:
            calls.append(edrpou)
            return {
                "tax_debt": self.fixture("tax_debt_found.csv"),
                "vat": self.fixture("vat_active.csv"),
            }

        result = fetch_tax_status("05747991", fetcher=fake_fetcher)

        self.assertEqual(calls, ["05747991"])
        self.assertEqual(result["source"], "tax")
        self.assertTrue(result["checked"])
        self.assertTrue(result["found"])
        self.assertEqual(result["searched_edrpou"], "05747991")
        self.assertTrue(result["tax_debt"]["found"])
        self.assertEqual(result["tax_debt"]["amount"], 12345.67)
        self.assertEqual(result["tax_debt"]["currency"], "UAH")
        self.assertEqual(result["tax_debt"]["dataset_date"], "2026-06-01")
        self.assertTrue(result["vat"]["found"])
        self.assertEqual(result["vat"]["status"], "active")
        self.assertIn("Знайдено податковий борг", result["signals"])
        self.assertIn("Компанія є платником ПДВ", result["signals"])
        self.assertEqual(result["risk_flags"], ["tax_debt_found"])
        self.assertIsNone(result["error"])

    def test_fetch_tax_status_returns_large_tax_debt_flag_above_threshold(self):
        from app.services.tax_lookup import fetch_tax_status

        def fake_fetcher(edrpou: str) -> dict[str, str]:
            return {"tax_debt": self.fixture("tax_debt_found.csv")}

        result = fetch_tax_status("11111111", fetcher=fake_fetcher)

        self.assertTrue(result["tax_debt"]["found"])
        self.assertEqual(result["tax_debt"]["amount"], 150000.0)
        self.assertIn("tax_debt_found", result["risk_flags"])
        self.assertIn("large_tax_debt_found", result["risk_flags"])

    def test_fetch_tax_status_returns_no_risk_flags_when_no_tax_debt(self):
        from app.services.tax_lookup import fetch_tax_status

        def fake_fetcher(edrpou: str) -> dict[str, str]:
            return {
                "tax_debt": self.fixture("tax_debt_empty.csv"),
                "vat": self.fixture("vat_active.csv"),
            }

        result = fetch_tax_status("12345678", fetcher=fake_fetcher)

        self.assertTrue(result["checked"])
        self.assertTrue(result["found"])
        self.assertFalse(result["tax_debt"]["found"])
        self.assertEqual(result["tax_debt"]["amount"], 0)
        self.assertEqual(result["risk_flags"], [])

    def test_vat_cancellation_adds_vat_registration_cancelled_flag(self):
        from app.services.tax_lookup import fetch_tax_status

        def fake_fetcher(edrpou: str) -> dict[str, str]:
            return {
                "tax_debt": self.fixture("tax_debt_empty.csv"),
                "vat": self.fixture("vat_cancelled.csv"),
            }

        result = fetch_tax_status("05747991", fetcher=fake_fetcher)

        self.assertTrue(result["vat"]["found"])
        self.assertEqual(result["vat"]["status"], "cancelled")
        self.assertEqual(result["vat"]["cancelled_date"], "2025-02-03")
        self.assertIn("vat_registration_cancelled", result["risk_flags"])

    def test_fetch_tax_status_returns_clean_unavailable_result_on_fetch_error(self):
        from app.services.tax_lookup import fetch_tax_status

        def failing_fetcher(edrpou: str) -> dict[str, str]:
            raise TimeoutError("slow tax dataset")

        result = fetch_tax_status("05747991", fetcher=failing_fetcher)

        self.assertFalse(result["checked"])
        self.assertFalse(result["found"])
        self.assertIsNone(result["tax_debt"])
        self.assertIsNone(result["vat"])
        self.assertEqual(result["risk_flags"], ["tax_source_unavailable"])
        self.assertEqual(result["error"], "tax_source_unavailable")

    def test_fetch_tax_status_returns_clean_unavailable_result_on_unrecognized_format(self):
        from app.services.tax_lookup import fetch_tax_status

        def html_fetcher(edrpou: str) -> str:
            return "<html><body>service page</body></html>"

        result = fetch_tax_status("05747991", fetcher=html_fetcher)

        self.assertFalse(result["checked"])
        self.assertFalse(result["found"])
        self.assertEqual(result["risk_flags"], ["tax_source_unavailable"])
        self.assertEqual(result["error"], "tax_source_unavailable")


if __name__ == "__main__":
    unittest.main()
