from __future__ import annotations

import logging
from typing import Any


logger = logging.getLogger(__name__)


RISK_FLAG_DEFINITIONS: dict[str, dict[str, Any]] = {
    "company_not_found": {
        "weight": 100,
        "label_uk": "Компанію не знайдено",
        "description": "Компанію не знайдено в одному з джерел перевірки.",
    },
    "company_inactive": {
        "weight": 80,
        "label_uk": "Компанія неактивна",
        "description": "Є ознаки неактивного, ліквідованого або анульованого статусу.",
    },
    "company_in_termination": {
        "weight": 70,
        "label_uk": "Компанія у стані припинення",
        "description": "Є ознаки процедури припинення компанії.",
    },
    "bankruptcy_found": {
        "weight": 90,
        "label_uk": "Є ознаки банкрутства",
        "description": "Знайдено згадки або записи, пов'язані з банкрутством.",
    },
    "sanctions_found": {
        "weight": 90,
        "label_uk": "Є санкційні ознаки",
        "description": "Знайдено санкційні або обмежувальні ознаки щодо компанії.",
    },
    "enforcement_found": {
        "weight": 35,
        "label_uk": "Є виконавчі провадження",
        "description": "Знайдено виконавчі провадження або боргові ознаки.",
    },
    "many_enforcement_proceedings_found": {
        "weight": 10,
        "label_uk": "Значна кількість виконавчих проваджень",
        "description": "Знайдено значну кількість виконавчих проваджень.",
    },
    "debtor_registry_found": {
        "weight": 15,
        "label_uk": "Компанія є в Єдиному реєстрі боржників",
        "description": "Компанія знайдена в Єдиному реєстрі боржників.",
    },
    "multiple_debtor_records": {
        "weight": 15,
        "label_uk": "Кілька записів у реєстрі боржників",
        "description": "Знайдено кілька записів у Єдиному реєстрі боржників.",
    },
    "court_fee_enforcement_found": {
        "weight": 10,
        "label_uk": "Стягнення судового збору",
        "description": "Є виконавчі провадження щодо стягнення судового збору.",
    },
    "salary_debt_enforcement_found": {
        "weight": 35,
        "label_uk": "Заборгованість із заробітної плати",
        "description": "Є виконавче провадження щодо заборгованості із заробітної плати.",
    },
    "debt_collection_found": {
        "weight": 45,
        "label_uk": "Стягнення боргу",
        "description": "Є виконавче провадження щодо стягнення коштів або заборгованості.",
    },
    "tax_debt_enforcement_found": {
        "weight": 30,
        "label_uk": "Податковий борг у виконавчому провадженні",
        "description": "Є виконавче провадження або запис щодо податкового боргу.",
    },
    "fine_or_penalty_enforcement_found": {
        "weight": 25,
        "label_uk": "Штраф або пеня у виконавчому провадженні",
        "description": "Є виконавче провадження щодо штрафу, пені або санкції.",
    },
    "tax_debt_found": {
        "weight": 25,
        "label_uk": "Є податковий борг",
        "description": "Джерело показує ознаку податкового або обов'язкового боргу.",
    },
    "large_tax_debt_found": {
        "weight": 45,
        "label_uk": "Суттєвий податковий борг",
        "description": "ДПС або відкриті податкові дані показують суттєву суму податкового боргу.",
    },
    "vat_registration_cancelled": {
        "weight": 35,
        "label_uk": "ПДВ-реєстрацію анульовано",
        "description": "Є ознаки анульованої або скасованої ПДВ-реєстрації.",
    },
    "vat_status_problem": {
        "weight": 25,
        "label_uk": "Проблема з ПДВ-статусом",
        "description": "Податкове джерело показує неоднозначний або проблемний ПДВ-статус.",
    },
    "website_unavailable": {
        "weight": 10,
        "label_uk": "Сайт постачальника недоступний",
        "description": "Сайт постачальника не вдалося відкрити автоматично.",
    },
    "ssl_missing": {
        "weight": 15,
        "label_uk": "HTTPS/SSL не підтверджено",
        "description": "Сайт доступний без підтвердженого HTTPS/SSL.",
    },
    "dns_not_found": {
        "weight": 15,
        "label_uk": "DNS не підтверджено",
        "description": "Для домену сайту не знайдено базових DNS-записів.",
    },
    "suspicious_redirects": {
        "weight": 35,
        "label_uk": "Підозрілі редиректи сайту",
        "description": "Сайт має довгий ланцюг редиректів або переводить на інший домен.",
    },
    "free_email_used": {
        "weight": 15,
        "label_uk": "Безкоштовна email-адреса на сайті",
        "description": "На сайті знайдено тільки безкоштовні email-адреси замість доменної пошти.",
    },
    "company_edrpou_not_found_on_website": {
        "weight": 25,
        "label_uk": "ЄДРПОУ не знайдено на сайті",
        "description": "На сайті постачальника не знайдено ЄДРПОУ компанії.",
    },
    "company_name_not_found_on_website": {
        "weight": 25,
        "label_uk": "Назву компанії не знайдено на сайті",
        "description": "На сайті постачальника не знайдено назву компанії або очевидну коротку форму.",
    },
    "website_address_mismatch": {
        "weight": 35,
        "label_uk": "Адреса на сайті не збігається",
        "description": "Адреса на сайті явно не збігається з даними з реєстрів.",
    },
    "website_phone_mismatch": {
        "weight": 30,
        "label_uk": "Телефон на сайті не збігається",
        "description": "Телефон на сайті суперечить телефонам з інших джерел.",
    },
    "domain_company_mismatch": {
        "weight": 25,
        "label_uk": "Домен не схожий на компанію",
        "description": "Домен або назва сайту не має очевидного зв'язку з компанією.",
    },
    "empty_website": {
        "weight": 20,
        "label_uk": "Порожній сайт",
        "description": "Сайт відкривається, але сторінка порожня або майже без змісту.",
    },
    "website_source_unavailable": {
        "weight": 0,
        "label_uk": "Перевірка сайту недоступна",
        "description": "Технічну перевірку сайту не вдалося виконати.",
    },
    "debt_collection_case": {
        "weight": 35,
        "label_uk": "Справи про стягнення боргу",
        "description": "Є судові згадки, схожі на спори щодо стягнення боргу або санкцій.",
    },
    "contract_nonperformance_case": {
        "weight": 40,
        "label_uk": "Спір щодо невиконання договору",
        "description": "Є судові згадки про можливе невиконання договірних зобов'язань.",
    },
    "criminal_case_found": {
        "weight": 50,
        "label_uk": "Кримінальні згадки",
        "description": "Знайдено судові згадки кримінального характеру.",
    },
    "court_cases_found": {
        "weight": 1,
        "label_uk": "Є судові згадки",
        "description": "Знайдено судові справи або згадки, їх зміст треба перевірити окремо.",
    },
    "several_court_mentions_found": {
        "weight": 7,
        "label_uk": "Кілька судових документів",
        "description": "Знайдено кілька судових документів; потрібна ручна перевірка їх змісту.",
    },
    "many_court_mentions_found": {
        "weight": 10,
        "label_uk": "Значна кількість судових згадок",
        "description": "Є значна кількість судових згадок у відкритих джерелах.",
    },
    "very_many_court_mentions_found": {
        "weight": 0,
        "label_uk": "Дуже велика кількість судових згадок",
        "description": "Є дуже велика кількість судових документів або згадок у відкритих джерелах.",
    },
    "negative_equity_found": {
        "weight": 45,
        "label_uk": "Від’ємний власний капітал",
        "description": "Фінансова звітність показує від’ємний власний капітал.",
    },
    "severe_negative_equity": {
        "weight": 65,
        "label_uk": "Суттєво від’ємний власний капітал",
        "description": "Власний капітал суттєво від’ємний або зобов’язання значно перевищують активи.",
    },
    "liabilities_exceed_assets": {
        "weight": 35,
        "label_uk": "Зобов’язання перевищують активи",
        "description": "Фінансова звітність показує, що зобов’язання перевищують активи.",
    },
    "negative_equity_multiple_years": {
        "weight": 65,
        "label_uk": "Від’ємний власний капітал кілька років",
        "description": "Власний капітал був від’ємним у кількох звітних періодах.",
    },
    "losses_with_negative_equity": {
        "weight": 55,
        "label_uk": "Збиток на фоні від’ємного капіталу",
        "description": "Компанія має збиток і від’ємний власний капітал.",
    },
    "small_loss_found": {
        "weight": 2,
        "label_uk": "Невеликий збиток",
        "description": "Компанія має невеликий збиток, але сам по собі він не є критичним.",
    },
    "medium_loss_found": {
        "weight": 5,
        "label_uk": "Помірний збиток",
        "description": "Компанія має помірний збиток.",
    },
    "large_loss_found": {
        "weight": 10,
        "label_uk": "Значний збиток",
        "description": "Компанія має збиток; його масштаб потрібно оцінювати відносно активів і доходу.",
    },
    "very_large_loss_found": {
        "weight": 20,
        "label_uk": "Великий збиток",
        "description": "Компанія має великий збиток, що потребує уваги.",
    },
    "critical_loss_found": {
        "weight": 35,
        "label_uk": "Критичний збиток",
        "description": "Компанія має критичний збиток відносно активів, доходу або на фоні проблемного балансу.",
    },
    "weak_financial_position": {
        "weight": 40,
        "label_uk": "Слабкий фінансовий стан",
        "description": "Одночасно виявлено кілька сильних фінансових проблем.",
    },
    "positive_profit_found": {
        "weight": 0,
        "label_uk": "Прибуткова діяльність",
        "description": "Фінансова звітність показує прибуток.",
    },
    "positive_equity_found": {
        "weight": 0,
        "label_uk": "Позитивний власний капітал",
        "description": "Фінансова звітність показує позитивний власний капітал.",
    },
    "equity_growth_found": {
        "weight": 0,
        "label_uk": "Зростання власного капіталу",
        "description": "Власний капітал зростає за доступними фінансовими періодами.",
    },
    "assets_exceed_liabilities": {
        "weight": 0,
        "label_uk": "Активи перевищують зобов’язання",
        "description": "Фінансова звітність показує, що активи перевищують зобов’язання.",
    },
    "strong_revenue_found": {
        "weight": 0,
        "label_uk": "Значний дохід",
        "description": "Компанія має значний дохід за останній фінансовий період.",
    },
    "strong_financial_profile": {
        "weight": 0,
        "label_uk": "Стабільний фінансовий профіль",
        "description": "Фінансовий профіль виглядає стабільним: прибуток, позитивний капітал, активи перевищують зобов’язання та є значний дохід.",
    },
    "very_strong_financial_profile": {
        "weight": 0,
        "label_uk": "Дуже сильний фінансовий профіль",
        "description": "Компанія має дуже сильний фінансовий профіль за доходом або активами на фоні здорових фінансових показників.",
    },
    "low_authorized_capital_found": {
        "weight": 8,
        "label_uk": "Дуже низький статутний капітал",
        "description": "Статутний капітал дуже низький.",
    },
    "financial_data_missing": {
        "weight": 12,
        "label_uk": "Повні фінансові показники не знайдено",
        "description": "Повні фінансові показники у доступних джерелах не знайдено.",
    },
    "prozorro_unconfirmed_search_noise": {
        "weight": 2,
        "label_uk": "Багато непідтверджених збігів у Prozorro",
        "description": "У Prozorro є багато пошукових збігів без підтвердженої участі компанії.",
    },
    "weak_public_financial_profile": {
        "weight": 5,
        "label_uk": "Слабко підтверджений публічний фінансовий профіль",
        "description": "Публічний фінансовий профіль слабко підтверджений.",
    },
    "low_statutory_capital_with_debt": {
        "weight": 5,
        "label_uk": "Невеликий статутний капітал на фоні боргових ознак",
        "description": "Статутний капітал невеликий, а також є боргові ознаки.",
    },
    "prozorro_termination_found": {
        "weight": 25,
        "label_uk": "Розірвання в Prozorro",
        "description": "Є ознаки розірваних закупівель або проблемних завершень у Prozorro.",
    },
    "multiple_prozorro_terminations_found": {
        "weight": 35,
        "label_uk": "Кілька розірвань договорів у Prozorro",
        "description": "Знайдено кілька розірвань договорів або високу частку розірваних договорів у Prozorro.",
    },
    "frequent_prozorro_disqualifications": {
        "weight": 20,
        "label_uk": "Часті відхилення в Prozorro",
        "description": "Компанію часто відхиляли в закупівлях або частка відхилень є високою.",
    },
    "supplier_disqualified": {
        "weight": 10,
        "label_uk": "Відхилення постачальника в Prozorro",
        "description": "У Prozorro знайдено факт відхилення пропозиції або неуспішного аварду постачальника.",
    },
    "problematic_documents_found": {
        "weight": 35,
        "label_uk": "Проблемні/недостовірні документи",
        "description": "У причинах відхилення знайдено ознаки проблемних, недостовірних або неналежних документів.",
    },
    "qualification_mismatch_found": {
        "weight": 20,
        "label_uk": "Невідповідність кваліфікаційним вимогам",
        "description": "У Prozorro є ознаки невідповідності кваліфікаційним вимогам закупівлі.",
    },
    "single_buyer_concentration": {
        "weight": 15,
        "label_uk": "Значна концентрація договорів на одному замовнику",
        "description": "Значна частина договорів або суми договорів припадає на одного замовника.",
    },
    "low_competition_wins": {
        "weight": 15,
        "label_uk": "Перемоги у закупівлях з низькою конкуренцією",
        "description": "Компанія часто перемагала у закупівлях з одним учасником або дуже низькою конкуренцією.",
    },
    "frequent_contract_changes": {
        "weight": 10,
        "label_uk": "Часті зміни договорів у Prozorro",
        "description": "За договорами знайдено багато додаткових угод або часті зміни умов.",
    },
    "substantial_contract_amount_increase": {
        "weight": 20,
        "label_uk": "Суттєве збільшення суми договорів у Prozorro",
        "description": "Через зміни договору сума суттєво збільшувалась.",
    },
    "possible_prozorro_dumping": {
        "weight": 10,
        "label_uk": "Можливий демпінг у Prozorro",
        "description": "Компанія неодноразово подавала пропозиції суттєво нижче очікуваної вартості.",
    },
    "supplier_related_prozorro_complaints": {
        "weight": 15,
        "label_uk": "Скарги в Prozorro, пов'язані з постачальником",
        "description": "Знайдено скарги, які прямо стосуються компанії, її документів або дій.",
    },
    "prozorro_sale_risky_auction": {
        "weight": 35,
        "label_uk": "Ризиковий аукціон Prozorro.Sale",
        "description": "У Prozorro.Sale знайдено підтверджений аукціон з негативним маркером.",
    },
    "prozorro_sale_failed_obligations": {
        "weight": 45,
        "label_uk": "Невиконання умов у Prozorro.Sale",
        "description": "У Prozorro.Sale знайдено підтверджений маркер невиконання умов переможцем.",
    },
    "prozorro_sale_refusal_to_sign": {
        "weight": 45,
        "label_uk": "Відмова від підписання у Prozorro.Sale",
        "description": "У Prozorro.Sale знайдено підтверджений маркер відмови або непідписання документів.",
    },
    "prozorro_sale_disqualified_winner": {
        "weight": 45,
        "label_uk": "Дискваліфікація переможця у Prozorro.Sale",
        "description": "У Prozorro.Sale знайдено підтверджений маркер дискваліфікації переможця.",
    },
    "prozorro_sale_nonpayment": {
        "weight": 45,
        "label_uk": "Несплата у Prozorro.Sale",
        "description": "У Prozorro.Sale знайдено підтверджений маркер несплати або невнесення платежу.",
    },
    "prozorro_sale_multiple_unsuccessful_auctions": {
        "weight": 0,
        "label_uk": "Повторні або неуспішні аукціони Prozorro.Sale",
        "description": "У Prozorro.Sale знайдено неуспішний або повторний аукціон, але негативної дії саме з боку компанії не підтверджено.",
    },
    "prozorro_sale_bankruptcy_asset_sale": {
        "weight": 70,
        "label_uk": "Продаж майна банкрута у Prozorro.Sale",
        "description": "У Prozorro.Sale знайдено підтверджений продаж майна, пов’язаного з ліквідаційною масою або банкрутством.",
    },
    "prozorro_sale_debtor_mention": {
        "weight": 0,
        "label_uk": "Інформаційна згадка в Prozorro.Sale",
        "description": "Компанія згадується у складі дебіторської заборгованості банкрута. Це не означає банкрутство самої компанії.",
    },
    "prozorro_sale_informational_auction_mention": {
        "weight": 0,
        "label_uk": "Інформаційна згадка аукціону Prozorro.Sale",
        "description": "У Prozorro.Sale знайдено аукціон з участю або згадкою компанії, але негативної дії саме з боку компанії не підтверджено.",
    },
    "prozorro_search_results_found": {
        "weight": 0,
        "label_uk": "Пошукові результати Prozorro",
        "description": "У пошуку Prozorro є результати без підтвердженого негативного факту щодо компанії.",
    },
    "young_company": {
        "weight": 15,
        "label_uk": "Молода компанія",
        "description": "Компанія зареєстрована відносно недавно.",
    },
    "kved_mismatch": {
        "weight": 20,
        "label_uk": "КВЕД може не відповідати",
        "description": "Основний КВЕД може не відповідати предмету співпраці.",
    },
    "data_mismatch_between_sources": {
        "weight": 20,
        "label_uk": "Дані відрізняються між джерелами",
        "description": "Різні джерела повернули неузгоджені дані.",
    },
    "company_status_mismatch": {
        "weight": 50,
        "label_uk": "Конфлікт статусу компанії між джерелами",
        "description": "Одне джерело показує компанію зареєстрованою, а інше вказує на припинення, ліквідацію або банкрутство.",
    },
    "tax_debt_source_mismatch": {
        "weight": 0,
        "label_uk": "Розбіжність щодо податкового боргу",
        "description": "Одне джерело показує податкове стягнення, а інше не підтверджує податковий борг.",
    },
    "source_unavailable": {
        "weight": 0,
        "label_uk": "Джерело недоступне",
        "description": "Одне з джерел тимчасово недоступне або обмежило автоматичний доступ.",
    },
}

