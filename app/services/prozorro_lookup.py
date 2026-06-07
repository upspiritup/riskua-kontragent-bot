from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.models.company_lookup import ProzorroAnalysis, ProzorroProcurement
from app.services.prozorro_analysis import analyze_prozorro_data
from app.services.prozorro_api_source import fetch_recent_prozorro_procurements_by_edrpou


ProzorroSource = Callable[[str], Any]
ProzorroLiveSource = Callable[[str], list[ProzorroProcurement]]
EDRPOU_FIELDS = (
    "edrpou",
    "supplier_edrpou",
    "supplier_identifier",
    "supplier_code",
    "participant_edrpou",
    "participant_identifier",
    "company_edrpou",
)


def lookup_prepared_prozorro(
    edrpou: str,
    *,
    source: ProzorroSource | None = None,
    live_source: ProzorroLiveSource | None = None,
    company_context: dict[str, Any] | None = None,
) -> ProzorroAnalysis:
    logging.info("Prozorro analysis start edrpou=%s", edrpou)
    try:
        if source is not None:
            payload = source(edrpou)
        else:
            cache_path = os.environ.get("PROZORRO_CACHE_PATH")
            payload = load_prozorro_cache_file(edrpou, cache_path) if cache_path else None

        if not payload:
            payload = load_live_prozorro_records(edrpou, live_source)
    except Exception as exc:
        analysis = analyze_prozorro_data({"error": str(exc)}, company_context=company_context)
        log_prozorro_analysis_done(edrpou, analysis)
        return analysis

    analysis = analyze_prozorro_data(payload, company_context=company_context)
    log_prozorro_analysis_done(edrpou, analysis)
    return analysis


def load_live_prozorro_records(
    edrpou: str,
    live_source: ProzorroLiveSource | None = None,
) -> list[ProzorroProcurement] | None:
    if live_source is not None:
        return live_source(edrpou)
    if not prozorro_live_enabled():
        return None
    return fetch_recent_prozorro_procurements_sync(edrpou)


def prozorro_live_enabled() -> bool:
    return os.environ.get("PROZORRO_LIVE_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def fetch_recent_prozorro_procurements_sync(edrpou: str) -> list[ProzorroProcurement]:
    max_pages = int(os.environ.get("PROZORRO_LIVE_MAX_PAGES", "3"))
    limit = int(os.environ.get("PROZORRO_LIVE_LIMIT", "100"))
    return asyncio.run(fetch_recent_prozorro_procurements_by_edrpou(edrpou, max_pages=max_pages, limit=limit))


def log_prozorro_analysis_done(edrpou: str, analysis: ProzorroAnalysis) -> None:
    logging.info(
        "Prozorro analysis done status=%s participations=%s wins=%s contracts=%s terminated=%s disqualified=%s flags=%s edrpou=%s",
        analysis.status,
        analysis.stats.participations_count,
        analysis.stats.wins_count,
        analysis.stats.contracts_count,
        analysis.stats.terminated_contracts_count,
        analysis.stats.disqualifications_count,
        len(analysis.risk_flags),
        edrpou,
    )


def load_prozorro_cache_file(edrpou: str, cache_path: str | os.PathLike[str]) -> Any | None:
    with Path(cache_path).open(encoding="utf-8") as cache_file:
        cache_data = json.load(cache_file)

    if isinstance(cache_data, list):
        matched = filter_items_by_edrpou(cache_data, edrpou)
        return matched or None

    if not isinstance(cache_data, dict):
        return None

    if edrpou in cache_data:
        return cache_data[edrpou]

    items = cache_data.get("items")
    if isinstance(items, dict):
        return items.get(edrpou)
    if isinstance(items, list):
        matched = filter_items_by_edrpou(items, edrpou)
        return matched or None

    return None


def filter_items_by_edrpou(items: list[Any], edrpou: str) -> list[dict[str, Any]]:
    return [item for item in items if isinstance(item, dict) and item_matches_edrpou(item, edrpou)]


def item_matches_edrpou(item: dict[str, Any], edrpou: str) -> bool:
    return any(str(item.get(field) or "").strip() == edrpou for field in EDRPOU_FIELDS)
