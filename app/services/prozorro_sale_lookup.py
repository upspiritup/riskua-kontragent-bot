from __future__ import annotations

import logging
import os
import re
from html import unescape
from html.parser import HTMLParser
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request, urlopen

from app.models.company_lookup import ProzorroSaleAnalysis, ProzorroSaleRiskAuction
from app.utils.validators import is_valid_edrpou


PROZORRO_SALE_SEARCH_URL = "https://prozorro.sale/auction/?query={edrpou}"
PROZORRO_SALE_TIMEOUT_SECONDS = 8.0
DEFAULT_MAX_ITEMS = 10
RISK_MARKERS: tuple[tuple[str, str], ...] = (
    ("аукціон не відбувся", "аукціон не відбувся"),
    ("торги не відбулися", "аукціон не відбувся"),
    ("не відбувся", "аукціон не відбувся"),
    ("переможець не виконав умови", "переможець не виконав умови"),
    ("не виконав умови", "переможець не виконав умови"),
    ("дискваліф", "дискваліфікація переможця"),
    ("несплат", "несплата"),
    ("відмова від підписання", "відмова від підписання"),
    ("не підписав протокол", "відмова від підписання"),
    ("не підписав договір", "відмова від підписання"),
    ("повторний аукціон", "повторний аукціон"),
    ("повторні торги", "повторний аукціон"),
    ("аукціон скасовано", "скасування торгів"),
    ("торги скасовано", "скасування торгів"),
    ("скасування торгів", "скасування торгів"),
)
INFORMATIONAL_ONLY_RISKS: tuple[str, ...] = (
    "аукціон не відбувся",
    "повторний аукціон",
    "скасування торгів",
)
BANKRUPTCY_RISK = "ознаки банкрутства / ліквідаційна маса"
BANKRUPTCY_MARKERS: tuple[str, ...] = (
    "ліквідаційна маса банкрута",
    "ліквідаційної маси банкрута",
    "справа про банкрутство",
    "справі про банкрутство",
    "процедура банкрутства",
    "визнано банкрутом",
    "боржника банкрутом",
)
BANKRUPTCY_NEGATIVE_MARKERS: tuple[str, ...] = (
    "банкрутство не виявлено",
    "банкрутство відсут",
    "банкрутство не знайдено",
    "справи про банкрутство відсут",
    "відомості про банкрутство відсут",
)
DEBTOR_MENTION_MARKERS: tuple[str, ...] = (
    "борг",
    "дебіторська заборгованість",
    "дебіторської заборгованості",
    "право вимоги",
    "права вимоги",
    "заборгованість",
)
OWNER_MENTION_MARKERS: tuple[str, ...] = (
    "продаж майна",
    "майна банкрута",
    "ліквідаційна маса",
    "ліквідаційної маси",
)
DISQUALIFICATION_MARKERS: tuple[str, ...] = ("дискваліф", "відхилен")
DISQUALIFICATION_CONFIRMATION_MARKERS: tuple[str, ...] = (
    "статус учасника",
    "статус переможця",
    "дискваліфіковано",
    "дискваліфікований",
    "дискваліфікована",
    "відхилено",
    "відхилена",
)
DISQUALIFICATION_GENERIC_CONTEXT_MARKERS: tuple[str, ...] = (
    "порядок дискваліфікації",
    "процедура дискваліфікації",
    "регламент",
    "не стосується",
)
WINNER_MARKERS: tuple[str, ...] = ("переможець", "не виконав умови")
PARTICIPANT_MARKERS: tuple[str, ...] = ("учасник", "пропозиція", "заява на участь")
ORGANIZER_MARKERS: tuple[str, ...] = ("організатор", "замовник", "продавець")


class AuctionLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        for name, value in attrs:
            if name == "href" and value:
                self.links.append(unescape(value))


def build_prozorro_sale_search_url(edrpou: str) -> str:
    return PROZORRO_SALE_SEARCH_URL.format(edrpou=edrpou)