RISK_FLAG_ALIASES = {
    "company_not_registered_or_inactive": "company_inactive",
    "company_not_registered": "company_inactive",
    "inactive_company": "company_inactive",
    "enforcement_proceeding_found": "enforcement_found",
    "multiple_enforcement_proceedings": "enforcement_found",
    "court_mentions_found": "court_cases_found",
    "esv_debt_found": "tax_debt_found",
}

LEVEL_LABELS_UK = {
    "low": "Низький ризик",
    "medium": "Середній ризик",
    "high": "Високий ризик",
    "critical": "Критичний ризик",
    "manual_review": "Потребує ручної перевірки",
}

NO_HARD_FACT_SCORE_CAP = 65
CONFLICT_SCORE_CAP = 65
NON_MAXIMUM_TOP_SCORE_CAP = 80
HARD_FACT_TYPES = {
    "company_not_found",
    "company_inactive",
    "company_in_termination",
    "bankruptcy_found",
    "sanctions_found",
    "negative_equity_found",
    "severe_negative_equity",
    "liabilities_exceed_assets",
    "negative_equity_multiple_years",
    "losses_with_negative_equity",
    "weak_financial_position",
    "large_tax_debt_found",
    "enforcement_found",
    "tax_debt_enforcement_found",
    "salary_debt_enforcement_found",
    "debt_collection_found",
    "prozorro_sale_failed_obligations",
    "prozorro_sale_refusal_to_sign",
    "prozorro_sale_disqualified_winner",
    "prozorro_sale_nonpayment",
    "prozorro_sale_bankruptcy_asset_sale",
}
MAXIMUM_RISK_SINGLE_FACT_TYPES = {
    "company_not_found",
}
TERMINAL_CRITICAL_FACT_TYPES = {
    "bankruptcy_found",
    "sanctions_found",
    "company_inactive",
    "company_in_termination",
}
SUPPORTING_CRITICAL_FACT_TYPES = {
    "enforcement_found",
    "tax_debt_enforcement_found",
    "salary_debt_enforcement_found",
    "debt_collection_found",
    "large_tax_debt_found",
    "severe_negative_equity",
    "negative_equity_multiple_years",
    "losses_with_negative_equity",
    "weak_financial_position",
    "prozorro_sale_failed_obligations",
    "prozorro_sale_refusal_to_sign",
    "prozorro_sale_disqualified_winner",
    "prozorro_sale_nonpayment",
    "prozorro_sale_bankruptcy_asset_sale",
}
NEGATIVE_FINANCIAL_REASON_TYPES = {
    "negative_equity_found",
    "severe_negative_equity",
    "liabilities_exceed_assets",
    "negative_equity_multiple_years",
    "losses_with_negative_equity",
    "small_loss_found",
    "medium_loss_found",
    "large_loss_found",
    "very_large_loss_found",
    "critical_loss_found",
    "weak_financial_position",
}
POSITIVE_FINANCIAL_REDUCER_TYPES = {
    "strong_financial_profile",
    "very_strong_financial_profile",
}
POSITIVE_FINANCIAL_REDUCER_BLOCKING_TYPES = {
    "bankruptcy_found",
    "sanctions_found",
    "company_inactive",
    "company_in_termination",
    "criminal_case_found",
}
SIGNIFICANT_DEBT_OR_ENFORCEMENT_TYPES = {
    "large_tax_debt_found",
    "enforcement_found",
    "many_enforcement_proceedings_found",
    "tax_debt_enforcement_found",
    "salary_debt_enforcement_found",
    "debt_collection_found",
}
SIGNIFICANT_DEBT_REDUCER_FLOOR = 50
STRONG_FINANCIAL_PROFILE_REDUCER = 8
VERY_STRONG_FINANCIAL_PROFILE_REDUCER = 15
MAXIMUM_INFORMATION_FLOOR = 10
MINIMUM_COMPANY_SCORE = 5
INFORMATION_FLOORS_BY_TYPE = {
    "court_cases_found": 1,
    "several_court_mentions_found": 8,
    "many_court_mentions_found": 5,
    "very_many_court_mentions_found": 8,
    "prozorro_sale_debtor_mention": 3,
    "prozorro_sale_informational_auction_mention": 3,
    "prozorro_search_results_found": 1,
}


