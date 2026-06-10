import unittest
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError, URLError


CLARITY_COMPANY_HTML = """
<html>
  <body>
    <h1>ТОВ "ФІРМА "ОДЯГ""</h1>
    <dl>
      <dt>Стан</dt><dd>Зареєстровано</dd>
      <dt>Дата реєстрації</dt><dd>2003-10-31</dd>
      <dt>Керівник</dt><dd>Мельник Вадим Олександрович</dd>
      <dt>Статутний капітал</dt><dd>96 984,60 грн</dd>
      <dt>Основний КВЕД</dt><dd>68.20 Надання в оренду й експлуатацію власного чи орендованого нерухомого майна</dd>
    </dl>
    <section>
      <h2>Податки</h2>
      <p>Податковий борг відсутній</p>
      <p>Борг ЄСВ відсутній</p>
      <p>ПДВ активний</p>
      <p>Єдиний податок активний</p>
    </section>
    <section>
      <h2>Сигнали</h2>
      <p>Банкрутство</p><p>0</p>
      <p>Виконавчі провадження</p><p>1</p>
      <p>Перевірки</p><p>2</p>
      <p>Історія ЄДР</p><p>20</p>
      <p>Ліцензії</p><p>0</p>
      <p>Prozorro.Sale</p><p>0</p>
    </section>
  </body>
</html>
"""


class FakeHttpHeaders:
    def get_content_charset(self) -> str:
        return "utf-8"


class FakeHttpResponse:
    headers = FakeHttpHeaders()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def read(self) -> bytes:
        return b"<html>ok</html>"


