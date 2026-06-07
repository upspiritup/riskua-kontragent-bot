from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from app.models.company_lookup import ProzorroAnalysis, ProzorroProcurement, ProzorroStats


SOURCE = "prozorro_analysis"
NONPERFORMANCE_MARKERS = [
    "refusal to supply",
    "deadline breach",
    "failed to supply",
    "nonperformance",
    "poor quality",
    "nonconforming quality",
    "quality issue",
    "\u0432\u0456\u0434\u043c\u043e\u0432\u0430 \u0432\u0456\u0434 \u043f\u043e\u0441\u0442\u0430\u0447\u0430\u043d\u043d\u044f",
    "\u043f\u043e\u0440\u0443\u0448\u0435\u043d\u043d\u044f \u0441\u0442\u0440\u043e\u043a",
    "\u043d\u0435\u0432\u0438\u043a\u043e\u043d\u0430\u043d\u043d\u044f",
    "\u043d\u0435\u043d\u0430\u043b\u0435\u0436\u043d\u0430 \u044f\u043a\u0456\u0441\u0442\u044c",
    "\u043d\u0438\u0437\u044c\u043a\u0430 \u044f\u043a\u0456\u0441\u0442\u044c",
    "\u044f\u043a\u0456\u0441\u0442\u044c \u043f\u043e\u0441\u0442\u0430\u0432\u043a\u0438",
]
DISQUALIFICATION_REASON_FLAGS = {
    "large_tax_debt_found": [
        "large tax debt",
        "significant tax debt",
        "\u0437\u043d\u0430\u0447\u043d\u0438\u0439 \u043f\u043e\u0434\u0430\u0442\u043a\u043e\u0432\u0438\u0439 \u0431\u043e\u0440\u0433",
        "\u0432\u0435\u043b\u0438\u043a\u0438\u0439 \u043f\u043e\u0434\u0430\u0442\u043a\u043e\u0432\u0438\u0439 \u0431\u043e\u0440\u0433",
    ],
    "tax_debt_found": [
        "tax debt is present",
        "tax debt found",
        "\u043f\u043e\u0434\u0430\u0442\u043a\u043e\u0432\u0438\u0439 \u0431\u043e\u0440\u0433",
        "\u0437\u0430\u0431\u043e\u0440\u0433\u043e\u0432\u0430\u043d\u0456\u0441\u0442\u044c \u0437 \u043f\u043e\u0434\u0430\u0442\u043a",
    ],
    "bankruptcy_found": [
        "bankrupt",
        "bankruptcy",
        "\u0431\u0430\u043d\u043a\u0440\u0443\u0442",
    ],
    "sanctions_found": [
        "sanction",
        "\u0441\u0430\u043d\u043a\u0446",
    ],
    "problematic_documents_found": [
        "problematic documents",
        "invalid documents",
        "missing documents",
        "\u043d\u0435\u0432\u0456\u0434\u043f\u043e\u0432\u0456\u0434\u043d\u0456 \u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442",
        "\u043f\u0440\u043e\u0431\u043b\u0435\u043c\u043d\u0456 \u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442",
    ],
    "qualification_mismatch_found": [
        "qualification mismatch",
        "does not meet qualification",
        "\u043d\u0435 \u0432\u0456\u0434\u043f\u043e\u0432\u0456\u0434\u0430\u0454 \u043a\u0432\u0430\u043b\u0456\u0444\u0456\u043a\u0430\u0446",
        "\u043a\u0432\u0430\u043b\u0456\u0444\u0456\u043a\u0430\u0446\u0456\u0439\u043d\u0438\u043c \u043a\u0440\u0438\u0442\u0435\u0440\u0456\u044f\u043c",
    ],
}
CPV_GROUPS = {
    "medical": {
        "cpv_prefixes": ("331", "336", "380"),
        "keywords": (
            "medical",
            "laboratory",
            "lab ",
            "medicine",
            "hospital",
            "медич",
            "лаборатор",
            "лікар",
        ),
    },
    "fuel": {
        "cpv_prefixes": ("091", "092"),
        "keywords": ("fuel", "gasoline", "diesel", "petrol", "палив", "бензин", "дизел"),
    },
    "food": {
        "cpv_prefixes": ("15",),
        "keywords": ("food", "meat", "bread", "milk", "харч", "продукт", "молок", "хліб"),
    },
    "construction": {
        "cpv_prefixes": ("45",),
        "keywords": ("construction", "repair", "будів", "ремонт"),
    },
    "office": {
        "cpv_prefixes": ("301",),
        "keywords": ("office", "paper", "stationery", "офіс", "папер", "канцеляр"),
    },
}
KVED_GROUPS = {
    "medical": ("медич", "фармац", "лаборатор", "лікар"),
    "fuel": ("палив", "нафт", "бензин", "дизел"),
    "food": ("харч", "продукт", "молок", "м'яс", "хліб"),
    "construction": ("будів", "ремонт"),
    "office": ("офіс", "папер", "канцеляр"),
}
PRESENCE_NOTE = (
    "Компанія фігурує у публічних закупівлях. Сам факт участі не є ризиком, "
    "але дозволяє оцінити досвід, дисципліну та виконання договорів."
)
NO_WINS_NOTE = (
    "Компанія брала участь у закупівлях, але перемог не має. Це не підтверджує "
    "успішний досвід виконання державних контрактів."
)


