from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.models.clarity import ClarityData


LookupStatus = Literal["found", "not_found", "source_error", "parse_error", "partial"]


class OwnerData(BaseModel):
    name: str | None = None
    country: str | None = None
    role: str | None = None
    share_percent: float | None = None
    contribution_uah: int | None = None
    is_beneficial_owner: bool = False


class CompanyData(BaseModel):
    full_name: str | None = None
    short_name: str | None = None
    edrpou: str | None = None
    status: str | None = None
    address: str | None = None
    city: str | None = None
    region: str | None = None
    registration_date: str | None = None
    registry_extract_time: str | None = None
    director: str | None = None
    website: str | None = None
    phones: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)
    statutory_capital_uah: int | None = None
    vat_status: str | None = None
    main_activity_code: str | None = None
    main_activity_name: str | None = None
    additional_activities: list[str] = Field(default_factory=list)
    tenders_count: int | None = None
    tenders_text: str | None = None
    owners_count: int = 0
    owners: list[OwnerData] = Field(default_factory=list)
    beneficial_owners: list[OwnerData] = Field(default_factory=list)


class FinancialYearData(BaseModel):
    revenue_uah: int | None = None
    revenue_change_percent: float | None = None
    net_profit_uah: int | None = None
    profitability_percent: float | None = None
    assets_uah: int | None = None
    liabilities_uah: int | None = None
    equity_uah: int | None = None
    employees_count: int | None = None
    revenue_per_employee_uah: int | None = None


class FinancialData(BaseModel):
    years: dict[str, FinancialYearData] = Field(default_factory=dict)
    forecast: dict[str, Any] = Field(default_factory=dict)
    financial_reports: list[str] = Field(default_factory=list)
    parse_warnings: list[str] = Field(default_factory=list)


class RegistrationChange(BaseModel):
    date: str | None = None
    date_requires_login: bool = False
    change_type: str | None = None
    before: str | None = None
    after: str | None = None


class CourtData(BaseModel):
    has_court_mentions: bool = False
    court_mentions_count: int = 0
    court_unique_cases_count: int | None = None
    court_risky_cases_count: int | None = None
    total_cases_found: int = 0
    court_categories: dict[str, int] = Field(default_factory=dict)
    latest_court_date: str | None = None
    source_urls: list[str] = Field(default_factory=list)
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    parse_warnings: list[str] = Field(default_factory=list)


class ProzorroProcurement(BaseModel):
    procurement_id: str | None = None
    url: str | None = None
    title: str | None = None
    cpv_code: str | None = None
    cpv_name: str | None = None
    procedure_type: str | None = None
    status: str | None = None
    expected_value_uah: float | None = None
    bid_value_uah: float | None = None
    contract_value_uah: float | None = None
    buyer_name: str | None = None
    buyer_edrpou: str | None = None
    participants_count: int | None = None
    participated: bool = False
    won: bool = False
    disqualified: bool = False
    disqualification_reason: str | None = None
    has_contract: bool = False
    contract_completed: bool = False
    contract_terminated: bool = False
    termination_reason: str | None = None
    complaints_count: int = 0
    supplier_related_complaints_count: int = 0
    amendments_count: int = 0
    contract_amount_change_uah: float | None = None
    contract_amount_change_percent: float | None = None
    date: str | None = None
    award_date: str | None = None
    contract_date: str | None = None


class ProzorroStats(BaseModel):
    procurements_count: int = 0
    participations_count: int = 0
    wins_count: int = 0
    contracts_count: int = 0
    completed_contracts_count: int = 0
    terminated_contracts_count: int = 0
    disqualifications_count: int = 0
    complaints_count: int = 0
    supplier_related_complaints_count: int = 0
    first_participation_date: str | None = None
    last_participation_date: str | None = None
    last_win_date: str | None = None
    win_rate_percent: float | None = None
    termination_rate_percent: float | None = None
    disqualification_rate_percent: float | None = None
    single_buyer_contract_share_percent: float | None = None
    single_buyer_value_share_percent: float | None = None
    low_competition_wins_count: int = 0
    high_discount_bids_count: int = 0


class ProzorroAnalysis(BaseModel):
    source: str = "prozorro_analysis"
    status: Literal["found", "not_found", "partial", "source_error"] = "not_found"
    stats: ProzorroStats = Field(default_factory=ProzorroStats)
    procurements: list[ProzorroProcurement] = Field(default_factory=list)
    risk_flags: list[dict[str, Any]] = Field(default_factory=list)
    info_notes: list[str] = Field(default_factory=list)
    summary: str | None = None
    parse_warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RiskInput(BaseModel):
    company_age_years: int | None = None
    has_full_registration_data: bool = False
    has_director: bool = False
    has_beneficial_owner: bool = False
    owners_count: int = 0
    statutory_capital_uah: int | None = None
    has_financial_history: bool = False
    latest_revenue_uah: int | None = None
    latest_net_profit_uah: int | None = None
    latest_profitability_percent: float | None = None
    latest_employees_count: int | None = None
    had_losses_in_previous_years: bool = False
    revenue_drop_detected: bool = False
    registration_address_changed: bool = False
    main_activity_code: str | None = None
    main_activity_name: str | None = None
    has_court_mentions: bool = False
    court_mentions_count: int = 0
    court_unique_cases_count: int | None = None
    court_risky_cases_count: int | None = None
    total_court_cases_found: int = 0
    tax_debt_found: bool = False
    tax_debt_count: int = 0
    tax_debt_text: str | None = None


class SourceDiagnostic(BaseModel):
    source: str
    status: str
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)


class RiskFlagSnapshot(BaseModel):
    source: str
    sources: list[str] = Field(default_factory=list)
    level: str
    code: str
    type: str | None = None
    weight: int = 0
    text: str


class RiskSummary(BaseModel):
    score: int = 0
    level: str = "low"
    label_uk: str = "Низький ризик"
    reasons: list[dict[str, Any]] = Field(default_factory=list)
    flags: list[RiskFlagSnapshot] = Field(default_factory=list)
    signals: list[dict[str, Any]] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    manual_review_required: bool = False
    hard_fact_present: bool = False


class CompanyLookupResult(BaseModel):
    check_id: str = Field(default_factory=lambda: str(uuid4()))
    telegram_user_id: int | None = None
    edrpou: str
    source: str = "opendatabot"
    source_url: str | None = None
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: LookupStatus
    company_data: CompanyData | None = None
    financial_data: FinancialData = Field(default_factory=FinancialData)
    registration_changes: list[RegistrationChange] = Field(default_factory=list)
    court_data: CourtData = Field(default_factory=CourtData)
    risk_input: RiskInput = Field(default_factory=RiskInput)
    risk_summary: RiskSummary = Field(default_factory=RiskSummary)
    parse_warnings: list[str] = Field(default_factory=list)
    source_diagnostics: list[SourceDiagnostic] = Field(default_factory=list)
    clarity_data: ClarityData | None = None
    youcontrol_data: dict[str, Any] | None = None
    debtors_registry_data: dict[str, Any] | None = None
    tax_data: dict[str, Any] | None = None
    domain_reputation_data: dict[str, Any] | None = None
    prozorro_analysis: ProzorroAnalysis | None = None
    contacts_summary: dict[str, Any] | None = None
    sources: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