def calculate_final_risk(risk_flags: list[Any]) -> dict:
    reasons, signals = dedupe_risk_flags(risk_flags)
    conflicts = build_conflicts(reasons)
    hard_fact_present = any(
        reason["type"] in HARD_FACT_TYPES and reason.get("status") != "conflict"
        for reason in reasons
    )
    maximum_risk_confirmed = has_maximum_risk_cluster(reasons)
    terminal_critical_fact_present = has_terminal_critical_fact(reasons)
    raw_score = min(sum(reason["weight"] for reason in reasons), 100)
    score = raw_score
    applied_caps: list[str] = []
    cap_reason: str | None = None
    if not hard_fact_present:
        score = min(score, NO_HARD_FACT_SCORE_CAP)
        applied_caps.append("no_hard_fact_score_cap")
        cap_reason = "no_hard_fact"
    if not maximum_risk_confirmed and not terminal_critical_fact_present and score >= 90:
        score = min(score, NON_MAXIMUM_TOP_SCORE_CAP)
        applied_caps.append("non_maximum_top_score_cap")
        cap_reason = cap_reason or "non_maximum_top_score"
    elif not maximum_risk_confirmed and score >= 100:
        score = min(score, NON_MAXIMUM_TOP_SCORE_CAP)
        applied_caps.append("non_maximum_top_score_cap")
        cap_reason = cap_reason or "non_maximum_top_score"
    if conflicts:
        score = min(score, CONFLICT_SCORE_CAP)
        applied_caps.append("conflict_score_cap")
        cap_reason = "conflict"
        level = "manual_review"
        positive_financial_reducer = 0
        positive_financial_reducer_floor = None
        positive_financial_reducer_blocked_by = []
        score_after_reducer = score
        information_floor = 0
        minimum_score_floor = MINIMUM_COMPANY_SCORE
        score = max(score, minimum_score_floor)
    else:
        max_hard_flag_weight = max_hard_weight(reasons)
        score = max(score, max_hard_flag_weight)
        score = apply_minimum_hard_fact_score(score, reasons)
        positive_financial_reducer, positive_financial_reducer_blocked_by = positive_financial_reducer_amount(reasons)
        score, positive_financial_reducer_floor = apply_positive_financial_reducer(
            score,
            reasons,
            positive_financial_reducer,
        )
        score_after_reducer = score
        information_floor = calculate_information_floor(reasons)
        minimum_score_floor = MINIMUM_COMPANY_SCORE
        score = max(score_after_reducer, information_floor, minimum_score_floor)
        level = risk_level_from_score(score)
    max_hard_flag_weight = max_hard_weight(reasons)
    hard_flags = [
        reason["type"]
        for reason in reasons
        if reason["type"] in HARD_FACT_TYPES and reason.get("status") != "conflict"
    ]
    applied_flags = [reason["type"] for reason in reasons]
    logger.info(
        "Risk score breakdown raw_score=%s final_score=%s level=%s applied_flags=%s "
        "applied_caps=%s hard_flags=%s max_hard_flag_weight=%s cap_reason=%s "
        "positive_financial_reducer=%s positive_financial_reducer_floor=%s "
        "positive_financial_reducer_blocked_by=%s score_after_reducer=%s "
        "information_floor=%s minimum_score_floor=%s",
        raw_score,
        score,
        level,
        applied_flags,
        applied_caps,
        hard_flags,
        max_hard_flag_weight,
        cap_reason,
        positive_financial_reducer,
        positive_financial_reducer_floor,
        positive_financial_reducer_blocked_by,
        score_after_reducer,
        information_floor,
        minimum_score_floor,
    )
    return {
        "score": score,
        "raw_score": raw_score,
        "final_score": score,
        "level": level,
        "label_uk": LEVEL_LABELS_UK[level],
        "reasons": reasons,
        "signals": signals,
        "conflicts": conflicts,
        "manual_review_required": bool(conflicts),
        "hard_fact_present": hard_fact_present,
        "maximum_risk_confirmed": maximum_risk_confirmed,
        "terminal_critical_fact_present": terminal_critical_fact_present,
        "applied_caps": applied_caps,
        "hard_flags": hard_flags,
        "applied_flags": applied_flags,
        "max_hard_flag_weight": max_hard_flag_weight,
        "cap_reason": cap_reason,
        "positive_financial_reducer": positive_financial_reducer,
        "positive_financial_reducer_floor": positive_financial_reducer_floor,
        "positive_financial_reducer_blocked_by": positive_financial_reducer_blocked_by,
        "score_after_reducer": score_after_reducer,
        "information_floor": information_floor,
        "minimum_score_floor": minimum_score_floor,
    }


