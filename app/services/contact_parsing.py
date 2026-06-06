from __future__ import annotations

import re
import time
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from app.services.diagnostic_logging import log_diagnostic_event


HTTP_TIMEOUT_SECONDS = 8.0
EMPTY_CONTACTS = {"website": None, "phone": None, "email": None}
EMPTY_COMPANY = {
    "edrpou": None,
    "name": None,
    "full_name": None,
    "status": None,
    "address": None,
    "director": None,
    "kved": None,
}


class VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = normalize_spaces(data)
        if text:
            self.parts.append(text)


def fetch_url(url: str) -> str:
    started_at = time.monotonic()
    request = Request(
        url,
        headers={
            "User-Agent": "RiskUA Bot MVP/0.1",
            "Accept": "text/html,application/xhtml+xml,application/xml,text/xml",
        },
    )
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read().decode(charset, errors="replace")
            log_diagnostic_event(
                "http_response",
                route="contact_fetch",
                method="GET",
                url=url,
                status_code=getattr(response, "status", None) or response.getcode(),
                final_url=response.geturl(),
                duration_ms=int((time.monotonic() - started_at) * 1000),
                response_preview=body,
            )
            return body
    except Exception as exc:
        log_diagnostic_event(
            "http_error",
            route="contact_fetch",
            method="GET",
            url=url,
            duration_ms=int((time.monotonic() - started_at) * 1000),
            error_type=exc.__class__.__name__,
            error=str(exc),
        )
        raise


def search_web(query: str, *, limit: int = 5) -> list[str]:
    url = f"https://www.bing.com/search?q={quote_plus(query)}"
    started_at = time.monotonic()
    html = fetch_url(url)
    candidates = re.findall(r"https?://[^\s\"'<>]+", html or "", flags=re.IGNORECASE)
    results: list[str] = []
    for candidate in candidates:
        cleaned = unescape(candidate).split("&")[0].rstrip(".,;")
        if "bing.com" in cleaned or "microsoft.com" in cleaned:
            continue
        if cleaned not in results:
            results.append(cleaned)
        if len(results) >= limit:
            break
    log_diagnostic_event(
        "search_results",
        route="contact_search",
        query=query,
        url=url,
        duration_ms=int((time.monotonic() - started_at) * 1000),
        results_count=len(results),
        results=results[:5],
    )
    return results


def empty_result(source: str, *, status: str, raw_url: str | None = None, error: str | None = None, evidence: list[str] | None = None) -> dict:
    return {
        "source": source,
        "status": status,
        "company": dict(EMPTY_COMPANY),
        "contacts": dict(EMPTY_CONTACTS),
        "evidence": evidence or [],
        "confidence": "unknown",
        "raw_url": raw_url,
        "error": error,
    }


def source_error_result(source: str, raw_url: str, error: BaseException) -> dict:
    if isinstance(error, HTTPError):
        close_error_response(error)
        if error.code == 404:
            return empty_result(source, status="not_found", raw_url=raw_url, error="not_found")
        if error.code in {403, 429}:
            return empty_result(source, status="blocked", raw_url=raw_url, error=f"http_{error.code}")
        return empty_result(source, status="unavailable", raw_url=raw_url, error=f"http_{error.code}")
    if isinstance(error, (URLError, TimeoutError, OSError)):
        return empty_result(source, status="unavailable", raw_url=raw_url, error=str(error))
    return empty_result(source, status="parse_error", raw_url=raw_url, error=str(error))


def close_error_response(error: HTTPError) -> None:
    try:
        error.close()
    except OSError:
        pass


def visible_text(html: str) -> str:
    parser = VisibleTextParser()
    parser.feed(html or "")
    return normalize_spaces(" ".join(parser.parts))


def remove_footer_text(html: str) -> str:
    return re.sub(r"<footer\b.*?</footer>", " ", html or "", flags=re.IGNORECASE | re.DOTALL)


