from __future__ import annotations

from typing import Any


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
    "many_court_mentions_found": {
        "weight": 10,
        "label_uk": "Значна кількість судових згадок",
        "description": "Є значна кількість судових згадок у відкритих джерелах.",
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
HARD_FACT_TYPES = {
    "company_not_found",
    "company_inactive",
    "company_in_termination",
    "bankruptcy_found",
    "sanctions_found",
    "large_tax_debt_found",
    "enforcement_found",
    "tax_debt_enforcement_found",
    "salary_debt_enforcement_found",
    "debt_collection_found",
}


def calculate_final_risk(risk_flags: list[Any]) -> dict:
    reasons, signals = dedupe_risk_flags(risk_flags)
    conflicts = build_conflicts(reasons)
    hard_fact_present = any(
        reason["type"] in HARD_FACT_TYPES and reason.get("status") != "conflict"
        for reason in reasons
    )
    score = min(sum(reason["weight"] for reason in reasons), 100)
    if not hard_fact_present:
        score = min(score, NO_HARD_FACT_SCORE_CAP)
    if conflicts:
        score = min(score, CONFLICT_SCORE_CAP)
        level = "manual_review"
    else:
        level = risk_level_from_score(score)
    return {
        "score": score,
        "level": level,
        "label_uk": LEVEL_LABELS_UK[level],
        "reasons": reasons,
        "signals": signals,
        "conflicts": conflicts,
        "manual_review_required": bool(conflicts),
        "hard_fact_present": hard_fact_present,
    }


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

    canonical_type = RISK_FLAG_ALIASES.get(flag_type, flag_type)
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


def risk_level_from_score(score: int) -> str:
    if score <= 20:
        return "low"
    if score <= 50:
        return "medium"
    if score <= 80:
        return "high"
    return "critical"
