import json
import unittest
from threading import Event


class FakeMessage:
    def __init__(self, text: str, user_id: int | None = None):
        self.text = text
        self.answers: list[str] = []
        self.answer_kwargs: list[dict[str, object]] = []
        self.from_user = type("FakeUser", (), {"id": user_id})() if user_id is not None else None

    async def answer(self, text: str, **kwargs: object) -> None:
        self.answers.append(text)
        self.answer_kwargs.append(kwargs)


def no_youcontrol_lookup(edrpou: str) -> None:
    return None


def no_debtors_lookup(edrpou: str) -> None:
    return None


def no_tax_lookup(edrpou: str) -> None:
    return None


def no_domain_reputation_lookup(domain_or_url: str | None, company_context: dict | None = None) -> dict:
    return {
        "source": "domain_reputation",
        "checked": False,
        "found": False,
        "url": None,
        "domain": None,
        "signals": [],
        "risk_flags": [],
        "error": "website_not_provided",
    }


def no_contacts_lookup(edrpou: str, company_context: dict | None = None) -> dict:
    return {
        "website": {"value": None, "confidence": "unknown", "sources": [], "evidence": []},
        "phone": {"value": None, "confidence": "unknown", "sources": [], "evidence": []},
        "email": {"value": None, "confidence": "unknown", "sources": [], "evidence": []},
        "checked_sources": [],
        "missing_sources": [],
        "warnings": [],
        "source_statuses": {},
        "source_results": [],
    }