class ClarityLookupTests(unittest.TestCase):
    def test_build_clarity_url(self):
        from app.services.clarity_lookup import build_clarity_url

        self.assertEqual(
            build_clarity_url("32697149"),
            "https://clarity-project.info/edr/32697149",
        )

    def test_fetch_clarity_page_uses_service_http_timeout(self):
        import app.services.clarity_lookup as service

        timeouts: list[float] = []

        def fake_urlopen(request, timeout: float):
            timeouts.append(timeout)
            return FakeHttpResponse()

        with patch("app.services.clarity_lookup.urlopen", fake_urlopen):
            html = service.fetch_clarity_page(service.build_clarity_url("32697149"))

        self.assertEqual(html, "<html>ok</html>")
        self.assertEqual(timeouts, [service.HTTP_TIMEOUT_SECONDS])
        self.assertLessEqual(service.HTTP_TIMEOUT_SECONDS, 10)

    def test_lookup_uses_clarity_api_key_without_exposing_it(self):
        from app.services.clarity_lookup import lookup_clarity_by_edrpou

        requested_urls: list[str] = []

        def fake_api_fetcher(url: str) -> dict:
            requested_urls.append(url)
            return {
                "edr": "32697149",
                "name": "ТОВ ТЕСТ",
                "edr_data": {
                    "name": "ТОВ ТЕСТ",
                    "statusName": "Зареєстровано",
                    "capital": "1000",
                    "activity": [
                        {
                            "code": "46.90",
                            "name": "Неспеціалізована оптова торгівля",
                            "is_primary": True,
                        }
                    ],
                    "registration": {"date": "2003-10-31"},
                    "signers": [{"name": "Іваненко Іван Іванович"}],
                },
                "tax_debt": {"amount": 0, "actual_date": "2026-01-01"},
                "history": 4,
                "licenses_count": 2,
            }

        def fail_html_fetcher(url: str) -> str:
            raise AssertionError(f"HTML fetcher should not be used when API key is configured: {url}")

        with patch.dict("os.environ", {"CLARITY_API_KEY": "test-secret"}, clear=False):
            result = lookup_clarity_by_edrpou(
                "32697149",
                fetcher=fail_html_fetcher,
                api_fetcher=fake_api_fetcher,
            )

        self.assertEqual(result.status, "found")
        self.assertEqual(result.source_url, "https://clarity-project.info/edr/32697149")
        self.assertNotIn("test-secret", result.model_dump_json())
        self.assertIn("https://clarity-project.info/api/edr.info/32697149?", requested_urls[0])
        self.assertIn("key=test-secret", requested_urls[0])
        self.assertEqual(result.company.name, "ТОВ ТЕСТ")
        self.assertEqual(result.company.status, "Зареєстровано")
        self.assertEqual(result.company.director, "Іваненко Іван Іванович")
        self.assertEqual(result.company.main_activity, "46.90 Неспеціалізована оптова торгівля")
        self.assertFalse(result.tax.tax_debt)
        self.assertEqual(result.signals.edr_history_count, 4)
        self.assertEqual(result.signals.licenses_count, 2)

    def test_clarity_api_error_returns_source_error_without_key(self):
        from app.services.clarity_lookup import lookup_clarity_by_edrpou

        with patch.dict("os.environ", {"CLARITY_API_KEY": "test-secret"}, clear=False):
            result = lookup_clarity_by_edrpou(
                "32697149",
                api_fetcher=lambda url: {"error": {"code": 401, "text": "Invalid API key"}},
            )

        self.assertEqual(result.status, "source_error")
        self.assertEqual(result.error, "clarity_api_401")
        self.assertNotIn("test-secret", result.model_dump_json())

    def test_clarity_api_transport_error_does_not_expose_key(self):
        from app.services.clarity_lookup import lookup_clarity_by_edrpou

        def failing_api_fetcher(url: str) -> dict:
            raise ValueError(f"failed url={url}")

        with patch.dict("os.environ", {"CLARITY_API_KEY": "test-secret"}, clear=False):
            result = lookup_clarity_by_edrpou("32697149", api_fetcher=failing_api_fetcher)

        self.assertEqual(result.status, "source_error")
        self.assertEqual(result.error, "clarity_api_source_error")
        self.assertNotIn("test-secret", result.model_dump_json())

    def test_clarity_api_boolean_tax_debt_does_not_create_fake_amount(self):
        from app.services.clarity_lookup import lookup_clarity_by_edrpou

        def fake_api_fetcher(url: str) -> dict:
            return {
                "edr": "32697149",
                "name": "ТОВ ТЕСТ",
                "edr_data": {"name": "ТОВ ТЕСТ", "statusName": "Зареєстровано"},
                "tax_debt": True,
            }

        with patch.dict("os.environ", {"CLARITY_API_KEY": "test-secret"}, clear=False):
            result = lookup_clarity_by_edrpou("32697149", api_fetcher=fake_api_fetcher)

        self.assertTrue(result.tax.tax_debt)
        self.assertIsNone(result.tax.tax_debt_amount_uah)

    def test_parse_company_fields(self):
        from app.services.clarity_lookup import build_clarity_url, parse_clarity_page

        result = parse_clarity_page(
            CLARITY_COMPANY_HTML,
            "32697149",
            build_clarity_url("32697149"),
        )

        self.assertEqual(result.status, "found")
        self.assertEqual(result.company.name, 'ТОВ "ФІРМА "ОДЯГ""')
        self.assertEqual(result.company.status, "Зареєстровано")
        self.assertEqual(result.company.registration_date, "2003-10-31")
        self.assertEqual(result.company.director, "Мельник Вадим Олександрович")
        self.assertEqual(result.company.statutory_capital_uah, 96984.60)
        self.assertEqual(
            result.company.main_activity,
            "68.20 Надання в оренду й експлуатацію власного чи орендованого нерухомого майна",
        )

    def test_parse_main_activity_from_activities_section(self):
        from app.services.clarity_lookup import build_clarity_url, parse_clarity_page

        html = CLARITY_COMPANY_HTML.replace(
            "<dt>Основний КВЕД</dt><dd>68.20 Надання в оренду й експлуатацію власного чи орендованого нерухомого майна</dd>",
            "<p>Види діяльності:</p><p>07.29 Добування руд інших кольорових металів</p><p>41.20 Будівництво житлових і нежитлових будівель</p>",
        )

        result = parse_clarity_page(html, "32697149", build_clarity_url("32697149"))

        self.assertEqual(result.company.main_activity, "07.29 Добування руд інших кольорових металів")
        self.assertNotIn("Не вдалося визначити основний КВЕД у Clarity", result.parse_warnings)

    def test_parse_director_from_authorized_persons_section(self):
        from app.services.clarity_lookup import build_clarity_url, parse_clarity_page

        html = CLARITY_COMPANY_HTML.replace(
            "<dt>Керівник</dt><dd>Мельник Вадим Олександрович</dd>",
            "<p>Уповноважені особи:</p><p>Мельник Вадим Олександрович</p><p>-</p><p>керівник</p>",
        )

        result = parse_clarity_page(html, "32697149", build_clarity_url("32697149"))

        self.assertEqual(result.company.director, "Мельник Вадим Олександрович")
        self.assertNotIn("Не вдалося визначити керівника у Clarity", result.parse_warnings)

    def test_parse_director_ignores_non_person_after_manager_label(self):
        from app.services.clarity_lookup import build_clarity_url, parse_clarity_page

        html = CLARITY_COMPANY_HTML.replace(
            "<dt>Керівник</dt><dd>Мельник Вадим Олександрович</dd>",
            (
                "<p>Уповноважені особи:</p><p>Мельник Вадим Олександрович</p><p>-</p><p>керівник</p>"
                "<p>Тип особи, ким підписано структуру власності:</p><p>Керівник</p>"
                "<p>Відмітка, що структуру власності підписано:</p><p>так</p>"
            ),
        )

        result = parse_clarity_page(html, "32697149", build_clarity_url("32697149"))

        self.assertEqual(result.company.director, "Мельник Вадим Олександрович")

    def test_parse_tax_booleans(self):
        from app.services.clarity_lookup import build_clarity_url, parse_clarity_page

        result = parse_clarity_page(
            CLARITY_COMPANY_HTML,
            "32697149",
            build_clarity_url("32697149"),
        )

        self.assertFalse(result.tax.tax_debt)
        self.assertFalse(result.tax.esv_debt)
        self.assertTrue(result.tax.vat_active)
        self.assertTrue(result.tax.single_tax_active)

    def test_parse_tax_booleans_from_split_live_labels(self):
        from app.services.clarity_lookup import build_clarity_url, parse_clarity_page

        html = CLARITY_COMPANY_HTML.replace(
            "<p>Борг ЄСВ відсутній</p>",
            "<p>Борг по ЄСВ:</p><p>Відсутній</p>",
        )

        result = parse_clarity_page(html, "32697149", build_clarity_url("32697149"))

        self.assertFalse(result.tax.esv_debt)
        self.assertNotIn("Не вдалося визначити борг ЄСВ у Clarity", result.parse_warnings)

    def test_parse_tax_debt_amount_and_date_from_amount_line(self):
        from app.services.clarity_lookup import build_clarity_url, parse_clarity_page

        html = CLARITY_COMPANY_HTML.replace(
            "<p>Податковий борг відсутній</p>",
            "<p>Податковий борг: 414 839 394.24 грн / на 28.01.2022</p>",
        )

        result = parse_clarity_page(html, "32697149", build_clarity_url("32697149"))

        self.assertTrue(result.tax.tax_debt)
        self.assertEqual(result.tax.tax_debt_amount_uah, 414839394.24)
        self.assertEqual(result.tax.tax_debt_as_of, "28.01.2022")
        self.assertFalse(result.tax.esv_debt)
        risk_text = " ".join(flag.text for flag in result.risk_flags)
        self.assertIn("414 839 394.24 грн", risk_text)
        self.assertIn("28.01.2022", risk_text)
        self.assertIn("large_tax_debt_found", [flag.code for flag in result.risk_flags])

    def test_parse_signals(self):
        from app.services.clarity_lookup import build_clarity_url, parse_clarity_page

        result = parse_clarity_page(
            CLARITY_COMPANY_HTML,
            "32697149",
            build_clarity_url("32697149"),
        )

        self.assertEqual(result.signals.bankruptcy_count, 0)
        self.assertEqual(result.signals.enforcement_proceedings_count, 1)
        self.assertEqual(result.signals.inspections_count, 2)
        self.assertEqual(result.signals.edr_history_count, 20)
        self.assertEqual(result.signals.licenses_count, 0)
        self.assertEqual(result.signals.prozorro_sales_count, 0)

    def test_parse_signal_count_from_parentheses(self):
        from app.services.clarity_lookup import build_clarity_url, parse_clarity_page

        html = CLARITY_COMPANY_HTML.replace("<p>Банкрутство</p><p>0</p>", "<p>Банкрутство (0)</p>")

        result = parse_clarity_page(html, "32697149", build_clarity_url("32697149"))

        self.assertEqual(result.signals.bankruptcy_count, 0)
        self.assertNotIn("Не вдалося визначити кількість записів банкрутства у Clarity", result.parse_warnings)

    def test_parse_signal_count_does_not_reuse_next_signal_value(self):
        from app.services.clarity_lookup import build_clarity_url, parse_clarity_page

        html = CLARITY_COMPANY_HTML.replace("<p>Банкрутство</p><p>0</p>", "<p>Банкрутство</p>")

        result = parse_clarity_page(html, "32697149", build_clarity_url("32697149"))

        self.assertIsNone(result.signals.bankruptcy_count)
        self.assertEqual(result.signals.enforcement_proceedings_count, 1)
        self.assertNotIn(
            ("high", "bankruptcy_found"),
            [(flag.level, flag.code) for flag in result.risk_flags],
        )

    def test_bankruptcy_count_creates_high_risk_flag(self):
        from app.services.clarity_lookup import build_clarity_url, parse_clarity_page

        html = CLARITY_COMPANY_HTML.replace("<p>Банкрутство</p><p>0</p>", "<p>Банкрутство</p><p>2</p>")

        result = parse_clarity_page(html, "32697149", build_clarity_url("32697149"))

        self.assertIn(
            ("high", "bankruptcy_found"),
            [(flag.level, flag.code) for flag in result.risk_flags],
        )

    def test_parse_rejects_page_with_different_edrpou(self):
        from app.services.clarity_lookup import build_clarity_url, parse_clarity_page

        html = CLARITY_COMPANY_HTML.replace(
            "<h1>ТОВ \"ФІРМА \"ОДЯГ\"\"</h1>",
            "<h1>ТОВ \"ФІРМА \"ОДЯГ\"\"</h1><p>ЄДРПОУ</p><p>99999999</p>",
        )

        result = parse_clarity_page(html, "32697149", build_clarity_url("32697149"))

        self.assertEqual(result.status, "parse_error")
        self.assertEqual(result.error, "edrpou_mismatch")
        self.assertIsNone(result.company)

    def test_parse_ignores_related_company_edrpou_outside_header_area(self):
        from app.services.clarity_lookup import build_clarity_url, parse_clarity_page

        html = (
            CLARITY_COMPANY_HTML
            + """
            <section>
              <h2>Пов'язані компанії</h2>
              <p>Назва</p><p>ТОВ «ІНША КОМПАНІЯ»</p>
              <p>ЄДРПОУ</p><p>99999999</p>
            </section>
            """
        )

        result = parse_clarity_page(html, "32697149", build_clarity_url("32697149"))

        self.assertIn(result.status, {"found", "partial"})
        self.assertIsNotNone(result.company)
        self.assertNotEqual(result.error, "edrpou_mismatch")

    def test_parse_not_found_page(self):
        from app.services.clarity_lookup import build_clarity_url, parse_clarity_page

        result = parse_clarity_page(
            "<html><body><h1>За запитом нічого не знайдено</h1></body></html>",
            "12345678",
            build_clarity_url("12345678"),
        )

        self.assertEqual(result.status, "not_found")
        self.assertEqual(result.edrpou, "12345678")
        self.assertIsNone(result.company)
        self.assertIsNone(result.error)

    def test_parse_edr_information_missing_page_as_not_found(self):
        from app.services.clarity_lookup import build_clarity_url, parse_clarity_page

        html = """
        <html><body>
          <h1>ТОВ "Тестова компанія" (ЄДРПОУ 12345678) - перевірка компанії | Clarity Project</h1>
          <p>ТОВ "Тестова компанія"</p>
          <p>#12345678</p>
          <p>Основна інформація</p>
          <p>Інформація з ЄДР:</p>
          <p>Інформацію не знайдено</p>
        </body></html>
        """

        result = parse_clarity_page(html, "12345678", build_clarity_url("12345678"))

        self.assertEqual(result.status, "not_found")
        self.assertIsNone(result.company)
        self.assertIsNone(result.error)

    def test_lookup_returns_source_error_on_http_error(self):
        from app.services.clarity_lookup import lookup_clarity_by_edrpou

        def failing_fetcher(url: str) -> str:
            raise URLError("Forbidden")

        result = lookup_clarity_by_edrpou("32697149", fetcher=failing_fetcher)

        self.assertEqual(result.status, "source_error")
        self.assertEqual(result.edrpou, "32697149")
        self.assertIsNone(result.company)

    def test_lookup_treats_404_as_not_found(self):
        from app.services.clarity_lookup import lookup_clarity_by_edrpou

        def not_found_fetcher(url: str) -> str:
            raise HTTPError(url=url, code=404, msg="Not Found", hdrs=None, fp=BytesIO())

        result = lookup_clarity_by_edrpou("12345678", fetcher=not_found_fetcher)

        self.assertEqual(result.status, "not_found")
        self.assertEqual(result.edrpou, "12345678")
        self.assertIsNone(result.company)
        self.assertIsNone(result.error)


if __name__ == "__main__":
    unittest.main()
