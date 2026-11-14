from __future__ import annotations

import unittest


SEARCH_HTML = """
<html>
  <body>
    <a href="/auction/BSE001-UA-20260601-12345">Risk auction</a>
    <a href="https://prozorro.sale/auction/BSE001-UA-20260602-99999">Text match only</a>
  </body>
</html>
"""


DETAIL_RISK_HTML = """
<html>
  <body>
    <h1>BSE001-UA-20260601-12345</h1>
    <p>ЄДРПОУ: 12345678</p>
    <p>Переможець не виконав умови аукціону.</p>
  </body>
</html>
"""


DETAIL_TEXT_MATCH_HTML = """
<html>
  <body>
    <h1>BSE001-UA-20260602-99999</h1>
    <p>На сторінці згадано 12345678 у довільному тексті видачі немає.</p>
    <p>Аукціон скасовано.</p>
  </body>
</html>
""".replace("12345678", "87654321")


class ProzorroSaleLookupTests(unittest.TestCase):
    def test_lookup_returns_only_confirmed_risky_detail_pages(self):
        from app.services.prozorro_sale_lookup import lookup_prozorro_sale_by_edrpou

        pages = {
            "https://prozorro.sale/auction/?query=12345678": SEARCH_HTML,
            "https://prozorro.sale/auction/BSE001-UA-20260601-12345": DETAIL_RISK_HTML,
            "https://prozorro.sale/auction/BSE001-UA-20260602-99999": DETAIL_TEXT_MATCH_HTML,
        }
        requested_urls: list[str] = []

        def fake_fetcher(url: str) -> str:
            requested_urls.append(url)
            return pages[url]

        result = lookup_prozorro_sale_by_edrpou("12345678", fetcher=fake_fetcher, max_items=10)

        self.assertEqual(result.status, "found")
        self.assertEqual(result.checked_count, 2)
        self.assertEqual(result.confirmed_count, 1)
        self.assertEqual(len(result.risky_auctions), 1)
        self.assertEqual(result.risky_auctions[0].auction_id, "BSE001-UA-20260601-12345")
        self.assertEqual(result.risky_auctions[0].risk, "переможець не виконав умови")
        self.assertEqual(
            result.risk_flags,
            [
                {
                    "type": "prozorro_sale_risky_auction",
                    "source": "prozorro_sale",
                    "status": "found",
                    "confidence": "medium",
                    "raw_text": "BSE001-UA-20260601-12345 — переможець не виконав умови",
                    "url": "https://prozorro.sale/auction/BSE001-UA-20260601-12345",
                }
            ],
        )
        self.assertEqual(requested_urls[0], "https://prozorro.sale/auction/?query=12345678")

    def test_lookup_uses_auction_id_from_detail_url_before_page_text(self):
        from app.services.prozorro_sale_lookup import lookup_prozorro_sale_by_edrpou

        search_html = """
        <html>
          <body>
            <a href="/auction/UA-PS-2020-09-19-000002-3/">Old auction</a>
          </body>
        </html>
        """
        detail_html = DETAIL_RISK_HTML.replace(
            "BSE001-UA-20260601-12345",
            "SPE001-UA-20260528-69365",
        )
        pages = {
            "https://prozorro.sale/auction/?query=12345678": search_html,
            "https://prozorro.sale/auction/UA-PS-2020-09-19-000002-3/": detail_html,
        }

        result = lookup_prozorro_sale_by_edrpou("12345678", fetcher=lambda url: pages[url], max_items=10)

        self.assertEqual(result.status, "found")
        self.assertEqual(result.risky_auctions[0].auction_id, "UA-PS-2020-09-19-000002-3")
        self.assertTrue(result.risk_flags[0]["raw_text"].startswith("UA-PS-2020-09-19-000002-3"))

    def test_lookup_marks_confirmed_liquidation_mass_auction_as_bankruptcy_signal(self):
        from app.services.prozorro_sale_lookup import lookup_prozorro_sale_by_edrpou

        search_html = """
        <html>
          <body>
            <a href="/auction/BRD001-UA-20250508-60050/">Bankruptcy sale</a>
          </body>
        </html>
        """
        detail_html = """
        <html>
          <body>
            <h1>BRD001-UA-20250508-60050</h1>
            <p>ЄДРПОУ 25102871</p>
            <p>Продаж майна ТОВ «УКРІНВЕСТ», яке увійшло до ліквідаційної маси банкрута.</p>
            <p>Справа про банкрутство №904/4250/24.</p>
          </body>
        </html>
        """
        pages = {
            "https://prozorro.sale/auction/?query=25102871": search_html,
            "https://prozorro.sale/auction/BRD001-UA-20250508-60050/": detail_html,
        }

        result = lookup_prozorro_sale_by_edrpou("25102871", fetcher=lambda url: pages[url], max_items=10)

        self.assertEqual(result.status, "found")
        self.assertEqual(result.confirmed_count, 1)
        self.assertEqual(result.risky_auctions[0].risk, "ознаки банкрутства / ліквідаційна маса")
        self.assertIn("bankruptcy_found", [flag["type"] for flag in result.risk_flags])

    def test_lookup_treats_edrpou_in_bankrupt_debtor_receivables_as_informational_mention(self):
        from app.services.prozorro_sale_lookup import lookup_prozorro_sale_by_edrpou

        search_html = """
        <html>
          <body>
            <a href="/auction/UA-PS-2021-08-20-000052-3/">Bankrupt receivables sale</a>
          </body>
        </html>
        """
        detail_html = """
        <html>
          <body>
            <h1>UA-PS-2021-08-20-000052-3</h1>
            <p>Аукціон не відбувся</p>
            <p>Аукціон з продажу майна банкрута ПрАТ "Креатив"</p>
            <p>Права вимоги (борги) на суму 3 768 026 760.51 грн.</p>
            <p>42) борг АТБ Маркет ООО (ідент. код 30487219) (дог. №123) в розмірі 46 500,00 грн.</p>
            <p>Додатковий класифікатор: З питань законодавства у сфері банкрутства</p>
          </body>
        </html>
        """
        pages = {
            "https://prozorro.sale/auction/?query=30487219": search_html,
            "https://prozorro.sale/auction/UA-PS-2021-08-20-000052-3/": detail_html,
        }

        result = lookup_prozorro_sale_by_edrpou("30487219", fetcher=lambda url: pages[url], max_items=10)

        self.assertEqual(result.status, "found")
        self.assertEqual(result.confirmed_count, 1)
        self.assertEqual(result.risky_auctions, [])
        self.assertEqual(len(result.informational_mentions), 1)
        self.assertEqual(result.informational_mentions[0].auction_id, "UA-PS-2021-08-20-000052-3")
        self.assertEqual(result.informational_mentions[0].role, "debtor_mention")
        self.assertEqual(
            [flag["type"] for flag in result.risk_flags],
            ["prozorro_sale_debtor_mention"],
        )
        self.assertNotIn("bankruptcy_found", [flag["type"] for flag in result.risk_flags])
        self.assertNotIn("prozorro_sale_bankruptcy_asset_sale", [flag["type"] for flag in result.risk_flags])

    def test_lookup_treats_unsuccessful_auction_without_company_fault_as_information(self):
        from app.services.prozorro_sale_lookup import lookup_prozorro_sale_by_edrpou

        search_html = """
        <html>
          <body>
            <a href="/auction/SPE001-UA-20260401-11111/">Unsuccessful auction 1</a>
            <a href="/auction/SPE001-UA-20260402-22222/">Unsuccessful auction 2</a>
          </body>
        </html>
        """
        detail_one = """
        <html>
          <body>
            <h1>SPE001-UA-20260401-11111</h1>
            <p>Учасник: ТОВ "Приклад", код ЄДРПОУ 32265298</p>
            <p>Аукціон не відбувся.</p>
          </body>
        </html>
        """
        detail_two = """
        <html>
          <body>
            <h1>SPE001-UA-20260402-22222</h1>
            <p>Учасник: ТОВ "Приклад", код ЄДРПОУ 32265298</p>
            <p>Торги не відбулися.</p>
          </body>
        </html>
        """
        pages = {
            "https://prozorro.sale/auction/?query=32265298": search_html,
            "https://prozorro.sale/auction/SPE001-UA-20260401-11111/": detail_one,
            "https://prozorro.sale/auction/SPE001-UA-20260402-22222/": detail_two,
        }

        result = lookup_prozorro_sale_by_edrpou("32265298", fetcher=lambda url: pages[url], max_items=10)

        self.assertEqual(result.status, "found")
        self.assertEqual(result.confirmed_count, 2)
        self.assertEqual(result.risky_auctions, [])
        self.assertEqual(len(result.informational_mentions), 2)
        self.assertEqual({mention.role for mention in result.informational_mentions}, {"auction_participant"})
        self.assertEqual(result.risk_flags, [])

    def test_lookup_does_not_score_disqualification_marker_without_company_specific_confirmation(self):
        from app.services.prozorro_sale_lookup import lookup_prozorro_sale_by_edrpou

        search_html = """
        <html>
          <body>
            <a href="/auction/UA-PS-2021-02-03-000015-1/">Auction with unrelated disqualification marker</a>
          </body>
        </html>
        """
        detail_html = """
        <html>
          <body>
            <h1>UA-PS-2021-02-03-000015-1</h1>
            <section>
              <h2>Переможець</h2>
              <p>ТОВ "АТБ-МАРКЕТ", код ЄДРПОУ 30487219</p>
              <p>Аукціон завершено. Договір підписано.</p>
            </section>
            <section>
              <h2>Документи та довідкова інформація</h2>
              <p>Порядок дискваліфікації учасників описано в регламенті аукціону.</p>
              <p>Цей текст не стосується підписаного договору переможця.</p>
            </section>
          </body>
        </html>
        """
        pages = {
            "https://prozorro.sale/auction/?query=30487219": search_html,
            "https://prozorro.sale/auction/UA-PS-2021-02-03-000015-1/": detail_html,
        }

        result = lookup_prozorro_sale_by_edrpou("30487219", fetcher=lambda url: pages[url], max_items=10)

        self.assertEqual(result.status, "found")
        self.assertEqual(result.confirmed_count, 1)
        self.assertEqual(result.risky_auctions, [])
        self.assertEqual(len(result.informational_mentions), 1)
        self.assertEqual(result.informational_mentions[0].role, "winner")
        self.assertEqual(result.risk_flags, [])

    def test_lookup_scores_disqualification_only_when_same_company_is_disqualified(self):
        from app.services.prozorro_sale_lookup import lookup_prozorro_sale_by_edrpou

        search_html = """
        <html>
          <body>
            <a href="/auction/UA-PS-2021-02-03-000015-1/">Auction with confirmed disqualification</a>
          </body>
        </html>
        """
        detail_html = """
        <html>
          <body>
            <h1>UA-PS-2021-02-03-000015-1</h1>
            <section>
              <h2>Переможець</h2>
              <p>ТОВ "АТБ-МАРКЕТ", код ЄДРПОУ 30487219</p>
              <p>Статус учасника: дискваліфіковано.</p>
            </section>
          </body>
        </html>
        """
        pages = {
            "https://prozorro.sale/auction/?query=30487219": search_html,
            "https://prozorro.sale/auction/UA-PS-2021-02-03-000015-1/": detail_html,
        }

        result = lookup_prozorro_sale_by_edrpou("30487219", fetcher=lambda url: pages[url], max_items=10)

        self.assertEqual(result.status, "found")
        self.assertEqual(result.confirmed_count, 1)
        self.assertEqual(result.informational_mentions, [])
        self.assertEqual(len(result.risky_auctions), 1)
        self.assertEqual(result.risky_auctions[0].role, "disqualified_winner")
        self.assertEqual(result.risky_auctions[0].risk, "дискваліфікація переможця")

    def test_lookup_returns_not_found_when_no_confirmed_risks(self):
        from app.services.prozorro_sale_lookup import lookup_prozorro_sale_by_edrpou

        pages = {
            "https://prozorro.sale/auction/?query=12345678": SEARCH_HTML,
            "https://prozorro.sale/auction/BSE001-UA-20260601-12345": "<p>ЄДРПОУ 12345678</p><p>Звичайний аукціон.</p>",
            "https://prozorro.sale/auction/BSE001-UA-20260602-99999": DETAIL_TEXT_MATCH_HTML,
        }

        result = lookup_prozorro_sale_by_edrpou("12345678", fetcher=lambda url: pages[url], max_items=10)

        self.assertEqual(result.status, "not_found")
        self.assertEqual(result.confirmed_count, 1)
        self.assertEqual(result.risky_auctions, [])
        self.assertEqual(result.risk_flags, [])

    def test_lookup_converts_source_error_without_risk_flags(self):
        from app.services.prozorro_sale_lookup import lookup_prozorro_sale_by_edrpou

        def failing_fetcher(url: str) -> str:
            raise TimeoutError("sale timeout")

        result = lookup_prozorro_sale_by_edrpou("12345678", fetcher=failing_fetcher)

        self.assertEqual(result.status, "source_error")
        self.assertEqual(result.error, "sale timeout")
        self.assertEqual(result.risk_flags, [])


if __name__ == "__main__":
    unittest.main()
