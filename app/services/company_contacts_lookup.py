from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from urllib.parse import urlparse

from app.services.contact_parsing import search_web
from app.services.business_guide_lookup import fetch_business_guide_company
from app.services.diagnostic_logging import log_diagnostic_event
from app.services.prat_lookup import fetch_prat_company
from app.services.smida_lookup import fetch_smida_company
from app.services.ua_region_lookup import fetch_ua_region_company


CONTACT_FIELDS = ("website", "phone", "email")
CONFIDENCE_RANK = {"unknown": 0, "low": 1, "medium": 2, "high": 3}
SOURCE_ORDER = ("ua-region.com.ua", "prat.ua/pat.ua", "smida.gov.ua", "business-guide.com.ua")
SOURCE_TIMEOUTS = {
    "ua-region.com.ua": 6.0,
    "prat.ua/pat.ua": 8.0,
    "smida.gov.ua": 8.0,
    "business-guide.com.ua": 6.0,
}
CONTACT_SEARCH_TIMEOUT_SECONDS = 14.0
CONTACT_SEARCH_CONCURRENCY = 4
CONTACT_SOURCE_STATUSES = {"found", "not_found", "unavailable", "blocked", "parse_error"}


def fetch_company_contacts(
    edrpou: str,
    company_context: dict | None = None,
    *,
    lookups: list[Callable[[str, dict | None], dict] | tuple[str, Callable[[str, dict | None], dict]]] | None = None,
) -> dict:
    return asyncio.run(fetch_company_contacts_async(edrpou, company_context, lookups=lookups))


async def fetch_company_contacts_async(
    edrpou: str,
    company_context: dict | None = None,
    *,
    lookups: list[Callable[[str, dict | None], dict] | tuple[str, Callable[[str, dict | None], dict]]] | None = None,
    source_timeouts: dict[str, float] | None = None,
    overall_timeout: float = CONTACT_SEARCH_TIMEOUT_SECONDS,
    concurrency_limit: int = CONTACT_SEARCH_CONCURRENCY,
) -> dict:
    lookup_configs = [normalize_lookup_config(configured_lookup) for configured_lookup in (lookups or default_contact_lookups())]
    source_timeouts = {**SOURCE_TIMEOUTS, **(source_timeouts or {})}
    semaphore = asyncio.Semaphore(max(1, concurrency_limit))
    tasks = {
        asyncio.create_task(
            run_contact_source_lookup(
                edrpou,
                company_context or {},
                source,
                lookup,
                semaphore,
                source_timeouts.get(source, 6.0),
            )
        ): source
        for source, lookup in lookup_configs
    }
    done, pending = await asyncio.wait(tasks, timeout=overall_timeout)
    results: list[dict] = []
    for task in done:
        try:
            results.append(task.result())
        except Exception as exc:
            source = tasks[task]
            logging.exception("Contact lookup task failed for source %s and EDRPOU %s", source, edrpou)
            results.append(contact_source_error_result(source, exc, error_type=exc.__class__.__name__))
    for task in pending:
        source = tasks[task]
        task.cancel()
        results.append(
            contact_source_error_result(
                source,
                TimeoutError("contact_search_overall_timeout"),
                error_type="overall_timeout",
                duration_ms=int(overall_timeout * 1000),
            )
        )
    return build_contacts_summary(order_source_results(results), company_context or {})


def default_contact_lookups() -> list[tuple[str, Callable[[str, dict | None], dict]]]:
    return [
        ("ua-region.com.ua", lambda code, context: fetch_ua_region_company(code, context, searcher=search_web)),
        ("prat.ua/pat.ua", lambda code, context: fetch_prat_company(code, context, searcher=search_web)),
        ("smida.gov.ua", lambda code, context: fetch_smida_company(code, context, searcher=search_web)),
        ("business-guide.com.ua", lambda code, context: fetch_business_guide_company(code, context, searcher=search_web)),
    ]


