from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.models.company_lookup import ProzorroAnalysis
from app.services.prozorro_analysis import analyze_prozorro_data


ProzorroSource = Callable[[str], Any]


def lookup_prepared_prozorro(
    edrpou: str,
    *,
    source: ProzorroSource | None = None,
    company_context: dict[str, Any] | None = None,
) -> ProzorroAnalysis:
    try:
        if source is not None:
            payload = source(edrpou)
        else:
            cache_path = os.environ.get("PROZORRO_CACHE_PATH")
            payload = load_prozorro_cache_file(edrpou, cache_path) if cache_path else None
    except Exception as exc:
        return analyze_prozorro_data({"error": str(exc)}, company_context=company_context)

    return analyze_prozorro_data(payload, company_context=company_context)


def load_prozorro_cache_file(edrpou: str, cache_path: str | os.PathLike[str]) -> Any | None:
    with Path(cache_path).open(encoding="utf-8") as cache_file:
        cache_data = json.load(cache_file)

    if not isinstance(cache_data, dict):
        return None

    if edrpou in cache_data:
        return cache_data[edrpou]

    items = cache_data.get("items")
    if isinstance(items, dict):
        return items.get(edrpou)
    if isinstance(items, list):
        return cache_data

    return None