def analyze_prozorro_data(
    data: list[dict[str, Any]] | dict[str, Any] | list[ProzorroProcurement] | None,
    *,
    company_context: dict[str, Any] | None = None,
) -> ProzorroAnalysis:
    checked_at = datetime.now(UTC)
    procurements, warnings, source_error = normalize_procurements(data)
    if source_error:
        return ProzorroAnalysis(
            status="source_error",
            summary="Prozorro-дані недоступні. Score не підвищено.",
            parse_warnings=warnings,
            error=source_error,
            checked_at=checked_at,
        )
    if not procurements:
        return ProzorroAnalysis(
            status="not_found",
            summary="Prozorro-дані відсутні або не передані. Score не підвищено.",
            parse_warnings=warnings,
            checked_at=checked_at,
        )

    stats = calculate_stats(procurements)
    notes = [PRESENCE_NOTE]
    if stats.participations_count >= 3 and stats.wins_count == 0:
        notes.append(NO_WINS_NOTE)

    add_context_notes(notes, procurements, stats, checked_at, company_context or {})

    risk_flags = build_risk_flags(procurements, stats, company_context or {})

    return ProzorroAnalysis(
        status="partial" if warnings else "found",
        stats=stats,
        procurements=procurements,
        risk_flags=risk_flags,
        info_notes=notes,
        summary=build_summary(stats),
        parse_warnings=warnings,
        checked_at=checked_at,
    )


