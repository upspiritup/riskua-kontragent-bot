from __future__ import annotations

import csv
import io
import json
import logging
import re
import zipfile
from datetime import UTC, datetime
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.utils.validators import is_valid_edrpou


SOURCE = "tax"
TAX_SOURCE_UNAVAILABLE = "tax_source_unavailable"
LARGE_TAX_DEBT_THRESHOLD_UAH = 100_000
HTTP_TIMEOUT_SECONDS = 12.0
MAX_DATASET_BYTES = 20_000_000

TAX_DEBT_DATASET_ID = "0e347d45-4db5-44ee-a14a-533d7cf17d7b"
VAT_DATASET_ID = "db391c93-1e68-43c9-bd85-7c6a8427b114"
DATA_GOV_PACKAGE_URL = "https://data.gov.ua/api/3/action/package_show?id={dataset_id}"
TAX_DEBT_DATASET_URL = f"https://data.gov.ua/dataset/{TAX_DEBT_DATASET_ID}"
VAT_DATASET_URL = f"https://data.gov.ua/dataset/{VAT_DATASET_ID}"

EDRPOU_FIELDS = (
    "edrpou",
    "код єдрпоу",
    "єдрпоу",
    "едрпоу",
    "код платника",
    "податковий номер",
    "tin",
    "code",
    "код",
)
AMOUNT_FIELDS = (
    "tax_debt_amount",
    "amount",
    "sum",
    "сума",
    "сума боргу",
    "сума податкового боргу",
    "загальна сума податкового боргу",
    "податковий борг",
)
CURRENCY_FIELDS = ("currency", "валюта")
DATASET_DATE_FIELDS = ("dataset_date", "date", "дата", "станом на", "as_of")
TAX_TYPE_FIELDS = ("tax_type", "податок", "вид податку", "платіж", "код платежу")
BUDGET_FIELDS = ("budget", "бюджет", "тип бюджету")
NAME_FIELDS = ("name", "назва", "найменування", "платник")

VAT_STATUS_FIELDS = ("status", "стан", "статус", "ознака")
VAT_REGISTRATION_DATE_FIELDS = ("registration_date", "дата реєстрації", "дата реєстрації платником пдв")
VAT_CANCELLED_DATE_FIELDS = ("cancelled_date", "дата анулювання", "термін дії реєстрації", "дата скасування")
VAT_TAX_NUMBER_FIELDS = ("individual_tax_number", "іпн", "індивідуальний податковий номер", "податковий номер пдв")


def build_tax_debt_dataset_url() -> str:
    return TAX_DEBT_DATASET_URL


def build_vat_dataset_url() -> str:
    return VAT_DATASET_URL


def fetch_tax_status(
    edrpou: str,
    fetcher: Callable[[str], Any] | None = None,
) -> dict:
    if not is_valid_edrpou(edrpou):
        return unavailable_result(edrpou, error="invalid_edrpou")

    try:
        payload = fetcher(edrpou) if fetcher else fetch_tax_open_data_datasets(edrpou)
        return parse_tax_payload(payload, edrpou)
    except (
        TimeoutError,
        OSError,
        HTTPError,
        URLError,
        ValueError,
        json.JSONDecodeError,
        zipfile.BadZipFile,
        csv.Error,
    ) as exc:
        logging.info("Tax open data unavailable for EDRPOU %s: %s", edrpou, exc)
        return unavailable_result(edrpou)


def fetch_tax_open_data_datasets(edrpou: str) -> dict[str, bytes | None]:
    return {
        "tax_debt": fetch_latest_dataset_resource(TAX_DEBT_DATASET_ID),
        "vat": fetch_latest_dataset_resource(VAT_DATASET_ID),
    }


def fetch_latest_dataset_resource(dataset_id: str) -> bytes | None:
    package_url = DATA_GOV_PACKAGE_URL.format(dataset_id=dataset_id)
    package = json.loads(fetch_url(package_url).decode("utf-8", errors="replace"))
    resources = list(((package.get("result") or {}).get("resources") or []))
    resource_url = choose_resource_url(resources)
    if not resource_url:
        return None
    return fetch_url(resource_url)


