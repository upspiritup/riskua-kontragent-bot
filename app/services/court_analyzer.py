from __future__ import annotations

import re
from dataclasses import dataclass


OPERATIVE_MARKER_PATTERN = re.compile(
    r"(У\s*Х\s*В\s*А\s*Л\s*И\s*В|ПОСТАНОВИВ|ВИРІШИВ)\s*:",
    re.IGNORECASE,
)
PROCEDURAL_PHRASES = (
    "відкрити провадження",
    "витребувати докази",
    "запропонувати відповідачу подати відзив",
    "в задоволенні клопотання",
    "у задоволенні клопотання",
    "клопотання про зупинення провадження",
    "зупинення провадження",
    "зупинити провадження",
)
NEGATIVE_OUTCOME_PHRASES = (
    "стягнути з відповідача",
    "задовольнити позов",
    "накласти штраф",
    "визнати винним",
    "притягнути до відповідальності",
)
CLAIM_REQUEST_PATTERN = re.compile(r"просить\s+суд.{0,120}", re.IGNORECASE | re.DOTALL)
CLAIM_SUBJECT_PATTERN = re.compile(
    r"(стягнен\w*\s+(?:санкцій|пені|штрафу|заборгованості)|"
    r"стягнути\s+з\s+відповідача|"
    r"накласти\s+штраф|"
    r"притягнути\s+до\s+відповідальності)",
    re.IGNORECASE,
)
UAH_AMOUNT_PATTERN = re.compile(r"(\d[\d\s]*(?:[,.]\d{1,2})?)\s*(?:грн|гривень|uah)", re.IGNORECASE)


@dataclass(frozen=True)
class CourtAnalysisResult:
    operative_part_excerpt: str | None
    procedural_decision_detected: bool
    liability_detected: bool
    negative_outcome_detected: bool
    claim_subject: str | None
    claimed_amount_uah: int | None
    company_role: str | None
    risk_level: str
    risk_summary: str


def analyze_court_decision(text: str) -> CourtAnalysisResult:
    normalized_text = normalize_text(text)
    operative_part = extract_operative_part(normalized_text)
    operative_excerpt = make_excerpt(operative_part) if operative_part else None
    operative_lower = (operative_part or "").lower()

    procedural_decision_detected = contains_any(operative_lower, PROCEDURAL_PHRASES)
    negative_phrase_in_operative = contains_any(operative_lower, NEGATIVE_OUTCOME_PHRASES)
    liability_detected = negative_phrase_in_operative and not procedural_decision_detected
    negative_outcome_detected = liability_detected

    claim_subject = detect_claim_subject(normalized_text)
    claimed_amount_uah = extract_claimed_amount(normalized_text)
    company_role = detect_company_role(normalized_text)
    risk_level, risk_summary = build_risk_assessment(
        procedural_decision_detected=procedural_decision_detected,
        liability_detected=liability_detected,
        claim_subject=claim_subject,
        company_role=company_role,
    )

    return CourtAnalysisResult(
        operative_part_excerpt=operative_excerpt,
        procedural_decision_detected=procedural_decision_detected,
        liability_detected=liability_detected,
        negative_outcome_detected=negative_outcome_detected,
        claim_subject=claim_subject,
        claimed_amount_uah=claimed_amount_uah,
        company_role=company_role,
        risk_level=risk_level,
        risk_summary=risk_summary,
    )


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def extract_operative_part(text: str) -> str | None:
    match = OPERATIVE_MARKER_PATTERN.search(text)
    if not match:
        return None
    return text[match.end() :].strip()


def make_excerpt(text: str, limit: int = 700) -> str:
    return text[:limit].strip()


def contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def detect_claim_subject(text: str) -> str | None:
    claim_request = CLAIM_REQUEST_PATTERN.search(text)
    search_area = claim_request.group(0) if claim_request else text
    subject_match = CLAIM_SUBJECT_PATTERN.search(search_area)
    if not subject_match:
        return None
    return subject_match.group(0).lower()


def extract_claimed_amount(text: str) -> int | None:
    match = UAH_AMOUNT_PATTERN.search(text)
    if not match:
        return None

    raw_amount = match.group(1).replace(" ", "").replace(",", ".")
    try:
        return int(float(raw_amount))
    except ValueError:
        return None


def detect_company_role(text: str) -> str | None:
    lowered = text.lower()
    if "відповідач" in lowered or "з відповідача" in lowered:
        return "defendant"
    if "позивач" in lowered:
        return "claimant"
    return None


def build_risk_assessment(
    *,
    procedural_decision_detected: bool,
    liability_detected: bool,
    claim_subject: str | None,
    company_role: str | None,
) -> tuple[str, str]:
    if (
        procedural_decision_detected
        and company_role == "defendant"
        and claim_subject
        and ("санкц" in claim_subject or "пені" in claim_subject or "стягнути" in claim_subject)
    ):
        return (
            "medium",
            "Компанія є відповідачем у справі про стягнення санкцій/пені, але документ є процесуальною ухвалою і не підтверджує фактичне стягнення.",
        )

    if liability_detected:
        return (
            "high",
            "У резолютивній частині є ознаки негативного результату для відповідача. Потребує додаткової перевірки за повним текстом рішення.",
        )

    if procedural_decision_detected:
        return (
            "medium",
            "Документ виглядає як процесуальна ухвала і не підтверджує фактичне стягнення або відповідальність.",
        )

    return (
        "low",
        "У тексті не знайдено явних ознак встановленої відповідальності. Результат потребує додаткової перевірки за повним текстом документа.",
    )