def max_hard_weight(reasons: list[dict]) -> int:
    hard_weights = [
        reason["weight"]
        for reason in reasons
        if reason["type"] in HARD_FACT_TYPES and reason.get("status") != "conflict"
    ]
    return max(hard_weights, default=0)


def positive_financial_reducer_amount(reasons: list[dict]) -> tuple[int, list[str]]:
    found_types = {
        reason["type"]
        for reason in reasons
        if reason.get("status") != "conflict"
    }
    if not found_types.intersection(POSITIVE_FINANCIAL_REDUCER_TYPES):
        return 0, []

    blocked_by = sorted(found_types.intersection(POSITIVE_FINANCIAL_REDUCER_BLOCKING_TYPES | NEGATIVE_FINANCIAL_REASON_TYPES))
    if blocked_by:
        return 0, blocked_by

    if "very_strong_financial_profile" in found_types:
        return VERY_STRONG_FINANCIAL_PROFILE_REDUCER, []
    if "strong_financial_profile" in found_types:
        return STRONG_FINANCIAL_PROFILE_REDUCER, []
    return 0, []


def apply_positive_financial_reducer(score: int, reasons: list[dict], reducer: int) -> tuple[int, int | None]:
    if reducer <= 0 or score <= 0:
        return score, None

    floor = positive_financial_reducer_floor(reasons)
    reduced_score = max(score - reducer, 0)
    if floor is not None:
        if score <= floor:
            return score, floor
        reduced_score = max(reduced_score, floor)
    return min(score, reduced_score), floor