class BotResponseTests(unittest.TestCase):
    def test_start_handler_sends_intro_and_pricing_text(self):
        import asyncio

        from app.bot import start_handler

        message = FakeMessage("/start")

        asyncio.run(start_handler(message))

        self.assertIn("RiskUA — швидка перевірка контрагента 🔎", message.answers[0])
        self.assertNotIn("Приклад: 12345678", message.answers[0])
        self.assertIn("У демо ви отримаєте:", message.answers[0])
        self.assertIn("💳 Повна перевірка", message.answers[0])
        self.assertIn("✅ рекомендацію: чи варто співпрацювати", message.answers[0])
        self.assertIn("🎁 Демо-перевірка — безкоштовно", message.answers[0])
        self.assertIn("🔎 1 повна перевірка — 29 грн", message.answers[0])
        self.assertIn("📦 10 повних перевірок — 199 грн", message.answers[0])
        self.assertIn("Надішліть ЄДРПОУ, щоб почати 👇", message.answers[0])
        self.assertNotIn("Перевіряйте контрагентів перед оплатою", message.answers[0])
        self.assertNotIn("Просто надішліть код ЄДРПОУ", message.answers[0])

    def test_main_keyboard_includes_admin_contact_button(self):
        from app.bot import CONTACT_ADMIN_BUTTON_TEXT, build_main_keyboard

        keyboard = build_main_keyboard()
        button_texts = [button.text for row in keyboard.keyboard for button in row]

        self.assertEqual(CONTACT_ADMIN_BUTTON_TEXT, "📩 Написати адміністратору")
        self.assertIn(CONTACT_ADMIN_BUTTON_TEXT, button_texts)

    def test_main_keyboard_includes_payment_button(self):
        from app.bot import PAYMENT_BUTTON_TEXT, build_main_keyboard

        keyboard = build_main_keyboard()
        button_texts = [button.text for row in keyboard.keyboard for button in row]

        self.assertIn(PAYMENT_BUTTON_TEXT, button_texts)

    def test_contact_admin_handler_sends_telegram_account(self):
        import asyncio

        from app.bot import ADMIN_TELEGRAM_URL, CONTACT_ADMIN_TEXT, contact_admin_handler

        message = FakeMessage("📩 Написати адміністратору")

        asyncio.run(contact_admin_handler(message))

        self.assertEqual(message.answers, [CONTACT_ADMIN_TEXT])
        self.assertIn("reng_363", CONTACT_ADMIN_TEXT)
        self.assertIn(ADMIN_TELEGRAM_URL, CONTACT_ADMIN_TEXT)

    def test_payment_handler_sends_stub_package_choices(self):
        import asyncio

        from app.bot import PAYMENT_STUB_TEXT, payment_handler

        message = FakeMessage("Оплатити")

        asyncio.run(payment_handler(message))

        self.assertEqual(message.answers, [PAYMENT_STUB_TEXT])
        self.assertEqual(
            PAYMENT_STUB_TEXT,
            "💳 Оберіть пакет перевірок\n\n"
            "🔎 1 повна перевірка — 29 грн\n"
            "📦 10 повних перевірок — 199 грн\n\n"
            "✅ Що входить у повну перевірку:\n\n"
            "🏢 Реєстраційні дані компанії\n"
            "👤 Керівник, адреса, статус та КВЕД\n"
            "💰 Фінансові показники\n"
            "☎️ Контактна інформація\n"
            "📈 Динаміка статутного капіталу\n"
            "🏛 Перевірка Prozorro\n"
            "⚖️ Судові та ризикові сигнали\n"
            "🚨 Ознаки банкрутства, припинення або боргів\n"
            "🧩 Причини оцінки ризику\n"
            "🤖 AI-висновок щодо співпраці\n"
            "📊 Загальний ризик від 0 до 100\n\n"
            "Оберіть пакет нижче 👇",
        )

    def test_highest_risk_level_uses_strongest_known_level(self):
        from app.bot import highest_risk_level

        self.assertEqual(highest_risk_level([]), "low")
        self.assertEqual(highest_risk_level(["info", "medium"]), "medium")
        self.assertEqual(highest_risk_level(["medium", "high", "info"]), "high")

    def test_build_risk_summary_includes_prozorro_analysis_flags(self):
        from app.bot import build_risk_summary
        from app.models.company_lookup import CompanyLookupResult, ProzorroAnalysis, ProzorroStats

        result = CompanyLookupResult(
            status="found",
            edrpou="12345678",
            prozorro_analysis=ProzorroAnalysis(
                status="found",
                stats=ProzorroStats(procurements_count=1),
                risk_flags=[
                    {
                        "type": "prozorro_termination_found",
                        "source": "prozorro_analysis",
                        "status": "found",
                        "confidence": "medium",
                        "raw_text": "Виявлено розірвання договору в Prozorro.",
                    }
                ],
            ),
        )

        summary = build_risk_summary(result, None)

        self.assertEqual(summary.score, 25)
        self.assertEqual(summary.reasons[0]["type"], "prozorro_termination_found")
        self.assertEqual(summary.reasons[0]["sources"], ["prozorro_analysis"])

    def test_build_risk_summary_ignores_source_error_prozorro_flags(self):
        from app.bot import build_risk_summary
        from app.models.company_lookup import CompanyLookupResult, ProzorroAnalysis

        result = CompanyLookupResult(
            status="found",
            edrpou="12345678",
            prozorro_analysis=ProzorroAnalysis(
                status="source_error",
                risk_flags=[
                    {
                        "type": "multiple_prozorro_terminations_found",
                        "source": "prozorro_analysis",
                    }
                ],
            ),
        )

        summary = build_risk_summary(result, None)

        self.assertEqual(summary.score, 5)
        self.assertNotIn("multiple_prozorro_terminations_found", [reason["type"] for reason in summary.reasons])

    def test_build_risk_summary_ignores_not_found_prozorro_flags(self):
        from app.bot import build_risk_summary
        from app.models.company_lookup import CompanyLookupResult, ProzorroAnalysis

        result = CompanyLookupResult(
            status="found",
            edrpou="12345678",
            prozorro_analysis=ProzorroAnalysis(
                status="not_found",
                risk_flags=[
                    {
                        "type": "multiple_prozorro_terminations_found",
                        "source": "prozorro_analysis",
                    }
                ],
            ),
        )

        summary = build_risk_summary(result, None)

        self.assertEqual(summary.score, 5)
        self.assertNotIn("multiple_prozorro_terminations_found", [reason["type"] for reason in summary.reasons])

    def test_build_risk_summary_ignores_prozorro_search_summary_without_flags(self):
        from app.bot import build_risk_summary
        from app.models.company_lookup import CompanyLookupResult, ProzorroAnalysis, ProzorroSearchSummary

        result = CompanyLookupResult(
            status="found",
            edrpou="12345678",
            prozorro_analysis=ProzorroAnalysis(
                status="partial",
                search_summary=ProzorroSearchSummary(total_count=370, checked_count=10),
                risk_flags=[],
            ),
        )

        summary = build_risk_summary(result, None)

        self.assertEqual(summary.score, 5)
        self.assertEqual(summary.reasons, [])

    def test_build_sources_snapshot_includes_prozorro_analysis(self):
        from app.bot import build_sources_snapshot
        from app.models.company_lookup import CompanyLookupResult, ProzorroAnalysis, ProzorroStats

        analysis = ProzorroAnalysis(status="found", stats=ProzorroStats(procurements_count=2))
        result = CompanyLookupResult(status="found", edrpou="12345678", prozorro_analysis=analysis)

        sources = build_sources_snapshot(result, None, None)

        self.assertEqual(sources["prozorro"]["status"], "found")
        self.assertEqual(sources["prozorro"]["stats"]["procurements_count"], 2)

    def test_build_risk_summary_includes_confirmed_prozorro_sale_risk(self):
        from app.bot import build_risk_summary
        from app.models.company_lookup import CompanyLookupResult, ProzorroSaleAnalysis, ProzorroSaleRiskAuction

        result = CompanyLookupResult(
            status="found",
            edrpou="12345678",
            prozorro_sale_analysis=ProzorroSaleAnalysis(
                status="found",
                checked_count=2,
                confirmed_count=1,
                risky_auctions=[
                    ProzorroSaleRiskAuction(
                        auction_id="BSE001-UA-20260601-12345",
                        risk="переможець не виконав умови",
                        url="https://prozorro.sale/auction/BSE001-UA-20260601-12345",
                    )
                ],
                risk_flags=[
                    {
                        "type": "prozorro_sale_risky_auction",
                        "source": "prozorro_sale",
                        "status": "found",
                    }
                ],
            ),
        )

        summary = build_risk_summary(result, None)

        self.assertEqual(summary.score, 35)
        self.assertEqual(summary.reasons[0]["type"], "prozorro_sale_risky_auction")
        self.assertEqual(summary.reasons[0]["sources"], ["prozorro_sale"])

    def test_build_risk_summary_adds_negative_equity_financial_flags(self):
        from app.bot import build_risk_summary
        from app.models.company_lookup import CompanyLookupResult, FinancialData, FinancialYearData

        result = CompanyLookupResult(
            status="found",
            edrpou="12345678",
            financial_data=FinancialData(
                years={
                    "2025": FinancialYearData(
                        assets_uah=1_000_000,
                        liabilities_uah=1_200_000,
                        equity_uah=-200_000,
                        net_profit_uah=50_000,
                    )
                }
            ),
        )

        summary = build_risk_summary(result, None)
        reason_types = [reason["type"] for reason in summary.reasons]

        self.assertIn("negative_equity_found", reason_types)
        self.assertIn("liabilities_exceed_assets", reason_types)

    def test_low_capital_and_missing_financial_data_create_moderate_soft_risk(self):
        from app.bot import build_risk_summary
        from app.models.company_lookup import CompanyData, CompanyLookupResult, RiskInput

        result = CompanyLookupResult(
            status="found",
            edrpou="42263098",
            company_data=CompanyData(
                short_name="ТОВ «ПАРАГВАЙ ТРЕЙД»",
                edrpou="42263098",
                statutory_capital_uah=5001,
            ),
            risk_input=RiskInput(statutory_capital_uah=5001),
        )

        summary = build_risk_summary(result, None)
        reason_types = [reason["type"] for reason in summary.reasons]

        self.assertIn("low_authorized_capital_found", reason_types)
        self.assertIn("financial_data_missing", reason_types)
        self.assertIn("weak_public_financial_profile", reason_types)
        self.assertGreaterEqual(summary.score, 21)
        self.assertLessEqual(summary.score, 31)
        self.assertEqual(summary.level, "medium")

    def test_financial_data_missing_without_low_capital_is_soft_low_risk(self):
        from app.bot import build_risk_summary
        from app.models.company_lookup import CompanyData, CompanyLookupResult, RiskInput

        result = CompanyLookupResult(
            status="found",
            edrpou="12345678",
            company_data=CompanyData(
                short_name="ТОВ «ТЕСТ»",
                edrpou="12345678",
                statutory_capital_uah=100_000,
            ),
            risk_input=RiskInput(statutory_capital_uah=100_000),
        )

        summary = build_risk_summary(result, None)
        reason_types = [reason["type"] for reason in summary.reasons]

        self.assertNotIn("low_authorized_capital_found", reason_types)
        self.assertIn("financial_data_missing", reason_types)
        self.assertNotIn("weak_public_financial_profile", reason_types)
        self.assertEqual(summary.score, 12)

    def test_low_capital_without_missing_financial_data_is_soft_low_risk(self):
        from app.bot import build_risk_summary
        from app.models.company_lookup import CompanyData, CompanyLookupResult, FinancialData, FinancialYearData, RiskInput

        result = CompanyLookupResult(
            status="found",
            edrpou="12345678",
            company_data=CompanyData(
                short_name="ТОВ «ТЕСТ»",
                edrpou="12345678",
                statutory_capital_uah=5001,
            ),
            financial_data=FinancialData(
                years={"2025": FinancialYearData(revenue_uah=100_000)}
            ),
            risk_input=RiskInput(statutory_capital_uah=5001, has_financial_history=True),
        )

        summary = build_risk_summary(result, None)
        reason_types = [reason["type"] for reason in summary.reasons]

        self.assertIn("low_authorized_capital_found", reason_types)
        self.assertNotIn("financial_data_missing", reason_types)
        self.assertNotIn("weak_public_financial_profile", reason_types)
        self.assertEqual(summary.score, 8)

    def test_low_capital_with_strong_finances_can_be_compensated(self):
        from app.bot import build_risk_summary
        from app.models.company_lookup import CompanyData, CompanyLookupResult, FinancialData, FinancialYearData, RiskInput

        result = CompanyLookupResult(
            status="found",
            edrpou="12345678",
            company_data=CompanyData(
                short_name="ТОВ «ТЕСТ»",
                edrpou="12345678",
                statutory_capital_uah=5001,
            ),
            financial_data=FinancialData(
                years={
                    "2024": FinancialYearData(
                        revenue_uah=50_000_000,
                        assets_uah=20_000_000,
                        liabilities_uah=5_000_000,
                        equity_uah=15_000_000,
                        net_profit_uah=2_000_000,
                    ),
                    "2025": FinancialYearData(
                        revenue_uah=60_000_000,
                        assets_uah=25_000_000,
                        liabilities_uah=6_000_000,
                        equity_uah=19_000_000,
                        net_profit_uah=3_000_000,
                    ),
                }
            ),
            risk_input=RiskInput(statutory_capital_uah=5001, company_age_years=7, has_financial_history=True),
        )

        summary = build_risk_summary(result, None)
        reason_types = [reason["type"] for reason in summary.reasons]

        self.assertIn("low_authorized_capital_found", reason_types)
        self.assertIn("strong_financial_profile", reason_types)
        self.assertNotIn("financial_data_missing", reason_types)
        self.assertLess(summary.score, 8)

    def test_unconfirmed_large_prozorro_search_noise_adds_only_small_weight(self):
        from app.bot import build_risk_summary
        from app.models.company_lookup import CompanyLookupResult, ProzorroAnalysis, ProzorroSearchSummary

        result = CompanyLookupResult(
            status="found",
            edrpou="42263098",
            prozorro_analysis=ProzorroAnalysis(
                status="partial",
                search_summary=ProzorroSearchSummary(
                    total_count=1406,
                    checked_count=50,
                    detail_checked_count=50,
                    confirmed_participation_count=0,
                    items=[
                        {
                            "tenderID": "UA-2026-01-01-000001-a",
                            "status": "unsuccessful",
                            "risk_marker_codes": ["termination"],
                        }
                    ],
                ),
                risk_flags=[],
            ),
        )

        summary = build_risk_summary(result, None)
        reason_types = [reason["type"] for reason in summary.reasons]

        self.assertIn("prozorro_unconfirmed_search_noise", reason_types)
        self.assertNotIn("prozorro_termination_found", reason_types)
        self.assertEqual(summary.score, 5)

    def test_low_capital_missing_finance_and_unconfirmed_search_noise_scores_about_27(self):
        from app.bot import build_risk_summary
        from app.models.company_lookup import CompanyData, CompanyLookupResult, ProzorroAnalysis, ProzorroSearchSummary, RiskInput

        result = CompanyLookupResult(
            status="found",
            edrpou="42263098",
            company_data=CompanyData(
                short_name="ТОВ «ПАРАГВАЙ ТРЕЙД»",
                edrpou="42263098",
                statutory_capital_uah=5001,
            ),
            risk_input=RiskInput(statutory_capital_uah=5001),
            prozorro_analysis=ProzorroAnalysis(
                status="partial",
                search_summary=ProzorroSearchSummary(
                    total_count=1406,
                    checked_count=50,
                    detail_checked_count=50,
                    confirmed_participation_count=0,
                    items=[
                        {
                            "tenderID": "UA-2026-01-01-000001-a",
                            "status": "unsuccessful",
                            "risk_marker_codes": ["termination"],
                        }
                    ],
                ),
                risk_flags=[],
            ),
        )

        summary = build_risk_summary(result, None)
        reason_types = [reason["type"] for reason in summary.reasons]

        self.assertIn("low_authorized_capital_found", reason_types)
        self.assertIn("financial_data_missing", reason_types)
        self.assertIn("weak_public_financial_profile", reason_types)
        self.assertIn("prozorro_unconfirmed_search_noise", reason_types)
        self.assertGreaterEqual(summary.score, 25)
        self.assertLessEqual(summary.score, 30)
        self.assertEqual(summary.level, "medium")

    def test_low_capital_missing_finance_reason_lines_are_shown(self):
        from app.bot import build_edrpou_response
        from app.models.company_lookup import CompanyData, CompanyLookupResult, RiskInput

        result = CompanyLookupResult(
            status="found",
            edrpou="42263098",
            company_data=CompanyData(
                short_name="ТОВ «ПАРАГВАЙ ТРЕЙД»",
                edrpou="42263098",
                status="Зареєстровано",
                registration_date="25.06.2018",
                statutory_capital_uah=5001,
            ),
            risk_input=RiskInput(statutory_capital_uah=5001, company_age_years=8),
        )

        response = build_edrpou_response("42263098", result)
        reason_block = response.split("Причини оцінки:", 1)[1].split("Загальний ризик:", 1)[0]

        self.assertIn("⚠️ Статутний капітал дуже низький.", reason_block)
        self.assertIn("⚠️ Повні фінансові показники у доступних джерелах не знайдено.", reason_block)
        self.assertIn("⚠️ Публічний фінансовий профіль слабко підтверджений.", reason_block)
        self.assertIn("Загальний ризик: помірний", response)

    def build_loss_summary(
        self,
        loss: int,
        *,
        assets: int | None = None,
        liabilities: int | None = None,
        revenue: int | None = None,
        equity: int | None = None,
    ):
        from app.bot import build_risk_summary
        from app.models.company_lookup import CompanyLookupResult, FinancialData, FinancialYearData

        result = CompanyLookupResult(
            status="found",
            edrpou="12345678",
            financial_data=FinancialData(
                years={
                    "2025": FinancialYearData(
                        revenue_uah=revenue,
                        assets_uah=assets,
                        liabilities_uah=liabilities,
                        equity_uah=equity,
                        net_profit_uah=loss,
                    )
                }
            ),
        )

        return build_risk_summary(result, None)

    def test_loss_amounts_create_expected_single_loss_flag(self):
        loss_cases = [
            (-5_000, "small_loss_found", 5),
            (-26_000, "medium_loss_found", 5),
            (-150_000, "large_loss_found", 10),
            (-2_000_000, "large_loss_found", 10),
            (-467_000_000, "large_loss_found", 10),
        ]
        loss_flag_types = {
            "small_loss_found",
            "medium_loss_found",
            "large_loss_found",
            "very_large_loss_found",
            "critical_loss_found",
        }

        for loss, expected_type, expected_score in loss_cases:
            with self.subTest(loss=loss):
                summary = self.build_loss_summary(loss)
                reason_types = [reason["type"] for reason in summary.reasons]
                found_loss_flags = [reason_type for reason_type in reason_types if reason_type in loss_flag_types]

                self.assertEqual(found_loss_flags, [expected_type])
                self.assertEqual(summary.score, expected_score)

    def test_ukrposhta_scale_loss_is_not_critical_when_balance_is_healthy(self):
        summary = self.build_loss_summary(
            -204_779_000,
            assets=14_983_924_000,
            liabilities=9_979_299_000,
            equity=5_004_625_000,
        )
        reason_types = [reason["type"] for reason in summary.reasons]

        self.assertIn("large_loss_found", reason_types)
        self.assertNotIn("critical_loss_found", reason_types)
        self.assertNotIn("weak_financial_position", reason_types)

    def test_loss_greater_than_revenue_is_critical(self):
        summary = self.build_loss_summary(
            -12_000_000,
            revenue=10_000_000,
            assets=300_000_000,
            liabilities=100_000_000,
            equity=200_000_000,
        )
        reason_types = [reason["type"] for reason in summary.reasons]

        self.assertIn("critical_loss_found", reason_types)

    def test_loss_to_assets_at_least_ten_percent_is_critical(self):
        summary = self.build_loss_summary(
            -20_000_000,
            assets=100_000_000,
            liabilities=40_000_000,
            equity=60_000_000,
        )
        reason_types = [reason["type"] for reason in summary.reasons]

        self.assertIn("critical_loss_found", reason_types)

    def test_medium_loss_with_large_assets_is_not_critical(self):
        summary = self.build_loss_summary(
            -26_000,
            assets=396_000_000,
            liabilities=100_000_000,
        )
        reason_types = [reason["type"] for reason in summary.reasons]

        self.assertIn("medium_loss_found", reason_types)
        self.assertNotIn("critical_loss_found", reason_types)
        self.assertNotIn("very_large_loss_found", reason_types)

    def test_critical_loss_with_bad_balance_strengthens_financial_position(self):
        summary = self.build_loss_summary(
            -467_000_000,
            assets=66_000_000,
            liabilities=1_828_000_000,
            equity=-1_762_000_000,
        )
        reason_types = [reason["type"] for reason in summary.reasons]

        self.assertIn("critical_loss_found", reason_types)
        self.assertIn("negative_equity_found", reason_types)
        self.assertIn("liabilities_exceed_assets", reason_types)
        self.assertIn("severe_negative_equity", reason_types)
        self.assertIn("weak_financial_position", reason_types)

    def test_large_loss_with_negative_equity_is_critical(self):
        summary = self.build_loss_summary(
            -20_000_000,
            assets=300_000_000,
            liabilities=200_000_000,
            equity=-10_000_000,
        )
        reason_types = [reason["type"] for reason in summary.reasons]

        self.assertIn("critical_loss_found", reason_types)
        self.assertIn("negative_equity_found", reason_types)

    def test_large_loss_with_liabilities_above_assets_is_critical(self):
        summary = self.build_loss_summary(
            -20_000_000,
            assets=300_000_000,
            liabilities=350_000_000,
            equity=10_000_000,
        )
        reason_types = [reason["type"] for reason in summary.reasons]

        self.assertIn("critical_loss_found", reason_types)
        self.assertIn("liabilities_exceed_assets", reason_types)

    def test_build_risk_summary_adds_losses_with_negative_equity_flag(self):
        from app.bot import build_risk_summary
        from app.models.company_lookup import CompanyLookupResult, FinancialData, FinancialYearData

        result = CompanyLookupResult(
            status="found",
            edrpou="12345678",
            financial_data=FinancialData(
                years={
                    "2025": FinancialYearData(
                        assets_uah=1_000_000,
                        liabilities_uah=1_400_000,
                        equity_uah=-400_000,
                        net_profit_uah=-120_000,
                    )
                }
            ),
        )

        summary = build_risk_summary(result, None)
        reason_types = [reason["type"] for reason in summary.reasons]

        self.assertIn("losses_with_negative_equity", reason_types)
        self.assertIn("weak_financial_position", reason_types)

    def test_build_risk_summary_adds_negative_equity_multiple_years_flag(self):
        from app.bot import build_risk_summary
        from app.models.company_lookup import CompanyLookupResult, FinancialData, FinancialYearData

        result = CompanyLookupResult(
            status="found",
            edrpou="12345678",
            financial_data=FinancialData(
                years={
                    "2024": FinancialYearData(assets_uah=900_000, liabilities_uah=1_000_000, equity_uah=-100_000),
                    "2025": FinancialYearData(assets_uah=1_000_000, liabilities_uah=1_300_000, equity_uah=-300_000),
                }
            ),
        )

        summary = build_risk_summary(result, None)

        self.assertIn("negative_equity_multiple_years", [reason["type"] for reason in summary.reasons])

    def test_build_risk_summary_adds_severe_negative_equity_flag(self):
        from app.bot import build_risk_summary
        from app.models.company_lookup import CompanyLookupResult, FinancialData, FinancialYearData

        result = CompanyLookupResult(
            status="found",
            edrpou="25102871",
            financial_data=FinancialData(
                years={
                    "2023": FinancialYearData(
                        assets_uah=66_773_100,
                        liabilities_uah=1_828_097_500,
                        equity_uah=-1_761_324_400,
                        net_profit_uah=-467_497_000,
                    )
                }
            ),
        )

        summary = build_risk_summary(result, None)
        reason_types = [reason["type"] for reason in summary.reasons]

        self.assertIn("severe_negative_equity", reason_types)
        self.assertIn("weak_financial_position", reason_types)

    def test_build_risk_summary_adds_positive_financial_profile_and_reducer(self):
        from app.bot import build_risk_summary
        from app.models.company_lookup import CompanyLookupResult, CourtData, FinancialData, FinancialYearData, RiskInput

        result = CompanyLookupResult(
            status="found",
            edrpou="30487219",
            risk_input=RiskInput(company_age_years=25),
            court_data=CourtData(has_court_mentions=True, court_mentions_count=25),
            financial_data=FinancialData(
                years={
                    "2024": FinancialYearData(
                        revenue_uah=200_000_000,
                        assets_uah=70_000_000,
                        liabilities_uah=40_000_000,
                        equity_uah=30_000_000,
                        net_profit_uah=5_000_000,
                    ),
                    "2025": FinancialYearData(
                        revenue_uah=250_000_000,
                        assets_uah=90_000_000,
                        liabilities_uah=45_000_000,
                        equity_uah=45_000_000,
                        net_profit_uah=8_000_000,
                    ),
                }
            ),
        )

        summary = build_risk_summary(result, None)
        reason_types = [reason["type"] for reason in summary.reasons]

        self.assertIn("positive_profit_found", reason_types)
        self.assertIn("positive_equity_found", reason_types)
        self.assertIn("equity_growth_found", reason_types)
        self.assertIn("assets_exceed_liabilities", reason_types)
        self.assertIn("strong_revenue_found", reason_types)
        self.assertIn("strong_financial_profile", reason_types)
        self.assertEqual(summary.score, 5)

    def test_build_risk_summary_adds_very_strong_financial_profile_for_large_healthy_company(self):
        from app.bot import build_risk_summary
        from app.models.company_lookup import CompanyLookupResult, FinancialData, FinancialYearData, RiskInput

        result = CompanyLookupResult(
            status="found",
            edrpou="30487219",
            risk_input=RiskInput(company_age_years=25),
            financial_data=FinancialData(
                years={
                    "2024": FinancialYearData(
                        revenue_uah=180_000_000_000,
                        assets_uah=55_000_000_000,
                        liabilities_uah=42_000_000_000,
                        equity_uah=13_000_000_000,
                        net_profit_uah=2_900_000_000,
                    ),
                    "2025": FinancialYearData(
                        revenue_uah=247_348_831_000,
                        assets_uah=62_752_080_000,
                        liabilities_uah=44_228_798_000,
                        equity_uah=18_523_282_000,
                        net_profit_uah=3_427_397_000,
                    ),
                }
            ),
        )

        summary = build_risk_summary(result, None)
        reason_types = [reason["type"] for reason in summary.reasons]

        self.assertIn("very_strong_financial_profile", reason_types)
        self.assertNotIn("negative_equity_found", reason_types)
        self.assertEqual(summary.score, 5)

    def test_very_many_court_mentions_create_information_floor_for_healthy_company(self):
        from app.bot import build_risk_summary
        from app.models.company_lookup import CompanyLookupResult, CourtData, FinancialData, FinancialYearData, RiskInput

        result = CompanyLookupResult(
            status="found",
            edrpou="30487219",
            risk_input=RiskInput(company_age_years=25),
            court_data=CourtData(has_court_mentions=True, court_mentions_count=26_690),
            financial_data=FinancialData(
                years={
                    "2024": FinancialYearData(
                        revenue_uah=180_000_000_000,
                        assets_uah=55_000_000_000,
                        liabilities_uah=42_000_000_000,
                        equity_uah=13_000_000_000,
                        net_profit_uah=2_900_000_000,
                    ),
                    "2025": FinancialYearData(
                        revenue_uah=247_348_831_000,
                        assets_uah=62_752_080_000,
                        liabilities_uah=44_228_798_000,
                        equity_uah=18_523_282_000,
                        net_profit_uah=3_427_397_000,
                    ),
                }
            ),
        )

        summary = build_risk_summary(result, None)
        reason_types = [reason["type"] for reason in summary.reasons]

        self.assertIn("very_many_court_mentions_found", reason_types)
        self.assertEqual(summary.score, 8)

    def test_six_court_documents_keep_small_but_visible_score_even_with_strong_finances(self):
        from app.bot import build_risk_summary
        from app.models.company_lookup import CompanyData, CompanyLookupResult, CourtData, FinancialData, FinancialYearData, RiskInput

        result = CompanyLookupResult(
            status="found",
            edrpou="40483430",
            company_data=CompanyData(
                short_name="ТОВ «АВАРТЕХ УКРАЇНА»",
                edrpou="40483430",
                statutory_capital_uah=5_000,
            ),
            court_data=CourtData(has_court_mentions=True, court_mentions_count=6),
            financial_data=FinancialData(
                years={
                    "2023": FinancialYearData(
                        revenue_uah=24_000_000,
                        assets_uah=8_000_000,
                        liabilities_uah=3_300_000,
                        equity_uah=4_700_000,
                        net_profit_uah=900_000,
                    ),
                    "2025": FinancialYearData(
                        revenue_uah=36_637_100,
                        assets_uah=12_144_600,
                        liabilities_uah=4_600_100,
                        equity_uah=7_544_500,
                        net_profit_uah=1_764_100,
                    ),
                }
            ),
            risk_input=RiskInput(
                company_age_years=10,
                statutory_capital_uah=5_000,
                has_court_mentions=True,
                court_mentions_count=6,
                has_financial_history=True,
            ),
        )

        summary = build_risk_summary(result, None)
        reason_types = [reason["type"] for reason in summary.reasons]

        self.assertIn("court_cases_found", reason_types)
        self.assertIn("several_court_mentions_found", reason_types)
        self.assertIn("low_authorized_capital_found", reason_types)
        self.assertEqual(summary.score, 8)

    def test_large_statutory_capital_with_negative_equity_does_not_get_financial_reducer(self):
        from app.bot import build_risk_summary
        from app.models.company_lookup import CompanyLookupResult, FinancialData, FinancialYearData, RiskInput

        result = CompanyLookupResult(
            status="found",
            edrpou="25102871",
            risk_input=RiskInput(statutory_capital_uah=426_500_601),
            financial_data=FinancialData(
                years={
                    "2023": FinancialYearData(
                        revenue_uah=563_400,
                        assets_uah=66_773_100,
                        liabilities_uah=1_828_097_500,
                        equity_uah=-1_761_324_400,
                        net_profit_uah=-467_497_000,
                    )
                }
            ),
        )

        summary = build_risk_summary(result, None)
        reason_types = [reason["type"] for reason in summary.reasons]

        self.assertNotIn("strong_financial_profile", reason_types)
        self.assertNotIn("very_strong_financial_profile", reason_types)
        self.assertIn("weak_financial_position", reason_types)
        self.assertGreaterEqual(summary.score, 65)

    def test_positive_financial_reason_lines_are_shown_for_healthy_company(self):
        from app.bot import build_edrpou_response
        from app.models.company_lookup import CompanyData, CompanyLookupResult, FinancialData, FinancialYearData, RiskInput

        result = CompanyLookupResult(
            status="found",
            edrpou="30487219",
            company_data=CompanyData(
                short_name="ТОВ «АТБ-МАРКЕТ»",
                edrpou="30487219",
                status="Зареєстровано",
                registration_date="19.07.1999",
                main_activity_code="47.11",
                main_activity_name="Роздрібна торгівля",
            ),
            risk_input=RiskInput(company_age_years=25),
            financial_data=FinancialData(
                years={
                    "2024": FinancialYearData(
                        revenue_uah=180_000_000_000,
                        assets_uah=55_000_000_000,
                        liabilities_uah=42_000_000_000,
                        equity_uah=13_000_000_000,
                        net_profit_uah=2_900_000_000,
                    ),
                    "2025": FinancialYearData(
                        revenue_uah=247_348_831_000,
                        assets_uah=62_752_080_000,
                        liabilities_uah=44_228_798_000,
                        equity_uah=18_523_282_000,
                        net_profit_uah=3_427_397_000,
                    ),
                }
            ),
        )

        response = build_edrpou_response("30487219", result)
        reason_block = response.split("Причини оцінки:", 1)[1].split("Загальний ризик:", 1)[0]

        self.assertIn(
            "✅ Фінансовий профіль виглядає стабільним: прибуток, активи перевищують зобов’язання, власний капітал позитивний.",
            reason_block,
        )
        self.assertIn("✅ Власний капітал зростає.", reason_block)
        self.assertIn("✅ Компанія має значний дохід/активи.", reason_block)

    def test_found_company_response_groups_overlapping_bankruptcy_and_financial_reasons(self):
        from app.bot import build_edrpou_response
        from app.models.company_lookup import (
            CompanyData,
            CompanyLookupResult,
            CourtData,
            FinancialData,
            FinancialYearData,
            ProzorroSaleAnalysis,
            ProzorroSaleRiskAuction,
        )

        result = CompanyLookupResult(
            status="found",
            edrpou="25102871",
            company_data=CompanyData(
                short_name="ТОВ «УКРІНВЕСТ»",
                edrpou="25102871",
                status="припинено",
                registration_date="27.08.1997",
            ),
            financial_data=FinancialData(
                years={
                    "2021": FinancialYearData(
                        assets_uah=100_000_000,
                        liabilities_uah=1_349_696_900,
                        equity_uah=-1_249_696_900,
                        net_profit_uah=-100_000_000,
                    ),
                    "2023": FinancialYearData(
                        assets_uah=66_773_100,
                        liabilities_uah=1_828_097_500,
                        equity_uah=-1_761_324_400,
                        net_profit_uah=-467_497_000,
                    ),
                }
            ),
            court_data=CourtData(risk_flags=["bankruptcy_found"]),
            prozorro_sale_analysis=ProzorroSaleAnalysis(
                status="found",
                checked_count=5,
                confirmed_count=5,
                risky_auctions=[
                    ProzorroSaleRiskAuction(
                        auction_id="BRD001-UA-20250508-60050",
                        risk="аукціон не відбувся; ознаки банкрутства / ліквідаційна маса",
                        url="https://prozorro.sale/auction/BRD001-UA-20250508-60050/",
                    )
                ],
                risk_flags=[
                    {
                        "type": "prozorro_sale_risky_auction",
                        "source": "prozorro_sale",
                        "status": "found",
                        "raw_text": "BRD001-UA-20250508-60050 — аукціон не відбувся; ознаки банкрутства / ліквідаційна маса",
                    },
                    {
                        "type": "bankruptcy_found",
                        "source": "prozorro_sale",
                        "status": "found",
                        "raw_text": "BRD001-UA-20250508-60050 — аукціон не відбувся; ознаки банкрутства / ліквідаційна маса",
                    },
                ],
            ),
        )

        response = build_edrpou_response("25102871", result)
        reason_block = response.split("Причини оцінки:", 1)[1].split("Загальний ризик:", 1)[0]

        self.assertIn("Фінансова звітність показує комплексні проблеми", reason_block)
        self.assertEqual(reason_block.count("Фінансова звітність показує"), 1)
        self.assertNotIn("Фінансова звітність показує від’ємний власний капітал.", reason_block)
        self.assertNotIn("Фінансова звітність показує, що зобов’язання перевищують активи.", reason_block)
        self.assertNotIn("Компанія має збиток і від’ємний власний капітал.", reason_block)
        self.assertNotIn("У Prozorro.Sale знайдено підтверджений продаж майна", reason_block)
        self.assertIn("Банкрутний ризик підтверджено", reason_block)
        self.assertNotIn("✅ Компанія працює тривалий час.", response)
        self.assertIn("Загальний ризик: критичний", response)

    def test_found_company_response_shows_prozorro_sale_only_for_confirmed_risks(self):
        from app.bot import build_edrpou_response
        from app.models.company_lookup import (
            CompanyData,
            CompanyLookupResult,
            ProzorroSaleAnalysis,
            ProzorroSaleRiskAuction,
        )

        result = CompanyLookupResult(
            status="found",
            edrpou="12345678",
            company_data=CompanyData(short_name='ТОВ "Тест"', edrpou="12345678", status="зареєстровано"),
            prozorro_sale_analysis=ProzorroSaleAnalysis(
                status="found",
                checked_count=2,
                confirmed_count=1,
                risky_auctions=[
                    ProzorroSaleRiskAuction(
                        auction_id="BSE001-UA-20260601-12345",
                        risk="переможець не виконав умови",
                        url="https://prozorro.sale/auction/BSE001-UA-20260601-12345",
                    )
                ],
                risk_flags=[
                    {
                        "type": "prozorro_sale_risky_auction",
                        "source": "prozorro_sale",
                        "status": "found",
                    }
                ],
            ),
        )

        response = build_edrpou_response("12345678", result)

        self.assertIn("Prozorro.Sale:", response)
        self.assertIn("⚠️ Знайдено ризикові аукціони: 1", response)
        self.assertIn("1. BSE001-UA-20260601-12345 — переможець не виконав умови", response)
        self.assertIn("https://prozorro.sale/auction/BSE001-UA-20260601-12345", response)
        self.assertIn("Джерела: Opendatabot, Prozorro.Sale", response)

    def test_found_company_response_shows_prozorro_sale_debtor_mention_as_information(self):
        from app.bot import build_edrpou_response, build_risk_summary
        from app.models.company_lookup import (
            CompanyData,
            CompanyLookupResult,
            ProzorroSaleAnalysis,
            ProzorroSaleRiskAuction,
        )

        result = CompanyLookupResult(
            status="found",
            edrpou="30487219",
            company_data=CompanyData(short_name='ТОВ "АТБ Маркет"', edrpou="30487219", status="зареєстровано"),
            prozorro_sale_analysis=ProzorroSaleAnalysis(
                status="found",
                checked_count=1,
                confirmed_count=1,
                informational_mentions=[
                    ProzorroSaleRiskAuction(
                        auction_id="UA-PS-2021-08-20-000052-3",
                        risk="компанія згадується у складі дебіторської заборгованості банкрута",
                        url="https://prozorro.sale/auction/UA-PS-2021-08-20-000052-3/",
                        role="debtor_mention",
                    )
                ],
                risk_flags=[
                    {
                        "type": "prozorro_sale_debtor_mention",
                        "source": "prozorro_sale",
                        "status": "found",
                        "raw_text": "UA-PS-2021-08-20-000052-3 — компанія згадується у складі дебіторської заборгованості банкрута.",
                    }
                ],
            ),
        )

        response = build_edrpou_response("30487219", result)
        risk_summary = build_risk_summary(result, None)

        self.assertIn("Prozorro.Sale:", response)
        self.assertIn(
            "Компанія також згадується у лотах, пов’язаних із дебіторською заборгованістю.",
            response,
        )
        self.assertIn("Цей сигнал сам по собі не доводить банкрутство.", response)
        self.assertNotIn("статус компанії в ЄДР/судових джерелах", response)
        self.assertNotIn("⚠️ Знайдено ризикові аукціони", response)
        self.assertNotIn("банкрутство самої компанії", response.split("Причини оцінки:", 1)[1])
        self.assertEqual(risk_summary.score, 5)
        self.assertEqual([reason["type"] for reason in risk_summary.reasons], ["prozorro_sale_debtor_mention"])

    def test_prozorro_sale_debtor_mention_explains_separate_confirmed_bankruptcy_status(self):
        from app.bot import build_edrpou_response
        from app.models.company_lookup import (
            CompanyData,
            CompanyLookupResult,
            ProzorroSaleAnalysis,
            ProzorroSaleRiskAuction,
        )

        result = CompanyLookupResult(
            status="found",
            edrpou="39525257",
            company_data=CompanyData(
                short_name="ТОВ «ОДЕСАГАЗ-ПОСТАЧАННЯ»",
                edrpou="39525257",
                status="порушено справу про банкрутство",
            ),
            prozorro_sale_analysis=ProzorroSaleAnalysis(
                status="found",
                checked_count=1,
                confirmed_count=1,
                informational_mentions=[
                    ProzorroSaleRiskAuction(
                        auction_id="BRD001-UA-20260522-66821",
                        risk="компанія згадується у складі дебіторської заборгованості банкрута",
                        url="https://prozorro.sale/auction/BRD001-UA-20260522-66821/",
                        role="debtor_mention",
                    )
                ],
                risk_flags=[
                    {
                        "type": "prozorro_sale_debtor_mention",
                        "source": "prozorro_sale",
                        "status": "found",
                        "raw_text": "BRD001-UA-20260522-66821 — компанія згадується у складі дебіторської заборгованості банкрута.",
                    }
                ],
            ),
        )

        response = build_edrpou_response("39525257", result)
        reason_block = response.split("Причини оцінки:", 1)[1].split("Загальний ризик:", 1)[0]

        self.assertIn(
            "Цей сигнал сам по собі не доводить банкрутство, але окремо статус компанії в ЄДР/судових джерелах уже вказує на порушену справу про банкрутство.",
            response,
        )
        self.assertIn("Банкрутний ризик підтверджено", reason_block)

    def test_found_company_response_shows_unsuccessful_prozorro_sale_auction_as_information(self):
        from app.bot import build_edrpou_response, build_risk_summary
        from app.models.company_lookup import (
            CompanyData,
            CompanyLookupResult,
            ProzorroSaleAnalysis,
            ProzorroSaleRiskAuction,
        )

        result = CompanyLookupResult(
            status="found",
            edrpou="32265298",
            company_data=CompanyData(short_name='ТОВ "Приклад"', edrpou="32265298", status="зареєстровано"),
            prozorro_sale_analysis=ProzorroSaleAnalysis(
                status="found",
                checked_count=2,
                confirmed_count=2,
                informational_mentions=[
                    ProzorroSaleRiskAuction(
                        auction_id="SPE001-UA-20260401-11111",
                        risk="аукціон не відбувся",
                        url="https://prozorro.sale/auction/SPE001-UA-20260401-11111/",
                        role="auction_participant",
                    ),
                    ProzorroSaleRiskAuction(
                        auction_id="SPE001-UA-20260402-22222",
                        risk="аукціон не відбувся",
                        url="https://prozorro.sale/auction/SPE001-UA-20260402-22222/",
                        role="auction_participant",
                    ),
                ],
                risk_flags=[],
            ),
        )

        response = build_edrpou_response("32265298", result)
        risk_summary = build_risk_summary(result, None)

        self.assertIn("Prozorro.Sale:", response)
        self.assertIn(
            "Prozorro.Sale: знайдено аукціони з участю/згадкою компанії. Негативної дії саме з боку компанії не підтверджено.",
            response,
        )
        self.assertNotIn("⚠️ Знайдено ризикові аукціони", response)
        self.assertEqual(risk_summary.score, 5)
        self.assertEqual(risk_summary.reasons, [])

    def test_found_company_response_omits_prozorro_sale_without_risks(self):
        from app.bot import build_edrpou_response
        from app.models.company_lookup import CompanyData, CompanyLookupResult, ProzorroSaleAnalysis

        result = CompanyLookupResult(
            status="found",
            edrpou="12345678",
            company_data=CompanyData(short_name='ТОВ "Тест"', edrpou="12345678", status="зареєстровано"),
            prozorro_sale_analysis=ProzorroSaleAnalysis(status="not_found", checked_count=2, confirmed_count=1),
        )

        response = build_edrpou_response("12345678", result)

        self.assertNotIn("Prozorro.Sale:", response)
        self.assertNotIn("Prozorro.Sale", response.split("Джерело: Opendatabot")[-1])

    def test_found_company_response_shows_prozorro_block_when_analysis_exists(self):
        from app.bot import build_edrpou_response
        from app.models.company_lookup import (
            CompanyData,
            CompanyLookupResult,
            ProzorroAnalysis,
            ProzorroProcurement,
            ProzorroStats,
        )

        result = CompanyLookupResult(
            status="found",
            edrpou="12345678",
            company_data=CompanyData(short_name='ТОВ "Тест"', edrpou="12345678", status="зареєстровано"),
            prozorro_analysis=ProzorroAnalysis(
                status="found",
                stats=ProzorroStats(
                    procurements_count=4,
                    participations_count=4,
                    wins_count=0,
                    contracts_count=0,
                    completed_contracts_count=0,
                    terminated_contracts_count=0,
                    disqualifications_count=0,
                    win_rate_percent=0.0,
                    last_participation_date="2025-03-10",
                ),
                procurements=[ProzorroProcurement(procurement_id="UA-DETAIL-1", participated=True)],
                info_notes=[
                    "Сам факт участі не є ризиком.",
                    "Перемог у Prozorro не знайдено; score не підвищено.",
                ],
                summary="Prozorro: участей 4, перемог 0, договорів 0, розірвань 0.",
            ),
        )

        response = build_edrpou_response("12345678", result)
        lines = response.splitlines()

        self.assertIn("Prozorro:", response)
        self.assertIn("Закупівель: 4", lines)
        self.assertIn("Участей: 4", lines)
        self.assertNotIn("Перемог: 0", lines)
        self.assertNotIn("Договорів: 0", lines)
        self.assertNotIn("Завершених договорів: 0", lines)
        self.assertNotIn("Розірваних договорів: 0", lines)
        self.assertNotIn("Дискваліфікацій: 0", lines)
        self.assertIn("Остання участь: 2025-03-10", response)
        self.assertIn("Сам факт участі не є ризиком", response)
        self.assertIn("Джерела: Opendatabot, Prozorro", response)
        self.assertNotIn("Детальна історія закупівель Prozorro ще не підключена", response)

    def test_found_company_response_omits_prozorro_block_when_analysis_missing(self):
        from app.bot import build_edrpou_response
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        result = CompanyLookupResult(
            status="found",
            edrpou="12345678",
            company_data=CompanyData(short_name='ТОВ "Тест"', edrpou="12345678", status="зареєстровано"),
        )

        response = build_edrpou_response("12345678", result)

        self.assertNotIn("Prozorro:", response)
        self.assertNotIn("Prozorro", response.split("Джерело: Opendatabot")[-1])

    def test_found_company_response_shows_tender_fallback_when_prozorro_analysis_missing(self):
        from app.bot import build_edrpou_response
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        result = CompanyLookupResult(
            status="found",
            edrpou="12345678",
            company_data=CompanyData(
                short_name='ТОВ "Тест"',
                edrpou="12345678",
                status="зареєстровано",
                tenders_count=7,
                tenders_text="7 тендерів",
            ),
        )

        response = build_edrpou_response("12345678", result)

        self.assertIn("Prozorro:", response)
        self.assertIn("За відкритими даними знайдено участь у тендерах: 7 тендерів.", response)
        self.assertIn("Детальна історія закупівель Prozorro тимчасово недоступна або не знайдена live-пошуком.", response)
        self.assertIn("Score не підвищено.", response)
        self.assertIn("Джерело: Opendatabot", response)
        self.assertNotIn("Джерела: Opendatabot, Prozorro", response)

    def test_found_company_response_shows_prozorro_portal_summary(self):
        from app.bot import build_edrpou_response
        from app.models.company_lookup import (
            CompanyData,
            CompanyLookupResult,
            ProzorroAnalysis,
            ProzorroSearchSummary,
        )

        result = CompanyLookupResult(
            status="found",
            edrpou="12345678",
            company_data=CompanyData(
                short_name='ТОВ "Тест"',
                edrpou="12345678",
                status="зареєстровано",
                tenders_count=7,
                tenders_text="7 тендерів",
            ),
            prozorro_analysis=ProzorroAnalysis(
                status="partial",
                search_summary=ProzorroSearchSummary(
                    total_count=370,
                    checked_count=10,
                    detail_checked_count=10,
                    confirmed_participation_count=1,
                    source_url="https://prozorro.gov.ua/uk/search/tender?text=12345678",
                    items=[
                        {
                            "tenderID": f"UA-2026-01-{index:02d}-000001-a",
                            "title": f"Постачання товарів {index}",
                            "status": "cancelled" if index == 8 else "complete",
                            "buyer_name": "Тестовий замовник",
                            "expected_value_uah": 125000.0 + index,
                        }
                        for index in range(1, 11)
                    ],
                ),
            ),
        )

        with self.assertLogs(level="INFO") as logs:
            response = build_edrpou_response("12345678", result)

        self.assertIn("Prozorro:", response)
        self.assertIn("Результатів у пошуку Prozorro: 370.", response)
        self.assertIn("Перевірено у видачі: 10.", response)
        self.assertIn("Підтверджено участь компанії серед перевірених: 1.", response)
        self.assertNotIn("Перші закупівлі у видачі:", response)
        self.assertNotIn("UA-2026-01-01-000001-a", response)
        self.assertNotIn("Статус: complete; замовник: Тестовий замовник", response)
        self.assertIn("У перших 10 результатах пошуку знайдено явні маркери: 1.", response)
        self.assertIn("Участей/перемог/договорів: дані уточнюються за деталями закупівель.", response)
        self.assertNotIn("Примітка: Prozorro-блок є пошуковим оглядом.", response)
        self.assertNotIn("Детальна історія закупівель Prozorro тимчасово недоступна", response)
        self.assertNotIn("Закупівель: 0", response)
        self.assertIn("Джерела: Opendatabot, Prozorro", response)
        self.assertIn("Prozorro report mode: summary", "\n".join(logs.output))
        self.assertIn("Prozorro records_count=0", "\n".join(logs.output))
        self.assertIn("Prozorro source added=true", "\n".join(logs.output))

    def test_prozorro_search_summary_says_when_company_is_not_confirmed(self):
        from app.bot import build_edrpou_response, build_risk_summary
        from app.models.company_lookup import (
            CompanyData,
            CompanyLookupResult,
            ProzorroAnalysis,
            ProzorroSearchSummary,
        )

        result = CompanyLookupResult(
            status="found",
            edrpou="12345678",
            company_data=CompanyData(
                short_name='ТОВ "Тест"',
                edrpou="12345678",
                status="зареєстровано",
            ),
            prozorro_analysis=ProzorroAnalysis(
                status="partial",
                search_summary=ProzorroSearchSummary(
                    total_count=53,
                    checked_count=10,
                    detail_checked_count=10,
                    confirmed_participation_count=0,
                    items=[
                        {
                            "tenderID": f"UA-2026-02-{index:02d}-000001-a",
                            "title": f"Пошуковий збіг {index}",
                            "status": "unsuccessful" if index == 3 else "complete",
                            "buyer_name": "Інший замовник",
                            "expected_value_uah": 50000.0 + index,
                        }
                        for index in range(1, 11)
                    ],
                ),
                risk_flags=[],
            ),
        )

        response = build_edrpou_response("12345678", result)
        risk_summary = build_risk_summary(result, None)

        self.assertIn("Компанія має згадки у публічних закупівлях.", response)
        self.assertIn("Автоматично підтвердити роль у перевірених 10 результатах не вдалося.", response)
        self.assertNotIn("Підтверджено участь компанії серед перевірених: 0.", response)
        self.assertNotIn("Участей/перемог/договорів:", response)
        self.assertIn(
            "Сам факт згадки у Prozorro не є ризиком; потрібна окрема перевірка ролі: учасник, переможець, замовник або текстовий збіг.",
            response,
        )
        self.assertIn(
            (
                "У пошуковій видачі є потенційні маркери: 1, але участь компанії "
                "в цих результатах не підтверджена, тому вони не враховані як ризик."
            ),
            response,
        )
        self.assertNotIn("Примітка: Prozorro-блок є пошуковим оглядом.", response)
        self.assertEqual(
            [line for line in response.splitlines() if line.startswith("Джерел")][-1],
            "Джерела: Opendatabot, Prozorro search та інші джерела",
        )
        self.assertEqual(risk_summary.score, 5)
        self.assertEqual(risk_summary.reasons, [])

    def test_prozorro_search_scan_no_marker_text_is_precise(self):
        from app.bot import build_prozorro_search_risk_scan_line

        line = build_prozorro_search_risk_scan_line(
            [{"tenderID": f"UA-2026-01-{index:02d}-000001-a", "status": "complete"} for index in range(1, 11)]
        )

        self.assertEqual(
            line,
            (
                "У перших 10 результатах пошуку не знайдено явних маркерів: "
                "скасування, розірвання, скарги або моніторингу."
            ),
        )

    def test_prozorro_search_scan_without_confirmed_company_and_without_markers_is_short(self):
        from app.bot import build_prozorro_search_risk_scan_line

        line = build_prozorro_search_risk_scan_line(
            [{"tenderID": f"UA-2026-01-{index:02d}-000001-a", "status": "complete"} for index in range(1, 11)],
            confirmed_participation_count=0,
        )

        self.assertEqual(
            line,
            "У перших перевірених результатах не знайдено підтверджених ризикових ознак, пов’язаних із компанією.",
        )

    def test_prozorro_search_scan_uses_all_checked_items_not_only_first_ten(self):
        from app.bot import build_prozorro_search_risk_scan_line

        items = [
            {"tenderID": f"UA-2026-01-{index:02d}-000001-a", "status": "complete"}
            for index in range(1, 51)
        ]
        items[29]["risk_marker_codes"] = ["termination"]

        line = build_prozorro_search_risk_scan_line(items, confirmed_participation_count=0)

        self.assertEqual(
            line,
            (
                "У пошуковій видачі є потенційні маркери: 1, але участь компанії "
                "в цих результатах не підтверджена, тому вони не враховані як ризик."
            ),
        )

    def test_detailed_prozorro_block_shows_checked_count_and_detected_signals(self):
        from app.bot import build_edrpou_response
        from app.models.company_lookup import (
            CompanyData,
            CompanyLookupResult,
            ProzorroAnalysis,
            ProzorroProcurement,
            ProzorroSearchSummary,
            ProzorroStats,
        )

        result = CompanyLookupResult(
            status="found",
            edrpou="12345678",
            company_data=CompanyData(short_name='ТОВ "Тест"', edrpou="12345678", status="зареєстровано"),
            prozorro_analysis=ProzorroAnalysis(
                status="found",
                search_summary=ProzorroSearchSummary(
                    total_count=118,
                    checked_count=50,
                    detail_checked_count=50,
                    confirmed_participation_count=3,
                    items=[
                        {"tenderID": "UA-1", "participation_confirmed": True, "risk_marker_codes": ["monitoring"]},
                        {"tenderID": "UA-2", "participation_confirmed": True, "risk_marker_codes": ["complaint"]},
                    ],
                ),
                stats=ProzorroStats(
                    procurements_count=3,
                    participations_count=3,
                    wins_count=1,
                    contracts_count=2,
                    terminated_contracts_count=1,
                    disqualifications_count=1,
                    complaints_count=1,
                    win_rate_percent=33.33,
                ),
                procurements=[
                    ProzorroProcurement(
                        procurement_id="UA-1",
                        participated=True,
                        won=True,
                        has_contract=True,
                        contract_terminated=True,
                        complaints_count=1,
                    ),
                    ProzorroProcurement(procurement_id="UA-2", participated=True, disqualified=True),
                    ProzorroProcurement(procurement_id="UA-3", participated=True, has_contract=True),
                ],
                summary="Prozorro: участей 3, перемог 1, договорів 2, розірвань 1.",
            ),
        )

        response = build_edrpou_response("12345678", result)

        self.assertIn("Результатів у пошуку Prozorro: 118.", response)
        self.assertIn("Перевірено у видачі: 50.", response)
        self.assertIn("Підтверджено закупівель із компанією: 3.", response)
        self.assertIn("Участей: 3", response)
        self.assertIn("Перемог: 1", response)
        self.assertIn("Договорів: 2", response)
        self.assertIn("Розірваних договорів: 1", response)
        self.assertIn("Дискваліфікацій: 1", response)
        self.assertIn("Скарг/вимог: 1", response)
        self.assertIn("Моніторингів: 1", response)
        self.assertIn("⚠️ Виявлені сигнали:", response)
        self.assertIn("• Була дискваліфікація учасника.", response)
        self.assertIn("• Є розірвання договору.", response)
        self.assertIn("• Є скарги/вимоги у закупівлях.", response)
        self.assertIn("• Є моніторинг закупівлі.", response)

    def test_detailed_prozorro_block_shows_role_based_summary(self):
        from app.bot import build_edrpou_response
        from app.models.company_lookup import (
            CompanyData,
            CompanyLookupResult,
            ProzorroAnalysis,
            ProzorroProcurement,
            ProzorroSearchSummary,
            ProzorroStats,
        )

        result = CompanyLookupResult(
            status="found",
            edrpou="12345678",
            company_data=CompanyData(short_name='ТОВ "Тест"', edrpou="12345678", status="зареєстровано"),
            prozorro_analysis=ProzorroAnalysis(
                status="found",
                search_summary=ProzorroSearchSummary(
                    total_count=185,
                    checked_count=50,
                    detail_checked_count=50,
                    confirmed_participation_count=3,
                    participant_count=1,
                    winner_count=0,
                    supplier_contract_count=0,
                    buyer_count=2,
                    items=[
                        {"tenderID": "UA-1", "participation_confirmed": True, "confirmed_roles": ["buyer"]},
                        {"tenderID": "UA-2", "participation_confirmed": True, "confirmed_roles": ["buyer"]},
                        {"tenderID": "UA-3", "participation_confirmed": True, "confirmed_roles": ["participant"]},
                    ],
                ),
                stats=ProzorroStats(
                    procurements_count=3,
                    participations_count=1,
                    wins_count=0,
                    contracts_count=0,
                    terminated_contracts_count=0,
                    disqualifications_count=0,
                ),
                procurements=[ProzorroProcurement(procurement_id="UA-3", participated=True)],
            ),
        )

        response = build_edrpou_response("12345678", result)

        self.assertIn("Підтверджено закупівель із компанією: 3.", response)
        self.assertIn("Ролі:", response)
        self.assertIn("• учасник: 1", response)
        self.assertIn("• переможець/постачальник: 0", response)
        self.assertIn("• замовник: 2", response)
        self.assertNotIn("Негативні факти серед перевірених:", response)
        self.assertIn("Висновок: підтверджених негативних Prozorro-фактів серед перевірених закупівель не знайдено.", response)
        self.assertNotIn("Підтверджено збігів компанії у пошуку серед перевірених", response)

    def test_buyer_only_prozorro_block_does_not_show_supplier_risk_or_duplicate_counts(self):
        from app.bot import build_edrpou_response
        from app.models.company_lookup import (
            CompanyData,
            CompanyLookupResult,
            ProzorroAnalysis,
            ProzorroProcurement,
            ProzorroSearchSummary,
            ProzorroStats,
        )

        result = CompanyLookupResult(
            status="found",
            edrpou="21560045",
            company_data=CompanyData(short_name="АТ «УКРПОШТА»", edrpou="21560045", status="Зареєстровано"),
            prozorro_analysis=ProzorroAnalysis(
                status="found",
                search_summary=ProzorroSearchSummary(
                    total_count=10_000,
                    checked_count=50,
                    detail_checked_count=50,
                    confirmed_participation_count=49,
                    buyer_count=49,
                    items=[
                        {
                            "tenderID": "UA-BUYER-1",
                            "participation_confirmed": True,
                            "confirmed_roles": ["buyer"],
                            "risk_marker_codes": ["monitoring"],
                        }
                    ],
                ),
                stats=ProzorroStats(
                    procurements_count=49,
                    participations_count=0,
                    wins_count=0,
                    contracts_count=0,
                    complaints_count=1,
                ),
                procurements=[ProzorroProcurement(procurement_id="UA-BUYER-1", complaints_count=1)],
                summary="Prozorro: участей 0, перемог 0, договорів 0, розірвань 0.",
            ),
        )

        response = build_edrpou_response("21560045", result)
        lines = response.splitlines()

        self.assertIn("Підтверджено закупівель із компанією: 49.", response)
        self.assertIn("• замовник: 49", response)
        self.assertNotIn("Закупівель: 49", lines)
        self.assertNotIn("Prozorro: участей 0, перемог 0, договорів 0, розірвань 0.", response)
        self.assertIn("Сигнали серед закупівель як замовника:", response)
        self.assertIn("• скарги/моніторинги: 2", response)
        self.assertNotIn("Негативні факти серед перевірених:", response)

    def test_detailed_prozorro_block_distinguishes_search_matches_from_stats(self):
        from app.bot import build_edrpou_response
        from app.models.company_lookup import (
            CompanyData,
            CompanyLookupResult,
            ProzorroAnalysis,
            ProzorroProcurement,
            ProzorroSearchSummary,
            ProzorroStats,
        )

        result = CompanyLookupResult(
            status="found",
            edrpou="39582749",
            company_data=CompanyData(short_name="ТОВ «ЗАКАРПАТГАЗ ЗБУТ»", edrpou="39582749", status="зареєстровано"),
            prozorro_analysis=ProzorroAnalysis(
                status="found",
                search_summary=ProzorroSearchSummary(
                    total_count=185,
                    checked_count=50,
                    detail_checked_count=50,
                    confirmed_participation_count=3,
                    items=[
                        {"tenderID": "UA-1", "participation_confirmed": True},
                        {"tenderID": "UA-2", "participation_confirmed": True},
                        {"tenderID": "UA-3", "participation_confirmed": True},
                    ],
                ),
                stats=ProzorroStats(
                    procurements_count=1,
                    participations_count=1,
                    wins_count=0,
                    contracts_count=1,
                    terminated_contracts_count=1,
                ),
                procurements=[
                    ProzorroProcurement(
                        procurement_id="UA-2022-09-06-011139-a",
                        participated=True,
                        has_contract=True,
                        contract_terminated=True,
                    )
                ],
            ),
        )

        response = build_edrpou_response("39582749", result)
        lines = response.splitlines()

        self.assertIn("Підтверджено закупівель із компанією: 3.", response)
        self.assertIn("Участей у деталізованій статистиці: 1", response)
        self.assertNotIn("Ролі:", response)
        self.assertIn(
            "Примітка: кількість підтверджених закупівель і деталізована статистика можуть відрізнятися.",
            response,
        )
        self.assertNotIn("Підтверджено участь компанії серед перевірених: 3.", response)
        self.assertNotIn("Підтверджено збігів компанії у пошуку серед перевірених: 3.", response)
        self.assertNotIn("Участей: 1", lines)

    def test_found_company_response_uses_fallback_for_source_error_prozorro(self):
        from app.bot import build_edrpou_response
        from app.models.company_lookup import CompanyData, CompanyLookupResult, ProzorroAnalysis

        result = CompanyLookupResult(
            status="found",
            edrpou="12345678",
            company_data=CompanyData(
                short_name='ТОВ "Тест"',
                edrpou="12345678",
                tenders_count=7,
                tenders_text="7 тендерів",
            ),
            prozorro_analysis=ProzorroAnalysis(status="source_error", error="live_timeout"),
        )

        with self.assertLogs(level="INFO") as logs:
            response = build_edrpou_response("12345678", result)

        self.assertIn("Prozorro:", response)
        self.assertIn("За відкритими даними знайдено участь у тендерах: 7 тендерів.", response)
        self.assertIn("Детальна історія закупівель Prozorro тимчасово недоступна або не знайдена live-пошуком.", response)
        self.assertNotIn("Закупівель: 0", response)
        self.assertNotIn("Участей: 0", response)
        self.assertNotIn("Джерела: Opendatabot, Prozorro", response)
        self.assertIn("Prozorro report mode: source_error", "\n".join(logs.output))
        self.assertIn("Prozorro records_count=0", "\n".join(logs.output))
        self.assertIn("Prozorro source added=false", "\n".join(logs.output))

    def test_found_company_response_uses_fallback_for_unavailable_prozorro(self):
        from app.bot import build_edrpou_response
        from app.models.company_lookup import CompanyData, CompanyLookupResult, ProzorroAnalysis

        result = CompanyLookupResult(
            status="found",
            edrpou="12345678",
            company_data=CompanyData(
                short_name='ТОВ "Тест"',
                edrpou="12345678",
                tenders_count=7,
                tenders_text="7 тендерів",
            ),
            prozorro_analysis=ProzorroAnalysis(status="unavailable"),
        )

        response = build_edrpou_response("12345678", result)

        self.assertIn("Prozorro:", response)
        self.assertIn("Детальна історія закупівель Prozorro тимчасово недоступна або не знайдена live-пошуком.", response)
        self.assertNotIn("Закупівель: 0", response)
        self.assertNotIn("Джерела: Opendatabot, Prozorro", response)

    def test_found_company_response_uses_fallback_when_prozorro_has_no_records(self):
        from app.bot import build_edrpou_response
        from app.models.company_lookup import (
            CompanyData,
            CompanyLookupResult,
            ProzorroAnalysis,
            ProzorroStats,
        )

        result = CompanyLookupResult(
            status="found",
            edrpou="12345678",
            company_data=CompanyData(
                short_name='ТОВ "Тест"',
                edrpou="12345678",
                tenders_count=7,
                tenders_text="7 тендерів",
            ),
            prozorro_analysis=ProzorroAnalysis(status="found", stats=ProzorroStats(procurements_count=0)),
        )

        response = build_edrpou_response("12345678", result)

        self.assertIn("Prozorro:", response)
        self.assertIn("Детальна історія закупівель Prozorro тимчасово недоступна або не знайдена live-пошуком.", response)
        self.assertNotIn("Закупівель: 0", response)
        self.assertNotIn("Джерела: Opendatabot, Prozorro", response)

    def test_recommendation_text_changes_by_risk_level(self):
        from app.bot import build_recommendation_text

        self.assertIn("Критичних ознак", build_recommendation_text("low"))
        self.assertIn("Критичних ознак", build_recommendation_text("info"))
        self.assertIn("потребує додаткової перевірки перед оплатою", build_recommendation_text("medium"))
        self.assertIn(
            "не рекомендується робити передоплату без додаткової перевірки",
            build_recommendation_text("high"),
        )

    def test_calculate_company_age_years_accepts_ukrainian_and_iso_dates(self):
        from app.bot import calculate_company_age_years

        self.assertGreaterEqual(calculate_company_age_years("07.05.2008"), 10)
        self.assertGreaterEqual(calculate_company_age_years("2008-05-07"), 10)
        self.assertIsNone(calculate_company_age_years("not a date"))

    def test_start_text_matches_intro_copy(self):
        from app.bot import START_TEXT

        self.assertEqual(
            START_TEXT,
            "RiskUA — швидка перевірка контрагента 🔎\n\n"
            "🎁 Демо-перевірка — безкоштовно\n"
            "\n"
            "У демо ви отримаєте:\n\n"
            "🔎 базові реєстраційні дані\n"
            "🏢 назву, статус, адресу та керівника\n"
            "⚠️ короткий попередній огляд ризиків\n"
            "📊 орієнтовний рівень ризику\n\n"
            "💳 Повна перевірка\n\n"
            "Повна перевірка включає:\n\n"
            "🏢 розширені дані про контрагента\n"
            "📊 фінансові показники\n"
            "☎️ контактну інформацію\n"
            "📈 динаміку капіталу\n"
            "🏛 перевірку Prozorro\n"
            "⚖️ судові та ризикові сигнали\n"
            "🚨 ознаки банкрутства, припинення або боргів\n"
            "🧩 причини оцінки ризику\n"
            "🤖 AI-висновок щодо співпраці\n"
            "✅ рекомендацію: чи варто співпрацювати\n"
            "📊 загальний ризик від 0 до 100\n\n"
            "Тарифи:\n\n"
            "🔎 1 повна перевірка — 29 грн\n"
            "📦 10 повних перевірок — 199 грн\n\n"
            "⏳ Аналіз може зайняти до 1 хвилини.\n\n"
            "Надішліть ЄДРПОУ, щоб почати 👇",
        )

    def test_bot_profile_description_copy(self):
        from app.bot import BOT_DESCRIPTION_TEXT, BOT_SHORT_DESCRIPTION_TEXT

        self.assertEqual(
            BOT_DESCRIPTION_TEXT,
            "RiskUA — швидка перевірка контрагента 🔎",
        )
        self.assertEqual(
            BOT_SHORT_DESCRIPTION_TEXT,
            "RiskUA — швидка перевірка контрагента перед оплатою, договором або співпрацею.",
        )

    def test_configure_bot_profile_updates_description_fields(self):
        import asyncio

        from app.bot import BOT_DESCRIPTION_TEXT, BOT_SHORT_DESCRIPTION_TEXT, configure_bot_profile

        class FakeBot:
            def __init__(self):
                self.description: str | None = None
                self.short_description: str | None = None

            async def set_my_description(self, description: str) -> None:
                self.description = description

            async def set_my_short_description(self, short_description: str) -> None:
                self.short_description = short_description

        bot = FakeBot()

        asyncio.run(configure_bot_profile(bot))

        self.assertEqual(bot.description, BOT_DESCRIPTION_TEXT)
        self.assertEqual(bot.short_description, BOT_SHORT_DESCRIPTION_TEXT)

    def test_run_bot_syncs_profile_description_before_polling(self):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import patch

        from app.bot import BOT_DESCRIPTION_TEXT, BOT_SHORT_DESCRIPTION_TEXT, run_bot

        events: list[str] = []

        class FakeBot:
            def __init__(self, token: str):
                self.token = token
                self.description: str | None = None
                self.short_description: str | None = None

            async def set_my_description(self, description: str) -> None:
                self.description = description
                events.append(f"description:{description}")

            async def set_my_short_description(self, short_description: str) -> None:
                self.short_description = short_description
                events.append(f"short:{short_description}")

        class FakeDispatcher:
            async def start_polling(self, bot: FakeBot) -> None:
                events.append(f"polling:{bot.token}")

        with (
            patch("app.bot.load_settings", return_value=SimpleNamespace(bot_token="123456:test-token", app_env="test")),
            patch("app.bot.configure_diagnostic_logging"),
            patch("app.bot.log_diagnostic_event"),
            patch("app.bot.Bot", FakeBot),
            patch("app.bot.create_dispatcher", return_value=FakeDispatcher()),
        ):
            asyncio.run(run_bot())

        self.assertEqual(
            events,
            [
                f"description:{BOT_DESCRIPTION_TEXT}",
                f"short:{BOT_SHORT_DESCRIPTION_TEXT}",
                "polling:123456:test-token",
            ],
        )

    def test_default_analysis_timeout_is_one_minute(self):
        from app.bot import ANALYSIS_TIMEOUT_SECONDS

        self.assertEqual(ANALYSIS_TIMEOUT_SECONDS, 60.0)

    def test_invalid_edrpou_returns_format_hint(self):
        from app.bot import INVALID_EDRPOU_TEXT, build_edrpou_response

        self.assertEqual(
            build_edrpou_response("1234-5678"),
            INVALID_EDRPOU_TEXT,
        )

    def test_rejects_valid_edrpou_followed_by_non_url_text(self):
        from app.bot import INVALID_EDRPOU_TEXT, build_edrpou_response

        self.assertEqual(build_edrpou_response("12345678 abc"), INVALID_EDRPOU_TEXT)

    def test_accepts_edrpou_with_optional_website_url(self):
        from app.bot import parse_edrpou_query

        self.assertEqual(parse_edrpou_query("12345678 snvo.ua"), ("12345678", "https://snvo.ua"))

    def test_found_company_result_is_formatted(self):
        from app.bot import build_edrpou_response
        from app.models.clarity import ClarityData, ClaritySignals, ClarityTax
        from app.models.company_lookup import CompanyData, CompanyLookupResult, CourtData, FinancialData, FinancialYearData, RiskInput

        response = build_edrpou_response(
            "12345678",
            CompanyLookupResult(
                status="found",
                edrpou="12345678",
                source_url="https://opendatabot.ua/c/12345678?from=search",
                company_data=CompanyData(
                    full_name="ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ «ПРИКЛАД»",
                    short_name="ТОВ «ПРИКЛАД»",
                    edrpou="12345678",
                    status="Зареєстровано",
                    vat_status="Платник ПДВ",
                    registration_date="15.01.2024",
                    address="01001, Україна, місто Київ",
                    director="Іваненко Іван Іванович",
                    main_activity_code="46.90",
                    main_activity_name="Неспеціалізована оптова торгівля",
                    tenders_count=2,
                    tenders_text="учасник 2 закупівель",
                ),
                financial_data=FinancialData(
                    years={"2024": FinancialYearData(revenue_uah=1000000)}
                ),
                court_data=CourtData(has_court_mentions=True, total_cases_found=3),
                risk_input=RiskInput(
                    company_age_years=10,
                    has_financial_history=True,
                    has_court_mentions=True,
                    total_court_cases_found=3,
                ),
            ),
            ClarityData(
                source_url="https://clarity-project.info/edr/12345678",
                status="found",
                edrpou="12345678",
                tax=ClarityTax(tax_debt=False, esv_debt=False, vat_active=True),
                signals=ClaritySignals(
                    bankruptcy_count=0,
                    enforcement_proceedings_count=1,
                    edr_history_count=20,
                ),
            ),
        )

        self.assertIn("🔎 Перевірка контрагента", response)
        self.assertIn("ТОВ «ПРИКЛАД»", response)
        self.assertIn("ЄДРПОУ: 12345678", response)
        self.assertIn("Статус: Зареєстровано", response)
        self.assertIn("ПДВ-статус: Платник ПДВ", response)
        self.assertIn("Тендери за відкритими джерелами: 2", response)
        self.assertIn("✅ Компанія зареєстрована та працює тривалий час.", response)
        self.assertIn("Фінансові дані:", response)
        self.assertIn("Дохід (2024): 1 000 000 грн", response)
        self.assertIn("Судові документи: 3. Потрібна ручна перевірка змісту справ.", response)
        self.assertNotIn("Додаткові сигнали Clarity:", response)
        self.assertIn("Ознак банкрутства або припинення", response)
        self.assertIn("Податковий борг та борг ЄСВ", response)
        self.assertIn("Виконавчі провадження: 1", response)
        self.assertIn("Джерела: Opendatabot, Clarity", response)

    def test_compact_report_hides_masked_fields_and_moves_risk_to_end(self):
        from app.bot import format_found_company
        from app.models.company_lookup import CompanyData, CompanyLookupResult, CourtData, FinancialData, FinancialYearData, RiskInput

        contacts_summary = {
            "website": {"value": "****.*************.****", "confidence": "high", "sources": ["youcontrol"], "evidence": []},
            "phone": {"value": "+380322255437", "confidence": "high", "sources": ["youcontrol"], "evidence": []},
            "email": {"value": "*****@*************.****", "confidence": "high", "sources": ["youcontrol"], "evidence": []},
            "source_statuses": {"youcontrol": "found"},
        }
        decisions = [
            {
                "document_type": "Ухвала",
                "decision_date": f"0{index}.06.2026",
                "case_number": f"916/110{index}/26",
                "risk_summary": f"Документ {index} потребує ручної перевірки.",
                "url": f"https://court.example/doc-{index}" if index == 1 else None,
            }
            for index in range(1, 7)
        ]

        response = format_found_company(
            CompanyLookupResult(
                status="found",
                edrpou="12345678",
                company_data=CompanyData(
                    short_name='ТОВ "Тест"',
                    edrpou="12345678",
                    status="Зареєстровано",
                    tenders_count=401,
                    tenders_text="401 тендер",
                ),
                financial_data=FinancialData(
                    years={"2025": FinancialYearData(revenue_uah=1250000, net_profit_uah=110000)}
                ),
                court_data=CourtData(has_court_mentions=True, court_mentions_count=123, decisions=decisions),
                risk_input=RiskInput(has_court_mentions=True, court_mentions_count=123),
            ),
            contacts_summary=contacts_summary,
            domain_reputation_data={
                "source": "domain_reputation",
                "checked": True,
                "found": False,
                "url": "https://example.ua",
                "risk_flags": ["website_unavailable"],
                "error": "website_unavailable",
            },
        )

        self.assertIn("Тендери за відкритими джерелами: 401", response)
        self.assertNotIn("Тендери: 401 тендер", response)
        self.assertIn("Контакти:", response)
        self.assertIn("☎️ Телефон: +380322255437", response)
        self.assertNotIn("****.*************.****", response)
        self.assertNotIn("*****@*************.****", response)
        self.assertIn("Фінансові дані:", response)
        self.assertIn("Дохід (2025): 1 250 000 грн", response)
        self.assertNotIn("Доступність фінансових даних", response)
        self.assertIn("Судові документи:", response)
        self.assertIn("Знайдено судових документів: 123.", response)
        self.assertIn("Показано деталізованих документів: 3 з 123.", response)
        self.assertIn("1. Ухвала від 01.06.2026, справа №916/1101/26", response)
        self.assertIn("   Посилання: https://court.example/doc-1", response)
        self.assertNotIn("   Коротко:", response)
        self.assertIn("3. Ухвала від 03.06.2026, справа №916/1103/26", response)
        self.assertNotIn("916/1104/26", response)
        self.assertNotIn("916/1105/26", response)
        self.assertNotIn("916/1106/26", response)
        self.assertNotIn("   Посилання: None", response)
        self.assertIn("⚠️ Судові документи: 123. Потрібна ручна перевірка змісту справ.", response)
        self.assertIn("⚠️ Сайт не вдалося перевірити автоматично. Це не є доказом ризику, але потребує ручної перевірки.", response)
        self.assertNotIn("Рекомендація: перед передоплатою", response)
        self.assertLess(response.index("Судові документи:"), response.index("Причини оцінки:"))
        self.assertLess(response.index("Причини оцінки:"), response.index("Загальний ризик:"))
        self.assertLess(response.index("Загальний ризик:"), response.index("Джерела:"))
        self.assertIn("Судові джерела", response)
        self.assertNotIn("перевірка сайту", response)

    def test_financial_block_shows_equity_capital_growth(self):
        from app.bot import build_edrpou_response
        from app.models.company_lookup import CompanyData, CompanyLookupResult, FinancialData, FinancialYearData

        response = build_edrpou_response(
            "12345678",
            CompanyLookupResult(
                status="found",
                edrpou="12345678",
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou="12345678"),
                financial_data=FinancialData(
                    years={
                        "2025": FinancialYearData(assets_uah=3000000, liabilities_uah=900000),
                        "2024": FinancialYearData(assets_uah=2700000, liabilities_uah=800000),
                    }
                ),
            ),
        )

        self.assertIn("Динаміка власного капіталу: зростає", response)
        self.assertIn("2024: 1 900 000 грн → 2025: 2 100 000 грн", response)

    def test_financial_block_shows_equity_capital_decline(self):
        from app.bot import build_edrpou_response
        from app.models.company_lookup import CompanyData, CompanyLookupResult, FinancialData, FinancialYearData

        response = build_edrpou_response(
            "12345678",
            CompanyLookupResult(
                status="found",
                edrpou="12345678",
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou="12345678"),
                financial_data=FinancialData(
                    years={
                        "2025": FinancialYearData(equity_uah=1200000),
                        "2024": FinancialYearData(equity_uah=1500000),
                    }
                ),
            ),
        )

        self.assertIn("Динаміка власного капіталу: знижується", response)
        self.assertIn("2024: 1 500 000 грн → 2025: 1 200 000 грн", response)

    def test_normal_response_has_new_sections_and_no_raw_json(self):
        from app.bot import build_edrpou_response
        from app.models.clarity import ClarityData, ClarityRiskFlag
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        response = build_edrpou_response(
            "12345678",
            CompanyLookupResult(
                status="found",
                edrpou="12345678",
                company_data=CompanyData(
                    short_name="ТОВ «ПРИКЛАД»",
                    edrpou="12345678",
                    status="Зареєстровано",
                ),
            ),
            ClarityData(
                source_url="https://clarity-project.info/edr/12345678",
                status="found",
                edrpou="12345678",
                risk_flags=[
                    ClarityRiskFlag(
                        level="medium",
                        code="tax_debt_found",
                        text="У Clarity є ознака податкового боргу.",
                    )
                ],
            ),
        )

        for section in (
            "Назва компанії:",
            "ЄДРПОУ:",
            "Загальний ризик:",
            "Причини оцінки:",
            "Джерела:",
        ):
            self.assertIn(section, response)
        self.assertNotIn("Рекомендація: перед передоплатою", response)
        self.assertNotIn("Простими словами:", response)
        self.assertNotIn('{"', response)
        self.assertNotIn('"sources"', response)

    def test_source_error_clarity_is_omitted_from_response(self):
        from app.bot import build_edrpou_response
        from app.models.clarity import ClarityData
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        response = build_edrpou_response(
            "12345678",
            CompanyLookupResult(
                status="found",
                edrpou="12345678",
                source_url="https://opendatabot.ua/c/12345678?from=search",
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou="12345678"),
            ),
            ClarityData(
                source_url="https://clarity-project.info/edr/12345678",
                status="source_error",
                edrpou="12345678",
            ),
        )

        self.assertNotIn("Додаткові сигнали Clarity:", response)
        self.assertIn("Джерело: Opendatabot", response)
        self.assertNotIn("Обмеження перевірки:", response)
        self.assertNotIn("Clarity тимчасово недоступний", response)

    def test_timed_out_clarity_adds_limited_source_warning(self):
        from app.bot import build_edrpou_response
        from app.models.clarity import ClarityData
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        response = build_edrpou_response(
            "12345678",
            CompanyLookupResult(
                status="found",
                edrpou="12345678",
                source_url="https://opendatabot.ua/c/12345678?from=search",
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou="12345678"),
            ),
            ClarityData(
                source_url="https://clarity-project.info/edr/12345678",
                status="source_error",
                edrpou="12345678",
                error="analysis_timeout",
            ),
        )

        self.assertNotIn("Обмеження перевірки:", response)
        self.assertNotIn("Clarity не встигла відповісти", response)

    def test_not_found_clarity_is_omitted_from_response_sources(self):
        from app.bot import build_edrpou_response
        from app.models.clarity import ClarityData
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        response = build_edrpou_response(
            "12345678",
            CompanyLookupResult(
                status="found",
                edrpou="12345678",
                source_url="https://opendatabot.ua/c/12345678?from=search",
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou="12345678"),
            ),
            ClarityData(
                source_url="https://clarity-project.info/edr/12345678",
                status="not_found",
                edrpou="12345678",
            ),
        )

        self.assertNotIn("Додаткові сигнали Clarity:", response)
        self.assertIn("Джерело: Opendatabot", response)
        self.assertNotIn("Джерела: Opendatabot, Clarity", response)

    def test_clarity_company_data_is_used_as_fallback_for_missing_main_fields(self):
        from app.bot import build_edrpou_response
        from app.models.clarity import ClarityCompany, ClarityData
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        response = build_edrpou_response(
            "12345678",
            CompanyLookupResult(
                status="found",
                edrpou="12345678",
                source_url="https://opendatabot.ua/c/12345678?from=search",
                company_data=CompanyData(
                    short_name="ТОВ «ПРИКЛАД»",
                    edrpou="12345678",
                    director=None,
                    main_activity_code=None,
                    main_activity_name=None,
                ),
            ),
            ClarityData(
                source_url="https://clarity-project.info/edr/12345678",
                status="found",
                edrpou="12345678",
                company=ClarityCompany(
                    director="Петренко Петро Петрович",
                    main_activity="07.29 Добування руд інших кольорових металів",
                ),
            ),
        )

        self.assertIn("Керівник: Петренко Петро Петрович", response)
        self.assertIn("КВЕД: 07.29 Добування руд інших кольорових металів", response)
        self.assertIn("Джерела: Opendatabot, Clarity", response)

    def test_clarity_fallback_fields_are_reflected_in_main_signals(self):
        from app.bot import build_edrpou_response
        from app.models.clarity import ClarityCompany, ClarityData
        from app.models.company_lookup import CompanyData, CompanyLookupResult, RiskInput

        response = build_edrpou_response(
            "12345678",
            CompanyLookupResult(
                status="found",
                edrpou="12345678",
                company_data=CompanyData(
                    short_name="ТОВ «ПРИКЛАД»",
                    edrpou="12345678",
                    registration_date=None,
                    main_activity_code=None,
                    main_activity_name=None,
                ),
                risk_input=RiskInput(company_age_years=None, main_activity_code=None),
            ),
            ClarityData(
                source_url="https://clarity-project.info/edr/12345678",
                status="found",
                edrpou="12345678",
                company=ClarityCompany(
                    registration_date="2008-05-07",
                    main_activity="07.29 Добування руд інших кольорових металів",
                ),
            ),
        )

        self.assertIn("Дата реєстрації: 2008-05-07", response)
        self.assertIn("КВЕД: 07.29 Добування руд інших кольорових металів", response)
        self.assertIn("✅ Компанія працює тривалий час.", response)
        self.assertIn("✅ Основний КВЕД визначено: 07.29 Добування руд інших кольорових металів.", response)
        self.assertNotIn("Не вдалося визначити вік компанії.", response)
        self.assertNotIn("Основний КВЕД не вдалося визначити.", response)

    def test_partial_sources_add_limited_source_warning(self):
        from app.bot import build_edrpou_response
        from app.models.clarity import ClarityData
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        response = build_edrpou_response(
            "12345678",
            CompanyLookupResult(
                status="partial",
                edrpou="12345678",
                source_url="https://opendatabot.ua/c/12345678?from=search",
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou="12345678"),
                parse_warnings=["Не знайдено фінансову таблицю"],
            ),
            ClarityData(
                source_url="https://clarity-project.info/edr/12345678",
                status="partial",
                edrpou="12345678",
                parse_warnings=["Не вдалося визначити податковий борг у Clarity"],
            ),
        )

        self.assertNotIn("Обмеження перевірки:", response)
        self.assertNotIn("Opendatabot повернув неповні дані", response)
        self.assertNotIn("Clarity повернула неповні дані", response)

    def test_clarity_risk_flags_are_shown_carefully_in_response(self):
        from app.bot import build_edrpou_response
        from app.models.clarity import ClarityData, ClarityRiskFlag
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        response = build_edrpou_response(
            "12345678",
            CompanyLookupResult(
                status="found",
                edrpou="12345678",
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou="12345678"),
            ),
            ClarityData(
                source_url="https://clarity-project.info/edr/12345678",
                status="found",
                edrpou="12345678",
                risk_flags=[
                    ClarityRiskFlag(
                        level="high",
                        code="bankruptcy_found",
                        text="Знайдено записи, пов'язані з банкрутством. Потребує уважної додаткової перевірки.",
                    )
                ],
            ),
        )

        self.assertIn("Причини оцінки:", response)
        self.assertIn("критичний — 90/100", response)
        self.assertIn("Банкрутний ризик підтверджено", response)
        self.assertNotIn("шахрай", response.lower())
        self.assertNotIn("Рекомендація: перед передоплатою", response)
        self.assertNotIn("Критичних ознак у базовій інформаційній перевірці не виявлено", response)

    def test_medium_risk_flags_make_recommendation_more_careful(self):
        from app.bot import build_edrpou_response
        from app.models.clarity import ClarityData, ClarityRiskFlag
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        response = build_edrpou_response(
            "12345678",
            CompanyLookupResult(
                status="found",
                edrpou="12345678",
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou="12345678"),
            ),
            ClarityData(
                source_url="https://clarity-project.info/edr/12345678",
                status="found",
                edrpou="12345678",
                risk_flags=[
                    ClarityRiskFlag(
                        level="medium",
                        code="tax_debt_found",
                        text="У Clarity є ознака податкового боргу.",
                    )
                ],
            ),
        )

        self.assertNotIn("Рекомендація: перед передоплатою", response)
        self.assertNotIn("Критичних ознак у базовій інформаційній перевірці не виявлено", response)

    def test_clarity_tax_debt_amount_is_shown_and_not_reported_as_absent(self):
        from app.bot import build_edrpou_response
        from app.models.clarity import ClarityData, ClarityRiskFlag, ClarityTax
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        response = build_edrpou_response(
            "39388266",
            CompanyLookupResult(
                status="found",
                edrpou="39388266",
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou="39388266"),
            ),
            ClarityData(
                source_url="https://clarity-project.info/edr/39388266",
                status="found",
                edrpou="39388266",
                tax=ClarityTax(
                    tax_debt=True,
                    tax_debt_amount_uah=414839394.24,
                    tax_debt_as_of="28.01.2022",
                    esv_debt=False,
                ),
                risk_flags=[
                    ClarityRiskFlag(
                        level="medium",
                        code="tax_debt_found",
                        text=(
                            "Clarity показує податковий борг: 414 839 394.24 грн станом на 28.01.2022. "
                            "Через обмеження оновлення відкритих податкових даних із 2022 року це може бути "
                            "історичний запис, але його потрібно звірити вручну."
                        ),
                    ),
                ],
            ),
        )

        reason_block = response.split("Причини оцінки:", 1)[1].split("Загальний ризик:", 1)[0]
        self.assertIn("Clarity показує податковий борг: 414 839 394.24 грн станом на 28.01.2022", reason_block)
        self.assertIn("може бути історичний запис", reason_block)
        self.assertNotIn("Податковий борг та борг ЄСВ у доступних даних не виявлено.", reason_block)

    def test_opendatabot_tax_collection_overrides_clarity_absent_tax_debt(self):
        from app.bot import build_edrpou_response, with_source_diagnostics
        from app.models.clarity import ClarityData, ClarityRiskFlag, ClaritySignals, ClarityTax
        from app.services.opendatabot_lookup import parse_company_page

        html = """
        <html><body><main>
          <p>Код ЄДРПОУ</p><h1>44037141</h1>
          <h2>ТОВ «ПРОСКО»</h2>
          <p>Статус</p><p>Зареєстровано</p>
          <p>Повна назва</p><p>ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ «ПРОСКО»</p>
          <p>Дата заснування</p><p>17.12.2020</p>
          <p>Адреса</p><p>01001, Україна, місто Київ</p>
          <p>Директор</p><p>Іваненко Іван Іванович</p>
          <p>Статутний капітал</p><p>1 000 ₴</p>
          <p>Основний вид діяльності</p><p>23.99 Виробництво неметалевих мінеральних виробів, н.в.і.у.</p>
          <p>Державна податкова служба стягує з компанії 1 податковий борг</p>
          <p>Судовий реєстр</p><p>30 рішень</p>
        </main></body></html>
        """
        result = parse_company_page(html, "44037141")
        clarity_data = ClarityData(
            source_url="https://clarity-project.info/edr/44037141",
            status="found",
            edrpou="44037141",
            tax=ClarityTax(tax_debt=False, esv_debt=False),
            signals=ClaritySignals(enforcement_proceedings_count=19),
            risk_flags=[ClarityRiskFlag(level="medium", code="enforcement_found", text="Виконавчі провадження: 19")],
        )

        enriched = with_source_diagnostics(result, clarity_data)
        response = build_edrpou_response("44037141", result, clarity_data)

        reason_block = response.split("Причини оцінки:", 1)[1].split("Загальний ризик:", 1)[0]
        risk_codes = [reason["type"] for reason in enriched.risk_summary.reasons]
        self.assertIn("tax_debt_found", risk_codes)
        self.assertIn("tax_debt_source_mismatch", risk_codes)
        self.assertIn("opendatabot", next(reason for reason in enriched.risk_summary.reasons if reason["type"] == "tax_debt_found")["sources"])
        self.assertIn("Opendatabot показує, що ДПС стягує з компанії 1 податковий борг.", reason_block)
        self.assertIn("Виявлено значну кількість виконавчих проваджень", reason_block)
        self.assertIn("Судові документи: 30. Потрібна ручна перевірка змісту справ.", reason_block)
        self.assertIn("Статутний капітал невеликий: 1 000 грн.", reason_block)
        self.assertNotIn("Податковий борг та борг ЄСВ у доступних даних не виявлено.", reason_block)
        self.assertGreaterEqual(enriched.risk_summary.score, 60)

    def test_large_historical_tax_debt_enforcement_and_court_mentions_do_not_make_100(self):
        from app.bot import build_edrpou_response, with_source_diagnostics
        from app.models.clarity import ClarityData, ClaritySignals, ClarityTax
        from app.services.opendatabot_lookup import parse_company_page

        html = """
        <html><body><main>
          <p>Код ЄДРПОУ</p><h1>39388266</h1>
          <h2>ДП «ДЕРЖАВНА ВУГІЛЬНА КОМПАНІЯ»</h2>
          <p>Статус</p><p>Зареєстровано</p>
          <p>Повна назва</p><p>ДЕРЖАВНЕ ПІДПРИЄМСТВО «ДЕРЖАВНА ВУГІЛЬНА КОМПАНІЯ»</p>
          <p>Дата заснування</p><p>10.09.2014</p>
          <p>Адреса</p><p>01030, Україна, місто Київ</p>
          <p>Директор</p><p>Слюсар Сергій Анатолійович</p>
          <p>Статутний капітал</p><p>2 000 ₴</p>
          <p>Основний вид діяльності</p><p>46.71 Оптова торгівля твердим, рідким, газоподібним паливом і подібними продуктами</p>
          <p>Державна податкова служба стягує з компанії 1 податковий борг</p>
          <p>Судовий реєстр</p><p>30 рішень</p>
        </main></body></html>
        """
        result = parse_company_page(html, "39388266")
        clarity_data = ClarityData(
            source_url="https://clarity-project.info/edr/39388266",
            status="found",
            edrpou="39388266",
            tax=ClarityTax(
                tax_debt=True,
                esv_debt=False,
                tax_debt_amount_uah=414839394.24,
                tax_debt_as_of="28.01.2022",
            ),
            signals=ClaritySignals(
                bankruptcy_count=0,
                enforcement_proceedings_count=19,
            ),
        )

        enriched = with_source_diagnostics(result, clarity_data)
        response = build_edrpou_response("39388266", result, clarity_data)

        self.assertEqual(enriched.risk_summary.score, 80)
        self.assertEqual(enriched.risk_summary.level, "high")
        self.assertIn("Загальний ризик: високий — 80/100", response)
        self.assertNotIn("100/100", response)

    def test_tax_authority_is_not_reported_as_debtor_when_it_collects_tax_debt(self):
        from app.bot import build_edrpou_response, with_source_diagnostics
        from app.services.opendatabot_lookup import parse_company_page

        html = """
        <html><body><main>
          <p>Код ЄДРПОУ</p><h1>44116011</h1>
          <h2>ГУ ДПС У М. КИЄВІ</h2>
          <p>Статус</p><p>Зареєстровано</p>
          <p>Повна назва</p><p>ГОЛОВНЕ УПРАВЛІННЯ ДПС У М. КИЄВІ</p>
          <p>Дата заснування</p><p>30.09.2020</p>
          <p>Адреса</p><p>04116, Україна, місто Київ</p>
          <p>Директор</p><p>Іваненко Іван Іванович</p>
          <p>Основний вид діяльності</p><p>84.11 Державне управління загального характеру</p>
          <p>Державна податкова служба стягує з компанії 1 податковий борг</p>
        </main></body></html>
        """

        result = parse_company_page(html, "44116011")
        enriched = with_source_diagnostics(result, None)
        response = build_edrpou_response("44116011", result)
        risk_codes = [reason["type"] for reason in enriched.risk_summary.reasons]

        self.assertNotIn("tax_debt_found", risk_codes)
        self.assertNotIn("Opendatabot показує, що ДПС стягує з компанії", response)

    def test_debtors_registry_tax_creditor_is_shown_as_tax_enforcement(self):
        from app.bot import build_edrpou_response, with_source_diagnostics
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        debtors_registry_data = {
            "source": "debtors_registry",
            "checked": True,
            "found": True,
            "items_count": 1,
            "items": [
                {
                    "document_issuer": "ГУ ДПС у м. Києві",
                    "collection_category": "стягнення коштів до державного бюджету",
                }
            ],
            "risk_flags": ["debtor_registry_found", "tax_debt_enforcement_found"],
            "signals": [],
            "error": None,
        }
        result = CompanyLookupResult(
            status="found",
            edrpou="44037141",
            company_data=CompanyData(short_name="ТОВ «ПРОСКО»", edrpou="44037141"),
        )

        enriched = with_source_diagnostics(result, None, debtors_registry_data=debtors_registry_data)
        response = build_edrpou_response("44037141", result, debtors_registry_data=debtors_registry_data)

        self.assertIn("tax_debt_enforcement_found", [reason["type"] for reason in enriched.risk_summary.reasons])
        self.assertIn("Виявлено виконавче провадження на користь ДПС / державного бюджету.", response)

    def test_tax_source_unavailable_does_not_create_positive_no_debt_line(self):
        from app.bot import build_edrpou_response
        from app.models.clarity import ClarityData, ClarityTax
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        tax_data = {
            "source": "tax",
            "checked": False,
            "found": False,
            "tax_debt": None,
            "risk_flags": ["tax_source_unavailable"],
            "error": "tax_source_unavailable",
        }

        response = build_edrpou_response(
            "12345678",
            CompanyLookupResult(
                status="found",
                edrpou="12345678",
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou="12345678"),
            ),
            ClarityData(
                source_url="https://clarity-project.info/edr/12345678",
                status="found",
                edrpou="12345678",
                tax=ClarityTax(tax_debt=False, esv_debt=False),
            ),
            tax_data=tax_data,
        )

        reason_block = response.split("Причини оцінки:", 1)[1].split("Загальний ризик:", 1)[0]
        self.assertNotIn("Податковий борг та борг ЄСВ у доступних даних не виявлено.", reason_block)

    def test_large_enforcement_count_increases_risk_above_old_46_score(self):
        from app.bot import with_source_diagnostics
        from app.models.clarity import ClarityData, ClarityRiskFlag, ClaritySignals
        from app.models.company_lookup import CompanyData, CompanyLookupResult, CourtData, RiskInput

        enriched = with_source_diagnostics(
            CompanyLookupResult(
                status="found",
                edrpou="44037141",
                company_data=CompanyData(short_name="ТОВ «ПРОСКО»", edrpou="44037141"),
                court_data=CourtData(has_court_mentions=True, court_mentions_count=30),
                risk_input=RiskInput(has_court_mentions=True, court_mentions_count=30),
            ),
            ClarityData(
                source_url="https://clarity-project.info/edr/44037141",
                status="found",
                edrpou="44037141",
                signals=ClaritySignals(enforcement_proceedings_count=19),
                risk_flags=[ClarityRiskFlag(level="medium", code="enforcement_found", text="Виконавчі провадження: 19")],
            ),
        )

        self.assertNotEqual(enriched.risk_summary.score, 46)
        self.assertGreater(enriched.risk_summary.score, 46)
        self.assertIn("many_enforcement_proceedings_found", [reason["type"] for reason in enriched.risk_summary.reasons])
        self.assertIn("many_court_mentions_found", [reason["type"] for reason in enriched.risk_summary.reasons])

    def test_risk_flags_in_response_are_limited(self):
        from app.bot import build_risk_flag_lines
        from app.models.clarity import ClarityData, ClarityRiskFlag

        clarity_data = ClarityData(
            source_url="https://clarity-project.info/edr/12345678",
            status="found",
            edrpou="12345678",
            risk_flags=[
                ClarityRiskFlag(level="info", code=f"flag_{index}", text=f"Ознака {index}")
                for index in range(1, 5)
            ],
        )

        lines = build_risk_flag_lines(clarity_data)

        self.assertIn("• Ознака 1", lines)
        self.assertIn("• Ознака 3", lines)
        self.assertNotIn("• Ознака 4", lines)

    def test_source_snapshot_includes_youcontrol_and_dedupes_risk_flags(self):
        from app.bot import with_source_diagnostics
        from app.models.clarity import ClarityData, ClarityRiskFlag
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        result = CompanyLookupResult(
            status="found",
            edrpou="12345678",
            source_url="https://opendatabot.ua/c/12345678?from=search",
            company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou="12345678"),
        )
        clarity_data = ClarityData(
            source_url="https://clarity-project.info/edr/12345678",
            status="found",
            edrpou="12345678",
            risk_flags=[
                ClarityRiskFlag(
                    level="medium",
                    code="tax_debt_found",
                    text="У Clarity є ознака податкового боргу.",
                )
            ],
        )
        youcontrol_data = {
            "source": "youcontrol",
            "found": True,
            "url": "https://youcontrol.com.ua/catalog/company_details/12345678/",
            "company": {
                "name": "ТОВ «ПРИКЛАД»",
                "edrpou": "12345678",
                "status": "Зареєстровано",
                "registration_date": None,
                "address": None,
                "director": None,
                "main_kved": None,
                "additional_kveds": [],
            },
            "signals": ["Податковий борг: наявний", "Виконавчі провадження: 1"],
            "risk_flags": ["tax_debt_found", "enforcement_found"],
            "raw_text_excerpt": "ТОВ «ПРИКЛАД» ЄДРПОУ 12345678",
            "error": None,
        }

        enriched = with_source_diagnostics(result, clarity_data, youcontrol_data)

        self.assertEqual(enriched.youcontrol_data["source"], "youcontrol")
        self.assertEqual(enriched.sources["youcontrol"]["found"], True)
        self.assertIn("opendatabot", enriched.sources)
        self.assertIn("clarity", enriched.sources)
        self.assertIn("court_analysis", enriched.sources)
        risk_codes = [flag.code for flag in enriched.risk_summary.flags]
        self.assertEqual(risk_codes.count("tax_debt_found"), 1)
        self.assertIn("enforcement_found", risk_codes)

    def test_source_snapshot_includes_debtors_registry_and_dedupes_risk_flags(self):
        from app.bot import with_source_diagnostics
        from app.models.clarity import ClarityData, ClarityRiskFlag
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        result = CompanyLookupResult(
            status="found",
            edrpou="05747991",
            source_url="https://opendatabot.ua/c/05747991?from=search",
            company_data=CompanyData(short_name='АТ "СУМСЬКЕ МНВО"', edrpou="05747991"),
        )
        clarity_data = ClarityData(
            source_url="https://clarity-project.info/edr/05747991",
            status="found",
            edrpou="05747991",
            risk_flags=[
                ClarityRiskFlag(
                    level="medium",
                    code="tax_debt_found",
                    text="У Clarity є ознака податкового боргу.",
                )
            ],
        )
        debtors_registry_data = {
            "source": "debtors_registry",
            "checked": True,
            "found": True,
            "url": "https://erb.minjust.gov.ua/#/search-debtors",
            "searched_edrpou": "05747991",
            "items_count": 3,
            "items": [],
            "signals": ["Компанія знайдена в Єдиному реєстрі боржників"],
            "risk_flags": ["tax_debt_found", "debtor_registry_found", "multiple_debtor_records"],
            "error": None,
        }

        enriched = with_source_diagnostics(
            result,
            clarity_data,
            youcontrol_data=None,
            debtors_registry_data=debtors_registry_data,
        )

        self.assertEqual(enriched.debtors_registry_data["source"], "debtors_registry")
        self.assertEqual(enriched.sources["debtors_registry"]["found"], True)
        self.assertIn("opendatabot", enriched.sources)
        self.assertIn("clarity", enriched.sources)
        self.assertIn("youcontrol", enriched.sources)
        self.assertIn("debtors_registry", enriched.sources)
        self.assertIn("court_analysis", enriched.sources)
        risk_codes = [flag.code for flag in enriched.risk_summary.flags]
        self.assertEqual(risk_codes.count("tax_debt_found"), 1)
        self.assertIn("debtor_registry_found", risk_codes)
        self.assertIn("multiple_debtor_records", risk_codes)

    def test_debtors_registry_flags_are_shown_in_response(self):
        from app.bot import build_edrpou_response
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        debtors_registry_data = {
            "source": "debtors_registry",
            "checked": True,
            "found": True,
            "url": "https://erb.minjust.gov.ua/#/search-debtors",
            "searched_edrpou": "05747991",
            "items_count": 5,
            "items": [],
            "signals": [
                "Компанія знайдена в Єдиному реєстрі боржників",
                "Знайдено 5 записів у реєстрі боржників",
            ],
            "risk_flags": [
                "debtor_registry_found",
                "multiple_debtor_records",
                "salary_debt_enforcement_found",
                "court_fee_enforcement_found",
            ],
            "error": None,
        }

        response = build_edrpou_response(
            "05747991",
            CompanyLookupResult(
                status="found",
                edrpou="05747991",
                company_data=CompanyData(short_name='АТ "СУМСЬКЕ МНВО"', edrpou="05747991"),
            ),
            debtors_registry_data=debtors_registry_data,
        )

        self.assertIn("Компанія знайдена в Єдиному реєстрі боржників", response)
        self.assertIn("Знайдено кілька записів у Єдиному реєстрі боржників", response)
        self.assertIn("заборгованості із заробітної плати", response)
        self.assertIn("стягнення судового збору", response)
        self.assertIn("Єдиний реєстр боржників", response)

    def test_debtors_registry_budget_fine_and_court_fee_cases_are_shown_in_response(self):
        from app.bot import build_edrpou_response
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        debtors_registry_data = {
            "source": "debtors_registry",
            "checked": True,
            "found": True,
            "url": "https://erb.minjust.gov.ua/#/search-debtors",
            "searched_edrpou": "33000657",
            "items_count": 2,
            "items": [],
            "signals": [
                "Компанія знайдена в Єдиному реєстрі боржників",
                "Знайдено 2 записи у реєстрі боржників",
            ],
            "risk_flags": [
                "debtor_registry_found",
                "debt_collection_found",
                "fine_or_penalty_enforcement_found",
                "court_fee_enforcement_found",
            ],
            "error": None,
        }

        response = build_edrpou_response(
            "33000657",
            CompanyLookupResult(
                status="found",
                edrpou="33000657",
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou="33000657"),
            ),
            debtors_registry_data=debtors_registry_data,
        )

        self.assertIn("Компанія знайдена в Єдиному реєстрі боржників", response)
        self.assertIn("стягнення коштів, заборгованості або платежів до бюджету", response)
        self.assertIn("штрафів, пені або санкцій", response)
        self.assertIn("стягнення судового збору", response)
        self.assertNotIn("Податковий борг та борг ЄСВ у доступних даних не виявлено.", response)

    def test_source_snapshot_includes_tax_and_dedupes_tax_debt_risk_flags(self):
        from app.bot import with_source_diagnostics
        from app.models.clarity import ClarityData, ClarityRiskFlag
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        result = CompanyLookupResult(
            status="found",
            edrpou="05747991",
            source_url="https://opendatabot.ua/c/05747991?from=search",
            company_data=CompanyData(short_name='АТ "СУМСЬКЕ МНВО"', edrpou="05747991"),
        )
        clarity_data = ClarityData(
            source_url="https://clarity-project.info/edr/05747991",
            status="found",
            edrpou="05747991",
            risk_flags=[
                ClarityRiskFlag(
                    level="medium",
                    code="tax_debt_found",
                    text="У Clarity є ознака податкового боргу.",
                )
            ],
        )
        tax_data = {
            "source": "tax",
            "checked": True,
            "found": True,
            "searched_edrpou": "05747991",
            "tax_debt": {
                "found": True,
                "amount": 150000.0,
                "currency": "UAH",
                "details": [],
                "dataset_date": "2026-06-01",
            },
            "vat": None,
            "signals": ["Знайдено податковий борг"],
            "risk_flags": ["tax_debt_found", "large_tax_debt_found"],
            "error": None,
        }

        enriched = with_source_diagnostics(result, clarity_data, tax_data=tax_data)

        self.assertEqual(enriched.tax_data["source"], "tax")
        self.assertEqual(enriched.sources["tax"]["tax_debt"]["amount"], 150000.0)
        risk_codes = [flag.code for flag in enriched.risk_summary.flags]
        self.assertEqual(risk_codes.count("tax_debt_found"), 1)
        self.assertIn("large_tax_debt_found", risk_codes)
        tax_debt_reason = next(reason for reason in enriched.risk_summary.reasons if reason["type"] == "tax_debt_found")
        self.assertIn("tax", tax_debt_reason["sources"])

    def test_tax_debt_flags_are_shown_in_response(self):
        from app.bot import build_edrpou_response
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        tax_data = {
            "source": "tax",
            "checked": True,
            "found": True,
            "searched_edrpou": "05747991",
            "tax_debt": {
                "found": True,
                "amount": 150000.0,
                "currency": "UAH",
                "details": [],
                "dataset_date": "2026-06-01",
            },
            "vat": None,
            "signals": ["Знайдено податковий борг"],
            "risk_flags": ["tax_debt_found", "large_tax_debt_found"],
            "error": None,
        }

        response = build_edrpou_response(
            "05747991",
            CompanyLookupResult(
                status="found",
                edrpou="05747991",
                company_data=CompanyData(short_name='АТ "СУМСЬКЕ МНВО"', edrpou="05747991"),
            ),
            tax_data=tax_data,
        )

        self.assertIn("Знайдено податковий борг у доступних даних ДПС.", response)
        self.assertIn("Сума податкового боргу виглядає суттєвою", response)
        self.assertIn("ДПС / tax", response)

    def test_tax_no_debt_is_shown_in_good_section(self):
        from app.bot import build_edrpou_response
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        tax_data = {
            "source": "tax",
            "checked": True,
            "found": True,
            "searched_edrpou": "12345678",
            "tax_debt": {
                "found": False,
                "amount": 0,
                "currency": "UAH",
                "details": [],
                "dataset_date": None,
            },
            "vat": None,
            "signals": [],
            "risk_flags": [],
            "error": None,
        }

        response = build_edrpou_response(
            "12345678",
            CompanyLookupResult(
                status="found",
                edrpou="12345678",
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou="12345678"),
            ),
            tax_data=tax_data,
        )

        reason_block = response.split("Причини оцінки:", 1)[1].split("Загальний ризик:", 1)[0]
        self.assertIn("Податковий борг та борг ЄСВ у доступних даних не виявлено.", reason_block)

    def test_tax_source_unavailable_is_shown_only_in_limitations(self):
        from app.bot import build_edrpou_response, with_source_diagnostics
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        result = CompanyLookupResult(
            status="found",
            edrpou="12345678",
            company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou="12345678"),
        )
        tax_data = {
            "source": "tax",
            "checked": False,
            "found": False,
            "searched_edrpou": "12345678",
            "tax_debt": None,
            "vat": None,
            "signals": [],
            "risk_flags": ["tax_source_unavailable"],
            "error": "tax_source_unavailable",
        }

        enriched = with_source_diagnostics(result, None, tax_data=tax_data)
        response = build_edrpou_response("12345678", result, tax_data=tax_data)

        self.assertNotIn("tax_source_unavailable", [reason["type"] for reason in enriched.risk_summary.reasons])
        reason_block = response.split("Причини оцінки:", 1)[1].split("Загальний ризик:", 1)[0]
        self.assertNotIn("ДПС / податкові відкриті дані не вдалося перевірити автоматично.", response)
        self.assertNotIn("tax_source_unavailable", reason_block)

    def test_source_snapshot_includes_domain_reputation_and_dedupes_risk_flags(self):
        from app.bot import with_source_diagnostics
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        result = CompanyLookupResult(
            status="found",
            edrpou="05747991",
            company_data=CompanyData(short_name='АТ "СУМСЬКЕ НВО"', edrpou="05747991"),
        )
        domain_reputation_data = {
            "source": "domain_reputation",
            "checked": True,
            "found": True,
            "url": "https://snvo.ua",
            "domain": "snvo.ua",
            "http": {"status_code": 200, "final_url": "https://snvo.ua/", "redirects": [], "title": "АТ Сумське НВО", "is_empty": False},
            "ssl": {"present": True, "not_before": None, "not_after": None, "issuer": None},
            "dns": {"found": True, "a_records": ["192.0.2.10"], "mx_records": []},
            "contacts": {
                "emails": ["office@gmail.com"],
                "phones": [],
                "edrpou_found_on_page": False,
                "company_name_found_on_page": True,
                "address_found_on_page": False,
            },
            "signals": [],
            "risk_flags": ["free_email_used", "free_email_used", "company_edrpou_not_found_on_website"],
            "error": None,
        }

        enriched = with_source_diagnostics(result, None, domain_reputation_data=domain_reputation_data)

        self.assertEqual(enriched.domain_reputation_data["source"], "domain_reputation")
        self.assertEqual(enriched.sources["domain_reputation"]["domain"], "snvo.ua")
        risk_codes = [flag.code for flag in enriched.risk_summary.flags]
        self.assertEqual(risk_codes.count("free_email_used"), 1)
        self.assertIn("company_edrpou_not_found_on_website", risk_codes)

    def test_domain_reputation_flags_are_shown_in_website_block(self):
        from app.bot import build_edrpou_response
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        domain_reputation_data = {
            "source": "domain_reputation",
            "checked": True,
            "found": True,
            "url": "https://snvo.ua",
            "domain": "snvo.ua",
            "http": {"status_code": 200, "final_url": "https://snvo.ua/", "redirects": [], "title": "АТ Сумське НВО", "is_empty": False},
            "ssl": {"present": True, "not_before": None, "not_after": None, "issuer": None},
            "dns": {"found": True, "a_records": ["192.0.2.10"], "mx_records": []},
            "contacts": {
                "emails": ["office@gmail.com"],
                "phones": [],
                "edrpou_found_on_page": False,
                "company_name_found_on_page": True,
                "address_found_on_page": False,
            },
            "signals": [],
            "risk_flags": ["free_email_used", "company_edrpou_not_found_on_website"],
            "error": None,
        }

        response = build_edrpou_response(
            "05747991",
            CompanyLookupResult(
                status="found",
                edrpou="05747991",
                company_data=CompanyData(short_name='АТ "СУМСЬКЕ НВО"', edrpou="05747991"),
            ),
            domain_reputation_data=domain_reputation_data,
        )

        self.assertIn("Причини оцінки:", response)
        self.assertIn("не знайдено ЄДРПОУ компанії", response)
        self.assertIn("безкоштовні email-адреси", response)

    def test_website_unavailable_is_shown_without_fraud_claim(self):
        from app.bot import build_edrpou_response
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        domain_reputation_data = {
            "source": "domain_reputation",
            "checked": True,
            "found": False,
            "url": "https://example.ua",
            "domain": "example.ua",
            "http": {"status_code": None, "final_url": None, "redirects": []},
            "ssl": None,
            "dns": None,
            "contacts": None,
            "signals": ["Сайт постачальника не вдалося відкрити автоматично"],
            "risk_flags": ["website_unavailable"],
            "error": "website_unavailable",
        }

        response = build_edrpou_response(
            "12345678",
            CompanyLookupResult(
                status="found",
                edrpou="12345678",
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou="12345678"),
            ),
            domain_reputation_data=domain_reputation_data,
        )

        self.assertIn("Сайт не вдалося перевірити автоматично", response)
        self.assertIn("Це не є доказом ризику", response)
        self.assertNotIn("компанія шахрайська", response.lower())

    def test_website_not_provided_does_not_show_website_block(self):
        from app.bot import build_edrpou_response
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        response = build_edrpou_response(
            "12345678",
            CompanyLookupResult(
                status="found",
                edrpou="12345678",
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou="12345678"),
            ),
            domain_reputation_data={
                "source": "domain_reputation",
                "checked": False,
                "found": False,
                "url": None,
                "domain": None,
                "signals": [],
                "risk_flags": [],
                "error": "website_not_provided",
            },
        )

        self.assertNotIn("Перевірка сайту:", response)

    def test_large_court_cases_count_is_not_shown_as_raw_number_in_normal_response(self):
        from app.bot import build_edrpou_response
        from app.models.company_lookup import CompanyData, CompanyLookupResult, CourtData, RiskInput

        response = build_edrpou_response(
            "12345678",
            CompanyLookupResult(
                status="found",
                edrpou="12345678",
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou="12345678"),
                court_data=CourtData(has_court_mentions=True, total_cases_found=250),
                risk_input=RiskInput(has_court_mentions=True, total_court_cases_found=250),
            ),
        )

        self.assertIn("Судові документи: 250. Потрібна ручна перевірка змісту справ.", response)
        self.assertIn("Знайдено судових документів: 250.", response)

    def test_court_mentions_count_12162_is_not_shown_raw_in_normal_response(self):
        from app.bot import build_edrpou_response
        from app.models.company_lookup import CompanyData, CompanyLookupResult, CourtData, RiskInput

        response = build_edrpou_response(
            "05747991",
            CompanyLookupResult(
                status="found",
                edrpou="05747991",
                company_data=CompanyData(short_name='АТ "СУМСЬКЕ МНВО"', edrpou="05747991"),
                court_data=CourtData(
                    has_court_mentions=True,
                    court_mentions_count=12162,
                ),
                risk_input=RiskInput(
                    has_court_mentions=True,
                    court_mentions_count=12162,
                ),
            ),
        )

        self.assertIn("Судові документи: 12 162. Потрібна ручна перевірка змісту справ.", response)
        self.assertIn("Знайдено судових документів: 12 162.", response)

    def test_court_mentions_count_alone_does_not_make_risk_critical(self):
        from app.bot import with_source_diagnostics
        from app.models.company_lookup import CompanyData, CompanyLookupResult, CourtData, RiskInput

        enriched = with_source_diagnostics(
            CompanyLookupResult(
                status="found",
                edrpou="05747991",
                company_data=CompanyData(short_name='АТ "СУМСЬКЕ МНВО"', edrpou="05747991"),
                court_data=CourtData(
                    has_court_mentions=True,
                    court_mentions_count=12162,
                ),
                risk_input=RiskInput(
                    has_court_mentions=True,
                    court_mentions_count=12162,
                ),
            ),
            clarity_data=None,
        )

        self.assertNotEqual(enriched.risk_summary.level, "critical")
        self.assertEqual(
            [reason["type"] for reason in enriched.risk_summary.reasons],
            ["court_cases_found", "many_court_mentions_found", "very_many_court_mentions_found"],
        )

    def test_bankruptcy_plus_enforcement_can_make_risk_critical(self):
        from app.bot import with_source_diagnostics
        from app.models.clarity import ClarityData, ClarityRiskFlag
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        enriched = with_source_diagnostics(
            CompanyLookupResult(
                status="found",
                edrpou="12345678",
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou="12345678"),
            ),
            ClarityData(
                source_url="https://clarity-project.info/edr/12345678",
                status="found",
                edrpou="12345678",
                risk_flags=[
                    ClarityRiskFlag(level="high", code="bankruptcy_found", text="Є ознаки банкрутства."),
                    ClarityRiskFlag(level="medium", code="enforcement_found", text="Є виконавчі провадження."),
                ],
            ),
        )

        self.assertEqual(enriched.risk_summary.level, "critical")
        self.assertIn("bankruptcy_found", [flag.code for flag in enriched.risk_summary.flags])
        self.assertIn("enforcement_found", [flag.code for flag in enriched.risk_summary.flags])

    def test_opendatabot_bankruptcy_flag_makes_report_high_risk(self):
        from app.bot import build_edrpou_response, with_source_diagnostics
        from app.models.company_lookup import CompanyData, CompanyLookupResult, CourtData

        result = CompanyLookupResult(
            status="found",
            edrpou="25102871",
            company_data=CompanyData(
                short_name="ТОВ «УКРІНВЕСТ»",
                edrpou="25102871",
                status="припинено",
                registration_date="27.08.1997",
            ),
            court_data=CourtData(risk_flags=["bankruptcy_found", "company_in_termination"]),
        )

        enriched = with_source_diagnostics(result, clarity_data=None)
        response = build_edrpou_response("25102871", result)

        risk_codes = [flag.code for flag in enriched.risk_summary.flags]
        self.assertIn("bankruptcy_found", risk_codes)
        self.assertEqual(enriched.risk_summary.level, "critical")
        self.assertIn("Загальний ризик: критичний", response)
        self.assertIn("банкрут", response.lower())
        self.assertNotIn("✅ Ознак банкрутства або припинення", response)

    def test_large_enforcement_count_is_not_shown_as_raw_number_in_normal_response(self):
        from app.bot import build_edrpou_response
        from app.models.clarity import ClarityData, ClaritySignals
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        response = build_edrpou_response(
            "12345678",
            CompanyLookupResult(
                status="found",
                edrpou="12345678",
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou="12345678"),
            ),
            ClarityData(
                source_url="https://clarity-project.info/edr/12345678",
                status="found",
                edrpou="12345678",
                signals=ClaritySignals(enforcement_proceedings_count=150),
            ),
        )

        self.assertIn("велика кількість записів, пов’язаних з виконавчими провадженнями", response)
        self.assertNotIn("Виконавчі провадження: 150", response)

    def test_source_unavailable_is_shown_only_in_limitations(self):
        from app.bot import build_edrpou_response, with_source_diagnostics
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        result = CompanyLookupResult(
            status="found",
            edrpou="12345678",
            company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou="12345678"),
        )
        debtors_registry_data = {
            "source": "debtors_registry",
            "checked": False,
            "found": False,
            "url": "https://erb.minjust.gov.ua/#/search-debtors",
            "searched_edrpou": "12345678",
            "items_count": 0,
            "items": [],
            "signals": [],
            "risk_flags": ["source_unavailable"],
            "error": "source_unavailable",
        }

        enriched = with_source_diagnostics(result, None, None, debtors_registry_data)
        response = build_edrpou_response("12345678", result, debtors_registry_data=debtors_registry_data)

        self.assertNotIn("source_unavailable", [reason["type"] for reason in enriched.risk_summary.reasons])
        reason_block = response.split("Причини оцінки:", 1)[1].split("Загальний ризик:", 1)[0]
        self.assertNotIn("Обмеження перевірки:", response)
        self.assertNotIn("недоступ", reason_block.lower())

    def test_company_status_mismatch_is_added_for_registered_vs_termination_sources(self):
        from app.bot import with_source_diagnostics
        from app.models.clarity import ClarityCompany, ClarityData
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        enriched = with_source_diagnostics(
            CompanyLookupResult(
                status="found",
                edrpou="12345678",
                company_data=CompanyData(
                    short_name="ТОВ «ПРИКЛАД»",
                    edrpou="12345678",
                    status="Зареєстровано",
                ),
            ),
            ClarityData(
                source_url="https://clarity-project.info/edr/12345678",
                status="found",
                edrpou="12345678",
                company=ClarityCompany(status="в стані припинення"),
            ),
        )

        risk_codes = [flag.code for flag in enriched.risk_summary.flags]
        self.assertIn("company_status_mismatch", risk_codes)
        self.assertNotIn("company_in_termination", risk_codes)

    def test_conflicting_ukrposhta_status_is_shown_as_manual_review_not_termination(self):
        from app.bot import build_edrpou_response
        from app.models.clarity import ClarityCompany, ClarityData
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        response = build_edrpou_response(
            "21560045",
            CompanyLookupResult(
                status="found",
                edrpou="21560045",
                company_data=CompanyData(
                    short_name="АТ «УКРПОШТА»",
                    edrpou="21560045",
                    status="В стані припинення",
                ),
            ),
            ClarityData(
                source_url="https://clarity-project.info/edr/21560045",
                status="found",
                edrpou="21560045",
                company=ClarityCompany(status="Зареєстровано"),
            ),
        )

        self.assertIn("Статус: потребує ручної перевірки статусу", response)
        self.assertNotIn("Статус: В стані припинення", response)
        self.assertNotIn("Є ознаки процедури припинення компанії.", response)

    def test_negative_termination_status_does_not_add_termination_risk(self):
        from app.bot import with_source_diagnostics
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        enriched = with_source_diagnostics(
            CompanyLookupResult(
                status="found",
                edrpou="12345678",
                company_data=CompanyData(
                    short_name="ТОВ «ПРИКЛАД»",
                    edrpou="12345678",
                    status="не перебуває в процесі припинення",
                ),
            ),
            clarity_data=None,
        )

        risk_codes = [flag.code for flag in enriched.risk_summary.flags]
        self.assertNotIn("company_in_termination", risk_codes)
        self.assertNotIn("company_status_mismatch", risk_codes)

    def test_registered_ukrposhta_status_does_not_add_termination_risk(self):
        from app.bot import with_source_diagnostics
        from app.models.clarity import ClarityCompany, ClarityData
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        enriched = with_source_diagnostics(
            CompanyLookupResult(
                status="found",
                edrpou="21560045",
                company_data=CompanyData(
                    short_name="АТ «УКРПОШТА»",
                    edrpou="21560045",
                    status="Зареєстровано",
                ),
            ),
            ClarityData(
                source_url="https://clarity-project.info/edr/21560045",
                status="found",
                edrpou="21560045",
                company=ClarityCompany(status="Зареєстровано"),
            ),
        )

        risk_codes = [flag.code for flag in enriched.risk_summary.flags]
        self.assertNotIn("company_in_termination", risk_codes)
        self.assertNotIn("company_status_mismatch", risk_codes)

    def test_land_use_termination_phrase_does_not_add_company_termination_risk(self):
        from app.bot import with_source_diagnostics
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        enriched = with_source_diagnostics(
            CompanyLookupResult(
                status="found",
                edrpou="12345678",
                company_data=CompanyData(
                    short_name="ТОВ «ПРИКЛАД»",
                    edrpou="12345678",
                    status="Зареєстровано; рішення про припинення права користування землею",
                ),
            ),
            clarity_data=None,
        )

        risk_codes = [flag.code for flag in enriched.risk_summary.flags]
        self.assertNotIn("company_in_termination", risk_codes)

    def test_historical_reorganization_phrase_does_not_add_company_termination_risk(self):
        from app.bot import with_source_diagnostics
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        enriched = with_source_diagnostics(
            CompanyLookupResult(
                status="found",
                edrpou="12345678",
                company_data=CompanyData(
                    short_name="ТОВ «ПРИКЛАД»",
                    edrpou="12345678",
                    status="Зареєстровано; історична подія: припинення шляхом перетворення у 2017 році",
                ),
            ),
            clarity_data=None,
        )

        risk_codes = [flag.code for flag in enriched.risk_summary.flags]
        self.assertNotIn("company_in_termination", risk_codes)

    def test_conflicting_bankruptcy_sources_show_conflicting_data_block(self):
        from app.bot import build_edrpou_response, with_source_diagnostics
        from app.models.clarity import ClarityData, ClarityRiskFlag
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        result = CompanyLookupResult(
            status="found",
            edrpou="12345678",
            company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou="12345678"),
        )
        clarity_data = ClarityData(
            source_url="https://clarity-project.info/edr/12345678",
            status="found",
            edrpou="12345678",
            risk_flags=[
                ClarityRiskFlag(level="high", code="bankruptcy_found", text="Знайдено записи банкрутства.")
            ],
        )
        youcontrol_data = {
            "source": "youcontrol",
            "found": True,
            "url": "https://youcontrol.com.ua/catalog/company_details/12345678/",
            "company": {"name": "ТОВ «ПРИКЛАД»", "edrpou": "12345678", "status": "Зареєстровано"},
            "signals": ["Банкрутство: не виявлено"],
            "risk_flags": [],
            "error": None,
        }

        enriched = with_source_diagnostics(result, clarity_data, youcontrol_data=youcontrol_data)
        response = build_edrpou_response("12345678", result, clarity_data, youcontrol_data=youcontrol_data)

        self.assertEqual(enriched.risk_summary.level, "manual_review")
        self.assertTrue(enriched.risk_summary.manual_review_required)
        self.assertLess(enriched.risk_summary.score, 100)
        self.assertIn("Є суперечливі дані щодо банкрутства", response)
        self.assertIn("банкрут", response.lower())
        self.assertIn("потрібна ручна перевірка", response.lower())

    def test_critical_risk_response_has_top_reasons(self):
        from app.bot import build_edrpou_response
        from app.models.clarity import ClarityData, ClarityRiskFlag
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        response = build_edrpou_response(
            "12345678",
            CompanyLookupResult(
                status="found",
                edrpou="12345678",
                company_data=CompanyData(
                    short_name="ТОВ «ПРИКЛАД»",
                    edrpou="12345678",
                    status="в стані припинення",
                ),
            ),
            ClarityData(
                source_url="https://clarity-project.info/edr/12345678",
                status="found",
                edrpou="12345678",
                risk_flags=[
                    ClarityRiskFlag(level="high", code="bankruptcy_found", text="Є ознаки банкрутства."),
                    ClarityRiskFlag(level="medium", code="enforcement_found", text="Є виконавчі провадження."),
                    ClarityRiskFlag(level="medium", code="tax_debt_found", text="Є податковий борг."),
                ],
            ),
        )

        self.assertIn("Причини оцінки:", response)
        why_block = response.split("Причини оцінки:", 1)[1].split("Загальний ризик:", 1)[0].lower()
        self.assertIn("банкрут", why_block)
        self.assertIn("припинення", why_block)
        self.assertIn("виконавч", why_block)

    def test_not_found_result_is_formatted(self):
        from app.bot import build_edrpou_response
        from app.models.company_lookup import CompanyLookupResult

        response = build_edrpou_response(
            "12345678",
            CompanyLookupResult(
                status="not_found",
                edrpou="12345678",
                source_url="https://opendatabot.ua/c/12345678?from=search",
            ),
        )

        self.assertEqual(
            response,
            "ЄДРПОУ має правильний формат, але компанію з таким кодом не знайдено у джерелі перевірки.",
        )

    def test_source_error_result_is_formatted(self):
        from app.bot import build_edrpou_response
        from app.models.company_lookup import CompanyLookupResult

        response = build_edrpou_response(
            "12345678",
            CompanyLookupResult(
                status="source_error",
                edrpou="12345678",
                source_url="https://opendatabot.ua/c/12345678?from=search",
            ),
        )

        self.assertEqual(
            response,
            "Не вдалося отримати дані з джерела. Спробуйте пізніше або перевірте ЄДРПОУ вручну.",
        )

    def test_main_keyboard_contains_stop_and_info_buttons(self):
        from app.bot import INFO_BUTTON_TEXT, STOP_BUTTON_TEXT, build_main_keyboard

        keyboard = build_main_keyboard()

        self.assertEqual(STOP_BUTTON_TEXT, "🛑 Зупинити")
        self.assertEqual(INFO_BUTTON_TEXT, "ℹ️ Як працює")
        self.assertEqual(keyboard.keyboard[0][0].text, STOP_BUTTON_TEXT)
        self.assertEqual(keyboard.keyboard[0][1].text, INFO_BUTTON_TEXT)
        self.assertTrue(keyboard.resize_keyboard)

    def test_info_text_matches_requested_copy(self):
        from app.bot import INFO_TEXT

        self.assertEqual(
            INFO_TEXT,
            "RiskUA — бот для швидкої перевірки компаній за ЄДРПОУ перед оплатою, договором або співпрацею.\n\n"
            "Бот збирає базову інформацію з відкритих джерел, визначає можливі ризикові ознаки та за допомогою AI формує короткий зрозумілий висновок.\n\n"
            "Як користуватись:\n"
            "1. Надішліть ЄДРПОУ компанії у форматі 8 цифр.\n"
            "2. Дочекайтесь завершення аналізу.\n"
            "3. Отримайте базові дані, ризикові ознаки та рекомендацію.\n\n"
            "⏳ Аналіз може зайняти до 1 хвилини.",
        )


class EdrpouHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_handler_sends_main_keyboard(self):
        from app.bot import INFO_BUTTON_TEXT, START_TEXT, STOP_BUTTON_TEXT, start_handler

        message = FakeMessage("/start")

        await start_handler(message)

        self.assertEqual(message.answers, [START_TEXT])
        keyboard = message.answer_kwargs[0]["reply_markup"]
        self.assertEqual(keyboard.keyboard[0][0].text, STOP_BUTTON_TEXT)
        self.assertEqual(keyboard.keyboard[0][1].text, INFO_BUTTON_TEXT)

    async def test_info_handler_sends_info_text(self):
        from app.bot import INFO_TEXT, info_handler

        message = FakeMessage("/info")

        await info_handler(message)

        self.assertEqual(message.answers, [INFO_TEXT])

    async def test_stop_handler_removes_keyboard(self):
        from aiogram.types import ReplyKeyboardRemove

        from app.bot import STOP_TEXT, stop_handler

        message = FakeMessage("/stop")

        await stop_handler(message)

        self.assertEqual(message.answers, [STOP_TEXT])
        self.assertIsInstance(message.answer_kwargs[0]["reply_markup"], ReplyKeyboardRemove)

    async def test_valid_edrpou_sends_search_message_before_result(self):
        from app.bot import EDRPOU_SEARCH_TEXT, edrpou_handler
        from app.models.clarity import ClarityData, ClaritySignals, ClarityTax
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        message = FakeMessage("12345678", user_id=777)
        saved_results: list[tuple[str, int | None]] = []

        def fake_lookup(edrpou: str) -> CompanyLookupResult:
            return CompanyLookupResult(
                status="found",
                edrpou=edrpou,
                source_url="https://opendatabot.ua/c/12345678?from=search",
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou=edrpou),
            )

        def fake_clarity_lookup(edrpou: str) -> ClarityData:
            return ClarityData(
                source_url="https://clarity-project.info/edr/12345678",
                status="found",
                edrpou=edrpou,
                tax=ClarityTax(tax_debt=False, esv_debt=False),
                signals=ClaritySignals(bankruptcy_count=0, enforcement_proceedings_count=1),
            )

        await edrpou_handler(
            message,
            lookup=fake_lookup,
            clarity_lookup=fake_clarity_lookup,
            youcontrol_lookup=no_youcontrol_lookup,
            debtors_lookup=no_debtors_lookup,
            tax_lookup=no_tax_lookup,
            domain_reputation_lookup=no_domain_reputation_lookup,
            contacts_lookup=no_contacts_lookup,
            save=lambda result, user_id: saved_results.append((result.edrpou, user_id)),
        )

        self.assertEqual(message.answers[0], EDRPOU_SEARCH_TEXT)
        self.assertIn("ЄДРПОУ: 12345678", message.answers[1])
        self.assertNotIn("Додаткові сигнали Clarity:", message.answers[1])
        self.assertIn("Ознак банкрутства або припинення", message.answers[1])
        self.assertIn("Податковий борг та борг ЄСВ", message.answers[1])
        self.assertNotIn("Рекомендація:", message.answers[1])
        self.assertEqual(saved_results, [("12345678", 777)])

    async def test_valid_edrpou_runs_main_and_clarity_lookups_in_parallel(self):
        from app.bot import edrpou_handler
        from app.models.clarity import ClarityData, ClaritySignals, ClarityTax
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        message = FakeMessage("12345678", user_id=777)
        lookup_started = Event()
        clarity_started = Event()
        lookup_saw_clarity_started: list[bool] = []

        def fake_lookup(edrpou: str) -> CompanyLookupResult:
            lookup_started.set()
            lookup_saw_clarity_started.append(clarity_started.wait(0.1))
            return CompanyLookupResult(
                status="found",
                edrpou=edrpou,
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou=edrpou),
            )

        def fake_clarity_lookup(edrpou: str) -> ClarityData:
            clarity_started.set()
            lookup_started.wait(0.1)
            return ClarityData(
                source_url="https://clarity-project.info/edr/12345678",
                status="found",
                edrpou=edrpou,
                tax=ClarityTax(tax_debt=False, esv_debt=False),
                signals=ClaritySignals(bankruptcy_count=0),
            )

        await edrpou_handler(
            message,
            lookup=fake_lookup,
            clarity_lookup=fake_clarity_lookup,
            youcontrol_lookup=no_youcontrol_lookup,
            debtors_lookup=no_debtors_lookup,
            tax_lookup=no_tax_lookup,
            domain_reputation_lookup=no_domain_reputation_lookup,
            contacts_lookup=no_contacts_lookup,
            save=lambda result, user_id: None,
            analysis_timeout=1,
        )

        self.assertEqual(lookup_saw_clarity_started, [True])
        self.assertIn("Джерела: Opendatabot, Clarity", message.answers[1])

    async def test_edrpou_handler_shows_prozorro_from_injected_lookup(self):
        from app.bot import edrpou_handler
        from app.models.clarity import ClarityData
        from app.models.company_lookup import (
            CompanyData,
            CompanyLookupResult,
            ProzorroAnalysis,
            ProzorroProcurement,
            ProzorroStats,
        )

        message = FakeMessage("12345678", user_id=777)
        saved_results: list[CompanyLookupResult] = []

        def found_lookup(edrpou: str) -> CompanyLookupResult:
            return CompanyLookupResult(
                status="found",
                edrpou=edrpou,
                company_data=CompanyData(short_name='ТОВ "ПРОЗОРО"', edrpou=edrpou),
            )

        def found_clarity_lookup(edrpou: str) -> ClarityData:
            return ClarityData(source_url=f"https://clarity-project.info/edr/{edrpou}", status="found", edrpou=edrpou)

        def prepared_prozorro_lookup(edrpou: str) -> ProzorroAnalysis:
            return ProzorroAnalysis(
                status="found",
                stats=ProzorroStats(
                    procurements_count=2,
                    participations_count=2,
                    wins_count=1,
                    contracts_count=1,
                    terminated_contracts_count=0,
                    last_participation_date="2026-01-10",
                ),
                procurements=[ProzorroProcurement(procurement_id="UA-HANDLER-1", participated=True)],
                summary="Prozorro: участей 2, перемог 1, договорів 1, розірвань 0.",
                info_notes=["Сам факт участі не є ризиком."],
            )

        await edrpou_handler(
            message,
            lookup=found_lookup,
            clarity_lookup=found_clarity_lookup,
            youcontrol_lookup=no_youcontrol_lookup,
            debtors_lookup=no_debtors_lookup,
            tax_lookup=no_tax_lookup,
            domain_reputation_lookup=no_domain_reputation_lookup,
            contacts_lookup=no_contacts_lookup,
            prozorro_lookup=prepared_prozorro_lookup,
            save=lambda result, user_id: saved_results.append(result),
        )

        self.assertIn("Prozorro:", message.answers[1])
        self.assertIn("Участей: 2", message.answers[1])
        self.assertIn("Перемог: 1", message.answers[1])
        self.assertIn("Остання участь: 2026-01-10", message.answers[1])
        self.assertIn("Джерела: Opendatabot, Clarity, Prozorro", message.answers[1])
        self.assertEqual(saved_results[0].prozorro_analysis.status, "found")

    async def test_edrpou_handler_keeps_score_when_prozorro_source_errors(self):
        from app.bot import edrpou_handler
        from app.models.clarity import ClarityData
        from app.models.company_lookup import CompanyData, CompanyLookupResult, ProzorroAnalysis

        message = FakeMessage("12345678", user_id=777)
        saved_results: list[CompanyLookupResult] = []

        def found_lookup(edrpou: str) -> CompanyLookupResult:
            return CompanyLookupResult(
                status="found",
                edrpou=edrpou,
                company_data=CompanyData(short_name='ТОВ "ПРОЗОРО"', edrpou=edrpou),
            )

        def found_clarity_lookup(edrpou: str) -> ClarityData:
            return ClarityData(source_url=f"https://clarity-project.info/edr/{edrpou}", status="found", edrpou=edrpou)

        def failed_prozorro_lookup(edrpou: str) -> ProzorroAnalysis:
            return ProzorroAnalysis(
                status="source_error",
                error="cache_unavailable",
                risk_flags=[{"type": "multiple_prozorro_terminations_found"}],
            )

        await edrpou_handler(
            message,
            lookup=found_lookup,
            clarity_lookup=found_clarity_lookup,
            youcontrol_lookup=no_youcontrol_lookup,
            debtors_lookup=no_debtors_lookup,
            tax_lookup=no_tax_lookup,
            domain_reputation_lookup=no_domain_reputation_lookup,
            contacts_lookup=no_contacts_lookup,
            prozorro_lookup=failed_prozorro_lookup,
            save=lambda result, user_id: saved_results.append(result),
        )

        self.assertEqual(saved_results[0].risk_summary.score, 5)
        self.assertNotIn(
            "multiple_prozorro_terminations_found",
            [reason["type"] for reason in saved_results[0].risk_summary.reasons],
        )

    async def test_run_source_lookups_attaches_prozorro_analysis(self):
        from app.bot import run_source_lookups
        from app.models.clarity import ClarityData
        from app.models.company_lookup import CompanyData, CompanyLookupResult, ProzorroAnalysis, ProzorroStats

        def found_lookup(edrpou: str) -> CompanyLookupResult:
            return CompanyLookupResult(
                status="found",
                edrpou=edrpou,
                company_data=CompanyData(short_name='ТОВ "ПРОЗОРО"', edrpou=edrpou),
            )

        def found_clarity_lookup(edrpou: str) -> ClarityData:
            return ClarityData(source_url=f"https://clarity-project.info/edr/{edrpou}", status="found", edrpou=edrpou)

        def prepared_prozorro_lookup(edrpou: str) -> ProzorroAnalysis:
            return ProzorroAnalysis(status="found", stats=ProzorroStats(procurements_count=3))

        result, *_ = await run_source_lookups(
            "12345678",
            found_lookup,
            found_clarity_lookup,
            no_youcontrol_lookup,
            no_debtors_lookup,
            no_tax_lookup,
            no_domain_reputation_lookup,
            no_contacts_lookup,
            analysis_timeout=1,
            prozorro_lookup=prepared_prozorro_lookup,
        )

        self.assertEqual(result.prozorro_analysis.status, "found")
        self.assertEqual(result.prozorro_analysis.stats.procurements_count, 3)

    async def test_run_source_lookups_uses_one_shared_timeout_budget(self):
        from app.bot import run_source_lookups
        from app.models.clarity import ClarityData
        from app.models.company_lookup import CompanyData, CompanyLookupResult, ProzorroAnalysis

        asyncio_module = __import__("asyncio")

        def found_lookup(edrpou: str) -> CompanyLookupResult:
            return CompanyLookupResult(
                status="found",
                edrpou=edrpou,
                company_data=CompanyData(short_name='ТОВ "ПРИКЛАД"', edrpou=edrpou),
            )

        def found_clarity_lookup(edrpou: str) -> ClarityData:
            return ClarityData(source_url=f"https://clarity-project.info/edr/{edrpou}", status="found", edrpou=edrpou)

        async def slow_contacts_lookup(edrpou: str, company_context: dict | None = None) -> dict:
            await asyncio_module.sleep(0.2)
            return {
                "website": {"value": "https://slow.example", "confidence": "high", "sources": [], "evidence": []},
                "source_statuses": {"test": "found"},
            }

        *_, contacts_summary = await run_source_lookups(
            "12345678",
            found_lookup,
            found_clarity_lookup,
            no_youcontrol_lookup,
            no_debtors_lookup,
            no_tax_lookup,
            no_domain_reputation_lookup,
            slow_contacts_lookup,
            analysis_timeout=0.05,
            prozorro_lookup=lambda edrpou: ProzorroAnalysis(status="not_found"),
        )

        self.assertIsNone(contacts_summary["website"]["value"])
        self.assertIn("checked_sources", contacts_summary)

    async def test_edrpou_handler_preserves_positional_save_argument(self):
        from app.bot import edrpou_handler
        from app.models.clarity import ClarityData
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        message = FakeMessage("12345678", user_id=777)
        saved_results: list[CompanyLookupResult] = []

        def found_lookup(edrpou: str) -> CompanyLookupResult:
            return CompanyLookupResult(
                status="found",
                edrpou=edrpou,
                company_data=CompanyData(short_name='ТОВ "ПРОЗОРО"', edrpou=edrpou),
            )

        def found_clarity_lookup(edrpou: str) -> ClarityData:
            return ClarityData(source_url=f"https://clarity-project.info/edr/{edrpou}", status="found", edrpou=edrpou)

        await edrpou_handler(
            message,
            found_lookup,
            found_clarity_lookup,
            no_youcontrol_lookup,
            no_debtors_lookup,
            no_tax_lookup,
            no_domain_reputation_lookup,
            no_contacts_lookup,
            lambda result, user_id: saved_results.append(result),
            1,
        )

        self.assertEqual(len(saved_results), 1)
        self.assertEqual(saved_results[0].edrpou, "12345678")
        self.assertIsNotNone(saved_results[0].prozorro_analysis)
        self.assertEqual(saved_results[0].prozorro_analysis.status, "not_found")

    async def test_debug_handler_preserves_positional_analysis_timeout_argument(self):
        from app.bot import debug_handler
        from app.models.clarity import ClarityData
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        message = FakeMessage("/debug 12345678")
        release_slow_lookup = Event()

        def found_lookup(edrpou: str) -> CompanyLookupResult:
            release_slow_lookup.wait(0.05)
            return CompanyLookupResult(
                status="found",
                edrpou=edrpou,
                company_data=CompanyData(short_name='ТОВ "ПРОЗОРО"', edrpou=edrpou),
            )

        def found_clarity_lookup(edrpou: str) -> ClarityData:
            return ClarityData(source_url=f"https://clarity-project.info/edr/{edrpou}", status="found", edrpou=edrpou)

        await debug_handler(
            message,
            found_lookup,
            found_clarity_lookup,
            no_youcontrol_lookup,
            no_debtors_lookup,
            no_tax_lookup,
            no_domain_reputation_lookup,
            no_contacts_lookup,
            0.01,
        )
        release_slow_lookup.set()

        self.assertEqual(len(message.answers), 1)
        self.assertIn('"edrpou": "12345678"', message.answers[0])
        self.assertIn("opendatabot", json.loads(message.answers[0])["sources_unavailable"])

    async def test_valid_edrpou_uses_opendatabot_result_when_clarity_times_out(self):
        from app.bot import edrpou_handler
        from app.models.clarity import ClarityData, ClaritySignals, ClarityTax
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        message = FakeMessage("12345678", user_id=777)
        release_slow_clarity = Event()

        def fake_lookup(edrpou: str) -> CompanyLookupResult:
            return CompanyLookupResult(
                status="found",
                edrpou=edrpou,
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou=edrpou),
            )

        def slow_clarity_lookup(edrpou: str) -> ClarityData:
            release_slow_clarity.wait(0.2)
            return ClarityData(
                source_url="https://clarity-project.info/edr/12345678",
                status="found",
                edrpou=edrpou,
                tax=ClarityTax(tax_debt=False, esv_debt=False),
                signals=ClaritySignals(bankruptcy_count=0),
            )

        await edrpou_handler(
            message,
            lookup=fake_lookup,
            clarity_lookup=slow_clarity_lookup,
            youcontrol_lookup=no_youcontrol_lookup,
            debtors_lookup=no_debtors_lookup,
            tax_lookup=no_tax_lookup,
            domain_reputation_lookup=no_domain_reputation_lookup,
            contacts_lookup=no_contacts_lookup,
            save=lambda result, user_id: None,
            analysis_timeout=0.01,
        )
        release_slow_clarity.set()

        self.assertIn("ТОВ «ПРИКЛАД»", message.answers[1])
        self.assertIn("Джерело: Opendatabot", message.answers[1])
        self.assertNotIn("Додаткові сигнали Clarity:", message.answers[1])
        self.assertNotIn("Clarity не встигла відповісти", message.answers[1])
        self.assertNotIn("Обмеження перевірки:", message.answers[1])

    async def test_saved_result_contains_short_source_diagnostics(self):
        from app.bot import edrpou_handler
        from app.models.clarity import ClarityData
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        message = FakeMessage("12345678", user_id=777)
        saved_results: list[CompanyLookupResult] = []

        def partial_lookup(edrpou: str) -> CompanyLookupResult:
            return CompanyLookupResult(
                status="partial",
                edrpou=edrpou,
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou=edrpou),
                parse_warnings=["Не знайдено фінансову таблицю"],
            )

        def failed_clarity_lookup(edrpou: str) -> ClarityData:
            return ClarityData(
                source_url="https://clarity-project.info/edr/12345678",
                status="source_error",
                edrpou=edrpou,
                error="analysis_timeout",
            )

        await edrpou_handler(
            message,
            lookup=partial_lookup,
            clarity_lookup=failed_clarity_lookup,
            youcontrol_lookup=no_youcontrol_lookup,
            debtors_lookup=no_debtors_lookup,
            tax_lookup=no_tax_lookup,
            domain_reputation_lookup=no_domain_reputation_lookup,
            contacts_lookup=no_contacts_lookup,
            save=lambda result, user_id: saved_results.append(result),
        )

        diagnostics = saved_results[0].source_diagnostics
        self.assertEqual(
            [(item.source, item.status, item.error, item.warnings) for item in diagnostics],
            [
                ("opendatabot", "partial", None, ["Не знайдено фінансову таблицю"]),
                ("clarity_project", "source_error", "analysis_timeout", []),
            ],
        )

    async def test_saved_result_contains_successful_clarity_snapshot(self):
        from app.bot import edrpou_handler
        from app.models.clarity import ClarityData, ClarityRiskFlag, ClaritySignals, ClarityTax
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        message = FakeMessage("12345678", user_id=777)
        saved_results: list[CompanyLookupResult] = []

        def found_lookup(edrpou: str) -> CompanyLookupResult:
            return CompanyLookupResult(
                status="found",
                edrpou=edrpou,
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou=edrpou),
            )

        def found_clarity_lookup(edrpou: str) -> ClarityData:
            return ClarityData(
                source_url="https://clarity-project.info/edr/12345678",
                status="found",
                edrpou=edrpou,
                tax=ClarityTax(tax_debt=False, esv_debt=False),
                signals=ClaritySignals(bankruptcy_count=0, enforcement_proceedings_count=2),
                risk_flags=[
                    ClarityRiskFlag(
                        level="high",
                        code="bankruptcy_found",
                        text="Знайдено записи, пов'язані з банкрутством.",
                    )
                ],
            )

        await edrpou_handler(
            message,
            lookup=found_lookup,
            clarity_lookup=found_clarity_lookup,
            youcontrol_lookup=no_youcontrol_lookup,
            debtors_lookup=no_debtors_lookup,
            tax_lookup=no_tax_lookup,
            domain_reputation_lookup=no_domain_reputation_lookup,
            contacts_lookup=no_contacts_lookup,
            save=lambda result, user_id: saved_results.append(result),
        )

        self.assertIsNotNone(saved_results[0].clarity_data)
        self.assertEqual(saved_results[0].clarity_data.status, "found")
        self.assertFalse(saved_results[0].clarity_data.tax.tax_debt)
        self.assertEqual(saved_results[0].clarity_data.signals.enforcement_proceedings_count, 2)
        self.assertEqual(saved_results[0].risk_summary.level, "critical")
        self.assertEqual(saved_results[0].risk_summary.flags[0].source, "clarity_project")
        self.assertEqual(saved_results[0].risk_summary.flags[0].code, "bankruptcy_found")

    async def test_saved_result_contains_youcontrol_sources_and_deduped_risks(self):
        from app.bot import edrpou_handler
        from app.models.clarity import ClarityData, ClarityRiskFlag
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        message = FakeMessage("12345678", user_id=777)
        saved_results: list[CompanyLookupResult] = []

        def found_lookup(edrpou: str) -> CompanyLookupResult:
            return CompanyLookupResult(
                status="found",
                edrpou=edrpou,
                source_url=f"https://opendatabot.ua/c/{edrpou}?from=search",
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou=edrpou),
            )

        def found_clarity_lookup(edrpou: str) -> ClarityData:
            return ClarityData(
                source_url=f"https://clarity-project.info/edr/{edrpou}",
                status="found",
                edrpou=edrpou,
                risk_flags=[
                    ClarityRiskFlag(
                        level="medium",
                        code="tax_debt_found",
                        text="У Clarity є ознака податкового боргу.",
                    )
                ],
            )

        def found_youcontrol_lookup(edrpou: str) -> dict:
            return {
                "source": "youcontrol",
                "found": True,
                "url": f"https://youcontrol.com.ua/catalog/company_details/{edrpou}/",
                "company": {
                    "name": "ТОВ «ПРИКЛАД»",
                    "edrpou": edrpou,
                    "status": "Зареєстровано",
                    "registration_date": None,
                    "address": None,
                    "director": None,
                    "main_kved": None,
                    "additional_kveds": [],
                },
                "signals": ["Податковий борг: наявний", "Виконавчі провадження: 1"],
                "risk_flags": ["tax_debt_found", "enforcement_found"],
                "raw_text_excerpt": "ТОВ «ПРИКЛАД» ЄДРПОУ 12345678",
                "error": None,
            }

        await edrpou_handler(
            message,
            lookup=found_lookup,
            clarity_lookup=found_clarity_lookup,
            youcontrol_lookup=found_youcontrol_lookup,
            debtors_lookup=no_debtors_lookup,
            tax_lookup=no_tax_lookup,
            domain_reputation_lookup=no_domain_reputation_lookup,
            contacts_lookup=no_contacts_lookup,
            save=lambda result, user_id: saved_results.append(result),
        )

        saved = saved_results[0]
        self.assertEqual(saved.youcontrol_data["source"], "youcontrol")
        self.assertIn("youcontrol", saved.sources)
        self.assertEqual(saved.sources["youcontrol"]["found"], True)
        self.assertIn("opendatabot", saved.sources)
        self.assertIn("clarity", saved.sources)
        self.assertIn("court_analysis", saved.sources)
        risk_codes = [flag.code for flag in saved.risk_summary.flags]
        self.assertEqual(risk_codes.count("tax_debt_found"), 1)
        self.assertIn("enforcement_found", risk_codes)
        self.assertIn("YouControl", message.answers[1])

    async def test_youcontrol_unavailable_does_not_block_user_response(self):
        from app.bot import edrpou_handler
        from app.models.clarity import ClarityData
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        message = FakeMessage("12345678", user_id=777)
        saved_results: list[CompanyLookupResult] = []

        def found_lookup(edrpou: str) -> CompanyLookupResult:
            return CompanyLookupResult(
                status="found",
                edrpou=edrpou,
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou=edrpou),
            )

        def found_clarity_lookup(edrpou: str) -> ClarityData:
            return ClarityData(
                source_url=f"https://clarity-project.info/edr/{edrpou}",
                status="found",
                edrpou=edrpou,
            )

        def unavailable_youcontrol_lookup(edrpou: str) -> dict:
            return {
                "source": "youcontrol",
                "found": False,
                "url": f"https://youcontrol.com.ua/catalog/company_details/{edrpou}/",
                "company": {
                    "name": None,
                    "edrpou": edrpou,
                    "status": None,
                    "registration_date": None,
                    "address": None,
                    "director": None,
                    "main_kved": None,
                    "additional_kveds": [],
                },
                "signals": [],
                "risk_flags": [],
                "raw_text_excerpt": None,
                "error": "blocked_or_unavailable",
            }

        await edrpou_handler(
            message,
            lookup=found_lookup,
            clarity_lookup=found_clarity_lookup,
            youcontrol_lookup=unavailable_youcontrol_lookup,
            debtors_lookup=no_debtors_lookup,
            tax_lookup=no_tax_lookup,
            domain_reputation_lookup=no_domain_reputation_lookup,
            contacts_lookup=no_contacts_lookup,
            save=lambda result, user_id: saved_results.append(result),
        )

        self.assertIn("ТОВ «ПРИКЛАД»", message.answers[1])
        self.assertEqual(saved_results[0].youcontrol_data["error"], "blocked_or_unavailable")
        self.assertEqual(saved_results[0].sources["youcontrol"]["error"], "blocked_or_unavailable")

    async def test_saved_result_contains_debtors_registry_sources_and_response(self):
        from app.bot import edrpou_handler
        from app.models.clarity import ClarityData
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        message = FakeMessage("12345678", user_id=777)
        saved_results: list[CompanyLookupResult] = []

        def found_lookup(edrpou: str) -> CompanyLookupResult:
            return CompanyLookupResult(
                status="found",
                edrpou=edrpou,
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou=edrpou),
            )

        def found_clarity_lookup(edrpou: str) -> ClarityData:
            return ClarityData(
                source_url=f"https://clarity-project.info/edr/{edrpou}",
                status="found",
                edrpou=edrpou,
            )

        def found_debtors_lookup(edrpou: str) -> dict:
            return {
                "source": "debtors_registry",
                "checked": True,
                "found": True,
                "url": "https://erb.minjust.gov.ua/#/search-debtors",
                "searched_edrpou": edrpou,
                "items_count": 5,
                "items": [],
                "signals": ["Компанія знайдена в Єдиному реєстрі боржників"],
                "risk_flags": [
                    "debtor_registry_found",
                    "multiple_debtor_records",
                    "salary_debt_enforcement_found",
                ],
                "error": None,
            }

        await edrpou_handler(
            message,
            lookup=found_lookup,
            clarity_lookup=found_clarity_lookup,
            youcontrol_lookup=no_youcontrol_lookup,
            debtors_lookup=found_debtors_lookup,
            tax_lookup=no_tax_lookup,
            domain_reputation_lookup=no_domain_reputation_lookup,
            contacts_lookup=no_contacts_lookup,
            save=lambda result, user_id: saved_results.append(result),
        )

        saved = saved_results[0]
        self.assertEqual(saved.debtors_registry_data["source"], "debtors_registry")
        self.assertEqual(saved.sources["debtors_registry"]["items_count"], 5)
        risk_codes = [flag.code for flag in saved.risk_summary.flags]
        self.assertIn("debtor_registry_found", risk_codes)
        self.assertIn("multiple_debtor_records", risk_codes)
        self.assertIn("salary_debt_enforcement_found", risk_codes)
        self.assertIn("Єдиний реєстр боржників", message.answers[1])

    async def test_saved_result_contains_tax_sources_and_response(self):
        from app.bot import edrpou_handler
        from app.models.clarity import ClarityData, ClarityRiskFlag
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        message = FakeMessage("05747991", user_id=777)
        saved_results: list[CompanyLookupResult] = []

        def found_lookup(edrpou: str) -> CompanyLookupResult:
            return CompanyLookupResult(
                status="found",
                edrpou=edrpou,
                company_data=CompanyData(short_name='АТ "СУМСЬКЕ МНВО"', edrpou=edrpou),
            )

        def found_clarity_lookup(edrpou: str) -> ClarityData:
            return ClarityData(
                source_url=f"https://clarity-project.info/edr/{edrpou}",
                status="found",
                edrpou=edrpou,
                risk_flags=[
                    ClarityRiskFlag(
                        level="medium",
                        code="tax_debt_found",
                        text="У Clarity є ознака податкового боргу.",
                    )
                ],
            )

        def found_tax_lookup(edrpou: str) -> dict:
            return {
                "source": "tax",
                "checked": True,
                "found": True,
                "searched_edrpou": edrpou,
                "tax_debt": {
                    "found": True,
                    "amount": 150000.0,
                    "currency": "UAH",
                    "details": [],
                    "dataset_date": "2026-06-01",
                },
                "vat": None,
                "signals": ["Знайдено податковий борг"],
                "risk_flags": ["tax_debt_found", "large_tax_debt_found"],
                "error": None,
            }

        await edrpou_handler(
            message,
            lookup=found_lookup,
            clarity_lookup=found_clarity_lookup,
            youcontrol_lookup=no_youcontrol_lookup,
            debtors_lookup=no_debtors_lookup,
            tax_lookup=found_tax_lookup,
            domain_reputation_lookup=no_domain_reputation_lookup,
            contacts_lookup=no_contacts_lookup,
            save=lambda result, user_id: saved_results.append(result),
        )

        saved = saved_results[0]
        self.assertEqual(saved.tax_data["source"], "tax")
        self.assertEqual(saved.sources["tax"]["tax_debt"]["amount"], 150000.0)
        risk_codes = [flag.code for flag in saved.risk_summary.flags]
        self.assertEqual(risk_codes.count("tax_debt_found"), 1)
        self.assertIn("large_tax_debt_found", risk_codes)
        self.assertIn("Знайдено податковий борг у доступних даних ДПС.", message.answers[1])

    async def test_edrpou_handler_accepts_edrpou_and_website_url(self):
        from app.bot import edrpou_handler
        from app.models.clarity import ClarityData
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        message = FakeMessage("05747991 https://snvo.ua", user_id=777)
        saved_results: list[CompanyLookupResult] = []
        checked_domains: list[tuple[str | None, dict | None]] = []

        def found_lookup(edrpou: str) -> CompanyLookupResult:
            return CompanyLookupResult(
                status="found",
                edrpou=edrpou,
                company_data=CompanyData(
                    short_name='АТ "СУМСЬКЕ НВО"',
                    edrpou=edrpou,
                    address="40004, Україна, місто Суми",
                ),
            )

        def found_clarity_lookup(edrpou: str) -> ClarityData:
            return ClarityData(
                source_url=f"https://clarity-project.info/edr/{edrpou}",
                status="found",
                edrpou=edrpou,
            )

        def domain_lookup(domain_or_url: str | None, company_context: dict | None = None) -> dict:
            checked_domains.append((domain_or_url, company_context))
            return {
                "source": "domain_reputation",
                "checked": True,
                "found": True,
                "url": "https://snvo.ua",
                "domain": "snvo.ua",
                "http": {"status_code": 200, "final_url": "https://snvo.ua/", "redirects": [], "title": "АТ Сумське НВО", "is_empty": False},
                "ssl": {"present": True, "not_before": None, "not_after": None, "issuer": None},
                "dns": {"found": True, "a_records": ["192.0.2.10"], "mx_records": []},
                "contacts": {
                    "emails": ["office@snvo.ua"],
                    "phones": [],
                    "edrpou_found_on_page": True,
                    "company_name_found_on_page": True,
                    "address_found_on_page": False,
                },
                "signals": [],
                "risk_flags": [],
                "error": None,
            }

        await edrpou_handler(
            message,
            lookup=found_lookup,
            clarity_lookup=found_clarity_lookup,
            youcontrol_lookup=no_youcontrol_lookup,
            debtors_lookup=no_debtors_lookup,
            tax_lookup=no_tax_lookup,
            domain_reputation_lookup=domain_lookup,
            contacts_lookup=no_contacts_lookup,
            save=lambda result, user_id: saved_results.append(result),
        )

        self.assertEqual(checked_domains[0][0], "https://snvo.ua")
        self.assertEqual(checked_domains[0][1]["edrpou"], "05747991")
        self.assertEqual(checked_domains[0][1]["company_name"], 'АТ "СУМСЬКЕ НВО"')
        self.assertEqual(saved_results[0].sources["domain_reputation"]["domain"], "snvo.ua")
        self.assertIn("Джерела:", message.answers[1])

    async def test_pipeline_does_not_fail_when_website_is_not_provided(self):
        from app.bot import edrpou_handler
        from app.models.clarity import ClarityData
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        message = FakeMessage("12345678", user_id=777)
        saved_results: list[CompanyLookupResult] = []

        def found_lookup(edrpou: str) -> CompanyLookupResult:
            return CompanyLookupResult(
                status="found",
                edrpou=edrpou,
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou=edrpou),
            )

        def found_clarity_lookup(edrpou: str) -> ClarityData:
            return ClarityData(
                source_url=f"https://clarity-project.info/edr/{edrpou}",
                status="found",
                edrpou=edrpou,
            )

        await edrpou_handler(
            message,
            lookup=found_lookup,
            clarity_lookup=found_clarity_lookup,
            youcontrol_lookup=no_youcontrol_lookup,
            debtors_lookup=no_debtors_lookup,
            tax_lookup=no_tax_lookup,
            domain_reputation_lookup=no_domain_reputation_lookup,
            contacts_lookup=no_contacts_lookup,
            save=lambda result, user_id: saved_results.append(result),
        )

        self.assertEqual(saved_results[0].sources["domain_reputation"]["error"], "website_not_provided")
        self.assertNotIn("Перевірка сайту:", message.answers[1])

    async def test_saved_result_contains_contacts_summary_and_response(self):
        from app.bot import edrpou_handler
        from app.models.clarity import ClarityData
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        message = FakeMessage("01554522", user_id=777)
        saved_results: list[CompanyLookupResult] = []

        def found_lookup(edrpou: str) -> CompanyLookupResult:
            return CompanyLookupResult(
                status="found",
                edrpou=edrpou,
                company_data=CompanyData(
                    short_name='ПРАТ "ВЗУТТЯ-ІФ"',
                    edrpou=edrpou,
                    status="Зареєстровано",
                    address="Івано-Франківськ, вул. Торгова, 3",
                ),
            )

        def found_clarity_lookup(edrpou: str) -> ClarityData:
            return ClarityData(
                source_url=f"https://clarity-project.info/edr/{edrpou}",
                status="found",
                edrpou=edrpou,
            )

        def contacts_lookup(edrpou: str, company_context: dict | None = None) -> dict:
            return {
                "website": {
                    "value": "https://if-shoes.ua",
                    "confidence": "high",
                    "sources": ["ua-region.com.ua"],
                    "evidence": ["На сторінці знайдено ЄДРПОУ 01554522."],
                },
                "phone": {"value": "+380342551122", "confidence": "high", "sources": ["ua-region.com.ua"], "evidence": []},
                "email": {"value": "office@if-shoes.ua", "confidence": "high", "sources": ["ua-region.com.ua"], "evidence": []},
                "checked_sources": ["ua-region.com.ua", "prat.ua/pat.ua", "smida.gov.ua", "business-guide.com.ua"],
                "missing_sources": ["smida.gov.ua"],
                "warnings": [],
                "source_statuses": {
                    "ua-region.com.ua": "found",
                    "prat.ua/pat.ua": "not_found",
                    "smida.gov.ua": "not_found",
                    "business-guide.com.ua": "not_found",
                },
                "source_results": [],
            }

        await edrpou_handler(
            message,
            lookup=found_lookup,
            clarity_lookup=found_clarity_lookup,
            youcontrol_lookup=no_youcontrol_lookup,
            debtors_lookup=no_debtors_lookup,
            tax_lookup=no_tax_lookup,
            domain_reputation_lookup=no_domain_reputation_lookup,
            contacts_lookup=contacts_lookup,
            save=lambda result, user_id: saved_results.append(result),
        )

        saved = saved_results[0]
        self.assertEqual(saved.contacts_summary["website"]["value"], "https://if-shoes.ua")
        self.assertEqual(saved.sources["contacts_summary"]["email"]["value"], "office@if-shoes.ua")
        self.assertIn("Контакти:", message.answers[1])
        self.assertIn("🌐 Сайт: https://if-shoes.ua", message.answers[1])
        self.assertNotIn("UA-REGION: found", message.answers[1])
        self.assertNotIn("not_found", message.answers[1])
        self.assertLess(message.answers[1].index("Контакти:"), message.answers[1].index("Загальний ризик:"))

    def test_user_report_hides_contact_technical_statuses_and_has_single_limitations_block(self):
        from app.bot import format_found_company
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        result = CompanyLookupResult(
            status="found",
            edrpou="01554522",
            company_data=CompanyData(
                short_name='ПРАТ "ВЗУТТЯ-ІФ"',
                edrpou="01554522",
                status="Зареєстровано",
                director="Матей Юрій Густавович",
                address="Івано-Франківськ, вул. Торгова, 3",
            ),
        )
        contacts_summary = {
            "website": {
                "value": "https://vzuttjaif.prat.ua",
                "confidence": "high",
                "sources": ["prat.ua/pat.ua"],
                "evidence": ["На сторінці знайдено той самий ЄДРПОУ, назву компанії, адресу та керівника."],
            },
            "phone": {
                "value": "+380342222540",
                "confidence": "high",
                "sources": ["prat.ua/pat.ua"],
                "evidence": ["На сторінці знайдено той самий ЄДРПОУ, назву компанії, адресу та керівника."],
            },
            "email": {
                "value": "info@vzuttjaif.prat.ua",
                "confidence": "high",
                "sources": ["prat.ua/pat.ua"],
                "evidence": ["На сторінці знайдено той самий ЄДРПОУ, назву компанії, адресу та керівника."],
            },
            "checked_sources": ["ua-region.com.ua", "prat.ua/pat.ua", "smida.gov.ua", "business-guide.com.ua"],
            "missing_sources": ["business-guide.com.ua"],
            "warnings": ["Джерело smida.gov.ua тимчасово недоступне або заблокувало автоматичну перевірку."],
            "source_statuses": {
                "ua-region.com.ua": "unavailable",
                "prat.ua/pat.ua": "found",
                "smida.gov.ua": "analysis_timeout",
                "business-guide.com.ua": "not_found",
            },
            "source_results": [],
        }

        text = format_found_company(result, contacts_summary=contacts_summary)

        self.assertIn("Контакти:", text)
        self.assertIn("Сайт: https://vzuttjaif.prat.ua", text)
        self.assertIn("Телефон: (03422) 225-40", text)
        self.assertIn("Email: info@vzuttjaif.prat.ua", text)
        self.assertNotIn("Рівень довіри: високий", text)
        self.assertNotIn("Підстава:", text)
        self.assertIn("Контактні дані підтверджені відкритими джерелами.", text)
        self.assertEqual(text.count("Обмеження перевірки:"), 0)
        self.assertNotIn("\nОбмеження:\n", text)
        for forbidden in ("unavailable", "not_found", "parse_error", "analysis_timeout", "Перевірені джерела"):
            self.assertNotIn(forbidden, text)
        self.assertNotIn("Частина джерел могла бути недоступна або повернути неповні дані.", text)

    def test_manual_check_block_does_not_contain_clarity_positive_signals(self):
        from app.bot import build_edrpou_response
        from app.models.clarity import ClarityData, ClaritySignals, ClarityTax
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        response = build_edrpou_response(
            "12345678",
            CompanyLookupResult(
                status="found",
                edrpou="12345678",
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou="12345678"),
            ),
            ClarityData(
                source_url="https://clarity-project.info/edr/12345678",
                status="found",
                edrpou="12345678",
                tax=ClarityTax(tax_debt=False, esv_debt=False),
                signals=ClaritySignals(bankruptcy_count=0),
            ),
        )

        reason_block = response.split("Причини оцінки:", 1)[1].split("Загальний ризик:", 1)[0]
        self.assertNotIn("Додаткові сигнали Clarity", reason_block)
        self.assertIn("Ознак банкрутства або припинення", reason_block)
        self.assertIn("Податковий борг та борг ЄСВ", reason_block)

    def test_sources_line_is_not_duplicated_and_includes_pat(self):
        from app.bot import format_found_company
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        contacts_summary = {
            "website": {"value": "https://vzuttjaif.prat.ua", "confidence": "high", "sources": ["prat.ua/pat.ua"], "evidence": []},
            "phone": {"value": None, "confidence": "unknown", "sources": [], "evidence": []},
            "email": {"value": None, "confidence": "unknown", "sources": [], "evidence": []},
            "source_statuses": {"prat.ua/pat.ua": "found"},
        }

        response = format_found_company(
            CompanyLookupResult(
                status="found",
                edrpou="05786100",
                company_data=CompanyData(short_name="АТ «ГІДРОСИЛА»", edrpou="05786100"),
            ),
            contacts_summary=contacts_summary,
        )

        self.assertIn("Джерела: Opendatabot, PAT.UA", response)
        self.assertNotIn("Джерела:\nДжерела:", response)

    def test_hidrosyla_phone_is_displayed_in_human_readable_format(self):
        from app.bot import format_found_company
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        contacts_summary = {
            "website": {"value": "https://hydrosila.prat.ua", "confidence": "high", "sources": ["prat.ua/pat.ua"], "evidence": []},
            "phone": {"value": "+380522391394", "confidence": "high", "sources": ["prat.ua/pat.ua"], "evidence": []},
            "email": {"value": None, "confidence": "unknown", "sources": [], "evidence": []},
            "source_statuses": {"prat.ua/pat.ua": "found"},
        }

        response = format_found_company(
            CompanyLookupResult(
                status="found",
                edrpou="05786100",
                company_data=CompanyData(short_name="АТ «ГІДРОСИЛА»", edrpou="05786100"),
            ),
            contacts_summary=contacts_summary,
        )

        self.assertIn("Телефон: +38 (0522) 39-13-94", response)
        self.assertNotIn("+380578610038", response)

    def test_report_shows_up_to_three_extracted_court_decisions_without_summary(self):
        from app.bot import format_found_company
        from app.models.company_lookup import CompanyData, CompanyLookupResult, CourtData

        response = format_found_company(
            CompanyLookupResult(
                status="found",
                edrpou="12345678",
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou="12345678"),
                court_data=CourtData(
                    has_court_mentions=True,
                    court_mentions_count=9,
                    decisions=[
                        {
                            "document_type": "Ухвала",
                            "decision_date": "04.05.2026",
                            "case_number": "160/11282/25",
                            "risk_summary": "Документ виглядає як процесуальна ухвала.",
                            "url": "https://court.example/doc-1",
                        },
                        {
                            "document_type": "Ухвала",
                            "decision_date": "05.05.2026",
                            "case_number": "160/11283/25",
                            "risk_summary": "Є ознаки спору щодо стягнення пені.",
                            "url": "https://court.example/doc-2",
                        },
                        {
                            "document_type": "Ухвала",
                            "decision_date": "06.05.2026",
                            "case_number": "160/11286/25",
                            "risk_summary": "Документ 6.",
                            "url": "https://court.example/doc-3",
                        },
                        *[
                            {
                                "document_type": "Ухвала",
                                "decision_date": f"0{day}.05.2026",
                                "case_number": f"160/1128{day}/25",
                                "risk_summary": f"Документ {day}.",
                                "url": f"https://court.example/doc-{day}",
                            }
                            for day in range(7, 10)
                        ],
                    ],
                ),
            )
        )

        self.assertIn("Судові документи:", response)
        self.assertIn("Показано деталізованих документів: 3 з 9.", response)
        self.assertIn("справа №160/11282/25", response)
        self.assertIn("справа №160/11283/25", response)
        self.assertIn("справа №160/11286/25", response)
        self.assertIn("Посилання: https://court.example/doc-1", response)
        self.assertIn("Посилання: https://court.example/doc-2", response)
        self.assertIn("Посилання: https://court.example/doc-3", response)
        self.assertNotIn("Коротко:", response)
        self.assertNotIn("160/11287/25", response)
        self.assertNotIn("160/11288/25", response)
        self.assertNotIn("160/11289/25", response)

    def test_report_explains_when_only_one_court_decision_detail_is_available(self):
        from app.bot import format_found_company
        from app.models.company_lookup import CompanyData, CompanyLookupResult, CourtData

        response = format_found_company(
            CompanyLookupResult(
                status="found",
                edrpou="12345678",
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou="12345678"),
                court_data=CourtData(
                    has_court_mentions=True,
                    court_mentions_count=400,
                    decisions=[
                        {
                            "document_type": "Ухвала",
                            "decision_date": "04.06.2026",
                            "case_number": "463/1298/23",
                            "risk_summary": "У тексті не знайдено явних ознак встановленої відповідальності.",
                        }
                    ],
                ),
            )
        )

        self.assertIn("Знайдено судових документів: 400.", response)
        self.assertIn("Показано деталізованих документів: 1 з 400.", response)
        self.assertIn("1. Ухвала від 04.06.2026, справа №463/1298/23", response)
        self.assertNotIn("2. Ухвала", response)

    def test_user_report_uses_compact_business_format(self):
        from app.bot import format_found_company
        from app.models.clarity import ClarityData, ClaritySignals, ClarityTax
        from app.models.company_lookup import CompanyData, CompanyLookupResult, CourtData, RiskInput

        contacts_summary = {
            "website": {
                "value": "https://vzuttjaif.prat.ua",
                "confidence": "high",
                "sources": ["prat.ua/pat.ua"],
                "evidence": ["На сторінці знайдено той самий ЄДРПОУ, назву компанії, адресу та керівника."],
            },
            "phone": {
                "value": "+380342222540",
                "confidence": "high",
                "sources": ["prat.ua/pat.ua"],
                "evidence": ["На сторінці знайдено той самий ЄДРПОУ, назву компанії, адресу та керівника."],
            },
            "email": {
                "value": "info@vzuttjaif.prat.ua",
                "confidence": "high",
                "sources": ["prat.ua/pat.ua"],
                "evidence": ["Email має домен підтвердженого сайту компанії."],
            },
            "source_statuses": {"prat.ua/pat.ua": "found"},
        }

        response = format_found_company(
            CompanyLookupResult(
                status="found",
                edrpou="01554522",
                company_data=CompanyData(
                    short_name="ПРАТ «ВЗУТТЯ-ІФ»",
                    edrpou="01554522",
                    status="Зареєстровано",
                    registration_date="22.03.1996",
                    director="Матей Юрій Густавович",
                    address="76019, Україна, Івано-Франківська обл., місто Івано-Франківськ, вулиця Торгова, будинок 3",
                    statutory_capital_uah=104000,
                    main_activity_code="17.21",
                    main_activity_name="Виробництво гофрованого паперу та картону, паперової та картонної тари",
                ),
                court_data=CourtData(
                    has_court_mentions=True,
                    court_mentions_count=2,
                    decisions=[
                        {
                            "document_type": "Ухвала",
                            "decision_date": "15.06.2023",
                            "case_number": "344/9484/23",
                            "risk_summary": "У доступному тексті не знайдено явних ознак встановленої відповідальності або критичного ризику.",
                        }
                    ],
                ),
                risk_input=RiskInput(has_court_mentions=True, court_mentions_count=2),
            ),
            clarity_data=ClarityData(
                source_url="https://clarity-project.info/edr/01554522",
                status="found",
                edrpou="01554522",
                tax=ClarityTax(tax_debt=False, esv_debt=False),
                signals=ClaritySignals(bankruptcy_count=0),
            ),
            contacts_summary=contacts_summary,
        )

        self.assertIn("Фінансові дані:", response)
        self.assertIn("Статутний капітал: 104 000 грн", response)
        self.assertIn("Інші фінансові показники у доступних джерелах не знайдено.", response)
        self.assertIn("Загальний ризик: низький — 13/100", response)
        self.assertIn("Причини оцінки:", response)
        self.assertIn("✅ Компанія зареєстрована та працює тривалий час.", response)
        self.assertIn("✅ Контактні дані підтверджені відкритими джерелами.", response)
        self.assertIn("⚠️ Судові документи: 2. Потрібна ручна перевірка змісту справ.", response)
        self.assertIn("Судові документи:", response)
        self.assertNotIn("Рівень довіри:", response)
        self.assertNotIn("Підстава:", response)
        self.assertNotIn("Позитивні фактори:", response)
        self.assertNotIn("Що перевірити вручну:", response)
        self.assertNotIn("Обмеження перевірки:", response)

    def test_user_report_hides_unavailable_sources_and_manual_review_label(self):
        from app.bot import format_found_company
        from app.models.clarity import ClarityData, ClaritySignals
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        youcontrol_data = {
            "source": "youcontrol",
            "found": True,
            "company": {"status": "Зареєстровано"},
            "signals": ["Банкрутство: виявлено"],
            "risk_flags": ["bankruptcy_found"],
            "raw_text_excerpt": "Банкрутство: виявлено",
            "error": None,
        }
        response = format_found_company(
            CompanyLookupResult(
                status="found",
                edrpou="12345678",
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou="12345678", status="Зареєстровано"),
            ),
            clarity_data=ClarityData(
                source_url="https://clarity-project.info/edr/12345678",
                status="found",
                edrpou="12345678",
                signals=ClaritySignals(bankruptcy_count=0),
            ),
            youcontrol_data=youcontrol_data,
            debtors_registry_data={"checked": False, "error": "analysis_timeout", "risk_flags": []},
            tax_data={"checked": False, "error": "analysis_timeout", "risk_flags": []},
        )

        self.assertIn("Загальний ризик: помірний — 45/100", response)
        self.assertNotIn("Потребує ручної перевірки", response)
        self.assertNotIn("analysis_timeout", response)
        self.assertNotIn("тимчасово недоступ", response.lower())
        self.assertNotIn("Обмеження перевірки:", response)

    def test_user_report_uses_youcontrol_contact_fallback_when_contact_search_failed(self):
        from app.bot import format_found_company
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        contacts_summary = {
            "website": {"value": None, "confidence": "unknown", "sources": [], "evidence": []},
            "phone": {"value": None, "confidence": "unknown", "sources": [], "evidence": []},
            "email": {"value": None, "confidence": "unknown", "sources": [], "evidence": []},
            "source_statuses": {
                "ua-region.com.ua": "unavailable",
                "prat.ua/pat.ua": "unavailable",
                "smida.gov.ua": "unavailable",
                "business-guide.com.ua": "unavailable",
            },
        }
        youcontrol_data = {
            "source": "youcontrol",
            "found": True,
            "company": {
                "phone": "+38 (0569) 55-11-22",
                "email": "office@dlz.ua",
                "website": "https://dlz.ua",
            },
            "signals": [],
            "risk_flags": [],
            "error": None,
        }

        response = format_found_company(
            CompanyLookupResult(
                status="found",
                edrpou="38673411",
                company_data=CompanyData(short_name="ТОВ «ДЛЗ»", edrpou="38673411"),
            ),
            youcontrol_data=youcontrol_data,
            contacts_summary=contacts_summary,
        )

        self.assertIn("🌐 Сайт: https://dlz.ua", response)
        self.assertIn("☎️ Телефон: +38 (0569) 55-11-22", response)
        self.assertIn("✉️ Email: office@dlz.ua", response)

    def test_report_shows_source_specific_court_counts_when_youcontrol_differs(self):
        from app.bot import format_found_company
        from app.models.company_lookup import CompanyData, CompanyLookupResult, CourtData, RiskInput

        response = format_found_company(
            CompanyLookupResult(
                status="found",
                edrpou="38673411",
                company_data=CompanyData(short_name="ТОВ «ДЛЗ»", edrpou="38673411"),
                court_data=CourtData(has_court_mentions=True, court_mentions_count=11),
                risk_input=RiskInput(has_court_mentions=True, court_mentions_count=11),
            ),
            youcontrol_data={
                "source": "youcontrol",
                "found": True,
                "company": {"status": "Зареєстровано"},
                "signals": ["Судові справи: 4"],
                "risk_flags": ["court_cases_found"],
                "error": None,
            },
        )

        self.assertIn("Судові документи: Opendatabot — 11, YouControl — 4", response)
        self.assertNotIn("Є судові згадки: 11.", response)

    def test_enforcement_count_is_not_duplicated_by_generic_reason(self):
        from app.bot import format_found_company
        from app.models.clarity import ClarityData, ClarityRiskFlag, ClaritySignals
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        response = format_found_company(
            CompanyLookupResult(
                status="found",
                edrpou="38673411",
                company_data=CompanyData(short_name="ТОВ «ДЛЗ»", edrpou="38673411"),
            ),
            clarity_data=ClarityData(
                source_url="https://clarity-project.info/edr/38673411",
                status="found",
                edrpou="38673411",
                signals=ClaritySignals(enforcement_proceedings_count=7),
                risk_flags=[
                    ClarityRiskFlag(level="medium", code="enforcement_found", text="Знайдено виконавчі провадження.")
                ],
            ),
        )

        self.assertIn("Виконавчі провадження: 7", response)
        self.assertNotIn("Знайдено виконавчі провадження.", response)
        self.assertNotIn("Знайдено виконавчі провадження або боргові ознаки.", response)

    async def test_debug_handler_returns_technical_json(self):
        from app.bot import debug_handler
        from app.models.clarity import ClarityData, ClarityRiskFlag
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        message = FakeMessage("/debug 01554545", user_id=777)

        def found_lookup(edrpou: str) -> CompanyLookupResult:
            return CompanyLookupResult(
                status="found",
                edrpou=edrpou,
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou=edrpou),
            )

        def found_clarity_lookup(edrpou: str) -> ClarityData:
            return ClarityData(
                source_url=f"https://clarity-project.info/edr/{edrpou}",
                status="found",
                edrpou=edrpou,
                risk_flags=[
                    ClarityRiskFlag(
                        level="medium",
                        code="tax_debt_found",
                        text="У Clarity є ознака податкового боргу.",
                    )
                ],
            )

        def unavailable_youcontrol_lookup(edrpou: str) -> dict:
            return {
                "source": "youcontrol",
                "found": False,
                "url": f"https://youcontrol.com.ua/catalog/company_details/{edrpou}/",
                "company": {
                    "name": None,
                    "edrpou": edrpou,
                    "status": None,
                    "registration_date": None,
                    "address": None,
                    "director": None,
                    "main_kved": None,
                    "additional_kveds": [],
                },
                "signals": [],
                "risk_flags": [],
                "raw_text_excerpt": None,
                "error": "blocked_or_unavailable",
            }

        await debug_handler(
            message,
            lookup=found_lookup,
            clarity_lookup=found_clarity_lookup,
            youcontrol_lookup=unavailable_youcontrol_lookup,
            debtors_lookup=no_debtors_lookup,
            tax_lookup=no_tax_lookup,
            domain_reputation_lookup=no_domain_reputation_lookup,
            contacts_lookup=no_contacts_lookup,
        )

        payload = json.loads(message.answers[0])
        self.assertEqual(payload["edrpou"], "01554545")
        self.assertIn("opendatabot", payload["sources_checked"])
        self.assertIn("clarity", payload["sources_checked"])
        self.assertIn("youcontrol", payload["sources_unavailable"])
        self.assertEqual(payload["final_score"], 25)
        self.assertEqual(payload["final_level"], "medium")
        self.assertEqual(payload["risk_flags"][0]["type"], "tax_debt_found")
        self.assertNotEqual(payload["final_level"], "critical")

    def test_debug_payload_lists_prozorro_found_and_partial_sources(self):
        from app.bot import build_debug_payload, with_source_diagnostics
        from app.models.company_lookup import CompanyLookupResult, ProzorroAnalysis, ProzorroStats

        for status in ("found", "partial"):
            with self.subTest(status=status):
                result = CompanyLookupResult(
                    status="found",
                    edrpou="12345678",
                    prozorro_analysis=ProzorroAnalysis(status=status, stats=ProzorroStats(procurements_count=2)),
                )

                payload = build_debug_payload(with_source_diagnostics(result, None))

                self.assertIn("prozorro", payload["sources_checked"])
                self.assertNotIn("prozorro", payload["sources_unavailable"])

    def test_debug_payload_lists_unavailable_prozorro_source(self):
        from app.bot import build_debug_payload, with_source_diagnostics
        from app.models.company_lookup import CompanyLookupResult, ProzorroAnalysis

        result = CompanyLookupResult(
            status="found",
            edrpou="12345678",
            prozorro_analysis=ProzorroAnalysis(status="source_error", error="cache_unavailable"),
        )

        payload = build_debug_payload(with_source_diagnostics(result, None))

        self.assertIn("prozorro", payload["sources_unavailable"])
        self.assertNotIn("prozorro", payload["sources_checked"])

    async def test_debug_handler_returns_exact_raw_court_and_enforcement_counts(self):
        from app.bot import debug_handler
        from app.models.clarity import ClarityData, ClaritySignals
        from app.models.company_lookup import CompanyData, CompanyLookupResult, CourtData, RiskInput

        message = FakeMessage("/debug 12345678", user_id=777)

        def found_lookup(edrpou: str) -> CompanyLookupResult:
            return CompanyLookupResult(
                status="found",
                edrpou=edrpou,
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou=edrpou),
                court_data=CourtData(has_court_mentions=True, total_cases_found=250),
                risk_input=RiskInput(has_court_mentions=True, total_court_cases_found=250),
            )

        def found_clarity_lookup(edrpou: str) -> ClarityData:
            return ClarityData(
                source_url=f"https://clarity-project.info/edr/{edrpou}",
                status="found",
                edrpou=edrpou,
                signals=ClaritySignals(enforcement_proceedings_count=150),
            )

        await debug_handler(
            message,
            lookup=found_lookup,
            clarity_lookup=found_clarity_lookup,
            youcontrol_lookup=no_youcontrol_lookup,
            debtors_lookup=no_debtors_lookup,
            tax_lookup=no_tax_lookup,
            domain_reputation_lookup=no_domain_reputation_lookup,
            contacts_lookup=no_contacts_lookup,
        )

        payload = json.loads(message.answers[0])
        self.assertEqual(payload["raw_counts"]["court_mentions_count"], 250)
        self.assertEqual(payload["raw_counts"]["court_cases_count"], 250)
        self.assertEqual(payload["raw_counts"]["enforcement_count"], 150)

    async def test_debug_handler_returns_exact_court_mentions_count_12162(self):
        from app.bot import debug_handler
        from app.models.company_lookup import CompanyData, CompanyLookupResult, CourtData, RiskInput

        message = FakeMessage("/debug 05747991", user_id=777)

        def found_lookup(edrpou: str) -> CompanyLookupResult:
            return CompanyLookupResult(
                status="found",
                edrpou=edrpou,
                company_data=CompanyData(short_name='АТ "СУМСЬКЕ МНВО"', edrpou=edrpou),
                court_data=CourtData(
                    has_court_mentions=True,
                    court_mentions_count=12162,
                ),
                risk_input=RiskInput(
                    has_court_mentions=True,
                    court_mentions_count=12162,
                ),
            )

        await debug_handler(
            message,
            lookup=found_lookup,
            clarity_lookup=lambda edrpou: None,
            youcontrol_lookup=no_youcontrol_lookup,
            debtors_lookup=no_debtors_lookup,
            tax_lookup=no_tax_lookup,
            domain_reputation_lookup=no_domain_reputation_lookup,
            contacts_lookup=no_contacts_lookup,
        )

        payload = json.loads(message.answers[0])
        self.assertEqual(payload["raw_counts"]["court_mentions_count"], 12162)

    async def test_invalid_edrpou_sends_only_format_hint(self):
        from app.bot import INVALID_EDRPOU_TEXT, edrpou_handler

        message = FakeMessage("1234-5678")

        await edrpou_handler(message)

        self.assertEqual(message.answers, [INVALID_EDRPOU_TEXT])


if __name__ == "__main__":
    unittest.main()
