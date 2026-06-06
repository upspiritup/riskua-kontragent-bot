import unittest
from io import BytesIO
from urllib.error import HTTPError, URLError


YOUCONTROL_COMPANY_HTML = """
<html>
  <body>
    <main>
      <h1>ТОВ «ПРИКЛАД»</h1>
      <p>Код ЄДРПОУ</p><p>01554545</p>
      <p>Статус</p><p>Зареєстровано</p>
      <p>Дата реєстрації</p><p>12.04.2001</p>
      <p>Адреса</p><p>01001, Україна, місто Київ, вулиця Тестова, 1</p>
      <p>Керівник</p><p>Іваненко Іван Іванович</p>
      <p>Телефон</p><p>+38 (0569) 55-11-22</p>
      <p>Email</p><p>office@example.ua</p>
      <p>Сайт</p><p>https://example.ua</p>
      <p>Основний КВЕД</p><p>46.90 Неспеціалізована оптова торгівля</p>
      <p>Додаткові КВЕДи</p><p>47.19 Інші види роздрібної торгівлі</p>
      <p>Судові справи</p><p>3</p>
      <p>Виконавчі провадження</p><p>1</p>
      <p>Податковий борг</p><p>наявний</p>
      <p>Ризикові попередження</p><p>Виявлено можливі ризикові ознаки</p>
    </main>
  </body>
</html>
"""


