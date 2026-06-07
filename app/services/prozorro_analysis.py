from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.models.company_lookup import ProzorroAnalysis, ProzorroProcurement, ProzorroStats


SOURCE = "prozorro_analysis"
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

    return ProzorroAnalysis(
        status="partial" if warnings else "found",
        stats=stats,
        procurements=procurements,
        risk_flags=[],
        info_notes=notes,
        summary=build_summary(stats),
        parse_warnings=warnings,
        checked_at=checked_at,
    )


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
    contracts = [item for item in procurements if item.has_contract]
    terminated = [item for item in contracts if item.contract_terminated]
    disqualified = [item for item in procurements if item.disqualified]
    participation_dates = sorted(date for item in participations if (date := item.date or item.award_date or item.contract_date))
    win_dates = sorted(date for item in wins if (date := item.award_date or item.date or item.contract_date))
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
