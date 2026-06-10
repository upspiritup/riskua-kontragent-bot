from io import BytesIO
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError


FOUND_COMPANY_HTML = """
<html>
  <body>
    <main>
      <p>Реєстраційні дані</p>
      <p>Час витягу з ЄДР</p><p>5 червня 2026 р. о 00:40</p>
      <p>Код ЄДРПОУ</p>
      <h1>12345678</h1>
      <h2>ТОВ «ПРИКЛАД»</h2>
      <p>Статус</p><p>Зареєстровано</p>
      <p>Повна назва</p><p>ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ «ПРИКЛАД»</p>
      <p>Дата заснування</p><p>15.01.2024</p>
      <p>Адреса</p><p>01001, Україна, місто Київ, вулиця Тестова, будинок 1</p>
      <p>Директор</p><p>Іваненко Іван Іванович</p>
      <p>Статутний капітал</p><p>1 530 000 ₴</p>
      <p>ПДВ-статус</p><p>Платник ПДВ</p>
      <p>Основний вид діяльності</p><p>46.90 Неспеціалізована оптова торгівля</p>
      <p>Інші види діяльності</p><p>47.19 Інші види роздрібної торгівлі, 52.10 Складське господарство</p>
      <p>Власники</p>
      <p>Петренко Петро Петрович</p><p>Україна</p><p>Засновник</p><p>1 530 000 ₴</p><p>100%</p>
      <p>Петренко Петро Петрович</p><p>Україна</p><p>Кінцевий бенефіціарний власник</p>
      <p>Керівники з обмеженнями</p>
      <p>Фінансові показники</p>
      <p>Фінансові показники</p>
      <p>Прогноз на 2026 рік</p>
      <p>2025</p><p>2024</p>
      <p>Дохід</p><p>2 100 000 ₴</p><p>+5%</p><p>2 000 000 ₴</p><p>-10%</p><p>1 800 000 ₴</p>
      <p>Чистий прибуток</p><p>120 000 ₴</p><p>-50 000 ₴</p>
      <p>Рентабельність</p><p>6%</p><p>-2,7%</p>
      <p>Активи</p><p>3 000 000 ₴</p><p>2 700 000 ₴</p>
      <p>Зобов'язання</p><p>900 000 ₴</p><p>800 000 ₴</p>
      <p>Кількість працівників</p><p>12</p><p>10</p>
      <p>Дохід на працівника</p><p>166 667 ₴</p><p>180 000 ₴</p>
      <p>Фінансова звітність</p>
      <p>Баланс та фінансові результати_2025.xlsx</p>
      <p>Історія змін реєстраційної інформації</p>
      <p>Дата</p><p>Зміна</p><p>Було</p><p>Стало</p>
      <p>Увійдіть</p><p>для отримання дати останніх змін</p>
      <p>Змінилась адреса в едр</p><p>стара адреса</p><p>нова адреса</p>
      <p>Судові справи</p><p>3</p>
      <p>Тендери</p><p>учасник 2 закупівель</p>
    </main>
  </body>
</html>
"""

REALISTIC_OPENDATABOT_HTML = """
<html>
  <head><title>34994894 — ТОВ РЕЛАН</title></head>
  <body>
    <p>Опендатабот — країна у смартфоні</p>
    <p>Компанія зареєстрована на загальній системі оподаткування</p>
    <p>Код ЄДРПОУ</p><p>34994894</p>
    <h2>ТОВ «РЕЛАН»</h2>
    <p>Директор</p><p>Мєстоіванченко Сергій Михайлович</p>
    <p>Реєстраційні дані</p>
    <p>Повна назва</p><p>ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІД­ПО­ВІД­АЛЬ­НІ­СТЮ «РЕЛАН»</p>
      <p>Адреса</p><p>02002, Україна,</p><p>місто Київ</p><p>,</p><p>вулиця Степана Сагайдака</p><p>, будинок 101</p>
      <p>Дата заснування</p><p>02.03.2007</p>
      <p>Код ЄДРПОУ</p><p>34994894</p>
      <p>Основний вид діяльності</p><p>45.21.1 Будівництво будівель</p>
      <p>Судовий реєстр</p><p>50 рішень</p>
  </body>
</html>
"""