def positive_financial_reducer_floor(reasons: list[dict]) -> int | None:
    found_types = {
        reason["type"]
        for reason in reasons
        if reason.get("status") != "conflict"
    }
    if found_types.intersection(SIGNIFICANT_DEBT_OR_ENFORCEMENT_TYPES):
        return SIGNIFICANT_DEBT_REDUCER_FLOOR
    return None


def calculate_information_floor(reasons: list[dict]) -> int:
    floor = 0
    for reason in reasons:
        if reason.get("status") == "conflict":
            continue
        floor = max(floor, INFORMATION_FLOORS_BY_TYPE.get(reason["type"], 0))
    return min(floor, MAXIMUM_INFORMATION_FLOOR)


def apply_minimum_hard_fact_score(score: int, reasons: list[dict]) -> int:
    found_types = {
        reason["type"]
        for reason in reasons
        if reason.get("status") != "conflict"
    }
    if "bankruptcy_found" in found_types:
        score = max(score, 80)
    if {"bankruptcy_found", "company_in_termination"}.issubset(found_types):
        score = max(score, 90)
    if {"bankruptcy_found", "prozorro_sale_bankruptcy_asset_sale"}.issubset(found_types):
        score = max(score, 90)
    return score


def has_maximum_risk_cluster(reasons: list[dict]) -> bool:
    found_types = {
        reason["type"]
        for reason in reasons
        if reason.get("status") != "conflict"
    }
    if found_types.intersection(MAXIMUM_RISK_SINGLE_FACT_TYPES):
        return True
    return bool(
        found_types.intersection(TERMINAL_CRITICAL_FACT_TYPES)
        and found_types.intersection(SUPPORTING_CRITICAL_FACT_TYPES)
    )


