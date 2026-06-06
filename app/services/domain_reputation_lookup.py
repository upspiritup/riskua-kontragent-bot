from __future__ import annotations

from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser
import logging
import re
import socket
import ssl
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


SOURCE = "domain_reputation"
WEBSITE_NOT_PROVIDED = "website_not_provided"
WEBSITE_UNAVAILABLE = "website_unavailable"
WEBSITE_SOURCE_UNAVAILABLE = "website_source_unavailable"
HTTP_TIMEOUT_SECONDS = 8.0
SSL_TIMEOUT_SECONDS = 5.0
MAX_HTML_BYTES = 300_000
EMPTY_TEXT_THRESHOLD = 20
FREE_EMAIL_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "ukr.net",
    "i.ua",
    "meta.ua",
    "yahoo.com",
    "outlook.com",
    "hotmail.com",
    "live.com",
    "icloud.com",
    "proton.me",
    "protonmail.com",
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


def normalize_url(value: str | None) -> str | None:
    text = normalize_spaces(value)
    if not text:
        return None
    if not re.match(r"^[a-z][a-z0-9+.-]*://", text, flags=re.IGNORECASE):
        text = f"https://{text}"
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return text


def extract_domain(url: str | None) -> str | None:
    normalized_url = normalize_url(url)
    if not normalized_url:
        return None
    host = (urlparse(normalized_url).hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host or None


def fetch_domain_reputation(
    domain_or_url: str | None,
    company_context: dict | None = None,
    fetcher: Callable[[str], str | dict[str, Any]] | None = None,
) -> dict:
    url = normalize_url(domain_or_url)
    if not url:
        return website_not_provided_result()

    domain = extract_domain(url)
    if not domain:
        return website_not_provided_result()

    try:
        http_snapshot = fetch_http_snapshot(url, fetcher=fetcher)
    except (TimeoutError, OSError, HTTPError, URLError, ValueError) as exc:
        logging.info("Website unavailable for %s: %s", domain, exc)
        return website_unavailable_result(url, domain)

    status_code = http_snapshot.get("status_code")
    if status_code is None or int(status_code) >= 400:
        return website_unavailable_result(url, domain, http_snapshot=http_snapshot)

    html = str(http_snapshot.pop("html", "") or "")
    ssl_info = fetch_ssl_info(domain)
    dns_info = fetch_dns_info(domain)
    contacts = extract_contacts_from_html(html)
    contacts = apply_company_context_to_contacts(contacts, html, company_context or {})
    result = {
        "source": SOURCE,
        "checked": True,
        "found": True,
        "url": url,
        "domain": domain,
        "checked_at": checked_at(),
        "http": http_snapshot,
        "ssl": ssl_info,
        "dns": dns_info,
        "contacts": contacts,
        "trust_level": website_trust_level(contacts),
        "signals": [],
        "risk_flags": [],
        "error": None,
    }
    risk_flags = build_domain_risk_flags(result)
    risk_flags.extend(compare_website_with_company(result, company_context or {}))
    result["risk_flags"] = unique(risk_flags)
    result["signals"] = build_domain_signals(result)
    return result


def fetch_http_snapshot(
    url: str,
    fetcher: Callable[[str], str | dict[str, Any]] | None = None,
) -> dict:
    if fetcher is not None:
        payload = fetcher(url)
        if isinstance(payload, dict):
            return with_http_defaults(payload, url)
        return build_http_snapshot(status_code=200, final_url=url, redirects=[], html=str(payload or ""))

    request = Request(
        url,
        headers={
            "User-Agent": "RiskUA Bot MVP/0.1",
            "Accept": "text/html,application/xhtml+xml",
        },
        method="GET",
    )
    with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        raw = response.read(MAX_HTML_BYTES + 1)
        if len(raw) > MAX_HTML_BYTES:
            raise ValueError("website_html_too_large")
        charset = response.headers.get_content_charset() or "utf-8"
        html = raw.decode(charset, errors="replace")
        return build_http_snapshot(
            status_code=getattr(response, "status", None) or response.getcode(),
            final_url=response.geturl(),
            redirects=[],
            html=html,
        )


def fetch_ssl_info(domain: str) -> dict:
    try:
        context = ssl.create_default_context()
        with socket.create_connection((domain, 443), timeout=SSL_TIMEOUT_SECONDS) as sock:
            with context.wrap_socket(sock, server_hostname=domain) as tls:
                cert = tls.getpeercert()
    except (OSError, ssl.SSLError, TimeoutError):
        return {"present": False, "not_before": None, "not_after": None, "issuer": None}

    return {
        "present": True,
        "not_before": cert.get("notBefore"),
        "not_after": cert.get("notAfter"),
        "issuer": format_issuer(cert.get("issuer")),
    }


def fetch_dns_info(domain: str) -> dict:
    try:
        _hostname, _aliases, addresses = socket.gethostbyname_ex(domain)
    except OSError:
        return {"found": False, "a_records": [], "mx_records": []}
    return {"found": bool(addresses), "a_records": addresses, "mx_records": []}


def extract_contacts_from_html(html: str) -> dict:
    text = visible_text(html)
    emails = unique([email.lower() for email in re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", html)])
    phones = unique(normalize_phone(match) for match in re.findall(r"(?:\+?380|0)\D{0,3}\d{2}\D{0,3}\d{3}\D{0,3}\d{2}\D{0,3}\d{2}", html))
    return {
        "emails": [email for email in emails if email],
        "phones": [phone for phone in phones if phone],
        "edrpou_found_on_page": False,
        "company_name_found_on_page": False,
        "address_found_on_page": False,
        "_text": text,
    }


def compare_website_with_company(website_data: dict, company_context: dict) -> list[str]:
    contacts = website_data.get("contacts") or {}
    flags: list[str] = []
    if company_context.get("edrpou") and not contacts.get("edrpou_found_on_page"):
        flags.append("company_edrpou_not_found_on_website")
    if company_context.get("company_name") and not contacts.get("company_name_found_on_page"):
        flags.append("company_name_not_found_on_website")

    known_domains = [extract_domain(domain) for domain in company_context.get("known_domains", [])]
    domain = website_data.get("domain")
    if known_domains and domain not in known_domains:
        flags.append("domain_company_mismatch")
    return flags


def website_trust_level(contacts: dict) -> str:
    if contacts.get("edrpou_found_on_page"):
        return "high"
    if contacts.get("address_found_on_page"):
        return "medium"
    if contacts.get("company_name_found_on_page"):
        return "low"
    return "unknown"


def build_domain_risk_flags(result: dict) -> list[str]:
    if result.get("error") == WEBSITE_UNAVAILABLE:
        return ["website_unavailable"]
    if result.get("error") == WEBSITE_SOURCE_UNAVAILABLE:
        return ["website_source_unavailable"]

    flags: list[str] = []
    http = result.get("http") or {}
    ssl_info = result.get("ssl") or {}
    dns_info = result.get("dns") or {}
    contacts = result.get("contacts") or {}

    if http.get("is_empty"):
        flags.append("empty_website")
    if ssl_info.get("present") is False:
        flags.append("ssl_missing")
    if dns_info.get("found") is False:
        flags.append("dns_not_found")
    if suspicious_redirects_detected(result.get("url"), http):
        flags.append("suspicious_redirects")
    emails = contacts.get("emails") or []
    if emails and all(email_domain(email) in FREE_EMAIL_DOMAINS for email in emails):
        flags.append("free_email_used")
    return unique(flags)


def apply_company_context_to_contacts(contacts: dict, html: str, company_context: dict) -> dict:
    text = contacts.get("_text") or visible_text(html)
    normalized_text = normalize_compare(text)
    edrpou = normalize_spaces(company_context.get("edrpou"))
    company_name = normalize_spaces(company_context.get("company_name"))
    address = normalize_spaces(company_context.get("address"))

    prepared = dict(contacts)
    prepared["edrpou_found_on_page"] = bool(edrpou and edrpou in re.sub(r"\D", "", text))
    prepared["company_name_found_on_page"] = bool(company_name and company_name_matches(normalized_text, company_name))
    prepared["address_found_on_page"] = bool(address and address_matches(normalized_text, address))
    prepared.pop("_text", None)
    return prepared


def build_domain_signals(result: dict) -> list[str]:
    if result.get("error") == WEBSITE_UNAVAILABLE:
        return ["Сайт постачальника не вдалося відкрити автоматично"]
    signals: list[str] = []
    if result.get("found"):
        signals.append("Сайт постачальника відкривається")
    if (result.get("ssl") or {}).get("present"):
        signals.append("HTTPS працює")
    for flag in result.get("risk_flags") or []:
        if flag == "free_email_used":
            signals.append("На сайті знайдено тільки безкоштовну email-адресу")
        elif flag == "company_edrpou_not_found_on_website":
            signals.append("На сайті не знайдено ЄДРПОУ компанії")
        elif flag == "company_name_not_found_on_website":
            signals.append("На сайті не знайдено назву компанії")
        elif flag == "empty_website":
            signals.append("Сайт відкривається, але сторінка майже порожня")
    return unique(signals)


def website_not_provided_result() -> dict:
    return {
        "source": SOURCE,
        "checked": False,
        "found": False,
        "url": None,
        "domain": None,
        "signals": [],
        "risk_flags": [],
        "error": WEBSITE_NOT_PROVIDED,
    }


def website_unavailable_result(url: str, domain: str, *, http_snapshot: dict | None = None) -> dict:
    http = {
        "status_code": None,
        "final_url": None,
        "redirects": [],
    }
    if http_snapshot:
        http.update(
            {
                "status_code": http_snapshot.get("status_code"),
                "final_url": http_snapshot.get("final_url"),
                "redirects": list(http_snapshot.get("redirects") or []),
            }
        )
    return {
        "source": SOURCE,
        "checked": True,
        "found": False,
        "url": url,
        "domain": domain,
        "checked_at": checked_at(),
        "http": http,
        "ssl": None,
        "dns": None,
        "contacts": None,
        "signals": ["Сайт постачальника не вдалося відкрити автоматично"],
        "risk_flags": ["website_unavailable"],
        "error": WEBSITE_UNAVAILABLE,
    }


def with_http_defaults(payload: dict[str, Any], url: str) -> dict:
    return build_http_snapshot(
        status_code=payload.get("status_code"),
        final_url=str(payload.get("final_url") or url),
        redirects=list(payload.get("redirects") or []),
        html=str(payload.get("html") or ""),
        title=payload.get("title"),
        is_empty=payload.get("is_empty"),
    )


def build_http_snapshot(
    *,
    status_code: int | None,
    final_url: str | None,
    redirects: list[str],
    html: str,
    title: str | None = None,
    is_empty: bool | None = None,
) -> dict:
    page_text = visible_text(html)
    return {
        "status_code": status_code,
        "final_url": final_url,
        "redirects": redirects,
        "title": title if title is not None else extract_title(html),
        "is_empty": is_empty if is_empty is not None else len(page_text) < EMPTY_TEXT_THRESHOLD,
        "html": html,
    }


def visible_text(html: str) -> str:
    parser = VisibleTextParser()
    parser.feed(html or "")
    return normalize_spaces(" ".join(parser.parts))


def extract_title(html: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", html or "", flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return normalize_spaces(unescape(re.sub(r"<[^>]+>", " ", match.group(1)))) or None


def suspicious_redirects_detected(original_url: str | None, http: dict) -> bool:
    redirects = list(http.get("redirects") or [])
    if len(redirects) > 3:
        return True
    final_url = http.get("final_url")
    original_domain = extract_domain(original_url)
    final_domain = extract_domain(final_url)
    return bool(original_domain and final_domain and final_domain != original_domain)


def company_name_matches(normalized_text: str, company_name: str) -> bool:
    tokens = company_name_tokens(company_name)
    if not tokens:
        return False
    return all(token in normalized_text for token in tokens)


def company_name_tokens(company_name: str) -> list[str]:
    ignored = {"тов", "ат", "пат", "приватне", "акціонерне", "товариство", "обмеженою", "відповідальністю"}
    normalized = normalize_compare(company_name)
    return [token for token in re.findall(r"[a-zа-яіїєґ0-9]{3,}", normalized) if token not in ignored]


def address_matches(normalized_text: str, address: str) -> bool:
    tokens = [token for token in re.findall(r"[a-zа-яіїєґ0-9]{4,}", normalize_compare(address))[:6]]
    return bool(tokens and sum(1 for token in tokens if token in normalized_text) >= max(1, len(tokens) // 2))


def email_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower()


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("0"):
        digits = f"38{digits}"
    return f"+{digits}" if digits else ""


def normalize_spaces(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def normalize_compare(value: Any) -> str:
    return normalize_spaces(value).lower().replace("’", "'").replace("«", "").replace("»", "").replace('"', "")


def format_issuer(issuer: Any) -> str | None:
    if not issuer:
        return None
    parts: list[str] = []
    for item in issuer:
        for key, value in item:
            if key and value:
                parts.append(f"{key}={value}")
    return ", ".join(parts) or None


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def checked_at() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