def build_risk_flags(
    procurements: list[ProzorroProcurement],
    stats: ProzorroStats,
    company_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    terminated = [item for item in procurements if item.contract_terminated]
    disqualified = [item for item in procurements if item.disqualified]

    if terminated:
        flags.append(
            risk_flag(
                "prozorro_termination_found",
                terminated[0].termination_reason or terminated[0].procurement_id or "terminated contract",
                "contract_terminated",
            )
        )
    if stats.terminated_contracts_count >= 2 or (
        stats.termination_rate_percent is not None and stats.termination_rate_percent >= 30
    ):
        flags.append(
            risk_flag(
                "multiple_prozorro_terminations_found",
                f"terminated contracts: {stats.terminated_contracts_count}; termination rate: {stats.termination_rate_percent}%",
                "terminated_contracts_count>=2_or_termination_rate>=30",
            )
        )

    for item in terminated:
        reason = item.termination_reason or ""
        marker = text_has_marker(reason, NONPERFORMANCE_MARKERS)
        if marker:
            flags.append(risk_flag("contract_nonperformance_case", reason, marker))

    if stats.disqualifications_count >= 3 or (
        stats.disqualification_rate_percent is not None and stats.disqualification_rate_percent > 50
    ):
        flags.append(
            risk_flag(
                "frequent_prozorro_disqualifications",
                (
                    f"disqualifications: {stats.disqualifications_count}; "
                    f"disqualification rate: {stats.disqualification_rate_percent}%"
                ),
                "disqualifications_count>=3_or_disqualification_rate>50",
            )
        )

    for item in disqualified:
        reason = item.disqualification_reason or ""
        for flag_type, markers in DISQUALIFICATION_REASON_FLAGS.items():
            if flag_type == "tax_debt_found" and text_has_marker(
                reason, DISQUALIFICATION_REASON_FLAGS["large_tax_debt_found"]
            ):
                continue
            marker = text_has_marker(reason, markers)
            if marker:
                flags.append(risk_flag(flag_type, reason, marker))

    if stats.contracts_count >= 5 and (
        (stats.single_buyer_contract_share_percent or 0) >= 80
        or (stats.single_buyer_value_share_percent or 0) >= 80
    ):
        flags.append(
            risk_flag(
                "single_buyer_concentration",
                (
                    "single buyer contract share: "
                    f"{stats.single_buyer_contract_share_percent}%; value share: "
                    f"{stats.single_buyer_value_share_percent}%"
                ),
                "single_buyer_share>=80",
            )
        )

    if stats.wins_count >= 5 and rate(stats.low_competition_wins_count, stats.wins_count) >= 60:
        flags.append(
            risk_flag(
                "low_competition_wins",
                f"low competition wins: {stats.low_competition_wins_count} of {stats.wins_count}",
                "wins>=5_and_low_competition_share>=60",
            )
        )

    total_amendments = sum(item.amendments_count for item in procurements if item.has_contract or item.contract_terminated)
    average_amendments = total_amendments / stats.contracts_count if stats.contracts_count else 0
    if stats.contracts_count >= 5 and (total_amendments >= 10 or average_amendments >= 3):
        flags.append(
            risk_flag(
                "frequent_contract_changes",
                f"contract amendments: {total_amendments}; average: {round(average_amendments, 2)}",
                "contracts>=5_and_amendments>=10_or_average>=3",
            )
        )

    amount_increase = next(
        (
            item
            for item in procurements
            if item.contract_amount_change_percent is not None and item.contract_amount_change_percent >= 20
        ),
        None,
    )
    if amount_increase:
        flags.append(
            risk_flag(
                "substantial_contract_amount_increase",
                f"contract amount change percent: {amount_increase.contract_amount_change_percent}",
                "contract_amount_change_percent>=20",
            )
        )

    if stats.high_discount_bids_count >= 2:
        flags.append(
            risk_flag(
                "possible_prozorro_dumping",
                f"high discount bids: {stats.high_discount_bids_count}",
                "bid_value<=50_percent_of_expected_value_count>=2",
            )
        )

    if stats.supplier_related_complaints_count > 0:
        flags.append(
            risk_flag(
                "supplier_related_prozorro_complaints",
                f"supplier related complaints: {stats.supplier_related_complaints_count}",
                "supplier_related_complaints_count>0",
            )
        )

    if is_kved_mismatch(procurements, company_context or {}):
        flags.append(
            risk_flag(
                "kved_mismatch",
                "procurement CPV group does not match declared company activity",
                "classified_cpv_group_not_in_company_activity_groups",
            )
        )

    return dedupe_flags(flags)


def add_context_notes(
    notes: list[str],
    procurements: list[ProzorroProcurement],
    stats: ProzorroStats,
    checked_at: datetime,
    company_context: dict[str, Any],
) -> None:
    if stats.contracts_count >= 5 and (
        (stats.single_buyer_contract_share_percent or 0) >= 80
        or (stats.single_buyer_value_share_percent or 0) >= 80
    ):
        notes.append("Значна частина контрактів пов'язана з одним замовником.")

    if stats.last_participation_date and is_older_than_years(stats.last_participation_date, checked_at.date(), 3):
        notes.append("Остання участь у Prozorro була давно; актуальний досвід може бути обмеженим.")

    if company_context and cpv_kved_match_status(procurements, company_context) == "uncertain":
        notes.append("Неможливо впевнено визначити відповідність CPV основним видам діяльності компанії.")


def risk_flag(flag_type: str, raw_text: str, matched_pattern: str) -> dict[str, Any]:
    return {
        "type": flag_type,
        "source": SOURCE,
        "status": "found",
        "confidence": "medium",
        "raw_text": raw_text,
        "matched_pattern": matched_pattern,
        "match_type": "positive_match",
    }


def dedupe_flags(flags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique_flags: list[dict[str, Any]] = []
    seen: set[str] = set()
    for flag in flags:
        flag_type = str(flag.get("type") or "")
        if not flag_type or flag_type in seen:
            continue
        unique_flags.append(flag)
        seen.add(flag_type)
    return unique_flags


def text_has_marker(text: str | None, markers: list[str]) -> str | None:
    normalized = (text or "").casefold()
    for marker in markers:
        if marker.casefold() in normalized:
            return marker
    return None


def is_kved_mismatch(procurements: list[ProzorroProcurement], company_context: dict[str, Any]) -> bool:
    return cpv_kved_match_status(procurements, company_context) == "mismatch"


def cpv_kved_match_status(procurements: list[ProzorroProcurement], company_context: dict[str, Any]) -> str:
    procurement_groups = classified_procurement_groups(procurements)
    company_groups = classified_company_groups(company_context)
    if not procurement_groups or not company_groups:
        return "uncertain"

    top_group, top_count = max(procurement_groups.items(), key=lambda item: item[1])
    classified_count = sum(procurement_groups.values())
    if top_group in company_groups:
        return "match"
    if classified_count >= 2 and top_count / classified_count >= 0.6:
        return "mismatch"
    return "uncertain"


def classified_procurement_groups(procurements: list[ProzorroProcurement]) -> dict[str, int]:
    groups: dict[str, int] = {}
    for item in procurements:
        group = classify_procurement_group(item)
        if group:
            groups[group] = groups.get(group, 0) + 1
    return groups


def classify_procurement_group(item: ProzorroProcurement) -> str | None:
    cpv_digits = "".join(character for character in (item.cpv_code or "") if character.isdigit())
    text = " ".join(part for part in [item.title, item.cpv_name] if part).casefold()
    for group, rules in CPV_GROUPS.items():
        if cpv_digits and any(cpv_digits.startswith(prefix) for prefix in rules["cpv_prefixes"]):
            return group
        if any(keyword.casefold() in text for keyword in rules["keywords"]):
            return group
    return None


def classified_company_groups(company_context: dict[str, Any]) -> set[str]:
    activity_parts: list[str] = []
    for key in ("main_activity_name", "main_activity", "kved_name"):
        value = company_context.get(key)
        if value:
            activity_parts.append(str(value))
    additional = company_context.get("additional_activities") or []
    if isinstance(additional, list):
        for activity in additional:
            if isinstance(activity, dict):
                value = activity.get("name") or activity.get("activity_name")
            else:
                value = activity
            if value:
                activity_parts.append(str(value))

    text = " ".join(activity_parts).casefold()
    return {
        group
        for group, keywords in KVED_GROUPS.items()
        if any(keyword.casefold() in text for keyword in keywords)
    }


def is_older_than_years(value: str, checked_date: date, years: int) -> bool:
    parsed = parse_iso_date(value)
    if not parsed:
        return False
    try:
        threshold = checked_date.replace(year=checked_date.year - years)
    except ValueError:
        threshold = checked_date.replace(month=2, day=28, year=checked_date.year - years)
    return parsed < threshold


def parse_iso_date(value: str) -> date | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def normalize_procurements(data: Any) -> tuple[list[ProzorroProcurement], list[str], str | None]:
    warnings: list[str] = []
    if data is None:
        return [], warnings, None
    if isinstance(data, dict) and data.get("error"):
        return [], warnings, str(data.get("error"))
    raw_items = data.get("items") if isinstance(data, dict) else data
    if raw_items is None:
        return [], warnings, None
    if not isinstance(raw_items, list):
        return [], ["Prozorro payload is not a list"], None

    procurements: list[ProzorroProcurement] = []
    for index, item in enumerate(raw_items):
        try:
            if isinstance(item, ProzorroProcurement):
                procurements.append(item)
            elif isinstance(item, dict):
                procurements.append(normalize_procurement_dict(item))
            else:
                warnings.append(f"Prozorro item #{index + 1} has unsupported type")
        except (TypeError, ValueError) as exc:
            warnings.append(f"Prozorro item #{index + 1} skipped: {exc}")
    return procurements, warnings, None


def normalize_procurement_dict(item: dict[str, Any]) -> ProzorroProcurement:
    return ProzorroProcurement(
        procurement_id=first_text(item, "procurement_id", "id", "tender_id"),
        url=first_text(item, "url", "link"),
        title=first_text(item, "title", "name", "procurement_title"),
        cpv_code=first_text(item, "cpv_code", "cpv", "classification_id"),
        cpv_name=first_text(item, "cpv_name", "classification_description"),
        procedure_type=first_text(item, "procedure_type", "procurement_method_type"),
        status=first_text(item, "status"),
        expected_value_uah=first_float(item, "expected_value_uah", "expected_value", "value"),
        bid_value_uah=first_float(item, "bid_value_uah", "bid_value", "proposal_value"),
        contract_value_uah=first_float(item, "contract_value_uah", "contract_value", "award_value"),
        buyer_name=first_text(item, "buyer_name", "procuring_entity", "buyer"),
        buyer_edrpou=first_text(item, "buyer_edrpou", "buyer_identifier", "buyer_code"),
        participants_count=first_int(item, "participants_count", "number_of_bids"),
        participated=first_bool(item, "participated"),
        won=first_bool(item, "won"),
        disqualified=first_bool(item, "disqualified"),
        disqualification_reason=first_text(item, "disqualification_reason", "rejection_reason"),
        has_contract=first_bool(item, "has_contract"),
        contract_completed=first_bool(item, "contract_completed"),
        contract_terminated=first_bool(item, "contract_terminated"),
        termination_reason=first_text(item, "termination_reason"),
        complaints_count=first_int(item, "complaints_count") or 0,
        supplier_related_complaints_count=first_int(item, "supplier_related_complaints_count") or 0,
        amendments_count=first_int(item, "amendments_count") or 0,
        contract_amount_change_uah=first_float(item, "contract_amount_change_uah"),
        contract_amount_change_percent=first_float(item, "contract_amount_change_percent"),
        date=first_text(item, "date"),
        award_date=first_text(item, "award_date"),
        contract_date=first_text(item, "contract_date"),
    )


def calculate_stats(procurements: list[ProzorroProcurement]) -> ProzorroStats:
    participations = [item for item in procurements if item.participated]
    wins = [item for item in procurements if item.won]
    contracts = [item for item in procurements if item.has_contract or item.contract_terminated]
    terminated = [item for item in contracts if item.contract_terminated]
    disqualified = [item for item in procurements if item.disqualified]
    participation_dates = sorted(date for item in participations if (date := item.date or item.award_date or item.contract_date))
    win_dates = sorted(date for item in wins if (date := item.award_date or item.date or item.contract_date))
    buyer_counts: dict[str, int] = {}
    buyer_values: dict[str, float] = {}
    total_contract_value = 0.0
    for item in contracts:
        if item.buyer_edrpou:
            buyer_counts[item.buyer_edrpou] = buyer_counts.get(item.buyer_edrpou, 0) + 1
            if item.contract_value_uah is not None:
                buyer_values[item.buyer_edrpou] = buyer_values.get(item.buyer_edrpou, 0.0) + item.contract_value_uah
        if item.contract_value_uah is not None:
            total_contract_value += item.contract_value_uah

    return ProzorroStats(
        procurements_count=len(procurements),
        participations_count=len(participations),
        wins_count=len(wins),
        contracts_count=len(contracts),
        completed_contracts_count=len([item for item in contracts if item.contract_completed]),
        terminated_contracts_count=len(terminated),
        disqualifications_count=len(disqualified),
        complaints_count=sum(item.complaints_count for item in procurements),
        supplier_related_complaints_count=sum(item.supplier_related_complaints_count for item in procurements),
        first_participation_date=participation_dates[0] if participation_dates else None,
        last_participation_date=participation_dates[-1] if participation_dates else None,
        last_win_date=win_dates[-1] if win_dates else None,
        win_rate_percent=rate(len(wins), len(participations)),
        termination_rate_percent=rate(len(terminated), len(contracts)),
        disqualification_rate_percent=rate(len(disqualified), len(participations)),
        single_buyer_contract_share_percent=rate(max(buyer_counts.values(), default=0), len(contracts)),
        single_buyer_value_share_percent=(
            round(max(buyer_values.values(), default=0.0) / total_contract_value * 100, 2)
            if total_contract_value > 0
            else None
        ),
        low_competition_wins_count=len(
            [item for item in wins if item.participants_count is not None and item.participants_count <= 1]
        ),
        high_discount_bids_count=len(
            [
                item
                for item in procurements
                if item.expected_value_uah is not None
                and item.expected_value_uah > 0
                and item.bid_value_uah is not None
                and item.bid_value_uah <= item.expected_value_uah * 0.5
            ]
        ),
    )


def build_summary(stats: ProzorroStats) -> str:
    return (
        f"Prozorro: участей {stats.participations_count}, перемог {stats.wins_count}, "
        f"договорів {stats.contracts_count}, розірвань {stats.terminated_contracts_count}."
    )


def first_text(item: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def first_float(item: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = item.get(key)
        if value in (None, ""):
            continue
        try:
            return float(str(value).replace(" ", "").replace(",", "."))
        except ValueError:
            return None
    return None


def first_int(item: dict[str, Any], *keys: str) -> int | None:
    value = first_float(item, *keys)
    return int(value) if value is not None else None


def first_bool(item: dict[str, Any], *keys: str) -> bool:
    for key in keys:
        value = item.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes", "так"}:
                return True
            if lowered in {"false", "0", "no", "ні"}:
                return False
    return False


def rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100, 2)