def has_terminal_critical_fact(reasons: list[dict]) -> bool:
    return any(
        reason["type"] in TERMINAL_CRITICAL_FACT_TYPES and reason.get("status") != "conflict"
        for reason in reasons
    )


def dedupe_risk_flags(risk_flags: list[Any]) -> tuple[list[dict], list[dict]]:
    deduped: dict[str, dict] = {}
    signals: list[dict] = []
    for raw_flag in risk_flags:
        normalized = normalize_risk_flag(raw_flag)
        if normalized is None:
            continue
        flag_type = normalized["type"]
        source = normalized["source"]
        status = normalized["status"]
        signal = {
            "status": status,
            "source": source,
            "type": flag_type,
            "confidence": normalized.get("confidence") or "medium",
            "raw_text": normalized.get("raw_text"),
            "matched_pattern": normalized.get("matched_pattern"),
            "match_type": normalized.get("match_type"),
            "checked_at": normalized.get("checked_at"),
        }
        signals.append(signal)
        if flag_type not in deduped:
            definition = RISK_FLAG_DEFINITIONS[flag_type]
            deduped[flag_type] = {
                "type": flag_type,
                "sources": [],
                "found_sources": [],
                "not_found_sources": [],
                "evidence": [],
                "weight": definition["weight"],
                "label_uk": definition["label_uk"],
                "description": normalized.get("description") or definition["description"],
                "status": "found",
            }
        if source and source not in deduped[flag_type]["sources"]:
            deduped[flag_type]["sources"].append(source)
        if status == "not_found":
            if source and source not in deduped[flag_type]["not_found_sources"]:
                deduped[flag_type]["not_found_sources"].append(source)
        else:
            if source and source not in deduped[flag_type]["found_sources"]:
                deduped[flag_type]["found_sources"].append(source)
        deduped[flag_type]["evidence"].append(signal)

    reasons: list[dict] = []
    for reason in deduped.values():
        if not reason["found_sources"]:
            continue
        if reason["not_found_sources"]:
            reason["status"] = "conflict"
            reason["weight"] = min(reason["weight"], 45)
            reason["description"] = f"Джерела суперечать одне одному щодо ознаки: {reason['label_uk'].lower()}."
        reasons.append(reason)
    return reasons, signals


