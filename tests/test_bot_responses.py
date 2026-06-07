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

        self.assertEqual(summary.score, 0)
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

        self.assertEqual(summary.score, 0)
        self.assertNotIn("multiple_prozorro_terminations_found", [reason["type"] for reason in summary.reasons])

    def test_build_sources_snapshot_includes_prozorro_analysis(self):
        from app.bot import build_sources_snapshot
        from app.models.company_lookup import CompanyLookupResult, ProzorroAnalysis, ProzorroStats

        analysis = ProzorroAnalysis(status="found", stats=ProzorroStats(procurements_count=2))
        result = CompanyLookupResult(status="found", edrpou="12345678", prozorro_analysis=analysis)

        sources = build_sources_snapshot(result, None, None)

        self.assertEqual(sources["prozorro"]["status"], "found")
        self.assertEqual(sources["prozorro"]["stats"]["procurements_count"], 2)

    def test_found_company_response_shows_prozorro_block_when_analysis_exists(self):
        from app.bot import build_edrpou_response
        from app.models.company_lookup import CompanyData, CompanyLookupResult, ProzorroAnalysis, ProzorroStats

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
                info_notes=[
                    "Сам факт участі не є ризиком.",
                    "Перемог у Prozorro не знайдено; score не підвищено.",
                ],
                summary="Prozorro: участей 4, перемог 0, договорів 0, розірвань 0.",
            ),
        )

        response = build_edrpou_response("12345678", result)

        self.assertIn("Prozorro:", response)
        self.assertIn("Участей: 4", response)
        self.assertIn("Перемог: 0", response)
        self.assertIn("Договорів: 0", response)
        self.assertIn("Остання участь: 2025-03-10", response)
        self.assertIn("Сам факт участі не є ризиком", response)
        self.assertIn("Джерела: Opendatabot, Prozorro", response)

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
            "Вітаю! Я RiskUA.\n\n"
            "Допомагаю швидко перевірити компанію за ЄДРПОУ перед оплатою, договором або співпрацею.\n\n"
            "Надішліть код ЄДРПОУ — я покажу базові дані, можливі ризики та коротку рекомендацію.\n\n"
            "Приклад: 12345678\n\n"
            "⏳ Аналіз може зайняти до 30 секунд.",
        )

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
        self.assertIn("Тендери: учасник 2 закупівель", response)
        self.assertIn("✅ Компанія зареєстрована та працює тривалий час.", response)
        self.assertIn("Фінансові дані:", response)
        self.assertIn("Дохід (2024): 1 000 000 грн", response)
        self.assertIn("Є судові згадки: 3.", response)
        self.assertNotIn("Додаткові сигнали Clarity:", response)
        self.assertIn("Ознак банкрутства або припинення", response)
        self.assertIn("Податковий борг та борг ЄСВ", response)
        self.assertIn("Виконавчі провадження: 1", response)
        self.assertIn("Джерела: Opendatabot, Clarity", response)

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
            "Рекомендація: перед передоплатою",
            "Джерела:",
        ):
            self.assertIn(section, response)
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
        self.assertIn("високий — 90/100", response)
        self.assertIn("Знайдено записи, пов'язані з банкрутством", response)
        self.assertNotIn("шахрай", response.lower())
        self.assertIn("не рекомендується робити передоплату без додаткової перевірки", response)
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

        self.assertIn("потребує додаткової перевірки перед оплатою", response)
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

        reason_block = response.split("Причини оцінки:", 1)[1].split("Рекомендація:", 1)[0]
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

        reason_block = response.split("Причини оцінки:", 1)[1].split("Рекомендація:", 1)[0]
        risk_codes = [reason["type"] for reason in enriched.risk_summary.reasons]
        self.assertIn("tax_debt_found", risk_codes)
        self.assertIn("tax_debt_source_mismatch", risk_codes)
        self.assertIn("opendatabot", next(reason for reason in enriched.risk_summary.reasons if reason["type"] == "tax_debt_found")["sources"])
        self.assertIn("Opendatabot показує, що ДПС стягує з компанії 1 податковий борг.", reason_block)
        self.assertIn("Виявлено значну кількість виконавчих проваджень", reason_block)
        self.assertIn("Є значна кількість судових згадок", reason_block)
        self.assertIn("Статутний капітал невеликий: 1 000 грн.", reason_block)
        self.assertNotIn("Податковий борг та борг ЄСВ у доступних даних не виявлено.", reason_block)
        self.assertGreaterEqual(enriched.risk_summary.score, 60)

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

        reason_block = response.split("Причини оцінки:", 1)[1].split("Рекомендація:", 1)[0]
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

        reason_block = response.split("Причини оцінки:", 1)[1].split("Рекомендація:", 1)[0]
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
        reason_block = response.split("Причини оцінки:", 1)[1].split("Рекомендація:", 1)[0]
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

        self.assertIn("Сайт постачальника не вдалося відкрити автоматично", response)
        self.assertIn("Це не означає шахрайство", response)
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

        self.assertIn("Судові згадки: багато. Потрібна ручна перевірка змісту справ.", response)
        self.assertNotIn("Судові згадки: 250", response)

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

        self.assertIn("Судові згадки: багато. Потрібна ручна перевірка змісту справ.", response)
        self.assertNotIn("12162", response)

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
            ["court_cases_found", "many_court_mentions_found"],
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
        reason_block = response.split("Причини оцінки:", 1)[1].split("Рекомендація:", 1)[0]
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
        why_block = response.split("Причини оцінки:", 1)[1].split("Рекомендація:", 1)[0].lower()
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
            "⏳ Аналіз може зайняти до 30 секунд.",
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
        self.assertIn("Рекомендація:", message.answers[1])
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
        from app.models.company_lookup import CompanyData, CompanyLookupResult, ProzorroAnalysis, ProzorroStats

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

        self.assertEqual(saved_results[0].risk_summary.score, 0)
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

        reason_block = response.split("Причини оцінки:", 1)[1].split("Рекомендація:", 1)[0]
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

    def test_report_shows_at_most_two_extracted_court_decisions(self):
        from app.bot import format_found_company
        from app.models.company_lookup import CompanyData, CompanyLookupResult, CourtData

        response = format_found_company(
            CompanyLookupResult(
                status="found",
                edrpou="12345678",
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou="12345678"),
                court_data=CourtData(
                    has_court_mentions=True,
                    court_mentions_count=3,
                    decisions=[
                        {
                            "document_type": "Ухвала",
                            "decision_date": "04.05.2026",
                            "case_number": "160/11282/25",
                            "risk_summary": "Документ виглядає як процесуальна ухвала.",
                        },
                        {
                            "document_type": "Ухвала",
                            "decision_date": "05.05.2026",
                            "case_number": "160/11283/25",
                            "risk_summary": "Є ознаки спору щодо стягнення пені.",
                        },
                        {
                            "document_type": "Ухвала",
                            "decision_date": "06.05.2026",
                            "case_number": "160/11284/25",
                            "risk_summary": "Третю ухвалу не треба показувати.",
                        },
                    ],
                ),
            )
        )

        self.assertIn("Судові документи:", response)
        self.assertIn("справа №160/11282/25", response)
        self.assertIn("справа №160/11283/25", response)
        self.assertNotIn("160/11284/25", response)
        self.assertNotIn("Третю ухвалу не треба показувати", response)

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
        self.assertIn("Загальний ризик: низький — 1/100", response)
        self.assertIn("Причини оцінки:", response)
        self.assertIn("✅ Компанія зареєстрована та працює тривалий час.", response)
        self.assertIn("✅ Контактні дані підтверджені відкритими джерелами.", response)
        self.assertIn("⚠️ Є судові згадки: 2. Потрібно оцінювати зміст справ, а не сам факт наявності судових документів.", response)
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

        self.assertIn("Судові згадки: Opendatabot — 11, YouControl — 4", response)
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
