import asyncio
import unittest


class ProzorroApiTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_recent_procurements_stops_when_search_timeout_expires(self):
        from app.services.prozorro_api_source import fetch_recent_prozorro_procurements_by_edrpou

        async def fetch_json(url: str):
            if "/tenders/ocds-slow-1" in url:
                await asyncio.sleep(0.05)
                return {"data": {"id": "ocds-slow-1"}}
            return {"data": [{"id": "ocds-slow-1"}, {"id": "ocds-slow-2"}], "next_page": {"offset": "next"}}

        records = await fetch_recent_prozorro_procurements_by_edrpou(
            "12345678",
            max_pages=10,
            fetch_json=fetch_json,
            timeout_seconds=0.01,
        )

        self.assertEqual(records, [])

    async def test_fetch_recent_procurements_skips_failed_detail_and_continues(self):
        from app.services.prozorro_api_source import fetch_recent_prozorro_procurements_by_edrpou

        async def fetch_json(url: str):
            if "/tenders/ocds-failing-detail" in url:
                raise OSError("detail timeout")
            if "/tenders/ocds-matching-detail" in url:
                return {
                    "data": {
                        "id": "ocds-matching-detail",
                        "tenderID": "UA-MATCH-1",
                        "bids": [{"tenderers": [{"identifier": {"id": "12345678"}}]}],
                    }
                }
            return {
                "data": [{"id": "ocds-failing-detail"}, {"id": "ocds-matching-detail"}],
                "next_page": {},
            }

        records = await fetch_recent_prozorro_procurements_by_edrpou(
            "12345678",
            max_pages=1,
            fetch_json=fetch_json,
            timeout_seconds=1,
        )

        self.assertEqual([record.procurement_id for record in records], ["UA-MATCH-1"])