def build_conflicts(reasons: list[dict]) -> list[dict]:
    conflicts: list[dict] = []
    for reason in reasons:
        if reason.get("status") != "conflict":
            continue
        conflicts.append(
            {
                "type": reason["type"],
                "label_uk": reason["label_uk"],
                "found_sources": reason.get("found_sources", []),
                "not_found_sources": reason.get("not_found_sources", []),
                "description": reason["description"],
            }
        )
    return conflicts


def normalize_risk_flag(raw_flag: Any) -> dict | None:
    if raw_flag is None:
        return None
    if isinstance(raw_flag, str):
        flag_type = raw_flag
        source = None
        description = None
    elif isinstance(raw_flag, dict):
        flag_type = raw_flag.get("type") or raw_flag.get("code")
        source = raw_flag.get("source")
        sources = raw_flag.get("sources")
        if source is None and sources:
            source = sources[0]
        description = raw_flag.get("text") or raw_flag.get("description")
        status = raw_flag.get("status") or "found"
        confidence = raw_flag.get("confidence")
        raw_text = raw_flag.get("raw_text") or raw_flag.get("text")
        matched_pattern = raw_flag.get("matched_pattern")
        match_type = raw_flag.get("match_type")
        checked_at = raw_flag.get("checked_at")
    else:
        flag_type = getattr(raw_flag, "type", None) or getattr(raw_flag, "code", None)
        source = getattr(raw_flag, "source", None)
        sources = getattr(raw_flag, "sources", None)
        if source is None and sources:
            source = sources[0]
        description = getattr(raw_flag, "text", None)
        status = getattr(raw_flag, "status", "found")
        confidence = getattr(raw_flag, "confidence", None)
        raw_text = getattr(raw_flag, "raw_text", None) or description
        matched_pattern = getattr(raw_flag, "matched_pattern", None)
        match_type = getattr(raw_flag, "match_type", None)
        checked_at = getattr(raw_flag, "checked_at", None)

    if isinstance(raw_flag, str):
        status = "found"
        confidence = None
        raw_text = None
        matched_pattern = None
        match_type = None
        checked_at = None

    if not flag_type:
        return None

    canonical_type = classify_prozorro_sale_flag(flag_type, raw_text) or RISK_FLAG_ALIASES.get(flag_type, flag_type)
    if canonical_type in {
        "source_unavailable",
        "tax_source_unavailable",
        "website_source_unavailable",
        "vat_payer_found",
        "vat_not_found",
    }:
        return None
    if canonical_type not in RISK_FLAG_DEFINITIONS:
        return None
    return {
        "type": canonical_type,
        "source": source,
        "description": description,
        "status": status if status in {"found", "not_found", "conflict", "unknown"} else "found",
        "confidence": confidence,
        "raw_text": raw_text,
        "matched_pattern": matched_pattern,
        "match_type": match_type,
        "checked_at": checked_at,
    }


