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

    def test_lookup_uses_live_source_after_cache_miss(self):
        from app.models.company_lookup import ProzorroProcurement
        from app.services.prozorro_lookup import lookup_prepared_prozorro

        result = lookup_prepared_prozorro(
            "12345678",
            source=lambda edrpou: None,
            live_source=lambda edrpou: [
                ProzorroProcurement(
                    procurement_id="UA-LIVE-1",
                    participated=True,
                    won=True,
                    has_contract=True,
                    date="2026-01-01",
                )
            ],
        )

        self.assertEqual(result.status, "found")
        self.assertEqual(result.stats.procurements_count, 1)
        self.assertEqual(result.stats.participations_count, 1)
        self.assertEqual(result.stats.wins_count, 1)
        self.assertEqual(result.stats.contracts_count, 1)

    def test_lookup_returns_not_found_when_live_source_has_no_records(self):
        from app.services.prozorro_lookup import lookup_prepared_prozorro

        result = lookup_prepared_prozorro(
            "12345678",
            source=lambda edrpou: None,
            live_source=lambda edrpou: [],
        )

        self.assertEqual(result.status, "not_found")
        self.assertEqual(result.stats.procurements_count, 0)
        self.assertEqual(result.risk_flags, [])

    def test_lookup_converts_live_source_exception_to_source_error(self):
        from app.services.prozorro_lookup import lookup_prepared_prozorro

        def failing_live_source(edrpou: str):
            raise TimeoutError("prozorro timeout")

        result = lookup_prepared_prozorro(
            "12345678",
            source=lambda edrpou: None,
            live_source=failing_live_source,
        )

        self.assertEqual(result.status, "source_error")
        self.assertIn("prozorro timeout", result.error or "")
        self.assertEqual(result.risk_flags, [])

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

    def test_items_list_cache_does_not_apply_records_to_other_edrpou(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from app.services.prozorro_lookup import load_prozorro_cache_file, lookup_prepared_prozorro

        with TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "prozorro-cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "UA-OTHER-1",
                                "supplier_edrpou": "12345678",
                                "participated": True,
                                "won": True,
                                "has_contract": True,
                                "contract_terminated": True,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            self.assertIsNone(load_prozorro_cache_file("87654321", cache_path))
            analysis = lookup_prepared_prozorro(
                "87654321",
                source=lambda edrpou: load_prozorro_cache_file(edrpou, cache_path),
            )

        self.assertEqual(analysis.status, "not_found")
        self.assertEqual(analysis.risk_flags, [])

    def test_items_list_cache_filters_records_by_item_edrpou(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from app.services.prozorro_lookup import load_prozorro_cache_file

        with TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "prozorro-cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {"id": "UA-MATCH-1", "supplier_edrpou": "12345678", "participated": True},
                            {"id": "UA-OTHER-1", "supplier_edrpou": "87654321", "participated": True},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            records = load_prozorro_cache_file("12345678", cache_path)

        self.assertEqual([record["id"] for record in records], ["UA-MATCH-1"])