COURT_DECISION_URL = "https://opendatabot.ua/court/136256783-639cf087c944b803e805146e06c7d2d4"

COURT_LINKS_HTML = f"""
<html>
  <body>
    <main>
      <p>Код ЄДРПОУ</p><p>12345678</p>
      <h2>ТОВ «ПРИКЛАД»</h2>
      <p>Повна назва</p><p>ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ «ПРИКЛАД»</p>
      <p>Дата заснування</p><p>15.01.2024</p>
      <p>Адреса</p><p>01001, Україна, місто Київ</p>
      <p>Директор</p><p>Іваненко Іван Іванович</p>
      <p>Основний вид діяльності</p><p>46.90 Неспеціалізована оптова торгівля</p>
      <p>Судовий реєстр</p><p>2 рішення</p>
      <a href="{COURT_DECISION_URL}">Ухвала</a>
      <a href="/court/136256785-a37fd36115f607d7305448893333db4c">Постанова</a>
      <a href="https://court.opendatabot.ua/cause/160%2F11282%2F25">160/11282/25</a>
      <a href="https://opendatabot.ua/open/court-fair">Судова влада стан розгляду справ</a>
    </main>
  </body>
</html>
"""

COURT_DECISION_HTML = """
<html>
  <body>
    <h1>Ухвала № 136256783 від 04.05.2026 по справі 160/11282/25</h1>
    <article>
      Позивач просить суд стягнути з відповідача 12 500 грн пені.
      Суд дослідив матеріали справи.
      УХВАЛИВ: Відкрити провадження у справі.
      Запропонувати відповідачу подати відзив протягом встановленого строку.
    </article>
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


class OpendatabotLookupTests(unittest.TestCase):
    def test_validate_edrpou_accepts_exactly_eight_ascii_digits(self):
        from app.services.opendatabot_lookup import validate_edrpou

        self.assertTrue(validate_edrpou("12345678"))

    def test_validate_edrpou_rejects_invalid_values(self):
        from app.services.opendatabot_lookup import validate_edrpou

        for value in ["1234567", "123456789", "1234-5678", "abcdefgh"]:
            with self.subTest(value=value):
                self.assertFalse(validate_edrpou(value))

    def test_build_opendatabot_url(self):
        from app.services.opendatabot_lookup import build_opendatabot_url

        self.assertEqual(
            build_opendatabot_url("36192559"),
            "https://opendatabot.ua/c/36192559?from=search",
        )

    def test_fetch_company_page_uses_service_http_timeout(self):
        import app.services.opendatabot_lookup as service

        timeouts: list[float] = []

        def fake_urlopen(request, timeout: float):
            timeouts.append(timeout)
            return FakeHttpResponse()

        with patch("app.services.opendatabot_lookup.urlopen", fake_urlopen):
            html = service.fetch_company_page("12345678")

        self.assertEqual(html, "<html>ok</html>")
        self.assertEqual(timeouts, [service.HTTP_TIMEOUT_SECONDS])
        self.assertLessEqual(service.HTTP_TIMEOUT_SECONDS, 10)

    def test_fetch_court_decision_page_uses_service_http_timeout(self):
        import app.services.opendatabot_lookup as service

        timeouts: list[float] = []

        def fake_urlopen(request, timeout: float):
            timeouts.append(timeout)
            return FakeHttpResponse()

        with patch("app.services.opendatabot_lookup.urlopen", fake_urlopen):
            html = service.fetch_court_decision_page(COURT_DECISION_URL)

        self.assertEqual(html, "<html>ok</html>")
        self.assertEqual(timeouts, [service.HTTP_TIMEOUT_SECONDS])
        self.assertLessEqual(service.HTTP_TIMEOUT_SECONDS, 10)

    def test_parse_not_found_page(self):
        from app.services.opendatabot_lookup import parse_company_page

        result = parse_company_page(
            "<html><body>Невірний код компанії 12345678</body></html>",
            "12345678",
        )

        self.assertEqual(result.status, "not_found")
        self.assertEqual(result.edrpou, "12345678")
        self.assertIsNone(result.company_data)

    def test_parse_found_company_page(self):
        from app.services.opendatabot_lookup import parse_company_page

        result = parse_company_page(FOUND_COMPANY_HTML, "12345678")

        self.assertEqual(result.status, "found")
        self.assertEqual(result.company_data.full_name, "ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ «ПРИКЛАД»")
        self.assertEqual(result.company_data.short_name, "ТОВ «ПРИКЛАД»")
        self.assertEqual(result.company_data.edrpou, "12345678")
        self.assertEqual(result.company_data.status, "Зареєстровано")
        self.assertEqual(result.company_data.vat_status, "Платник ПДВ")
        self.assertEqual(result.company_data.registration_date, "15.01.2024")
        self.assertEqual(result.company_data.registry_extract_time, "5 червня 2026 р. о 00:40")
        self.assertEqual(
            result.company_data.address,
            "01001, Україна, місто Київ, вулиця Тестова, будинок 1",
        )
        self.assertEqual(result.company_data.city, "Київ")
        self.assertEqual(result.company_data.director, "Іваненко Іван Іванович")
        self.assertEqual(result.company_data.statutory_capital_uah, 1530000)
        self.assertEqual(result.company_data.main_activity_code, "46.90")
        self.assertEqual(result.company_data.main_activity_name, "Неспеціалізована оптова торгівля")
        self.assertEqual(result.company_data.additional_activities[0], "47.19 Інші види роздрібної торгівлі")
        self.assertEqual(result.company_data.owners_count, 1)
        self.assertEqual(result.company_data.owners[0].name, "Петренко Петро Петрович")
        self.assertEqual(result.company_data.owners[0].share_percent, 100)
        self.assertEqual(result.company_data.beneficial_owners[0].name, "Петренко Петро Петрович")
        self.assertEqual(result.company_data.tenders_count, 2)
        self.assertEqual(result.company_data.tenders_text, "учасник 2 закупівель")
        self.assertTrue(result.risk_input.has_beneficial_owner)

    def test_parse_realistic_page_does_not_use_site_title_as_company_name(self):
        from app.services.opendatabot_lookup import parse_company_page

        result = parse_company_page(REALISTIC_OPENDATABOT_HTML, "34994894")

        self.assertIn(result.status, {"found", "partial"})
        self.assertEqual(result.company_data.short_name, "ТОВ «РЕЛАН»")
        self.assertEqual(
            result.company_data.full_name,
            "ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ «РЕЛАН»",
        )
        self.assertEqual(result.company_data.status, "Зареєстровано")
        self.assertEqual(
            result.company_data.address,
            "02002, Україна, місто Київ, вулиця Степана Сагайдака, будинок 101",
        )
        self.assertTrue(result.court_data.has_court_mentions)
        self.assertEqual(result.court_data.total_cases_found, 50)
        self.assertEqual(result.court_data.court_mentions_count, 50)
        self.assertIsNone(result.court_data.court_unique_cases_count)
        self.assertIsNone(result.court_data.court_risky_cases_count)
        self.assertEqual(result.risk_input.court_mentions_count, 50)
        self.assertIsNone(result.risk_input.court_unique_cases_count)
        self.assertIsNone(result.risk_input.court_risky_cases_count)

    def test_parse_company_status_company_label_takes_precedence_over_tax_registration_text(self):
        from app.services.opendatabot_lookup import parse_company_page

        html = """
        <html><body><main>
          <p>Код ЄДРПОУ</p><h1>25102871</h1>
          <h2>ТОВ «УКРІНВЕСТ»</h2>
          <p>Компанія зареєстрована на загальній системі оподаткування</p>
          <p>Статус компанії</p><p>припинено</p>
          <p>Повна назва</p><p>ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ «УКРІНВЕСТ»</p>
          <p>Дата заснування</p><p>27.08.1997</p>
          <p>Адреса</p><p>49083, Україна, Дніпропетровська обл., місто Дніпро</p>
          <p>Директор</p><p>Мотрич Іван Олександрович</p>
          <p>Основний вид діяльності</p><p>73.20 Дослідження кон'юнктури ринку та виявлення громадської думки</p>
        </main></body></html>
        """

        result = parse_company_page(html, "25102871")

        self.assertEqual(result.status, "found")
        self.assertEqual(result.company_data.status, "припинено")

    def test_parse_company_status_ignores_historical_termination_context(self):
        from app.services.opendatabot_lookup import parse_company_page

        html = """
        <html><body><main>
          <p>Код ЄДРПОУ</p><h1>21560045</h1>
          <h2>АТ «УКРПОШТА»</h2>
          <p>Статус компанії</p><p>Зареєстровано</p>
          <p>Повна назва</p><p>АКЦІОНЕРНЕ ТОВАРИСТВО «УКРПОШТА»</p>
          <p>Дата заснування</p><p>15.12.1993</p>
          <p>Адреса</p><p>01001, Україна, місто Київ, вулиця Хрещатик, будинок 22</p>
          <p>Директор</p><p>Смілянський Ігор Юхимович</p>
          <p>Основний вид діяльності</p><p>53.10 Діяльність національної пошти</p>
          <p>Історична подія: припинення шляхом перетворення державного підприємства.</p>
          <p>Рішення про припинення права користування земельною ділянкою.</p>
        </main></body></html>
        """

        result = parse_company_page(html, "21560045")

        self.assertEqual(result.status, "found")
        self.assertEqual(result.company_data.status, "Зареєстровано")
        self.assertNotIn("company_in_termination", result.court_data.risk_flags)

    def test_parse_company_status_without_label_prefers_registered_over_document_termination_text(self):
        from app.services.opendatabot_lookup import parse_company_page

        html = """
        <html><body><main>
          <p>Код ЄДРПОУ</p><h1>21560045</h1>
          <h2>АТ «УКРПОШТА»</h2>
          <p>Компанія зареєстрована</p>
          <p>Повна назва</p><p>АКЦІОНЕРНЕ ТОВАРИСТВО «УКРПОШТА»</p>
          <p>Дата заснування</p><p>15.12.1993</p>
          <p>Адреса</p><p>01001, Україна, місто Київ, вулиця Хрещатик, будинок 22</p>
          <p>Директор</p><p>Смілянський Ігор Юхимович</p>
          <p>Основний вид діяльності</p><p>53.10 Діяльність національної пошти</p>
          <p>Судове рішення про припинення права користування майном.</p>
        </main></body></html>
        """

        result = parse_company_page(html, "21560045")

        self.assertEqual(result.status, "found")
        self.assertEqual(result.company_data.status, "Зареєстровано")
        self.assertNotIn("company_in_termination", result.court_data.risk_flags)

    def test_parse_company_page_adds_bankruptcy_risk_flag_from_opendatabot_text(self):
        from app.services.opendatabot_lookup import parse_company_page

        html = """
        <html><body><main>
          <p>Код ЄДРПОУ</p><h1>25102871</h1>
          <h2>ТОВ «УКРІНВЕСТ»</h2>
          <p>Статус компанії</p><p>припинено</p>
          <p>Повна назва</p><p>ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ «УКРІНВЕСТ»</p>
          <p>Дата заснування</p><p>27.08.1997</p>
          <p>Адреса</p><p>49083, Україна, Дніпропетровська обл., місто Дніпро</p>
          <p>Директор</p><p>Мотрич Іван Олександрович</p>
          <p>Основний вид діяльності</p><p>73.20 Дослідження кон'юнктури ринку та виявлення громадської думки</p>
          <p>Виконується процедура банкрутства</p>
        </main></body></html>
        """

        result = parse_company_page(html, "25102871")

        self.assertIn("bankruptcy_found", result.court_data.risk_flags)
        self.assertIn("company_in_termination", result.court_data.risk_flags)

    def test_parse_company_page_does_not_add_bankruptcy_flag_from_negative_phrase(self):
        from app.services.opendatabot_lookup import parse_company_page

        html = """
        <html><body><main>
          <p>Код ЄДРПОУ</p><h1>12345678</h1>
          <h2>ТОВ «ПРИКЛАД»</h2>
          <p>Статус</p><p>Зареєстровано</p>
          <p>Повна назва</p><p>ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ «ПРИКЛАД»</p>
          <p>Дата заснування</p><p>15.01.2024</p>
          <p>Адреса</p><p>01001, Україна, місто Київ</p>
          <p>Директор</p><p>Іваненко Іван Іванович</p>
          <p>Основний вид діяльності</p><p>46.90 Неспеціалізована оптова торгівля</p>
          <p>Банкрутство не виявлено</p>
        </main></body></html>
        """

        result = parse_company_page(html, "12345678")

        self.assertNotIn("bankruptcy_found", result.court_data.risk_flags)

    def test_parse_company_page_rejects_page_with_different_edrpou(self):
        from app.services.opendatabot_lookup import parse_company_page

        html = """
        <html>
          <head><title>99999999 — ТОВ «ЧУЖА КОМПАНІЯ»</title></head>
          <body>
            <main>
              <p>ЄДРПОУ 99999999</p>
              <h2>ТОВ «ЧУЖА КОМПАНІЯ»</h2>
              <p>Повна назва</p>
              <p>ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ «ЧУЖА КОМПАНІЯ»</p>
              <p>Компанія зареєстрована</p>
            </main>
          </body>
        </html>
        """

        result = parse_company_page(html, "12345678")

        self.assertEqual(result.status, "parse_error")
        self.assertEqual(result.error, "edrpou_mismatch")
        self.assertIsNone(result.company_data)
        self.assertIn("99999999", " ".join(result.parse_warnings))

    def test_extract_court_decision_links_ignores_non_decision_court_links(self):
        from app.services.opendatabot_lookup import extract_court_decision_links

        links = extract_court_decision_links(COURT_LINKS_HTML)

        self.assertEqual(
            links,
            [
                COURT_DECISION_URL,
                "https://opendatabot.ua/court/136256785-a37fd36115f607d7305448893333db4c",
            ],
        )

    def test_parse_company_page_stores_court_decision_source_urls(self):
        from app.services.opendatabot_lookup import parse_company_page

        result = parse_company_page(COURT_LINKS_HTML, "12345678")

        self.assertEqual(result.status, "found")
        self.assertEqual(result.court_data.total_cases_found, 2)
        self.assertEqual(result.court_data.source_urls[0], COURT_DECISION_URL)

    def test_parse_court_decision_page_returns_short_analysis_without_html(self):
        from app.services.opendatabot_lookup import parse_court_decision_page

        decision = parse_court_decision_page(COURT_DECISION_HTML, COURT_DECISION_URL)

        self.assertEqual(decision["source_url"], COURT_DECISION_URL)
        self.assertEqual(decision["document_type"], "Ухвала")
        self.assertEqual(decision["decision_number"], "136256783")
        self.assertEqual(decision["decision_date"], "04.05.2026")
        self.assertEqual(decision["case_number"], "160/11282/25")
        self.assertTrue(decision["procedural_decision_detected"])
        self.assertFalse(decision["liability_detected"])
        self.assertFalse(decision["negative_outcome_detected"])
        self.assertIn("Відкрити провадження", decision["operative_part_excerpt"])
        self.assertNotIn("<article>", str(decision))

    def test_lookup_company_enriches_first_court_decision_only(self):
        from app.services.opendatabot_lookup import lookup_company

        fetched_decision_urls = []

        def company_fetcher(edrpou: str) -> str:
            return COURT_LINKS_HTML

        def court_decision_fetcher(url: str) -> str:
            fetched_decision_urls.append(url)
            return COURT_DECISION_HTML

        result = lookup_company(
            "12345678",
            fetcher=company_fetcher,
            court_decision_fetcher=court_decision_fetcher,
            max_court_decisions=1,
        )

        self.assertEqual(fetched_decision_urls, [COURT_DECISION_URL])
        self.assertEqual(len(result.court_data.decisions), 1)
        self.assertTrue(result.court_data.decisions[0]["procedural_decision_detected"])

    def test_lookup_company_defaults_to_three_court_decisions_for_report_links(self):
        from app.services.opendatabot_lookup import lookup_company

        fetched_decision_urls = []
        third_decision_url = "https://opendatabot.ua/court/136256786-a37fd36115f607d7305448893333db5d"
        html_with_three_court_links = COURT_LINKS_HTML.replace(
            "</main>",
            f'<a href="{third_decision_url}">Рішення</a></main>',
        )

        def company_fetcher(edrpou: str) -> str:
            return html_with_three_court_links

        def court_decision_fetcher(url: str) -> str:
            fetched_decision_urls.append(url)
            return COURT_DECISION_HTML

        result = lookup_company(
            "12345678",
            fetcher=company_fetcher,
            court_decision_fetcher=court_decision_fetcher,
        )

        self.assertEqual(
            fetched_decision_urls,
            [
                COURT_DECISION_URL,
                "https://opendatabot.ua/court/136256785-a37fd36115f607d7305448893333db4c",
                third_decision_url,
            ],
        )
        self.assertEqual(len(result.court_data.decisions), 3)

    def test_parse_financial_table(self):
        from app.services.opendatabot_lookup import parse_company_page

        result = parse_company_page(FOUND_COMPANY_HTML, "12345678")

        self.assertEqual(result.financial_data.forecast["year"], 2026)
        self.assertEqual(result.financial_data.forecast["revenue_uah"], 2100000)
        self.assertEqual(result.financial_data.years["2025"].revenue_uah, 2000000)
        self.assertEqual(result.financial_data.years["2025"].revenue_change_percent, -10)
        self.assertEqual(result.financial_data.years["2024"].net_profit_uah, -50000)
        self.assertEqual(result.financial_data.years["2024"].profitability_percent, -2.7)
        self.assertEqual(result.financial_data.years["2025"].assets_uah, 3000000)
        self.assertEqual(result.financial_data.years["2025"].liabilities_uah, 900000)
        self.assertIn("Баланс та фінансові результати_2025.xlsx", result.financial_data.financial_reports)

    def test_parse_financial_table_with_equity_row(self):
        from app.services.opendatabot_lookup import parse_company_page

        html = """
        <html><body><main>
          <p>Реєстраційні дані</p>
          <p>Код ЄДРПОУ</p><h1>12345678</h1>
          <h2>ТОВ «ПРИКЛАД»</h2>
          <p>Статус</p><p>Зареєстровано</p>
          <p>Повна назва</p><p>ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ «ПРИКЛАД»</p>
          <p>Дата заснування</p><p>15.01.2024</p>
          <p>Адреса</p><p>01001, Україна, місто Київ</p>
          <p>Директор</p><p>Іваненко Іван Іванович</p>
          <p>Фінансові показники</p>
          <p>2025</p><p>2024</p><p>2023</p>
          <p>Власний капітал</p><p>2 100 000 ₴</p><p>1 900 000 ₴</p><p>1 500 000 ₴</p>
          <p>Фінансова звітність</p>
        </main></body></html>
        """

        result = parse_company_page(html, "12345678")

        self.assertEqual(result.financial_data.years["2025"].equity_uah, 2100000)
        self.assertEqual(result.financial_data.years["2024"].equity_uah, 1900000)
        self.assertEqual(result.financial_data.years["2023"].equity_uah, 1500000)

    def test_parse_tax_debt_collection_signal_from_dps_text(self):
        from app.services.opendatabot_lookup import parse_company_page

        html = """
        <html><body><main>
          <p>Реєстраційні дані</p>
          <p>Код ЄДРПОУ</p><h1>44037141</h1>
          <h2>ТОВ «ПРОСКО»</h2>
          <p>Статус</p><p>Зареєстровано</p>
          <p>Повна назва</p><p>ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ «ПРОСКО»</p>
          <p>Дата заснування</p><p>17.12.2020</p>
          <p>Адреса</p><p>01001, Україна, місто Київ</p>
          <p>Директор</p><p>Іваненко Іван Іванович</p>
          <p>Статутний капітал</p><p>1 000 ₴</p>
          <p>Основний вид діяльності</p><p>23.99 Виробництво неметалевих мінеральних виробів, н.в.і.у.</p>
          <p>Борги</p>
          <p>Державна податкова служба стягує з компанії 1 податковий борг</p>
          <p>Судовий реєстр</p><p>30 рішень</p>
        </main></body></html>
        """

        result = parse_company_page(html, "44037141")

        self.assertTrue(result.risk_input.tax_debt_found)
        self.assertEqual(result.risk_input.tax_debt_count, 1)
        self.assertIn("Державна податкова служба стягує", result.risk_input.tax_debt_text)
        self.assertEqual(result.risk_input.statutory_capital_uah, 1000)
        self.assertEqual(result.risk_input.court_mentions_count, 30)

    def test_dps_as_company_is_not_marked_debtor_when_dps_collects_tax_debt(self):
        from app.services.opendatabot_lookup import parse_company_page

        html = """
        <html><body><main>
          <p>Код ЄДРПОУ</p><h1>44116011</h1>
          <h2>ГУ ДПС У М. КИЄВІ</h2>
          <p>Статус</p><p>Зареєстровано</p>
          <p>Повна назва</p><p>ГОЛОВНЕ УПРАВЛІННЯ ДПС У М. КИЄВІ</p>
          <p>Дата заснування</p><p>30.09.2020</p>
          <p>Адреса</p><p>04116, Україна, місто Київ</p>
          <p>Директор</p><p>Іваненко Іван Іванович</p>
          <p>Основний вид діяльності</p><p>84.11 Державне управління загального характеру</p>
          <p>Державна податкова служба стягує з компанії 1 податковий борг</p>
        </main></body></html>
        """

        result = parse_company_page(html, "44116011")

        self.assertFalse(result.risk_input.tax_debt_found)
        self.assertEqual(result.risk_input.tax_debt_count, 0)
        self.assertIsNone(result.risk_input.tax_debt_text)

    def test_dps_as_company_is_marked_debtor_when_debt_collected_from_dps(self):
        from app.services.opendatabot_lookup import parse_company_page

        html = """
        <html><body><main>
          <p>Код ЄДРПОУ</p><h1>44116011</h1>
          <h2>ГУ ДПС У М. КИЄВІ</h2>
          <p>Статус</p><p>Зареєстровано</p>
          <p>Повна назва</p><p>ГОЛОВНЕ УПРАВЛІННЯ ДПС У М. КИЄВІ</p>
          <p>Дата заснування</p><p>30.09.2020</p>
          <p>Адреса</p><p>04116, Україна, місто Київ</p>
          <p>Директор</p><p>Іваненко Іван Іванович</p>
          <p>Основний вид діяльності</p><p>84.11 Державне управління загального характеру</p>
          <p>Боржник: ГУ ДПС У М. КИЄВІ. Стягнення податкового боргу</p>
        </main></body></html>
        """

        result = parse_company_page(html, "44116011")

        self.assertTrue(result.risk_input.tax_debt_found)
        self.assertEqual(result.risk_input.tax_debt_count, 1)
        self.assertIn("Боржник: ГУ ДПС", result.risk_input.tax_debt_text)

    def test_parse_registration_changes(self):
        from app.services.opendatabot_lookup import parse_company_page

        result = parse_company_page(FOUND_COMPANY_HTML, "12345678")

        self.assertEqual(len(result.registration_changes), 1)
        self.assertTrue(result.registration_changes[0].date_requires_login)
        self.assertEqual(result.registration_changes[0].change_type, "Змінилась адреса в едр")
        self.assertEqual(result.registration_changes[0].before, "стара адреса")
        self.assertEqual(result.registration_changes[0].after, "нова адреса")
        self.assertIn("Дата останньої зміни реєстраційної інформації закрита авторизацією", result.parse_warnings)

    def test_lookup_company_returns_source_error_on_fetch_error(self):
        from app.services.opendatabot_lookup import lookup_company

        def failing_fetcher(edrpou: str) -> str:
            raise URLError("network unavailable")

        result = lookup_company("12345678", fetcher=failing_fetcher)

        self.assertEqual(result.status, "source_error")
        self.assertEqual(result.edrpou, "12345678")
        self.assertIsNone(result.company_data)

    def test_lookup_company_treats_404_as_not_found(self):
        from app.services.opendatabot_lookup import lookup_company

        def not_found_fetcher(edrpou: str) -> str:
            raise HTTPError(
                url=f"https://opendatabot.ua/c/{edrpou}?from=search",
                code=404,
                msg="Not Found",
                hdrs=None,
                fp=BytesIO(),
            )

        result = lookup_company("12345678", fetcher=not_found_fetcher)

        self.assertEqual(result.status, "not_found")
        self.assertEqual(result.edrpou, "12345678")
        self.assertIsNone(result.company_data)


if __name__ == "__main__":
    unittest.main()