def choose_resource_url(resources: list[dict[str, Any]]) -> str | None:
    ranked_formats = {"csv": 0, "json": 1, "zip": 2}
    candidates: list[tuple[int, str, str]] = []
    for resource in resources:
        url = str(resource.get("url") or "")
        if not url:
            continue
        fmt = str(resource.get("format") or resource.get("mimetype") or url.rsplit(".", 1)[-1]).lower()
        resource_format = next((known for known in ranked_formats if known in fmt), None)
        if resource_format is None:
            continue
        modified = str(resource.get("last_modified") or resource.get("created") or "")
        candidates.append((ranked_formats[resource_format], modified, url))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=False)
    best_format_rank = candidates[0][0]
    best_format_candidates = [candidate for candidate in candidates if candidate[0] == best_format_rank]
    best_format_candidates.sort(key=lambda item: item[1], reverse=True)
    return best_format_candidates[0][2]


def fetch_url(url: str) -> bytes:
    request = Request(
        url,
        headers={
            "User-Agent": "RiskUA Bot MVP/0.1",
            "Accept": "text/csv,application/json,application/zip,*/*",
        },
    )
    with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        data = response.read(MAX_DATASET_BYTES + 1)
    if len(data) > MAX_DATASET_BYTES:
        raise ValueError("tax_dataset_too_large")
    return data


def parse_tax_payload(payload: Any, edrpou: str) -> dict:
    if isinstance(payload, dict) and payload.get("source") == SOURCE and "checked" in payload:
        return with_result_defaults(payload, edrpou)

    tax_content, vat_content = split_payload(payload)
    if tax_content is None and vat_content is None:
        return unavailable_result(edrpou)

    tax_debt = parse_tax_debt_dataset(tax_content, edrpou) if tax_content is not None else empty_tax_debt()
    vat = parse_vat_dataset(vat_content, edrpou) if vat_content is not None else None
    result = {
        "source": SOURCE,
        "checked": True,
        "found": True,
        "url": build_tax_debt_dataset_url(),
        "vat_url": build_vat_dataset_url(),
        "searched_edrpou": edrpou,
        "checked_at": checked_at(),
        "tax_debt": tax_debt,
        "vat": vat,
        "signals": build_tax_signals(tax_debt, vat),
        "risk_flags": [],
        "error": None,
    }
    result["risk_flags"] = build_tax_risk_flags(result)
    return result


def split_payload(payload: Any) -> tuple[Any | None, Any | None]:
    if isinstance(payload, dict):
        if "tax_debt" in payload or "vat" in payload:
            return payload.get("tax_debt"), payload.get("vat")
        if "content" in payload:
            return payload.get("content"), None
    if isinstance(payload, (list, tuple)):
        tax_content = payload[0] if len(payload) > 0 else None
        vat_content = payload[1] if len(payload) > 1 else None
        return tax_content, vat_content
    return payload, None


def parse_tax_debt_dataset(content: bytes | str, edrpou: str) -> dict:
    rows = parse_tabular_content(content)
    matching_rows = [row for row in rows if row_matches_edrpou(row, edrpou)]
    details: list[dict[str, Any]] = []
    total_amount = 0.0
    currency = "UAH"
    dataset_date = None

    for row in matching_rows:
        amount = parse_amount(first_value(row, AMOUNT_FIELDS))
        if amount is None:
            amount = 0.0
        row_currency = first_value(row, CURRENCY_FIELDS) or "UAH"
        row_dataset_date = first_value(row, DATASET_DATE_FIELDS)
        if row_dataset_date and not dataset_date:
            dataset_date = row_dataset_date
        currency = row_currency or currency
        total_amount += amount
        details.append(
            {
                "amount": amount,
                "currency": row_currency,
                "tax_type": first_value(row, TAX_TYPE_FIELDS),
                "budget": first_value(row, BUDGET_FIELDS),
                "name": first_value(row, NAME_FIELDS),
                "dataset_date": row_dataset_date,
            }
        )

    return {
        "found": bool(details) and total_amount > 0,
        "amount": round(total_amount, 2),
        "currency": currency,
        "details": details,
        "dataset_date": dataset_date,
    }


