import unittest
import asyncio
import time


class ContactsSummaryTests(unittest.TestCase):
    def test_repeated_email_across_two_sources_is_high_confidence(self):
        from app.services.company_contacts_lookup import build_contacts_summary

        summary = build_contacts_summary(
            [
                source_result("ua-region.com.ua", email="office@if-shoes.ua", confidence="medium"),
                source_result("business-guide.com.ua", email="office@if-shoes.ua", confidence="medium"),
            ],
            {"edrpou": "01554522"},
        )

        self.assertEqual(summary["email"]["value"], "office@if-shoes.ua")
        self.assertEqual(summary["email"]["confidence"], "high")
        self.assertEqual(summary["email"]["sources"], ["ua-region.com.ua", "business-guide.com.ua"])

    def test_email_domain_matching_confirmed_website_is_high_confidence(self):
        from app.services.company_contacts_lookup import build_contacts_summary

        summary = build_contacts_summary(
            [
                source_result("ua-region.com.ua", website="https://if-shoes.ua", confidence="high"),
                source_result("smida.gov.ua", email="office@if-shoes.ua", confidence="medium"),
            ],
            {"edrpou": "01554522"},
        )

        self.assertEqual(summary["website"]["value"], "https://if-shoes.ua")
        self.assertEqual(summary["email"]["value"], "office@if-shoes.ua")
        self.assertEqual(summary["email"]["confidence"], "high")

    def test_unavailable_source_adds_warning_and_does_not_create_contact(self):
        from app.services.company_contacts_lookup import build_contacts_summary

        summary = build_contacts_summary(
            [
                {
                    "source": "smida.gov.ua",
                    "status": "unavailable",
                    "company": {},
                    "contacts": {"website": None, "phone": None, "email": None},
                    "evidence": [],
                    "confidence": "unknown",
                    "raw_url": None,
                    "error": "timeout",
                }
            ],
            {"edrpou": "01554522"},
        )

        self.assertIsNone(summary["website"]["value"])
        self.assertEqual(summary["website"]["confidence"], "unknown")
        self.assertEqual(summary["checked_sources"], ["smida.gov.ua"])
        self.assertIn("smida.gov.ua", summary["warnings"][0])

    def test_lookup_exception_keeps_configured_source_name(self):
        from app.services.company_contacts_lookup import fetch_company_contacts

        def failing_lookup(edrpou: str, company_context: dict | None = None) -> dict:
            raise TimeoutError("slow source")

        summary = fetch_company_contacts(
            "01554522",
            {"edrpou": "01554522"},
            lookups=[("ua-region.com.ua", failing_lookup)],
        )

        self.assertEqual(summary["checked_sources"], ["ua-region.com.ua"])
        self.assertEqual(summary["source_statuses"]["ua-region.com.ua"], "unavailable")
        self.assertIn("ua-region.com.ua", summary["warnings"][0])

    def test_async_lookup_keeps_prat_found_when_smida_times_out(self):
        from app.services.company_contacts_lookup import fetch_company_contacts_async

        def found_prat(edrpou: str, company_context: dict | None = None) -> dict:
            return source_result(
                "prat.ua/pat.ua",
                website="https://vzuttjaif.prat.ua",
                email="office@vzuttjaif.prat.ua",
                confidence="high",
            )

        def slow_smida(edrpou: str, company_context: dict | None = None) -> dict:
            time.sleep(0.2)
            return source_result("smida.gov.ua", website="https://late.example", confidence="high")

        summary = asyncio.run(
            fetch_company_contacts_async(
                "01554522",
                {"edrpou": "01554522", "company_name": 'ПРАТ "ВЗУТТЯ-ІФ"'},
                lookups=[("prat.ua/pat.ua", found_prat), ("smida.gov.ua", slow_smida)],
                source_timeouts={"prat.ua/pat.ua": 1.0, "smida.gov.ua": 0.01},
                overall_timeout=1.0,
            )
        )

        self.assertEqual(summary["website"]["value"], "https://vzuttjaif.prat.ua")
        self.assertEqual(summary["website"]["sources"], ["prat.ua/pat.ua"])
        self.assertEqual(summary["source_statuses"]["prat.ua/pat.ua"], "found")
        self.assertEqual(summary["source_statuses"]["smida.gov.ua"], "unavailable")

    def test_timeout_one_contact_source_does_not_clear_other_results(self):
        from app.services.company_contacts_lookup import fetch_company_contacts_async

        def found_ua_region(edrpou: str, company_context: dict | None = None) -> dict:
            return source_result("ua-region.com.ua", phone="+380342551122", confidence="high")

        def slow_business_guide(edrpou: str, company_context: dict | None = None) -> dict:
            time.sleep(0.2)
            return source_result("business-guide.com.ua", phone="+380000000000", confidence="high")

        summary = asyncio.run(
            fetch_company_contacts_async(
                "01554522",
                {"edrpou": "01554522"},
                lookups=[("ua-region.com.ua", found_ua_region), ("business-guide.com.ua", slow_business_guide)],
                source_timeouts={"ua-region.com.ua": 1.0, "business-guide.com.ua": 0.01},
                overall_timeout=1.0,
            )
        )

        self.assertEqual(summary["phone"]["value"], "+380342551122")
        self.assertEqual(summary["source_statuses"]["ua-region.com.ua"], "found")
        self.assertEqual(summary["source_statuses"]["business-guide.com.ua"], "unavailable")

    def test_all_sources_unavailable_only_when_each_source_fails(self):
        from app.services.company_contacts_lookup import fetch_company_contacts_async

        def failing_lookup(edrpou: str, company_context: dict | None = None) -> dict:
            raise TimeoutError("slow source")

        summary = asyncio.run(
            fetch_company_contacts_async(
                "01554522",
                {"edrpou": "01554522"},
                lookups=[
                    ("ua-region.com.ua", failing_lookup),
                    ("prat.ua/pat.ua", failing_lookup),
                    ("smida.gov.ua", failing_lookup),
                    ("business-guide.com.ua", failing_lookup),
                ],
                overall_timeout=1.0,
            )
        )

        self.assertEqual(
            summary["source_statuses"],
            {
                "ua-region.com.ua": "unavailable",
                "prat.ua/pat.ua": "unavailable",
                "smida.gov.ua": "unavailable",
                "business-guide.com.ua": "unavailable",
            },
        )
        self.assertIsNone(summary["website"]["value"])

    def test_contact_source_debug_contains_duration_status_and_contact_count(self):
        from app.services.company_contacts_lookup import fetch_company_contacts_async

        summary = asyncio.run(
            fetch_company_contacts_async(
                "01554522",
                {"edrpou": "01554522"},
                lookups=[("ua-region.com.ua", lambda edrpou, context: source_result("ua-region.com.ua", email="office@if-shoes.ua"))],
            )
        )

        debug = summary["source_debug"][0]
        self.assertEqual(debug["source"], "ua-region.com.ua")
        self.assertEqual(debug["final_status"], "found")
        self.assertIsInstance(debug["duration_ms"], int)
        self.assertEqual(debug["contacts_found_count"], 1)

    def test_contact_summary_text_hides_raw_source_statuses(self):
        from app.bot import build_contacts_summary_lines

        summary = {
            "website": {"value": None, "confidence": "unknown", "sources": [], "evidence": []},
            "phone": {"value": None, "confidence": "unknown", "sources": [], "evidence": []},
            "email": {"value": None, "confidence": "unknown", "sources": [], "evidence": []},
            "checked_sources": ["ua-region.com.ua", "prat.ua/pat.ua"],
            "missing_sources": ["ua-region.com.ua"],
            "warnings": ["Джерело prat.ua/pat.ua тимчасово недоступне або заблокувало автоматичну перевірку."],
            "source_statuses": {"ua-region.com.ua": "not_found", "prat.ua/pat.ua": "unavailable"},
        }

        lines = build_contacts_summary_lines(summary)
        text = "\n".join(lines)

        self.assertIn("Сайт: не вдалося автоматично перевірити", text)
        self.assertIn("Телефон: не вдалося автоматично перевірити", text)
        self.assertIn("Email: не вдалося автоматично перевірити", text)
        self.assertNotIn("Сайт: не знайдено у перевірених джерелах", text)
        self.assertNotIn("not_found", text)
        self.assertNotIn("unavailable", text)
        self.assertNotIn("parse_error", text)
        self.assertNotIn("Перевірені джерела:", text)
        self.assertNotIn("Обмеження:", text)

    def test_all_contact_sources_unavailable_is_not_reported_as_not_found(self):
        from app.bot import build_contacts_summary_lines

        summary = {
            "website": {"value": None, "confidence": "unknown", "sources": [], "evidence": []},
            "phone": {"value": None, "confidence": "unknown", "sources": [], "evidence": []},
            "email": {"value": None, "confidence": "unknown", "sources": [], "evidence": []},
            "checked_sources": ["ua-region.com.ua", "prat.ua/pat.ua", "smida.gov.ua", "business-guide.com.ua"],
            "missing_sources": [],
            "warnings": [
                "Джерело ua-region.com.ua тимчасово недоступне або заблокувало автоматичну перевірку.",
                "Джерело prat.ua/pat.ua тимчасово недоступне або заблокувало автоматичну перевірку.",
                "Джерело smida.gov.ua тимчасово недоступне або заблокувало автоматичну перевірку.",
                "Джерело business-guide.com.ua тимчасово недоступне або заблокувало автоматичну перевірку.",
            ],
            "source_statuses": {
                "ua-region.com.ua": "unavailable",
                "prat.ua/pat.ua": "unavailable",
                "smida.gov.ua": "unavailable",
                "business-guide.com.ua": "unavailable",
            },
        }

        text = "\n".join(build_contacts_summary_lines(summary))

        self.assertIn("Сайт: не вдалося автоматично перевірити", text)
        self.assertIn("Телефон: не вдалося автоматично перевірити", text)
        self.assertIn("Email: не вдалося автоматично перевірити", text)
        self.assertNotIn("не знайдено у перевірених джерелах", text)
        self.assertNotIn("unavailable", text)

    def test_checked_contact_sources_without_hits_are_reported_as_not_found(self):
        from app.bot import build_contacts_summary_lines

        summary = {
            "website": {"value": None, "confidence": "unknown", "sources": [], "evidence": []},
            "phone": {"value": None, "confidence": "unknown", "sources": [], "evidence": []},
            "email": {"value": None, "confidence": "unknown", "sources": [], "evidence": []},
            "checked_sources": ["ua-region.com.ua", "business-guide.com.ua"],
            "missing_sources": ["ua-region.com.ua", "business-guide.com.ua"],
            "warnings": [],
            "source_statuses": {"ua-region.com.ua": "not_found", "business-guide.com.ua": "not_found"},
        }

        text = "\n".join(build_contacts_summary_lines(summary))

        self.assertIn("Сайт: не знайдено в доступних джерелах", text)
        self.assertIn("Телефон: не знайдено в доступних джерелах", text)
        self.assertIn("Email: не знайдено в доступних джерелах", text)
        self.assertNotIn("Пошук контактів неповний", text)


def source_result(
    source: str,
    *,
    website: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    confidence: str = "medium",
) -> dict:
    return {
        "source": source,
        "status": "found",
        "company": {"edrpou": "01554522"},
        "contacts": {"website": website, "phone": phone, "email": email},
        "evidence": ["ЄДРПОУ підтверджено"],
        "confidence": confidence,
        "raw_url": "https://example.test",
        "error": None,
    }


if __name__ == "__main__":
    unittest.main()
