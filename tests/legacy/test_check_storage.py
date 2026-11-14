import json
import tempfile
import unittest
from pathlib import Path


class CheckStorageTests(unittest.TestCase):
    def test_save_check_result_creates_separate_json_file(self):
        from app.models.company_lookup import CompanyLookupResult
        from app.services.check_storage import save_check_result

        with tempfile.TemporaryDirectory() as temp_dir:
            result = CompanyLookupResult(edrpou="36192559", status="found")

            saved_path = save_check_result(result, telegram_user_id=123456789, base_dir=Path(temp_dir))

            self.assertTrue(saved_path.exists())
            self.assertEqual(saved_path.parent.name, "123456789")
            self.assertEqual(saved_path.suffix, ".json")
            payload = json.loads(saved_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["telegram_user_id"], 123456789)
            self.assertEqual(payload["edrpou"], "36192559")
            self.assertEqual(payload["check_id"], saved_path.stem)

    def test_save_check_result_does_not_overwrite_previous_results(self):
        from app.models.company_lookup import CompanyLookupResult
        from app.services.check_storage import save_check_result

        with tempfile.TemporaryDirectory() as temp_dir:
            first = save_check_result(CompanyLookupResult(edrpou="11111111", status="found"), base_dir=Path(temp_dir))
            second = save_check_result(CompanyLookupResult(edrpou="22222222", status="not_found"), base_dir=Path(temp_dir))

            self.assertNotEqual(first, second)
            self.assertTrue(first.exists())
            self.assertTrue(second.exists())

    def test_save_check_result_uses_different_folders_for_different_users(self):
        from app.models.company_lookup import CompanyLookupResult
        from app.services.check_storage import save_check_result

        with tempfile.TemporaryDirectory() as temp_dir:
            first = save_check_result(
                CompanyLookupResult(edrpou="11111111", status="found"),
                telegram_user_id=1,
                base_dir=Path(temp_dir),
            )
            second = save_check_result(
                CompanyLookupResult(edrpou="22222222", status="found"),
                telegram_user_id=2,
                base_dir=Path(temp_dir),
            )
            anonymous = save_check_result(
                CompanyLookupResult(edrpou="33333333", status="found"),
                base_dir=Path(temp_dir),
            )

            self.assertEqual(first.parent.name, "1")
            self.assertEqual(second.parent.name, "2")
            self.assertEqual(anonymous.parent.name, "anonymous")

    def test_save_check_result_persists_source_diagnostics_without_html(self):
        from app.models.company_lookup import CompanyLookupResult, SourceDiagnostic
        from app.services.check_storage import save_check_result

        with tempfile.TemporaryDirectory() as temp_dir:
            result = CompanyLookupResult(
                edrpou="12345678",
                status="partial",
                source_diagnostics=[
                    SourceDiagnostic(
                        source="opendatabot",
                        status="partial",
                        warnings=["Не знайдено фінансову таблицю"],
                    ),
                    SourceDiagnostic(
                        source="clarity_project",
                        status="source_error",
                        error="analysis_timeout",
                    ),
                ],
            )

            saved_path = save_check_result(result, telegram_user_id=123, base_dir=Path(temp_dir))

            payload = json.loads(saved_path.read_text(encoding="utf-8"))
            self.assertEqual(
                payload["source_diagnostics"],
                [
                    {
                        "source": "opendatabot",
                        "status": "partial",
                        "error": None,
                        "warnings": ["Не знайдено фінансову таблицю"],
                    },
                    {
                        "source": "clarity_project",
                        "status": "source_error",
                        "error": "analysis_timeout",
                        "warnings": [],
                    },
                ],
            )
            self.assertNotIn("<html", saved_path.read_text(encoding="utf-8").lower())

    def test_save_check_result_persists_clarity_snapshot_without_html(self):
        from app.models.clarity import ClarityData, ClaritySignals, ClarityTax
        from app.models.company_lookup import CompanyLookupResult, RiskFlagSnapshot, RiskSummary
        from app.services.check_storage import save_check_result

        with tempfile.TemporaryDirectory() as temp_dir:
            result = CompanyLookupResult(
                edrpou="12345678",
                status="found",
                risk_summary=RiskSummary(
                    level="high",
                    flags=[
                        RiskFlagSnapshot(
                            source="clarity_project",
                            level="high",
                            code="bankruptcy_found",
                            text="Знайдено записи, пов'язані з банкрутством.",
                        )
                    ],
                ),
                clarity_data=ClarityData(
                    source_url="https://clarity-project.info/edr/12345678",
                    status="found",
                    edrpou="12345678",
                    tax=ClarityTax(tax_debt=False, esv_debt=False),
                    signals=ClaritySignals(bankruptcy_count=0, enforcement_proceedings_count=2),
                ),
            )

            saved_path = save_check_result(result, telegram_user_id=123, base_dir=Path(temp_dir))

            payload = json.loads(saved_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["clarity_data"]["status"], "found")
            self.assertFalse(payload["clarity_data"]["tax"]["tax_debt"])
            self.assertEqual(payload["clarity_data"]["signals"]["enforcement_proceedings_count"], 2)
            self.assertEqual(payload["risk_summary"]["level"], "high")
            self.assertEqual(payload["risk_summary"]["flags"][0]["code"], "bankruptcy_found")
            self.assertNotIn("<html", saved_path.read_text(encoding="utf-8").lower())


if __name__ == "__main__":
    unittest.main()