async def run_contact_source_lookup(
    edrpou: str,
    company_context: dict,
    source: str,
    lookup: Callable[[str, dict | None], dict],
    semaphore: asyncio.Semaphore,
    timeout_seconds: float,
) -> dict:
    start_time = datetime.now(UTC).isoformat()
    started_at = time.monotonic()
    try:
        async with semaphore:
            result = await asyncio.wait_for(
                asyncio.to_thread(lookup, edrpou, company_context),
                timeout=timeout_seconds,
            )
        result = normalize_source_result(result, source)
        error_type = result.get("error_type") or result.get("error")
    except asyncio.TimeoutError as exc:
        result = contact_source_error_result(source, exc, error_type="timeout")
        error_type = "timeout"
    except Exception as exc:
        logging.exception("Contact source lookup failed for source %s and EDRPOU %s", source, edrpou)
        result = contact_source_error_result(source, exc, error_type=exc.__class__.__name__)
        error_type = exc.__class__.__name__

    duration_ms = int((time.monotonic() - started_at) * 1000)
    debug = build_source_debug(result, source, start_time, duration_ms, error_type)
    result["debug"] = debug
    logging.info(
        "Contact lookup source=%s start_time=%s duration_ms=%s final_status=%s error_type=%s raw_url=%s fallback=%s contacts_found_count=%s",
        debug["source"],
        debug["start_time"],
        debug["duration_ms"],
        debug["final_status"],
        debug["error_type"],
        debug["raw_url"],
        debug["fallback"],
        debug["contacts_found_count"],
    )
    log_diagnostic_event(
        "contact_source_result",
        route="contact_search",
        edrpou=edrpou,
        source=debug["source"],
        start_time=debug["start_time"],
        duration_ms=debug["duration_ms"],
        final_status=debug["final_status"],
        error_type=debug["error_type"],
        raw_url=debug["raw_url"],
        fallback=debug["fallback"],
        contacts_found_count=debug["contacts_found_count"],
        request_context={
            "company_name": company_context.get("company_name"),
            "has_address": bool(company_context.get("address")),
            "known_domains": company_context.get("known_domains") or [],
        },
        response={
            "status": result.get("status"),
            "confidence": result.get("confidence"),
            "contacts": result.get("contacts") or {},
            "evidence": result.get("evidence") or [],
            "error": result.get("error"),
        },
    )
    return result


def normalize_source_result(result: dict | None, source: str) -> dict:
    if not isinstance(result, dict):
        return contact_source_error_result(source, ValueError("lookup_returned_empty_result"), error_type="parse_error")
    normalized = {
        "source": source,
        "status": result.get("status") or "parse_error",
        "company": result.get("company") or {},
        "contacts": result.get("contacts") or {"website": None, "phone": None, "email": None},
        "evidence": result.get("evidence") or [],
        "confidence": result.get("confidence") or "unknown",
        "raw_url": result.get("raw_url"),
        "error": result.get("error"),
        "fallback_used": bool(result.get("fallback_used")),
    }
    if normalized["status"] not in CONTACT_SOURCE_STATUSES:
        normalized["status"] = "parse_error"
        normalized["error"] = normalized["error"] or "unexpected_status"
    return normalized


def contact_source_error_result(
    source: str,
    error: BaseException | str,
    *,
    error_type: str | None = None,
    duration_ms: int | None = None,
) -> dict:
    debug_error_type = error_type or (error.__class__.__name__ if isinstance(error, BaseException) else "error")
    status = "blocked" if debug_error_type in {"blocked", "HTTPError_403", "HTTPError_429"} else "unavailable"
    result = {
        "source": source,
        "status": status,
        "company": {},
        "contacts": {"website": None, "phone": None, "email": None},
        "evidence": [],
        "confidence": "unknown",
        "raw_url": None,
        "error": "analysis_timeout" if debug_error_type in {"timeout", "overall_timeout"} else str(error),
        "error_type": debug_error_type,
        "fallback_used": False,
    }
    if duration_ms is not None:
        result["debug"] = build_source_debug(
            result,
            source,
            datetime.now(UTC).isoformat(),
            duration_ms,
            debug_error_type,
        )
    return result


def build_source_debug(
    result: dict,
    source: str,
    start_time: str,
    duration_ms: int,
    error_type: str | None,
) -> dict:
    return {
        "source": source,
        "start_time": start_time,
        "duration_ms": duration_ms,
        "final_status": result.get("status") or "unknown",
        "error_type": error_type,
        "raw_url": result.get("raw_url"),
        "fallback": bool(result.get("fallback_used")),
        "contacts_found_count": contacts_found_count(result.get("contacts") or {}),
    }


def contacts_found_count(contacts: dict) -> int:
    return sum(1 for field in CONTACT_FIELDS if contacts.get(field))


def order_source_results(results: list[dict]) -> list[dict]:
    rank = defaultdict(lambda: len(SOURCE_ORDER))
    for index, source in enumerate(SOURCE_ORDER):
        rank[source] = index
    return sorted(results, key=lambda result: (rank[str(result.get("source") or "")], str(result.get("source") or "")))


def normalize_lookup_config(
    configured_lookup: Callable[[str, dict | None], dict] | tuple[str, Callable[[str, dict | None], dict]],
) -> tuple[str, Callable[[str, dict | None], dict]]:
    if isinstance(configured_lookup, tuple):
        return configured_lookup
    return getattr(configured_lookup, "__name__", "unknown"), configured_lookup