def fetch_prozorro_sale_page(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "RiskUA Bot MVP/0.1",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urlopen(request, timeout=PROZORRO_SALE_TIMEOUT_SECONDS) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def lookup_prozorro_sale_by_edrpou(
    edrpou: str,
    *,
    fetcher: Callable[[str], str] = fetch_prozorro_sale_page,
    max_items: int | None = None,
) -> ProzorroSaleAnalysis:
    source_url = build_prozorro_sale_search_url(edrpou)
    if not is_valid_edrpou(edrpou):
        return ProzorroSaleAnalysis(source_url=source_url, status="source_error", error="invalid_edrpou")
    if fetcher is fetch_prozorro_sale_page and not prozorro_sale_enabled():
        return ProzorroSaleAnalysis(source_url=source_url, status="not_found")

    max_items = max_items if max_items is not None else prozorro_sale_max_items()
    logging.info("Prozorro.Sale lookup start edrpou=%s max_items=%s", edrpou, max_items)
    try:
        search_html = fetcher(source_url)
        detail_urls = extract_auction_detail_urls(search_html, max_items=max_items)
        risky_auctions: list[ProzorroSaleRiskAuction] = []
        informational_mentions: list[ProzorroSaleRiskAuction] = []
        confirmed_count = 0
        for detail_url in detail_urls:
            detail_html = fetcher(detail_url)
            detail_text = html_to_text(detail_html)
            if edrpou not in detail_text:
                continue
            confirmed_count += 1
            role = detect_company_role_in_prozorro_sale(edrpou, detail_text)
            bankruptcy_risk = (
                detect_prozorro_sale_bankruptcy_risk(detail_text)
                if role in {"bankrupt_company", "asset_owner"}
                else None
            )
            risk = combine_prozorro_sale_risks(
                detect_prozorro_sale_risk(detail_text),
                bankruptcy_risk,
            )
            if role == "debtor_mention":
                informational_mentions.append(
                    ProzorroSaleRiskAuction(
                        auction_id=extract_auction_id_from_url(detail_url) or extract_auction_id(detail_text),
                        risk="компанія згадується у складі дебіторської заборгованості банкрута",
                        url=detail_url,
                        role=role,
                    )
                )
                continue
            if is_informational_only_prozorro_sale_risk(risk):
                informational_mentions.append(
                    ProzorroSaleRiskAuction(
                        auction_id=extract_auction_id_from_url(detail_url) or extract_auction_id(detail_text),
                        risk=risk or "згадка компанії в аукціоні Prozorro.Sale",
                        url=detail_url,
                        role=role,
                    )
                )
                continue
            if risk and not is_confirmed_company_negative_action(risk, role):
                informational_mentions.append(
                    ProzorroSaleRiskAuction(
                        auction_id=extract_auction_id_from_url(detail_url) or extract_auction_id(detail_text),
                        risk="знайдено згадку/маркер, але негативну дію саме цієї компанії не підтверджено",
                        url=detail_url,
                        role=role,
                    )
                )
                continue
            if risk:
                auction = ProzorroSaleRiskAuction(
                    auction_id=extract_auction_id_from_url(detail_url) or extract_auction_id(detail_text),
                    risk=risk,
                    url=detail_url,
                    role=role,
                )
                risky_auctions.append(auction)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        logging.info("Prozorro.Sale lookup error edrpou=%s error=%s", edrpou, exc)
        return ProzorroSaleAnalysis(source_url=source_url, status="source_error", error=str(exc))

    status = "found" if risky_auctions or informational_mentions else "not_found"
    analysis = ProzorroSaleAnalysis(
        source_url=source_url,
        status=status,
        checked_count=len(detail_urls),
        confirmed_count=confirmed_count,
        risky_auctions=risky_auctions,
        informational_mentions=informational_mentions,
        risk_flags=build_prozorro_sale_risk_flags(risky_auctions, informational_mentions),
    )
    logging.info(
        "Prozorro.Sale lookup done edrpou=%s status=%s checked=%s confirmed=%s risks=%s",
        edrpou,
        analysis.status,
        analysis.checked_count,
        analysis.confirmed_count,
        len(analysis.risky_auctions),
    )
    return analysis


def prozorro_sale_enabled() -> bool:
    value = os.environ.get("PROZORRO_SALE_ENABLED")
    if value is None:
        return True
    return value.strip().lower() not in {"0", "false", "no", "off"}


def prozorro_sale_max_items() -> int:
    return int(os.environ.get("PROZORRO_SALE_MAX_ITEMS", str(DEFAULT_MAX_ITEMS)))


def extract_auction_detail_urls(html: str, *, max_items: int) -> list[str]:
    parser = AuctionLinkParser()
    parser.feed(html)
    urls: list[str] = []
    for href in parser.links:
        absolute_url = normalize_auction_url(href)
        if absolute_url and absolute_url not in urls:
            urls.append(absolute_url)
        if len(urls) >= max_items:
            break
    return urls


def normalize_auction_url(href: str) -> str | None:
    url = urljoin("https://prozorro.sale", href)
    if "/auction/" not in url:
        return None
    if "/auction/?" in url:
        return None
    return url.split("#", 1)[0]


def html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def detect_prozorro_sale_risk(text: str) -> str | None:
    lowered = text.casefold()
    for marker, risk in RISK_MARKERS:
        if marker.casefold() in lowered:
            return risk
    return None


def detect_prozorro_sale_bankruptcy_risk(text: str) -> str | None:
    lowered = text.casefold()
    if any(marker.casefold() in lowered for marker in BANKRUPTCY_NEGATIVE_MARKERS):
        return None
    if any(marker.casefold() in lowered for marker in BANKRUPTCY_MARKERS):
        return BANKRUPTCY_RISK
    return None


def detect_company_role_in_prozorro_sale(edrpou: str, text: str) -> str:
    contexts = edrpou_contexts(edrpou, text)
    if not contexts:
        return "unrelated_mention"

    if any(context_has_marker(context, DEBTOR_MENTION_MARKERS) for context in contexts):
        return "debtor_mention"
    if any(context_confirms_disqualified_company(context) for context in contexts):
        return "disqualified_winner"
    if any(context_has_marker(context, WINNER_MARKERS) for context in contexts):
        return "winner"
    if any(context_has_marker(context, ORGANIZER_MARKERS) for context in contexts):
        return "organizer"
    if any(context_has_marker(context, PARTICIPANT_MARKERS) for context in contexts):
        return "auction_participant"

    lowered = text.casefold()
    if detect_prozorro_sale_bankruptcy_risk(text) and context_has_marker(lowered, OWNER_MENTION_MARKERS):
        return "bankrupt_company"
    if context_has_marker(lowered, OWNER_MENTION_MARKERS):
        return "asset_owner"
    return "unrelated_mention"


def edrpou_contexts(edrpou: str, text: str, *, window: int = 90) -> list[str]:
    contexts: list[str] = []
    for match in re.finditer(re.escape(edrpou), text):
        start = max(0, match.start() - window)
        end = min(len(text), match.end() + window)
        contexts.append(text[start:end].casefold())
    return contexts


def context_has_marker(context: str, markers: tuple[str, ...]) -> bool:
    lowered = context.casefold()
    return any(marker.casefold() in lowered for marker in markers)


def context_confirms_disqualified_company(context: str) -> bool:
    lowered = context.casefold()
    if context_has_marker(lowered, DISQUALIFICATION_GENERIC_CONTEXT_MARKERS):
        return False
    return context_has_marker(lowered, DISQUALIFICATION_MARKERS) and context_has_marker(
        lowered,
        DISQUALIFICATION_CONFIRMATION_MARKERS,
    )


def combine_prozorro_sale_risks(primary: str | None, bankruptcy: str | None) -> str | None:
    if primary and bankruptcy and bankruptcy not in primary:
        return f"{primary}; {bankruptcy}"
    return primary or bankruptcy


def is_informational_only_prozorro_sale_risk(risk: str | None) -> bool:
    if not risk:
        return False
    risk_parts = [part.strip().casefold() for part in risk.split(";") if part.strip()]
    if not risk_parts:
        return False
    informational_risks = {item.casefold() for item in INFORMATIONAL_ONLY_RISKS}
    return all(part in informational_risks for part in risk_parts)


def is_confirmed_company_negative_action(risk: str, role: str) -> bool:
    lowered = risk.casefold()
    if BANKRUPTCY_RISK.casefold() in lowered:
        return role in {"bankrupt_company", "asset_owner"}
    if "дискваліф" in lowered or "відхилен" in lowered:
        return role == "disqualified_winner"
    if "переможець не виконав умови" in lowered or "не виконав умови" in lowered:
        return role in {"winner", "disqualified_winner"}
    if "відмова від підписання" in lowered or "не підписав" in lowered:
        return role in {"winner", "disqualified_winner"}
    if "несплат" in lowered or "не сплат" in lowered:
        return role in {"winner", "disqualified_winner"}
    return False


def extract_auction_id(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"\b[A-Z0-9]+-UA-\d{8}-\d{5}\b", value)
    return match.group(0) if match else None


def extract_auction_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    parts = [part for part in urlparse(url).path.split("/") if part]
    for index, part in enumerate(parts):
        if part == "auction" and index + 1 < len(parts):
            return unquote(parts[index + 1])
    return None


def build_prozorro_sale_risk_flags(
    auctions: list[ProzorroSaleRiskAuction],
    informational_mentions: list[ProzorroSaleRiskAuction] | None = None,
) -> list[dict[str, str]]:
    flags: list[dict[str, str]] = []
    bankruptcy_added = False
    for auction in auctions:
        raw_text = f"{auction.auction_id or 'auction'} — {auction.risk}"
        flags.append(
            {
                "type": "prozorro_sale_risky_auction",
                "source": "prozorro_sale",
                "status": "found",
                "confidence": "medium",
                "raw_text": raw_text,
                "url": auction.url,
            }
        )
        if BANKRUPTCY_RISK in auction.risk and not bankruptcy_added:
            flags.append(
                {
                    "type": "bankruptcy_found",
                    "source": "prozorro_sale",
                    "status": "found",
                    "confidence": "high",
                    "raw_text": raw_text,
                    "url": auction.url,
                }
            )
            bankruptcy_added = True
    for mention in informational_mentions or []:
        if mention.role != "debtor_mention":
            continue
        flags.append(
            {
                "type": "prozorro_sale_debtor_mention",
                "source": "prozorro_sale",
                "status": "found",
                "confidence": "medium",
                "raw_text": f"{mention.auction_id or 'auction'} — {mention.risk}",
                "url": mention.url,
            }
        )
    return flags
