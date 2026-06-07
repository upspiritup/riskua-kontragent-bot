from __future__ import annotations

import json
import unittest
from unittest.mock import patch


class ProzorroLookupTests(unittest.TestCase):
    def test_default_lookup_returns_not_found_without_cache(self):
        from app.services.prozorro_lookup import lookup_prepared_prozorro

        with patch.dict("os.environ", {"PROZORRO_CACHE_PATH": ""}, clear=False):
            result = lookup_prepared_prozorro("12345678")

        self.assertEqual(result.status, "not_found")
        self.assertEqual(result.stats.procurements_count, 0)
        self.assertEqual(result.risk_flags, [])

    def test_lookup_analyzes_prepared_records_from_injected_source(self):
        from app.services.prozorro_lookup import lookup_prepared_prozorro

        result = lookup_prepared_prozorro(
            "12345678",
            source=lambda edrpou: [
                {
                    "id": "UA-TEST-1",
                    "participated": True,
                    "won": True,
                    "has_contract": True,
                    "contract_terminated": True,
                    "termination_reason": "Contract terminated by agreement.",
                }
            ],
        )

        self.assertEqual(result.status, "found")
        self.assertEqual(result.stats.procurements_count, 1)
        self.assertEqual(result.stats.terminated_contracts_count, 1)
        self.assertEqual([flag["type"] for flag in result.risk_flags], ["prozorro_termination_found"])

    def test_lookup_converts_source_exception_to_source_error(self):
        from app.services.prozorro_lookup import lookup_prepared_prozorro

        def failing_source(edrpou: str):
            raise OSError("cache unavailable")

        result = lookup_prepared_prozorro("12345678", source=failing_source)

        self.assertEqual(result.status, "source_error")
        self.assertIn("cache unavailable", result.error or "")
        self.assertEqual(result.risk_flags, [])

    def test_cache_file_source_returns_records_by_edrpou(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from app.services.prozorro_lookup import load_prozorro_cache_file

        with TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "prozorro-cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "12345678": [
                            {
                                "id": "UA-CACHE-1",
                                "participated": True,
                                "won": True,
                                "has_contract": True,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(load_prozorro_cache_file("12345678", cache_path)[0]["id"], "UA-CACHE-1")
            self.assertIsNone(load_prozorro_cache_file("87654321", cache_path))