def build_contacts_summary(source_results: list[dict], company_context: dict | None = None) -> dict:
    summary = {
        "website": empty_contact_summary(),
        "phone": empty_contact_summary(),
        "email": empty_contact_summary(),
        "checked_sources": [],
        "missing_sources": [],
        "warnings": [],
        "source_statuses": {},
        "source_results": source_results,
        "source_debug": [],
    }

    for result in source_results:
        source = str(result.get("source") or "unknown")
        status = str(result.get("status") or "unknown")
        if result.get("debug"):
            summary["source_debug"].append(result["debug"])
        if source not in summary["checked_sources"]:
            summary["checked_sources"].append(source)
        summary["source_statuses"][source] = status
        if status == "not_found":
            summary["missing_sources"].append(source)
        if status in {"unavailable", "blocked", "parse_error"}:
            summary["warnings"].append(
                f"Джерело {source} тимчасово недоступне або заблокувало автоматичну перевірку."
            )

    confirmed_website_domain = None
    website_candidates = collect_candidates(source_results, "website")
    if website_candidates:
        best_website = choose_best_candidate(website_candidates)
        fill_contact_summary(summary["website"], best_website)
        if best_website["confidence"] == "high":
            confirmed_website_domain = normalized_domain(best_website["value"])

    for field in ("phone", "email"):
        candidates = collect_candidates(source_results, field)
        if field == "email" and confirmed_website_domain:
            for candidate in candidates:
                if email_domain(candidate["value"]) == confirmed_website_domain:
                    candidate["confidence"] = "high"
                    candidate["score"] = max(candidate["score"], CONFIDENCE_RANK["high"])
                    candidate["evidence"].append("Email має домен підтвердженого сайту компанії.")
        if candidates:
            best = choose_best_candidate(candidates)
            fill_contact_summary(summary[field], best)

    summary["checked_sources"] = order_sources(summary["checked_sources"])
    summary["missing_sources"] = order_sources(summary["missing_sources"])
    summary["warnings"] = dedupe(summary["warnings"])
    return summary


def empty_contact_summary() -> dict:
    return {"value": None, "confidence": "unknown", "sources": [], "evidence": []}


def collect_candidates(source_results: list[dict], field: str) -> list[dict]:
    by_value: dict[str, dict] = {}
    for result in source_results:
        if result.get("status") != "found":
            continue
        contacts = result.get("contacts") or {}
        value = contacts.get(field)
        if not value:
            continue
        normalized_value = normalize_contact_value(field, str(value))
        source = str(result.get("source") or "unknown")
        confidence = str(result.get("confidence") or "unknown")
        if normalized_value not in by_value:
            by_value[normalized_value] = {
                "value": normalized_value,
                "confidence": confidence,
                "sources": [],
                "evidence": [],
                "score": CONFIDENCE_RANK.get(confidence, 0),
            }
        candidate = by_value[normalized_value]
        if source not in candidate["sources"]:
            candidate["sources"].append(source)
        candidate["evidence"].extend(result.get("evidence") or [])
        candidate["score"] = max(candidate["score"], CONFIDENCE_RANK.get(confidence, 0))
        if len(candidate["sources"]) >= 2 and candidate["score"] >= CONFIDENCE_RANK["medium"]:
            candidate["confidence"] = "high"
            candidate["score"] = CONFIDENCE_RANK["high"]
        elif CONFIDENCE_RANK.get(confidence, 0) > CONFIDENCE_RANK.get(candidate["confidence"], 0):
            candidate["confidence"] = confidence
    return list(by_value.values())


def choose_best_candidate(candidates: list[dict]) -> dict:
    return max(candidates, key=lambda item: (item["score"], len(item["sources"])))


def fill_contact_summary(target: dict, candidate: dict) -> None:
    target["value"] = candidate["value"]
    target["confidence"] = candidate["confidence"]
    target["sources"] = order_sources(candidate["sources"])
    target["evidence"] = dedupe(candidate["evidence"])[:4]


def normalize_contact_value(field: str, value: str) -> str:
    if field == "email":
        return value.lower()
    if field == "website":
        return value.rstrip("/")
    return value


def normalized_domain(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = (parsed.hostname or "").lower()
    return host[4:] if host.startswith("www.") else host or None


def email_domain(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    return email.rsplit("@", 1)[-1].lower()


def order_sources(sources: list[str]) -> list[str]:
    rank = defaultdict(lambda: len(SOURCE_ORDER))
    for index, source in enumerate(SOURCE_ORDER):
        rank[source] = index
    return sorted(dedupe(sources), key=lambda source: (rank[source], source))


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
