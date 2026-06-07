import unittest


class ProzorroApiSourceTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_recent_procurements_normalizes_matching_tender(self):
        from app.services.prozorro_api_source import fetch_recent_prozorro_procurements_by_edrpou

        async def fetch_json(url: str):
            if "/tenders/ocds-test-1" in url:
                return {
                    "data": {
                        "id": "ocds-test-1",
                        "tenderID": "UA-2026-01-01-000001-a",
                        "title": "Поставка товарів",
                        "procurementMethodType": "belowThreshold",
                        "status": "active.tendering",
                        "dateModified": "2026-01-02T10:00:00+02:00",
                        "value": {"amount": 100000, "currency": "UAH"},
                        "procuringEntity": {
                            "name": "Державний замовник",
                            "identifier": {"id": "00000000"},
                        },
                        "items": [
                            {
                                "classification": {
                                    "id": "30190000-7",
                                    "description": "Офісне устаткування",
                                }
                            }
                        ],
                        "bids": [
                            {
                                "value": {"amount": 70000, "currency": "UAH"},
                                "tenderers": [
                                    {"name": "ТОВ Тест", "identifier": {"id": "12345678"}},
                                ],
                            }
                        ],
                        "awards": [
                            {
                                "status": "active",
                                "date": "2026-01-03T10:00:00+02:00",
                                "suppliers": [
                                    {"name": "ТОВ Тест", "identifier": {"id": "12345678"}},
                                ],
                            }
                        ],
                        "contracts": [
                            {
                                "status": "terminated",
                                "dateSigned": "2026-01-04T10:00:00+02:00",
                                "terminationDetails": "Договір розірвано за згодою сторін",
                                "value": {"amount": 80000, "currency": "UAH"},
                                "suppliers": [
                                    {"name": "ТОВ Тест", "identifier": {"id": "12345678"}},
                                ],
                                "changes": [{"id": "change-1"}],
                            }
                        ],
                        "complaints": [{"id": "complaint-1"}],
                    }
                }
            return {
                "data": [{"id": "ocds-test-1"}],
                "next_page": {"offset": "next-offset"},
            }

        records = await fetch_recent_prozorro_procurements_by_edrpou(
            "12345678",
            max_pages=1,
            limit=100,
            fetch_json=fetch_json,
        )

        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.procurement_id, "UA-2026-01-01-000001-a")
        self.assertEqual(record.title, "Поставка товарів")
        self.assertEqual(record.cpv_code, "30190000-7")
        self.assertEqual(record.expected_value_uah, 100000)
        self.assertEqual(record.bid_value_uah, 70000)
        self.assertEqual(record.contract_value_uah, 80000)
        self.assertEqual(record.buyer_name, "Державний замовник")
        self.assertEqual(record.buyer_edrpou, "00000000")
        self.assertEqual(record.participants_count, 1)
        self.assertTrue(record.participated)
        self.assertTrue(record.won)
        self.assertTrue(record.has_contract)
        self.assertTrue(record.contract_terminated)
        self.assertEqual(record.termination_reason, "Договір розірвано за згодою сторін")
        self.assertEqual(record.complaints_count, 1)
        self.assertEqual(record.amendments_count, 1)
        self.assertEqual(record.award_date, "2026-01-03")
        self.assertEqual(record.contract_date, "2026-01-04")

    async def test_fetch_recent_procurements_marks_unsuccessful_award_as_disqualified(self):
        from app.services.prozorro_api_source import fetch_recent_prozorro_procurements_by_edrpou

        async def fetch_json(url: str):
            if "/tenders/ocds-test-2" in url:
                return {
                    "data": {
                        "id": "ocds-test-2",
                        "tenderID": "UA-2026-01-02-000002-a",
                        "bids": [
                            {
                                "tenderers": [
                                    {"identifier": {"id": "12345678"}},
                                ],
                            }
                        ],
                        "awards": [
                            {
                                "status": "unsuccessful",
                                "description": "Не відповідає кваліфікаційним критеріям",
                                "suppliers": [
                                    {"identifier": {"id": "12345678"}},
                                ],
                            }
                        ],
                    }
                }
            return {"data": [{"id": "ocds-test-2"}], "next_page": {}}

        records = await fetch_recent_prozorro_procurements_by_edrpou(
            "12345678",
            max_pages=1,
            fetch_json=fetch_json,
        )

        self.assertEqual(len(records), 1)
        self.assertTrue(records[0].participated)
        self.assertTrue(records[0].disqualified)
        self.assertEqual(records[0].disqualification_reason, "Не відповідає кваліфікаційним критеріям")