def classify_prozorro_sale_flag(flag_type: str, raw_text: str | None) -> str | None:
    canonical_type = RISK_FLAG_ALIASES.get(flag_type, flag_type)
    if canonical_type != "prozorro_sale_risky_auction":
        return None

    lowered = (raw_text or "").casefold()
    if any(marker in lowered for marker in ("ліквідаційна маса", "ліквідаційної маси", "банкрут")):
        return "prozorro_sale_bankruptcy_asset_sale"
    if any(marker in lowered for marker in ("переможець не виконав умови", "не виконав умови")):
        return "prozorro_sale_failed_obligations"
    if any(marker in lowered for marker in ("дискваліф", "відхилен")):
        return "prozorro_sale_disqualified_winner"
    if any(marker in lowered for marker in ("несплат", "не сплат", "не вніс оплат")):
        return "prozorro_sale_nonpayment"
    if any(
        marker in lowered
        for marker in (
            "відмова від підписання",
            "не підписав протокол",
            "не підписав договір",
        )
    ):
        return "prozorro_sale_refusal_to_sign"
    if any(
        marker in lowered
        for marker in (
            "аукціон не відбувся",
            "торги не відбулися",
            "не відбувся",
            "повторний аукціон",
            "повторні торги",
        )
    ):
        return "prozorro_sale_informational_auction_mention"
    return canonical_type


def risk_level_from_score(score: int) -> str:
    if score <= 20:
        return "low"
    if score <= 50:
        return "medium"
    if score <= 80:
        return "high"
    return "critical"
