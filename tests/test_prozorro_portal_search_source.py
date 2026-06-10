import unittest


class ProzorroPortalSearchSourceTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_portal_search_summary_uses_fifty_items_by_default(self):
        from app.services.prozorro_portal_search_source import fetch_prozorro_search_summary_by_edrpou

        async def fetch_json(url: str):
            self.assertIn("per_page=50", url)
            return {"page": 1, "per_page": 50, "total": 0, "data": []}

        summary = await fetch_prozorro_search_summary_by_edrpou("12345678", fetch_json=fetch_json)

        self.assertIsNone(summary)

    async def test_fetch_portal_search_summary_reads_total_and_first_items(self):
        from app.services.prozorro_portal_search_source import fetch_prozorro_search_summary_by_edrpou

        async def fetch_json(url: str):
            self.assertIn("text=12345678", url)
            return {
                "page": 1,
                "per_page": 20,
                "total": 370,
                "data": [
                    {
                        "tenderID": f"UA-2026-01-{index:02d}-000001-a",
                        "title": f"Test tender {index}",
                        "status": "complete",
                        "value": {"amount": 1000 + index, "currency": "UAH"},
                        "procuringEntity": {
                            "identifier": {
                                "id": "00000000",
                                "legalName": "Test buyer",
                            }
                        },
                    }
                    for index in range(1, 13)
                ],
            }

        summary = await fetch_prozorro_search_summary_by_edrpou(
            "12345678",
            max_items=10,
            fetch_json=fetch_json,
        )

        self.assertEqual(summary.total_count, 370)
        self.assertEqual(summary.checked_count, 10)
        self.assertEqual(len(summary.items), 10)
        self.assertEqual(summary.items[0]["tenderID"], "UA-2026-01-01-000001-a")
        self.assertEqual(summary.items[0]["title"], "Test tender 1")
        self.assertEqual(summary.items[0]["buyer_name"], "Test buyer")
        self.assertEqual(summary.items[0]["buyer_edrpou"], "00000000")
        self.assertEqual(summary.items[0]["expected_value_uah"], 1001.0)
        self.assertIn("text=12345678", summary.source_url)

    async def test_fetch_portal_search_summary_returns_none_when_empty(self):
        from app.services.prozorro_portal_search_source import fetch_prozorro_search_summary_by_edrpou

        summary = await fetch_prozorro_search_summary_by_edrpou(
            "12345678",
            fetch_json=lambda url: {"page": 1, "per_page": 20, "total": 0, "data": []},
        )

        self.assertIsNone(summary)

    async def test_fetch_portal_search_summary_confirms_company_roles_from_detail(self):
        from app.services.prozorro_portal_search_source import fetch_prozorro_search_summary_by_edrpou

        async def fetch_json(url: str):
            if "/api/search/tenders" in url:
                return {
                    "page": 1,
                    "per_page": 20,
                    "total": 1,
                    "data": [
                        {
                            "tenderID": "UA-2026-01-01-000001-a",
                            "title": "Test tender",
                            "status": "complete",
                            "value": {"amount": 1000, "currency": "UAH"},
                            "procuringEntity": {"identifier": {"id": "00000000", "legalName": "Test buyer"}},
                        }
                    ],
                }
            if "/api/tenders/UA-2026-01-01-000001-a/summary" in url:
                return {"id": "ocds-test-1", "tenderID": "UA-2026-01-01-000001-a"}
            if "/api/2.5/tenders/ocds-test-1" in url:
                return {
                    "data": {
                        "id": "ocds-test-1",
                        "tenderID": "UA-2026-01-01-000001-a",
                        "procuringEntity": {"identifier": {"id": "00000000"}},
                        "bids": [{"tenderers": [{"identifier": {"id": "12345678"}}]}],
                        "awards": [{"status": "active", "suppliers": [{"identifier": {"id": "12345678"}}]}],
                        "contracts": [{"status": "active", "suppliers": [{"identifier": {"id": "12345678"}}]}],
                    }
                }
            raise AssertionError(f"Unexpected URL: {url}")

        summary = await fetch_prozorro_search_summary_by_edrpou(
            "12345678",
            max_items=10,
            fetch_json=fetch_json,
        )

        self.assertEqual(summary.detail_checked_count, 1)
        self.assertEqual(summary.confirmed_participation_count, 1)
        self.assertEqual(summary.participant_count, 1)
        self.assertEqual(summary.winner_count, 1)
        self.assertEqual(summary.supplier_contract_count, 1)
        self.assertEqual(summary.buyer_count, 0)
        self.assertTrue(summary.items[0]["participation_confirmed"])
        self.assertEqual(summary.items[0]["confirmed_roles"], ["contract_supplier", "participant", "winner"])
        self.assertEqual(len(summary.matched_procurements), 1)
        self.assertEqual(summary.matched_procurements[0].procurement_id, "UA-2026-01-01-000001-a")
        self.assertTrue(summary.matched_procurements[0].participated)
        self.assertTrue(summary.matched_procurements[0].won)
        self.assertTrue(summary.matched_procurements[0].has_contract)

    async def test_fetch_portal_search_summary_counts_company_roles_separately(self):
        from app.services.prozorro_portal_search_source import fetch_prozorro_search_summary_by_edrpou

        role_details = {
            "UA-BUYER": {
                "procuringEntity": {"identifier": {"id": "12345678"}},
            },
            "UA-PARTICIPANT": {
                "procuringEntity": {"identifier": {"id": "00000000"}},
                "bids": [{"tenderers": [{"identifier": {"id": "12345678"}}]}],
            },
            "UA-SUPPLIER": {
                "procuringEntity": {"identifier": {"id": "00000000"}},
                "awards": [{"status": "active", "suppliers": [{"identifier": {"id": "12345678"}}]}],
                "contracts": [{"status": "active", "suppliers": [{"identifier": {"id": "12345678"}}]}],
            },
        }

        async def fetch_json(url: str):
            if "/api/search/tenders" in url:
                return {
                    "page": 1,
                    "per_page": 3,
                    "total": 3,
                    "data": [
                        {
                            "tenderID": tender_id,
                            "title": tender_id,
                            "status": "complete",
                            "procuringEntity": {"identifier": {"id": "00000000", "legalName": "Test buyer"}},
                        }
                        for tender_id in role_details
                    ],
                }
            if "/api/tenders/" in url and url.endswith("/summary"):
                tender_id = url.split("/api/tenders/", 1)[1].split("/summary", 1)[0]
                return {"id": f"ocds-{tender_id}", "tenderID": tender_id}
            if "/api/2.5/tenders/ocds-" in url:
                tender_id = url.split("/api/2.5/tenders/ocds-", 1)[1]
                detail = {"id": f"ocds-{tender_id}", "tenderID": tender_id, **role_details[tender_id]}
                return {"data": detail}
            raise AssertionError(f"Unexpected URL: {url}")

        summary = await fetch_prozorro_search_summary_by_edrpou(
            "12345678",
            max_items=3,
            fetch_json=fetch_json,
        )

        self.assertEqual(summary.confirmed_participation_count, 3)
        self.assertEqual(summary.buyer_count, 1)
        self.assertEqual(summary.participant_count, 1)
        self.assertEqual(summary.winner_count, 1)
        self.assertEqual(summary.supplier_contract_count, 1)
        self.assertEqual(summary.items[0]["confirmed_roles"], ["buyer"])
        self.assertEqual(summary.items[1]["confirmed_roles"], ["participant"])
        self.assertEqual(summary.items[2]["confirmed_roles"], ["contract_supplier", "winner"])

    async def test_fetch_portal_search_summary_checks_more_than_ten_detail_items(self):
        from app.services.prozorro_portal_search_source import fetch_prozorro_search_summary_by_edrpou

        async def fetch_json(url: str):
            if "/api/search/tenders" in url:
                self.assertIn("per_page=12", url)
                return {
                    "page": 1,
                    "per_page": 12,
                    "total": 12,
                    "data": [
                        {
                            "tenderID": f"UA-2026-02-{index:02d}-000001-a",
                            "title": f"Test tender {index}",
                            "status": "complete",
                            "value": {"amount": 1000 + index, "currency": "UAH"},
                            "procuringEntity": {"identifier": {"id": "00000000", "legalName": "Test buyer"}},
                        }
                        for index in range(1, 13)
                    ],
                }
            if "/api/tenders/" in url and url.endswith("/summary"):
                tender_id = url.split("/api/tenders/", 1)[1].split("/summary", 1)[0]
                index = int(tender_id.split("-")[3])
                return {"id": f"ocds-test-{index}", "tenderID": tender_id}
            if "/api/2.5/tenders/ocds-test-" in url:
                index = int(url.rsplit("-", 1)[1])
                supplier_id = "12345678" if index == 12 else "87654321"
                return {
                    "data": {
                        "id": f"ocds-test-{index}",
                        "tenderID": f"UA-2026-02-{index:02d}-000001-a",
                        "procuringEntity": {"identifier": {"id": "00000000"}},
                        "bids": [{"tenderers": [{"identifier": {"id": supplier_id}}]}],
                    }
                }
            raise AssertionError(f"Unexpected URL: {url}")

        summary = await fetch_prozorro_search_summary_by_edrpou(
            "12345678",
            max_items=12,
            fetch_json=fetch_json,
        )

        self.assertEqual(summary.checked_count, 12)
        self.assertEqual(summary.detail_checked_count, 12)
        self.assertEqual(summary.confirmed_participation_count, 1)
        self.assertEqual(summary.items[11]["confirmed_roles"], ["participant"])
        self.assertEqual(len(summary.matched_procurements), 1)

    async def test_fetch_portal_search_summary_paginates_until_requested_limit(self):
        from app.services.prozorro_portal_search_source import fetch_prozorro_search_summary_by_edrpou

        search_pages: list[int] = []

        async def fetch_json(url: str):
            if "/api/search/tenders" in url:
                page = int(url.split("page=", 1)[1].split("&", 1)[0])
                search_pages.append(page)
                start_index = (page - 1) * 20 + 1
                return {
                    "page": page,
                    "per_page": 20,
                    "total": 1406,
                    "data": [
                        {
                            "tenderID": f"UA-2026-04-{index:02d}-000001-a",
                            "title": f"Test tender {index}",
                            "status": "complete",
                            "procuringEntity": {"identifier": {"id": "00000000", "legalName": "Test buyer"}},
                        }
                        for index in range(start_index, start_index + 20)
                    ],
                }
            if "/api/tenders/" in url and url.endswith("/summary"):
                tender_id = url.split("/api/tenders/", 1)[1].split("/summary", 1)[0]
                return {"id": f"ocds-{tender_id}", "tenderID": tender_id}
            if "/api/2.5/tenders/ocds-UA-2026-04-" in url:
                tender_id = url.split("/api/2.5/tenders/ocds-", 1)[1]
                return {"data": {"id": f"ocds-{tender_id}", "tenderID": tender_id}}
            raise AssertionError(f"Unexpected URL: {url}")

        summary = await fetch_prozorro_search_summary_by_edrpou(
            "12345678",
            max_items=50,
            fetch_json=fetch_json,
        )

        self.assertEqual(search_pages, [1, 2, 3])
        self.assertEqual(summary.total_count, 1406)
        self.assertEqual(summary.checked_count, 50)
        self.assertEqual(len(summary.items), 50)
        self.assertEqual(summary.items[-1]["tenderID"], "UA-2026-04-50-000001-a")

    async def test_fetch_portal_search_summary_collects_marker_codes_from_detail_text(self):
        from app.services.prozorro_portal_search_source import fetch_prozorro_search_summary_by_edrpou

        async def fetch_json(url: str):
            if "/api/search/tenders" in url:
                return {
                    "page": 1,
                    "per_page": 1,
                    "total": 1,
                    "data": [
                        {
                            "tenderID": "UA-2026-03-01-000001-a",
                            "title": "Test tender",
                            "status": "complete",
                            "procuringEntity": {"identifier": {"id": "00000000", "legalName": "Test buyer"}},
                        }
                    ],
                }
            if "/api/tenders/UA-2026-03-01-000001-a/summary" in url:
                return {"id": "ocds-marker-1", "tenderID": "UA-2026-03-01-000001-a"}
            if "/api/2.5/tenders/ocds-marker-1" in url:
                return {
                    "data": {
                        "id": "ocds-marker-1",
                        "tenderID": "UA-2026-03-01-000001-a",
                        "procuringEntity": {"identifier": {"id": "00000000"}},
                        "description": "У закупівлі є скарги до АМКУ та моніторинг.",
                    }
                }
            raise AssertionError(f"Unexpected URL: {url}")

        summary = await fetch_prozorro_search_summary_by_edrpou(
            "12345678",
            max_items=1,
            fetch_json=fetch_json,
        )

        self.assertEqual(summary.items[0]["risk_marker_codes"], ["complaint", "monitoring"])