def parse_vat_dataset(content: bytes | str, edrpou: str) -> dict:
    rows = parse_tabular_content(content)
    matching_row = next((row for row in rows if row_matches_edrpou(row, edrpou)), None)
    if not matching_row:
        return {
            "found": False,
            "status": "not_found",
            "registration_date": None,
            "cancelled_date": None,
            "individual_tax_number": None,
        }

    status = normalize_vat_status(first_value(matching_row, VAT_STATUS_FIELDS), matching_row)
    return {
        "found": True,
        "status": status,
        "registration_date": first_value(matching_row, VAT_REGISTRATION_DATE_FIELDS),
        "cancelled_date": first_value(matching_row, VAT_CANCELLED_DATE_FIELDS),
        "individual_tax_number": first_value(matching_row, VAT_TAX_NUMBER_FIELDS),
    }


def build_tax_risk_flags(result: dict) -> list[str]:
    flags: list[str] = []
    if result.get("checked") is False or result.get("error") == TAX_SOURCE_UNAVAILABLE:
        return [TAX_SOURCE_UNAVAILABLE]

    tax_debt = result.get("tax_debt") or {}
    if tax_debt.get("found"):
        flags.append("tax_debt_found")
        if float(tax_debt.get("amount") or 0) > LARGE_TAX_DEBT_THRESHOLD_UAH:
            flags.append("large_tax_debt_found")

    vat = result.get("vat") or {}
    vat_status = str(vat.get("status") or "").lower()
    if vat.get("cancelled_date") or vat_status in {"cancelled", "анульовано", "скасовано"}:
        flags.append("vat_registration_cancelled")
    elif vat_status and vat_status not in {"active", "not_found", "зареєстровано", "діючий", "чинний"}:
        flags.append("vat_status_problem")
    return unique(flags)


def build_tax_signals(tax_debt: dict | None, vat: dict | None) -> list[str]:
    signals: list[str] = []
    if tax_debt:
        if tax_debt.get("found"):
            signals.append("Знайдено податковий борг")
            if float(tax_debt.get("amount") or 0) > LARGE_TAX_DEBT_THRESHOLD_UAH:
                signals.append("Сума податкового боргу перевищує 100000 грн")
        else:
            signals.append("Податковий борг не знайдено")
    if vat:
        status = str(vat.get("status") or "").lower()
        if vat.get("found") and status == "active":
            signals.append("Компанія є платником ПДВ")
        elif vat.get("found") and (status == "cancelled" or vat.get("cancelled_date")):
            signals.append("ПДВ-реєстрацію анульовано")
        elif vat.get("found") is False:
            signals.append("Платника ПДВ не знайдено")
    return signals