def is_blocked_page(html: str, text: str | None = None) -> bool:
    lowered = f"{text or ''} {html or ''}".lower()
    return any(
        marker in lowered
        for marker in (
            "captcha",
            "cloudflare",
            "cf-chl",
            "just a moment",
            "access denied",
            "checking your browser",
        )
    )


def normalize_spaces(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def normalize_compare(value: Any) -> str:
    return normalize_spaces(value).lower().replace("’", "'").replace("«", "").replace("»", "").replace('"', "")


def extract_label_value(text: str, labels: tuple[str, ...], *, stop_labels: tuple[str, ...] = ()) -> str | None:
    label_pattern = "|".join(re.escape(label) for label in labels)
    stop_pattern = "|".join(re.escape(label) for label in stop_labels) if stop_labels else r"$^"
    match = re.search(
        rf"(?:{label_pattern})\s*[:\-]?\s*(.+?)(?=(?:{stop_pattern})\s*[:\-]?|$)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return normalize_spaces(match.group(1).strip(" .;,-")) or None


def extract_edrpou(text: str, expected_edrpou: str) -> str | None:
    if expected_edrpou and re.search(rf"(?<!\d){re.escape(expected_edrpou)}(?!\d)", text or ""):
        return expected_edrpou
    match = re.search(r"(?:єдрпоу|едрпоу|код\s+за\s+єдрпоу|код\s+єдрпоу)\D{0,30}(\d{8})", text, re.IGNORECASE)
    return match.group(1) if match else None


def extract_name(text: str) -> str | None:
    match = re.search(r"\b(?:ПРАТ|ПАТ|АТ|ТОВ|ПП|ФОП)\s*[\"«][^\"»]+[\"»]", text, flags=re.IGNORECASE)
    if match:
        return normalize_spaces(match.group(0))
    match = re.search(r"\b(?:ПРАТ|ПАТ|АТ|ТОВ|ПП|ФОП)\s+[A-ZА-ЯІЇЄҐ0-9][^:;]{2,80}", text, flags=re.IGNORECASE)
    return normalize_spaces(match.group(0)) if match else None


def extract_address(text: str) -> str | None:
    return extract_label_value(
        text,
        ("Адреса", "Юридична адреса", "Місцезнаходження"),
        stop_labels=("Телефон", "Email", "E-mail", "Офіційний сайт", "Вебсайт", "Сайт", "Керівник", "Директор", "КВЕД"),
    )


def extract_director(text: str) -> str | None:
    return extract_label_value(
        text,
        ("Керівник", "Директор"),
        stop_labels=("Адреса", "Телефон", "Email", "E-mail", "Офіційний сайт", "Вебсайт", "Сайт", "КВЕД"),
    )


def extract_kved(text: str) -> str | None:
    return extract_label_value(
        text,
        ("КВЕД", "Види діяльності", "Вид діяльності"),
        stop_labels=("Адреса", "Телефон", "Email", "E-mail", "Офіційний сайт", "Вебсайт", "Сайт", "Керівник", "Директор"),
    )


def extract_email(text: str, *, forbidden_domains: set[str] | None = None) -> str | None:
    forbidden_domains = forbidden_domains or set()
    for email in re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-zА-Яа-я]{2,}", text or ""):
        normalized = email.lower().strip(".,;:")
        domain = normalized.rsplit("@", 1)[-1]
        if domain in forbidden_domains:
            continue
        return normalized
    return None


PHONE_LABEL_RE = re.compile(r"(?<!\w)(?:телефон|тел\.?|phone|contact|контакти)(?!\w)", re.IGNORECASE)
PHONE_CANDIDATE_RE = re.compile(
    r"(?:\+?38\D{0,3})?\(?0\d{2,4}\)?(?:\D{0,4}\d{2,3}){2,4}",
    re.IGNORECASE,
)
UA_MOBILE_CODES = {
    "039",
    "050",
    "063",
    "066",
    "067",
    "068",
    "073",
    "075",
    "077",
    "091",
    "092",
    "093",
    "094",
    "095",
    "096",
    "097",
    "098",
    "099",
}
UA_AREA_PREFIXES = {"03", "04", "05", "06"}


def extract_phones(text: str, *, expected_edrpou: str | None = None) -> list[str]:
    text = normalize_spaces(text)
    if not text:
        return []

    candidates: list[tuple[int, str]] = []
    for label_match in PHONE_LABEL_RE.finditer(text):
        window = text[label_match.start() : min(len(text), label_match.end() + 140)]
        for phone_match in PHONE_CANDIDATE_RE.finditer(window):
            raw = phone_match.group(0)
            normalized = normalize_phone(raw)
            if not is_valid_ukrainian_phone(normalized, expected_edrpou=expected_edrpou):
                continue
            distance = max(0, phone_match.start() - len(label_match.group(0)))
            candidates.append((distance, normalized))

    result: list[str] = []
    for _distance, phone in sorted(candidates, key=lambda item: item[0]):
        if phone not in result:
            result.append(phone)
    return result


def extract_phone(text: str, *, expected_edrpou: str | None = None) -> str | None:
    phones = extract_phones(text, expected_edrpou=expected_edrpou)
    return phones[0] if phones else None


def extract_phone_raw(text: str, *, expected_edrpou: str | None = None) -> str | None:
    text = normalize_spaces(text)
    if not text:
        return None
    for label_match in PHONE_LABEL_RE.finditer(text):
        window = text[label_match.start() : min(len(text), label_match.end() + 140)]
        for phone_match in PHONE_CANDIDATE_RE.finditer(window):
            raw = phone_match.group(0)
            if is_valid_ukrainian_phone(normalize_phone(raw), expected_edrpou=expected_edrpou):
                return normalize_spaces(raw)
    return None


def normalize_phone(value: str) -> str | None:
    digits = re.sub(r"\D", "", value or "")
    if not digits:
        return None
    if digits.startswith("380"):
        return f"+{digits}"
    if digits.startswith("0"):
        return f"+38{digits}"
    if digits.startswith("80"):
        return f"+3{digits}"
    return f"+{digits}" if len(digits) >= 10 else None


def is_valid_ukrainian_phone(phone: str | None, *, expected_edrpou: str | None = None) -> bool:
    if not phone:
        return False
    digits = re.sub(r"\D", "", phone)
    if len(digits) != 12 or not digits.startswith("380"):
        return False
    national = digits[2:]
    if len(national) != 10 or not national.startswith("0"):
        return False
    if expected_edrpou and phone_contains_edrpou(digits, expected_edrpou):
        return False
    if is_placeholder_phone(national):
        return False
    code3 = national[:3]
    if code3 in UA_MOBILE_CODES:
        return True
    return national[:2] in UA_AREA_PREFIXES


def phone_contains_edrpou(phone_digits: str, expected_edrpou: str) -> bool:
    edrpou_digits = re.sub(r"\D", "", expected_edrpou or "")
    if len(edrpou_digits) != 8:
        return False
    if edrpou_digits in phone_digits:
        return True
    return any(edrpou_digits[start : start + 7] in phone_digits for start in range(0, 2))


def is_placeholder_phone(national_digits: str) -> bool:
    subscriber_digits = national_digits[3:]
    if subscriber_digits.count("0") >= 5:
        return True
    return len(set(subscriber_digits)) <= 2


def extract_website(text: str) -> str | None:
    match = re.search(r"https?://[^\s<>\)\"']+", text or "", flags=re.IGNORECASE)
    if match:
        return match.group(0).rstrip(".,;")
    label_value = extract_label_value(
        text,
        ("Офіційний сайт", "Вебсайт", "Сайт", "website"),
        stop_labels=("Адреса", "Телефон", "Email", "E-mail", "Керівник", "Директор", "КВЕД"),
    )
    if label_value and re.search(r"\w+\.\w+", label_value):
        return label_value if label_value.startswith(("http://", "https://")) else f"https://{label_value}"
    return None


def context_matches(text: str, context: dict | None) -> dict:
    context = context or {}
    normalized = normalize_compare(text)
    company_name = normalize_compare(context.get("company_name"))
    address = normalize_compare(context.get("address"))
    director = normalize_compare(context.get("director"))
    name_tokens = significant_tokens(company_name)
    address_tokens = significant_tokens(address)
    director_tokens = significant_tokens(director)
    return {
        "name": bool(name_tokens and all(token in normalized for token in name_tokens)),
        "address": bool(address_tokens and any(token in normalized for token in address_tokens[:6])),
        "director": bool(director_tokens and all(token in normalized for token in director_tokens)),
    }


def significant_tokens(value: str) -> list[str]:
    ignored = {
        "приватне",
        "акціонерне",
        "товариство",
        "товариство",
        "прат",
        "пат",
        "тов",
        "ат",
        "вул",
        "вулиця",
        "україна",
    }
    return [token for token in re.findall(r"[a-zа-яіїєґ0-9]{3,}", normalize_compare(value)) if token not in ignored]


def build_found_result(
    source: str,
    *,
    edrpou: str,
    html: str,
    raw_url: str,
    context: dict | None = None,
    website_override: str | None = None,
    forbidden_email_domains: set[str] | None = None,
    ignore_footer: bool = False,
    default_evidence: list[str] | None = None,
) -> dict:
    body = remove_footer_text(html) if ignore_footer else html
    text = visible_text(body)
    company = {
        **EMPTY_COMPANY,
        "edrpou": extract_edrpou(text, edrpou),
        "name": extract_name(text),
        "full_name": None,
        "status": extract_label_value(text, ("Статус", "Стан"), stop_labels=("Адреса", "Телефон", "Email", "E-mail")),
        "address": extract_address(text),
        "director": extract_director(text),
        "kved": extract_kved(text),
    }
    matches = context_matches(text, context)
    contacts = {
        "website": website_override or extract_website(text),
        "phone": extract_phone(text, expected_edrpou=edrpou),
        "email": extract_email(text, forbidden_domains=forbidden_email_domains),
    }
    evidence: list[str] = []
    if company["edrpou"] == edrpou and matches["name"] and matches["address"] and matches["director"]:
        evidence.append("На сторінці знайдено той самий ЄДРПОУ, назву компанії, адресу та керівника.")
    elif company["edrpou"] == edrpou:
        evidence.append(f"На сторінці знайдено ЄДРПОУ {edrpou}.")
    evidence.extend(default_evidence or [])
    if contacts["website"]:
        evidence.append("Знайдено сайт.")
    if contacts["phone"]:
        evidence.append("Знайдено телефон.")
    if contacts["email"]:
        evidence.append("Знайдено email.")
    confidence = calculate_source_confidence(text, edrpou, contacts, context)
    return {
        "source": source,
        "status": "found",
        "company": company,
        "contacts": contacts,
        "evidence": dedupe(evidence),
        "confidence": confidence,
        "raw_url": raw_url,
        "error": None,
    }


def calculate_source_confidence(text: str, edrpou: str, contacts: dict, context: dict | None = None) -> str:
    has_edrpou = extract_edrpou(text, edrpou) == edrpou
    has_contact = bool(contacts.get("website") or contacts.get("phone") or contacts.get("email"))
    matches = context_matches(text, context)
    if has_edrpou and has_contact and (matches["name"] or matches["address"] or not context):
        return "high"
    if has_edrpou:
        return "medium"
    if matches["name"] and (matches["address"] or contacts.get("phone")):
        return "medium"
    if matches["name"]:
        return "low"
    return "unknown"


def document_has_edrpou(html: str, edrpou: str) -> bool:
    return extract_edrpou(visible_text(html), edrpou) == edrpou


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
