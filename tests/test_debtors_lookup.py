from pathlib import Path
import os
import unittest
from unittest.mock import patch


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

    def test_debtors_browser_launch_options_default_to_headless_chromium(self):
        from app.services.debtors_lookup import build_browser_launch_options

        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(build_browser_launch_options(), {"headless": True})

    def test_debtors_browser_launch_options_support_edge_headed_mode(self):
        from app.services.debtors_lookup import build_browser_launch_options

        with patch.dict(
            os.environ,
            {
                "RISKUA_DEBTORS_BROWSER_CHANNEL": "msedge",
                "RISKUA_DEBTORS_BROWSER_HEADLESS": "false",
            },
        ):
            self.assertEqual(
                build_browser_launch_options(),
                {
                    "channel": "msedge",
                    "headless": False,
                    "args": ["--start-minimized"],
                },
            )

    def test_wait_for_networkidle_if_possible_does_not_fail_lookup_on_timeout(self):
        from app.services.debtors_lookup import wait_for_networkidle_if_possible

        class FakeTimeoutError(Exception):
            pass

        class FakePage:
            def wait_for_load_state(self, state: str, timeout: int) -> None:
                raise FakeTimeoutError("network stays active")

        self.assertFalse(wait_for_networkidle_if_possible(FakePage(), FakeTimeoutError))

    def test_visible_html_has_captcha_ignores_script_mentions(self):
        from app.services.debtors_lookup import visible_html_has_captcha

        html = """
        <html>
          <body>Єдиний реєстр боржників</body>
          <script>window.captchaToken = "technical-marker";</script>
        </html>
        """

        self.assertFalse(visible_html_has_captcha(html))

    def test_visible_html_has_captcha_detects_visible_security_check(self):
        from app.services.debtors_lookup import visible_html_has_captcha

        self.assertTrue(visible_html_has_captcha("<body>Перевірка безпеки</body>"))

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

    def test_parse_debtors_results_ignores_header_rows_when_registry_returns_empty_tables(self):
        from app.services.debtors_lookup import parse_debtors_results

        html = """
        <table>
          <tr>
            <td>Результат пошуку фізичних осіб. Дата та час пошуку:</td>
          </tr>
          <tr>
            <th>Прізвище, ім’я, по батькові</th>
            <th>Дата народження</th>
            <th>Документ виданий</th>
            <th>Номер ВП</th>
            <th>Категорія стягнення</th>
          </tr>
          <tr>
            <td>Записів не знайдено. Уточніть умови пошуку.</td>
          </tr>
        </table>
        <table>
          <tr>
            <td>Результат пошуку юридичних осіб. Дата та час пошуку: 10.06.2026 13:23</td>
          </tr>
          <tr>
            <th>Найменування</th>
            <th>Документ виданий</th>
            <th>Номер виконавчого провадження</th>
            <th>Категорія стягнення</th>
          </tr>
          <tr>
            <td>Записів не знайдено. Уточніть умови пошуку.</td>
          </tr>
        </table>
        """

        result = parse_debtors_results(html, "45549459")

        self.assertTrue(result["checked"])
        self.assertFalse(result["found"])
        self.assertEqual(result["items_count"], 0)
        self.assertEqual(result["items"], [])
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

    def test_parse_debtors_results_classifies_33000657_budget_and_court_fee_cases(self):
        from app.services.debtors_lookup import parse_debtors_results

        html = """
        <table>
          <tr>
            <th>Найменування</th>
            <th>Документ видав</th>
            <th>Номер виконавчого провадження</th>
            <th>Категорія стягнення</th>
            <th>Деталі виконавця</th>
          </tr>
          <tr>
            <td>ТОВ «ПРИКЛАД»</td>
            <td>державний виконавець</td>
            <td>12345001</td>
            <td>інші стягнення на користь державного бюджету (санкції, платежі, штрафи)</td>
            <td></td>
          </tr>
          <tr>
            <td>ТОВ «ПРИКЛАД»</td>
            <td>суд загальної юрисдикції</td>
            <td>12345002</td>
            <td>стягнення судового збору</td>
            <td></td>
          </tr>
        </table>
        """

        result = parse_debtors_results(html, "33000657")

        self.assertTrue(result["checked"])
        self.assertTrue(result["found"])
        self.assertEqual(result["items_count"], 2)
        self.assertEqual(result["proceeding_numbers"], ["12345001", "12345002"])
        self.assertIn("debtor_registry_found", result["risk_flags"])
        self.assertIn("debt_collection_found", result["risk_flags"])
        self.assertIn("fine_or_penalty_enforcement_found", result["risk_flags"])
        self.assertIn("court_fee_enforcement_found", result["risk_flags"])
        self.assertIn("Є стягнення коштів, заборгованості або платежів до бюджету", result["signals"])
        self.assertIn("Є стягнення штрафів, пені або санкцій", result["signals"])
        self.assertIn("Є стягнення судового збору", result["signals"])


if __name__ == "__main__":
    unittest.main()
