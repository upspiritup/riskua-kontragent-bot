from pathlib import Path
import unittest
from unittest.mock import patch


FIXTURES = Path(__file__).parent / "fixtures"


class DomainReputationLookupTests(unittest.TestCase):
    def fixture(self, name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    def test_normalize_url_adds_https_if_scheme_is_missing(self):
        from app.services.domain_reputation_lookup import normalize_url

        self.assertEqual(normalize_url("example.ua"), "https://example.ua")
        self.assertEqual(normalize_url("www.example.ua/path"), "https://www.example.ua/path")

    def test_extract_domain_returns_normalized_domain(self):
        from app.services.domain_reputation_lookup import extract_domain

        self.assertEqual(extract_domain("https://www.example.ua/path?q=1"), "example.ua")

    def test_fetch_domain_reputation_returns_website_not_provided_without_url(self):
        from app.services.domain_reputation_lookup import fetch_domain_reputation

        result = fetch_domain_reputation("")

        self.assertFalse(result["checked"])
        self.assertFalse(result["found"])
        self.assertIsNone(result["url"])
        self.assertIsNone(result["domain"])
        self.assertEqual(result["risk_flags"], [])
        self.assertEqual(result["error"], "website_not_provided")

    def test_http_200_creates_found_result(self):
        from app.services.domain_reputation_lookup import fetch_domain_reputation

        def fetcher(url: str) -> dict:
            return {"status_code": 200, "final_url": url, "redirects": [], "html": self.fixture("domain_reputation_ok.html")}

        with patch("app.services.domain_reputation_lookup.fetch_ssl_info", return_value={"present": True, "not_before": None, "not_after": None, "issuer": None}), patch(
            "app.services.domain_reputation_lookup.fetch_dns_info",
            return_value={"found": True, "a_records": ["192.0.2.10"], "mx_records": []},
        ):
            result = fetch_domain_reputation("example.ua", company_context={"edrpou": "12345678", "company_name": "ТОВ ПРИКЛАД"}, fetcher=fetcher)

        self.assertTrue(result["checked"])
        self.assertTrue(result["found"])
        self.assertEqual(result["http"]["status_code"], 200)
        self.assertTrue(result["ssl"]["present"])
        self.assertTrue(result["dns"]["found"])
        self.assertEqual(result["contacts"]["emails"], ["sales@example.ua"])
        self.assertTrue(result["contacts"]["edrpou_found_on_page"])
        self.assertTrue(result["contacts"]["company_name_found_on_page"])
        self.assertEqual(result["trust_level"], "high")

    def test_http_error_creates_website_unavailable(self):
        from app.services.domain_reputation_lookup import fetch_domain_reputation

        def failing_fetcher(url: str) -> dict:
            raise TimeoutError("slow site")

        result = fetch_domain_reputation("https://example.ua", fetcher=failing_fetcher)

        self.assertTrue(result["checked"])
        self.assertFalse(result["found"])
        self.assertEqual(result["risk_flags"], ["website_unavailable"])
        self.assertEqual(result["error"], "website_unavailable")

    def test_missing_ssl_creates_ssl_missing_flag(self):
        from app.services.domain_reputation_lookup import fetch_domain_reputation

        def fetcher(url: str) -> dict:
            return {"status_code": 200, "final_url": url, "redirects": [], "html": self.fixture("domain_reputation_ok.html")}

        with patch("app.services.domain_reputation_lookup.fetch_ssl_info", return_value={"present": False, "not_before": None, "not_after": None, "issuer": None}), patch(
            "app.services.domain_reputation_lookup.fetch_dns_info",
            return_value={"found": True, "a_records": ["192.0.2.10"], "mx_records": []},
        ):
            result = fetch_domain_reputation("http://example.ua", fetcher=fetcher)

        self.assertIn("ssl_missing", result["risk_flags"])

    def test_missing_dns_creates_dns_not_found_flag(self):
        from app.services.domain_reputation_lookup import fetch_domain_reputation

        def fetcher(url: str) -> dict:
            return {"status_code": 200, "final_url": url, "redirects": [], "html": self.fixture("domain_reputation_ok.html")}

        with patch("app.services.domain_reputation_lookup.fetch_ssl_info", return_value={"present": True, "not_before": None, "not_after": None, "issuer": None}), patch(
            "app.services.domain_reputation_lookup.fetch_dns_info",
            return_value={"found": False, "a_records": [], "mx_records": []},
        ):
            result = fetch_domain_reputation("example.ua", fetcher=fetcher)

        self.assertIn("dns_not_found", result["risk_flags"])

    def test_html_with_only_free_email_creates_free_email_flag(self):
        from app.services.domain_reputation_lookup import fetch_domain_reputation

        def fetcher(url: str) -> dict:
            return {"status_code": 200, "final_url": url, "redirects": [], "html": self.fixture("domain_reputation_free_email.html")}

        with patch("app.services.domain_reputation_lookup.fetch_ssl_info", return_value={"present": True, "not_before": None, "not_after": None, "issuer": None}), patch(
            "app.services.domain_reputation_lookup.fetch_dns_info",
            return_value={"found": True, "a_records": ["192.0.2.10"], "mx_records": []},
        ):
            result = fetch_domain_reputation("example.ua", fetcher=fetcher)

        self.assertEqual(result["contacts"]["emails"], ["supplier@gmail.com"])
        self.assertIn("free_email_used", result["risk_flags"])

    def test_missing_company_edrpou_creates_flag_when_context_has_edrpou(self):
        from app.services.domain_reputation_lookup import fetch_domain_reputation

        def fetcher(url: str) -> dict:
            return {"status_code": 200, "final_url": url, "redirects": [], "html": self.fixture("domain_reputation_company_mismatch.html")}

        with patch("app.services.domain_reputation_lookup.fetch_ssl_info", return_value={"present": True, "not_before": None, "not_after": None, "issuer": None}), patch(
            "app.services.domain_reputation_lookup.fetch_dns_info",
            return_value={"found": True, "a_records": ["192.0.2.10"], "mx_records": []},
        ):
            result = fetch_domain_reputation("example.ua", company_context={"edrpou": "05747991"}, fetcher=fetcher)

        self.assertFalse(result["contacts"]["edrpou_found_on_page"])
        self.assertIn("company_edrpou_not_found_on_website", result["risk_flags"])

    def test_matching_company_edrpou_does_not_create_missing_edrpou_flag(self):
        from app.services.domain_reputation_lookup import fetch_domain_reputation

        def fetcher(url: str) -> dict:
            return {"status_code": 200, "final_url": url, "redirects": [], "html": self.fixture("domain_reputation_company_match.html")}

        with patch("app.services.domain_reputation_lookup.fetch_ssl_info", return_value={"present": True, "not_before": None, "not_after": None, "issuer": None}), patch(
            "app.services.domain_reputation_lookup.fetch_dns_info",
            return_value={"found": True, "a_records": ["192.0.2.10"], "mx_records": []},
        ):
            result = fetch_domain_reputation("snvo.ua", company_context={"edrpou": "05747991"}, fetcher=fetcher)

        self.assertTrue(result["contacts"]["edrpou_found_on_page"])
        self.assertNotIn("company_edrpou_not_found_on_website", result["risk_flags"])

    def test_missing_company_name_creates_flag_when_context_has_company_name(self):
        from app.services.domain_reputation_lookup import fetch_domain_reputation

        def fetcher(url: str) -> dict:
            return {"status_code": 200, "final_url": url, "redirects": [], "html": self.fixture("domain_reputation_company_mismatch.html")}

        with patch("app.services.domain_reputation_lookup.fetch_ssl_info", return_value={"present": True, "not_before": None, "not_after": None, "issuer": None}), patch(
            "app.services.domain_reputation_lookup.fetch_dns_info",
            return_value={"found": True, "a_records": ["192.0.2.10"], "mx_records": []},
        ):
            result = fetch_domain_reputation("example.ua", company_context={"company_name": 'АТ "СУМСЬКЕ НВО"'}, fetcher=fetcher)

        self.assertFalse(result["contacts"]["company_name_found_on_page"])
        self.assertIn("company_name_not_found_on_website", result["risk_flags"])

    def test_website_trust_is_not_high_without_matching_edrpou(self):
        from app.services.domain_reputation_lookup import fetch_domain_reputation

        def fetcher(url: str) -> dict:
            return {"status_code": 200, "final_url": url, "redirects": [], "html": self.fixture("domain_reputation_company_mismatch.html")}

        with patch("app.services.domain_reputation_lookup.fetch_ssl_info", return_value={"present": True, "not_before": None, "not_after": None, "issuer": None}), patch(
            "app.services.domain_reputation_lookup.fetch_dns_info",
            return_value={"found": True, "a_records": ["192.0.2.10"], "mx_records": []},
        ):
            result = fetch_domain_reputation(
                "example.ua",
                company_context={"edrpou": "05747991", "company_name": 'ТОВ "ІНШИЙ ПРОДАВЕЦЬ"'},
                fetcher=fetcher,
            )

        self.assertFalse(result["contacts"]["edrpou_found_on_page"])
        self.assertEqual(result["trust_level"], "low")
        self.assertNotEqual(result["trust_level"], "high")


if __name__ == "__main__":
    unittest.main()
