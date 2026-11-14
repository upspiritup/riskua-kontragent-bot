import unittest
from io import BytesIO
from urllib.error import HTTPError, URLError


class ContactSourceLookupTests(unittest.TestCase):
    def test_ua_region_direct_profile_with_contacts_is_high_confidence(self):
        from app.services.ua_region_lookup import fetch_ua_region_company

        html = """
        <html><body>
          <h1>ПРАТ "ВЗУТТЯ-ІФ"</h1>
          <p>Код ЄДРПОУ: 01554522</p>
          <p>Адреса: Івано-Франківськ, вул. Торгова, 3</p>
          <p>Телефон: +38 (0342) 55-11-22</p>
          <p>Email: office@if-shoes.ua</p>
          <p>Офіційний сайт: https://if-shoes.ua</p>
          <p>Керівник: Матей Юрій Густавович</p>
          <p>КВЕД: 15.20 Виробництво взуття</p>
        </body></html>
        """

        result = fetch_ua_region_company("01554522", fetcher=lambda url: html)

        self.assertEqual(result["source"], "ua-region.com.ua")
        self.assertEqual(result["status"], "found")
        self.assertEqual(result["company"]["edrpou"], "01554522")
        self.assertEqual(result["contacts"]["website"], "https://if-shoes.ua")
        self.assertEqual(result["contacts"]["email"], "office@if-shoes.ua")
        self.assertEqual(result["contacts"]["phone"], "+380342551122")
        self.assertEqual(result["confidence"], "high")

    def test_ua_region_profile_without_contacts_is_found_with_medium_confidence(self):
        from app.services.ua_region_lookup import fetch_ua_region_company

        html = """
        <html><body>
          <h1>ПРАТ "ВЗУТТЯ-ІФ"</h1>
          <p>ЄДРПОУ 01554522</p>
          <p>Адреса: Івано-Франківськ, вул. Торгова, 3</p>
        </body></html>
        """

        result = fetch_ua_region_company("01554522", fetcher=lambda url: html)

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["contacts"], {"website": None, "phone": None, "email": None})
        self.assertEqual(result["confidence"], "medium")

    def test_ua_region_404_returns_not_found(self):
        from app.services.ua_region_lookup import fetch_ua_region_company

        def fetcher(url: str) -> str:
            raise HTTPError(url=url, code=404, msg="Not Found", hdrs=None, fp=BytesIO())

        result = fetch_ua_region_company("01554522", fetcher=fetcher)

        self.assertEqual(result["status"], "not_found")
        self.assertEqual(result["confidence"], "unknown")

    def test_ua_region_phone_digits_do_not_count_as_edrpou_confirmation(self):
        from app.services.ua_region_lookup import fetch_ua_region_company

        html = """
        <html><body>
          <h1>ПРАТ "ВЗУТТЯ-ІФ"</h1>
          <p>Телефон: +380155452299</p>
          <p>Email: office@if-shoes.ua</p>
        </body></html>
        """

        result = fetch_ua_region_company("01554522", {"company_name": 'ПРАТ "ВЗУТТЯ-ІФ"'}, fetcher=lambda url: html)

        self.assertEqual(result["status"], "not_found")
        self.assertEqual(result["confidence"], "unknown")

    def test_prat_registry_and_confirmed_subdomain_are_high_confidence(self):
        from app.services.prat_lookup import fetch_prat_company

        registry_html = """
        <html><body>
          <table><tr><td>01554522</td><td>ПРАТ "ВЗУТТЯ-ІФ"</td>
          <td><a href="http://ifshoes.prat.ua">Сайт емітента</a></td></tr></table>
        </body></html>
        """
        profile_html = """
        <html><body>
          <h1>ПРАТ "ВЗУТТЯ-ІФ"</h1>
          <p>Код за ЄДРПОУ: 01554522</p>
          <p>Юридична адреса: Івано-Франківськ, вул. Торгова, 3</p>
          <p>Телефон: 0342 55 11 22</p>
          <p>E-mail: office@if-shoes.ua</p>
        </body></html>
        """

        def fetcher(url: str) -> str:
            if "reestr.php" in url:
                return registry_html
            return profile_html

        result = fetch_prat_company("01554522", fetcher=fetcher)

        self.assertEqual(result["source"], "prat.ua/pat.ua")
        self.assertEqual(result["status"], "found")
        self.assertEqual(result["raw_url"], "https://ifshoes.prat.ua")
        self.assertEqual(result["contacts"]["website"], "https://ifshoes.prat.ua")
        self.assertEqual(result["contacts"]["email"], "office@if-shoes.ua")
        self.assertEqual(result["confidence"], "high")

    def test_prat_subdomain_unavailable_keeps_found_without_high_confidence(self):
        from app.services.prat_lookup import fetch_prat_company

        registry_html = """
        <html><body>
          01554522 ПРАТ "ВЗУТТЯ-ІФ" <a href="http://ifshoes.prat.ua">Сайт</a>
        </body></html>
        """

        def fetcher(url: str) -> str:
            if "reestr.php" in url:
                return registry_html
            raise URLError("host down")

        result = fetch_prat_company("01554522", fetcher=fetcher)

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["contacts"]["website"], "http://ifshoes.prat.ua")
        self.assertEqual(result["confidence"], "medium")
        self.assertIn("сайт компанії не відкривається", " ".join(result["evidence"]).lower())

    def test_prat_registry_uses_company_row_url_not_partner_banner(self):
        from app.services.prat_lookup import fetch_prat_company

        registry_html = """
        <html><body>
          <div class="banners"><a href="http://gazeta.pat.ua">partner</a></div>
          <div class="search"><input name="edrpou" value="01554522"></div>
          <div class="reestr_item">
            <a href="http://vzuttjaif.prat.ua" class="logo">logo</a>
            <h4><a href="http://vzuttjaif.prat.ua">Приватне акціонерне товариство &quot;ВЗУТТЯ-ІФ&quot;</a></h4>
            <p>ЄДРПОУ: 01554522</p>
            <p><a href="http://vzuttjaif.prat.ua">http://vzuttjaif.prat.ua</a></p>
            <div style="clear: both;"></div>
          </div>
        </body></html>
        """
        profile_html = """
        <html><body>
          <h1>ПРАТ "ВЗУТТЯ-ІФ"</h1>
          <p>ЄДРПОУ: 01554522</p>
          <p>Email: office@vzuttjaif.prat.ua</p>
        </body></html>
        """

        def fetcher(url: str) -> str:
            if "reestr.php" in url:
                return registry_html
            if url == "http://vzuttjaif.prat.ua":
                return profile_html
            raise URLError("wrong domain")

        result = fetch_prat_company("01554522", fetcher=fetcher)

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["raw_url"], "http://vzuttjaif.prat.ua")
        self.assertEqual(result["contacts"]["website"], "http://vzuttjaif.prat.ua")
        self.assertEqual(result["contacts"]["email"], "office@vzuttjaif.prat.ua")

    def test_prat_similar_name_without_edrpou_is_not_high_confidence(self):
        from app.services.prat_lookup import parse_prat_profile

        html = """
        <html><body>
          <h1>ПРАТ "ВЗУТТЯ-ІФ"</h1>
          <p>Адреса: Івано-Франківськ, вул. Торгова, 3</p>
          <p>Телефон: 0342 55 11 22</p>
        </body></html>
        """

        result = parse_prat_profile(
            html,
            "01554522",
            {"company_name": 'ПРАТ "ВЗУТТЯ-ІФ"', "address": "Івано-Франківськ, вул. Торгова, 3"},
            "http://ifshoes.prat.ua",
        )

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["confidence"], "low")
        self.assertNotEqual(result["confidence"], "high")

    def test_prat_fallback_search_tries_prat_query_and_https_variant(self):
        from app.services.prat_lookup import fetch_prat_company

        profile_html = """
        <html><body>
          <h1>ПРАТ "ВЗУТТЯ-ІФ"</h1>
          <p>Код за ЄДРПОУ: 01554522</p>
          <p>Юридична адреса: Івано-Франківськ, вул. Торгова, 3</p>
          <p>Керівник: Матей Юрій Густавович</p>
          <p>Телефон: 0342 55 11 22</p>
          <p>Email: office@if-shoes.ua</p>
        </body></html>
        """
        queries: list[str] = []
        fetched_urls: list[str] = []

        def fetcher(url: str) -> str:
            fetched_urls.append(url)
            if "reestr.php" in url or url.startswith("http://ifshoes.prat.ua"):
                raise URLError("not available")
            if url == "https://ifshoes.prat.ua":
                return profile_html
            raise URLError("unexpected url")

        def searcher(query: str) -> list[str]:
            queries.append(query)
            if query == '"01554522" "ПРАТ "ВЗУТТЯ-ІФ""':
                return ["https://search.example/result?url=http://ifshoes.prat.ua"]
            return []

        result = fetch_prat_company(
            "01554522",
            {"company_name": 'ПРАТ "ВЗУТТЯ-ІФ"', "address": "Івано-Франківськ, вул. Торгова, 3"},
            fetcher=fetcher,
            searcher=searcher,
        )

        self.assertIn('"01554522" site:pat.ua', queries)
        self.assertIn('"01554522" site:prat.ua', queries)
        self.assertIn('"01554522" "prat.ua"', queries)
        self.assertIn('"01554522" "ПРАТ "ВЗУТТЯ-ІФ""', queries)
        self.assertIn("http://ifshoes.prat.ua", fetched_urls)
        self.assertIn("https://ifshoes.prat.ua", fetched_urls)
        self.assertEqual(result["status"], "found")
        self.assertEqual(result["raw_url"], "https://ifshoes.prat.ua")
        self.assertEqual(result["contacts"]["email"], "office@if-shoes.ua")
        self.assertEqual(result["company"]["director"], "Матей Юрій Густавович")
        self.assertEqual(result["confidence"], "high")

    def test_prat_fallback_finds_vzuttjaif_prat_domain(self):
        from app.services.prat_lookup import fetch_prat_company

        profile_html = """
        <html><body>
          <h1>ПРАТ "ВЗУТТЯ-ІФ"</h1>
          <p>ЄДРПОУ: 01554522</p>
          <p>Адреса: Івано-Франківськ, вул. Торгова, 3</p>
          <p>Керівник: Матей Юрій Густавович</p>
          <p>Телефон: 0342 55 11 22</p>
          <p>Email: office@vzuttjaif.prat.ua</p>
        </body></html>
        """

        def fetcher(url: str) -> str:
            if "reestr.php" in url or url == "http://vzuttjaif.prat.ua":
                raise URLError("not available")
            if url == "https://vzuttjaif.prat.ua":
                return profile_html
            raise URLError("unexpected url")

        def searcher(query: str) -> list[str]:
            if query == '"01554522" "prat.ua"':
                return ["https://search.example/?url=https%3A%2F%2Fvzuttjaif.prat.ua%2F"]
            return []

        result = fetch_prat_company(
            "01554522",
            {"company_name": 'ПРАТ "ВЗУТТЯ-ІФ"', "address": "Івано-Франківськ, вул. Торгова, 3"},
            fetcher=fetcher,
            searcher=searcher,
        )

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["raw_url"], "https://vzuttjaif.prat.ua")
        self.assertEqual(result["contacts"]["website"], "https://vzuttjaif.prat.ua")
        self.assertEqual(result["contacts"]["email"], "office@vzuttjaif.prat.ua")
        self.assertEqual(result["contacts"]["phone"], "+380342551122")
        self.assertEqual(result["company"]["edrpou"], "01554522")
        self.assertEqual(result["company"]["director"], "Матей Юрій Густавович")
        self.assertTrue(result["fallback_used"])
        self.assertEqual(result["confidence"], "high")

    def test_prat_profile_extracts_phone_and_specific_high_confidence_evidence(self):
        from app.services.prat_lookup import parse_prat_profile

        html = """
        <html><body>
          <h1>ПРАТ "ВЗУТТЯ-ІФ"</h1>
          <p>ЄДРПОУ: 01554522</p>
          <p>Адреса: Івано-Франківськ, вул. Торгова, 3</p>
          <p>Керівник: Матей Юрій Густавович</p>
          <p>Телефон: (03422) 225-40</p>
          <p>Email: info@vzuttjaif.prat.ua</p>
        </body></html>
        """

        result = parse_prat_profile(
            html,
            "01554522",
            {
                "company_name": 'ПРАТ "ВЗУТТЯ-ІФ"',
                "address": "Івано-Франківськ, вул. Торгова, 3",
                "director": "Матей Юрій Густавович",
            },
            "https://vzuttjaif.prat.ua",
        )

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["contacts"]["website"], "https://vzuttjaif.prat.ua")
        self.assertEqual(result["contacts"]["phone"], "+380342222540")
        self.assertEqual(result["contacts"]["email"], "info@vzuttjaif.prat.ua")
        self.assertEqual(result["confidence"], "high")
        self.assertIn(
            "На сторінці знайдено той самий ЄДРПОУ, назву компанії, адресу та керівника.",
            result["evidence"],
        )
        self.assertNotIn("Ймовірний сайт компанії з порталу PRAT/PAT.", result["evidence"])

    def test_extract_phones_rejects_edrpou_digits_without_phone_label(self):
        from app.services.contact_parsing import extract_phones

        text = """
        АТ "ГІДРОСИЛА"
        ЄДРПОУ: 05786100
        Код за ЄДРПОУ: 05786100
        Службові цифри: 0578610038
        """

        self.assertNotIn("+380578610038", extract_phones(text, expected_edrpou="05786100"))
        self.assertEqual(extract_phones(text, expected_edrpou="05786100"), [])

    def test_extract_phones_returns_labelled_pat_phone(self):
        from app.services.contact_parsing import extract_phones

        text = """
        Код за ЄДРПОУ: 05786100
        Телефон: +38 (0522) 39-13-94
        """

        self.assertEqual(extract_phones(text, expected_edrpou="05786100"), ["+380522391394"])

    def test_prat_profile_extracts_hidrosyla_phone_from_phone_field(self):
        from app.services.prat_lookup import parse_prat_profile

        html = """
        <html><body>
          <h1>АТ "ГІДРОСИЛА"</h1>
          <p>ЄДРПОУ: 05786100</p>
          <p>Службові цифри: 0578610038</p>
          <p>Телефон: +38 (0522) 39-13-94</p>
          <p>Email: office@hydrosila.prat.ua</p>
        </body></html>
        """

        result = parse_prat_profile(
            html,
            "05786100",
            {"company_name": 'АТ "ГІДРОСИЛА"'},
            "https://hydrosila.prat.ua",
        )

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["contacts"]["phone"], "+380522391394")
        self.assertNotEqual(result["contacts"]["phone"], "+380578610038")

    def test_edrpou_cannot_be_part_of_phone(self):
        from app.services.contact_parsing import extract_phones

        text = "Телефон: +38 (05786100) 38"

        self.assertEqual(extract_phones(text, expected_edrpou="05786100"), [])

    def test_smida_report_xml_parses_company_email(self):
        from app.services.smida_lookup import fetch_smida_company

        xml = """
        <issuer>
          <edrpou>01554522</edrpou>
          <name>ПРАТ "ВЗУТТЯ-ІФ"</name>
          <address>Івано-Франківськ, вул. Торгова, 3</address>
          <email>office@if-shoes.ua</email>
          <phone>0342551122</phone>
          <website>https://if-shoes.ua</website>
        </issuer>
        """

        result = fetch_smida_company(
            "01554522",
            {"company_name": 'ПРАТ "ВЗУТТЯ-ІФ"'},
            fetcher=lambda url: xml,
            searcher=lambda query: ["https://smida.gov.ua/report.xml"],
        )

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["contacts"]["email"], "office@if-shoes.ua")
        self.assertEqual(result["contacts"]["website"], "https://if-shoes.ua")
        self.assertEqual(result["confidence"], "high")

    def test_smida_service_email_and_footer_phone_are_not_company_contacts(self):
        from app.services.smida_lookup import parse_smida_document

        html = """
        <html><body>
          <section>
            <h1>ПРАТ "ВЗУТТЯ-ІФ"</h1>
            <p>ЄДРПОУ: 01554522</p>
          </section>
          <footer>Підтримка SMIDA: help@smida.gov.ua, телефон +380445000000</footer>
        </body></html>
        """

        result = parse_smida_document(
            html,
            "01554522",
            {"company_name": 'ПРАТ "ВЗУТТЯ-ІФ"'},
            "https://smida.gov.ua/page",
        )

        self.assertEqual(result["status"], "found")
        self.assertIsNone(result["contacts"]["email"])
        self.assertIsNone(result["contacts"]["phone"])
        self.assertEqual(result["confidence"], "medium")

    def test_business_guide_profile_with_edrpou_and_contacts_is_high_confidence(self):
        from app.services.business_guide_lookup import fetch_business_guide_company

        html = """
        <html><body>
          <h1>ПРАТ "ВЗУТТЯ-ІФ"</h1>
          <p>ЄДРПОУ: 01554522</p>
          <p>Адреса: Івано-Франківськ, вул. Торгова, 3</p>
          <p>Телефон: +380342551122</p>
          <p>Email: office@if-shoes.ua</p>
        </body></html>
        """

        result = fetch_business_guide_company(
            "01554522",
            {"company_name": 'ПРАТ "ВЗУТТЯ-ІФ"'},
            fetcher=lambda url: html,
            searcher=lambda query: ["https://ifshoes.business-guide.com.ua"],
        )

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["confidence"], "high")
        self.assertEqual(result["contacts"]["phone"], "+380342551122")

    def test_business_guide_ignores_non_business_guide_search_results(self):
        from app.services.business_guide_lookup import fetch_business_guide_company

        fetched_urls: list[str] = []

        def fetcher(url: str) -> str:
            fetched_urls.append(url)
            return """
            <html><body>
              <p>ЄДРПОУ: 01554522</p>
              <p>Телефон: +380342551122</p>
            </body></html>
            """

        result = fetch_business_guide_company(
            "01554522",
            {"company_name": 'ПРАТ "ВЗУТТЯ-ІФ"'},
            fetcher=fetcher,
            searcher=lambda query: ["http://www.w3.org/1999/xhtml"],
        )

        self.assertEqual(result["status"], "not_found")
        self.assertEqual(fetched_urls, [])

    def test_business_guide_profile_without_edrpou_is_not_high(self):
        from app.services.business_guide_lookup import parse_business_guide_profile

        html = """
        <html><body>
          <h1>ПРАТ "ВЗУТТЯ-ІФ"</h1>
          <p>Адреса: Івано-Франківськ, вул. Торгова, 3</p>
          <p>Телефон: +380342551122</p>
        </body></html>
        """

        result = parse_business_guide_profile(
            html,
            "01554522",
            {"company_name": 'ПРАТ "ВЗУТТЯ-ІФ"', "address": "Івано-Франківськ, вул. Торгова, 3"},
            "https://ifshoes.business-guide.com.ua",
        )

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["confidence"], "medium")
        self.assertNotEqual(result["confidence"], "high")

    def test_business_guide_similar_name_without_confirmation_is_low(self):
        from app.services.business_guide_lookup import parse_business_guide_profile

        html = """
        <html><body>
          <h1>ПРАТ "ВЗУТТЯ-ІФ"</h1>
          <p>Продукція: взуття</p>
        </body></html>
        """

        result = parse_business_guide_profile(
            html,
            "01554522",
            {"company_name": 'ПРАТ "ВЗУТТЯ-ІФ"'},
            "https://ifshoes.business-guide.com.ua",
        )

        self.assertEqual(result["confidence"], "low")

    def test_empty_significant_company_name_tokens_do_not_match_any_catalog_page(self):
        from app.services.business_guide_lookup import parse_business_guide_profile

        html = """
        <html><body>
          <h1>Невідома компанія</h1>
          <p>Телефон: +380342551122</p>
        </body></html>
        """

        result = parse_business_guide_profile(
            html,
            "01554522",
            {"company_name": "ТОВ"},
            "https://unknown.business-guide.com.ua",
        )

        self.assertEqual(result["confidence"], "unknown")


if __name__ == "__main__":
    unittest.main()