def parse_tabular_content(content: bytes | str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for text in extract_text_payloads(content):
        stripped = text.strip()
        if not stripped:
            continue
        lowered_prefix = stripped[:200].lower()
        if lowered_prefix.startswith("<!doctype") or "<html" in lowered_prefix:
            raise ValueError("tax_dataset_format_not_recognized")
        if stripped.startswith("{") or stripped.startswith("["):
            rows.extend(parse_json_rows(stripped))
        else:
            rows.extend(parse_csv_rows(stripped))
    return rows


def extract_text_payloads(content: bytes | str) -> list[str]:
    if isinstance(content, str):
        return [content]
    if is_zip_payload(content):
        payloads: list[str] = []
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            for name in archive.namelist():
                if name.lower().endswith((".csv", ".json", ".txt")):
                    payloads.append(decode_bytes(archive.read(name)))
        return payloads
    return [decode_bytes(content)]


def parse_csv_rows(text: str) -> list[dict[str, Any]]:
    if not text:
        return []
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
        dialect = csv.excel()
        dialect.delimiter = delimiter
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    return [normalize_row(row) for row in reader if row]


def parse_json_rows(text: str) -> list[dict[str, Any]]:
    payload = json.loads(text)
    if isinstance(payload, dict):
        for key in ("data", "rows", "result", "records"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list):
        return []
    return [normalize_row(row) for row in payload if isinstance(row, dict)]


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in row.items():
        normalized[normalize_key(key)] = normalize_text(value)
    return normalized


def normalize_key(value: Any) -> str:
    return normalize_text(value).lower().replace("\ufeff", "")


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def first_value(row: dict[str, Any], fields: tuple[str, ...]) -> str | None:
    for field in fields:
        value = row.get(normalize_key(field))
        if value:
            return value
    return None


def row_matches_edrpou(row: dict[str, Any], edrpou: str) -> bool:
    for field in EDRPOU_FIELDS:
        value = row.get(normalize_key(field))
        if code_matches(value, edrpou):
            return True
    return any(code_matches(value, edrpou) for value in row.values())


def code_matches(value: Any, edrpou: str) -> bool:
    digits = re.sub(r"\D", "", str(value or ""))
    if not digits:
        return False
    return digits == edrpou or edrpou in split_possible_codes(digits)


def split_possible_codes(digits: str) -> list[str]:
    if len(digits) <= 8:
        return [digits]
    return [digits[index : index + 8] for index in range(0, len(digits) - 7)]


def parse_amount(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    cleaned = re.sub(r"[^\d,.\-]", "", text)
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def normalize_vat_status(status: str | None, row: dict[str, Any]) -> str:
    lowered = (status or "").lower()
    cancelled_date = first_value(row, VAT_CANCELLED_DATE_FIELDS)
    if cancelled_date or any(marker in lowered for marker in ("cancel", "ануль", "скас", "припин")):
        return "cancelled"
    if any(marker in lowered for marker in ("active", "зареєстр", "чинн", "діюч")):
        return "active"
    return status or "active"


def is_zip_payload(content: bytes) -> bool:
    return content.startswith(b"PK\x03\x04")


def decode_bytes(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def empty_tax_debt() -> dict:
    return {
        "found": False,
        "amount": 0,
        "currency": "UAH",
        "details": [],
        "dataset_date": None,
    }


def unavailable_result(edrpou: str, *, error: str = TAX_SOURCE_UNAVAILABLE) -> dict:
    return {
        "source": SOURCE,
        "checked": False,
        "found": False,
        "url": build_tax_debt_dataset_url(),
        "vat_url": build_vat_dataset_url(),
        "searched_edrpou": edrpou,
        "checked_at": checked_at(),
        "tax_debt": None,
        "vat": None,
        "signals": [],
        "risk_flags": [TAX_SOURCE_UNAVAILABLE],
        "error": error,
    }


def with_result_defaults(result: dict[str, Any], edrpou: str) -> dict:
    if result.get("checked") is False or result.get("error"):
        return {**unavailable_result(edrpou, error=str(result.get("error") or TAX_SOURCE_UNAVAILABLE)), **result}
    prepared = {
        "source": SOURCE,
        "checked": True,
        "found": True,
        "url": build_tax_debt_dataset_url(),
        "vat_url": build_vat_dataset_url(),
        "searched_edrpou": edrpou,
        "checked_at": checked_at(),
        "tax_debt": result.get("tax_debt") or empty_tax_debt(),
        "vat": result.get("vat"),
        "signals": list(result.get("signals") or []),
        "risk_flags": list(result.get("risk_flags") or []),
        "error": None,
    }
    if not prepared["signals"]:
        prepared["signals"] = build_tax_signals(prepared["tax_debt"], prepared["vat"])
    if not prepared["risk_flags"]:
        prepared["risk_flags"] = build_tax_risk_flags(prepared)
    return {**prepared, **result}


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def checked_at() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