class YouControlLookupTests(unittest.TestCase):
    def test_build_youcontrol_url(self):
        from app.services.youcontrol_lookup import build_youcontrol_url

        self.assertEqual(
            build_youcontrol_url("01554545"),
            "https://youcontrol.com.ua/catalog/company_details/01554545/",
        )

    def test_fetch_youcontrol_company_returns_public_source_data(self):
        from app.services.youcontrol_lookup import fetch_youcontrol_company

        def fetcher(url: str) -> str:
            self.assertEqual(url, "https://youcontrol.com.ua/catalog/company_details/01554545/")
            return YOUCONTROL_COMPANY_HTML

        result = fetch_youcontrol_company("01554545", fetcher=fetcher)

        self.assertEqual(result["source"], "youcontrol")
        self.assertTrue(result["found"])
        self.assertEqual(result["company"]["edrpou"], "01554545")
        self.assertEqual(result["company"]["name"], "ТОВ «ПРИКЛАД»")
        self.assertEqual(result["company"]["status"], "Зареєстровано")
        self.assertEqual(result["company"]["registration_date"], "12.04.2001")
        self.assertEqual(result["company"]["director"], "Іваненко Іван Іванович")
        self.assertEqual(result["company"]["phone"], "+38 (0569) 55-11-22")
        self.assertEqual(result["company"]["email"], "office@example.ua")
        self.assertEqual(result["company"]["website"], "https://example.ua")
        self.assertEqual(result["company"]["main_kved"], "46.90 Неспеціалізована оптова торгівля")
        self.assertIn("47.19 Інші види роздрібної торгівлі", result["company"]["additional_kveds"])
        self.assertIn("court_cases_found", result["risk_flags"])
        self.assertIn("enforcement_found", result["risk_flags"])
        self.assertIn("tax_debt_found", result["risk_flags"])
        self.assertNotIn("<html", result["raw_text_excerpt"].lower())

    def test_fetch_youcontrol_company_handles_blocked_page(self):
        from app.services.youcontrol_lookup import fetch_youcontrol_company

        result = fetch_youcontrol_company(
            "01554545",
            fetcher=lambda url: "<html><title>Just a moment...</title><body>Cloudflare captcha</body></html>",
        )

        self.assertEqual(result["source"], "youcontrol")
        self.assertFalse(result["found"])
        self.assertEqual(result["error"], "blocked_or_unavailable")

    def test_fetch_youcontrol_company_handles_network_error(self):
        from app.services.youcontrol_lookup import fetch_youcontrol_company

        def fetcher(url: str) -> str:
            raise URLError("network unavailable")

        result = fetch_youcontrol_company("01554545", fetcher=fetcher)

        self.assertFalse(result["found"])
        self.assertEqual(result["error"], "blocked_or_unavailable")

    def test_fetch_youcontrol_company_handles_http_404_as_not_found(self):
        from app.services.youcontrol_lookup import fetch_youcontrol_company

        def fetcher(url: str) -> str:
            raise HTTPError(url=url, code=404, msg="Not Found", hdrs=None, fp=BytesIO())

        result = fetch_youcontrol_company("01554545", fetcher=fetcher)

        self.assertFalse(result["found"])
        self.assertEqual(result["error"], "company_not_found")
        self.assertIn("company_not_found", result["risk_flags"])

    def test_negative_phrases_do_not_create_risk_flags(self):
        from app.services.youcontrol_lookup import fetch_youcontrol_company

        html = """
        <html>
          <body>
            <main>
              <h1>ТОВ «ПРИКЛАД»</h1>
              <p>Код ЄДРПОУ</p><p>01554545</p>
              <p>Статус</p><p>Зареєстровано</p>
              <p>Компанія не перебуває в процесі припинення</p>
              <p>Банкрутство не виявлено</p>
              <p>Податковий борг відсутній</p>
              <p>Виконавчі провадження відсутні</p>
              <p>Борг ЄСВ відсутній</p>
            </main>
          </body>
        </html>
        """

        result = fetch_youcontrol_company("01554545", fetcher=lambda url: html)

        self.assertTrue(result["found"])
        self.assertNotIn("company_in_termination", result["risk_flags"])
        self.assertNotIn("bankruptcy_found", result["risk_flags"])
        self.assertNotIn("tax_debt_found", result["risk_flags"])
        self.assertNotIn("enforcement_found", result["risk_flags"])
        self.assertIn("Банкрутство: не виявлено", result["signals"])

    def test_registered_status_and_safe_inactive_words_do_not_create_inactive_risk(self):
        from app.services.youcontrol_lookup import fetch_youcontrol_company

        html = """
        <html>
          <body>
            <main>
              <h1>ПРАТ "ВЗУТТЯ-ІФ"</h1>
              <p>Код ЄДРПОУ</p><p>01554522</p>
              <p>Статус</p><p>Зареєстровано</p>
              <p>Статус: Зареєстровано</p>
              <p>Відомості про припинення відсутні</p>
              <p>Не перебуває в процесі припинення</p>
              <p>Банкрутство не виявлено</p>
              <p>ПДВ-реєстрацію не анульовано</p>
            </main>
          </body>
        </html>
        """

        result = fetch_youcontrol_company("01554522", fetcher=lambda url: html)

        self.assertTrue(result["found"])
        self.assertEqual(result["company"]["status"], "Зареєстровано")
        self.assertNotIn("company_inactive", result["risk_flags"])
        self.assertNotIn("company_in_termination", result["risk_flags"])
        self.assertNotIn("bankruptcy_found", result["risk_flags"])

    def test_bankruptcy_label_without_confirmed_phrase_does_not_create_flag(self):
        from app.services.youcontrol_lookup import fetch_youcontrol_company

        html = """
        <html>
          <body>
            <main>
              <h1>ТОВ «ДЛЗ»</h1>
              <p>Код ЄДРПОУ</p><p>38673411</p>
              <p>Статус</p><p>Зареєстровано</p>
              <p>Банкрутство</p>
              <p>Перевірка джерела не дала підтвердженої ризикової ознаки</p>
            </main>
          </body>
        </html>
        """

        result = fetch_youcontrol_company("38673411", fetcher=lambda url: html)

        self.assertTrue(result["found"])
        self.assertNotIn("bankruptcy_found", result["risk_flags"])

    def test_confirmed_bankruptcy_phrase_creates_flag(self):
        from app.services.youcontrol_lookup import fetch_youcontrol_company

        html = """
        <html>
          <body>
            <main>
              <h1>ТОВ «ПРИКЛАД»</h1>
              <p>Код ЄДРПОУ</p><p>01554545</p>
              <p>Статус</p><p>Зареєстровано</p>
              <p>Адреса</p><p>01001, Україна, місто Київ</p>
              <p>Керівник</p><p>Іваненко Іван Іванович</p>
              <p>Відкрито провадження про банкрутство</p>
            </main>
          </body>
        </html>
        """

        result = fetch_youcontrol_company("01554545", fetcher=lambda url: html)

        self.assertTrue(result["found"])
        self.assertIn("bankruptcy_found", result["risk_flags"])


if __name__ == "__main__":
    unittest.main()
