from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


ClarityStatus = Literal["found", "not_found", "source_error", "parse_error", "partial"]


class ClarityCompany(BaseModel):
    name: str | None = None
    status: str | None = None
    registration_date: str | None = None
    director: str | None = None
    website: str | None = None
    statutory_capital_uah: float | None = None
    main_activity: str | None = None


class ClarityTax(BaseModel):
    tax_debt: bool | None = None
    tax_debt_amount_uah: float | None = None
    tax_debt_as_of: str | None = None
    esv_debt: bool | None = None
    vat_active: bool | None = None
    single_tax_active: bool | None = None


class ClaritySignals(BaseModel):
    bankruptcy_count: int | None = None
    enforcement_proceedings_count: int | None = None
    inspections_count: int | None = None
    edr_history_count: int | None = None
    licenses_count: int | None = None
    prozorro_sales_count: int | None = None


class ClarityRiskFlag(BaseModel):
    level: str
    code: str
    text: str


class ClarityData(BaseModel):
    source: str = "clarity_project"
    source_url: str
    checked_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    status: ClarityStatus
    edrpou: str
    company: ClarityCompany | None = None
    tax: ClarityTax | None = None
    signals: ClaritySignals | None = None
    risk_flags: list[ClarityRiskFlag] = Field(default_factory=list)
    parse_warnings: list[str] = Field(default_factory=list)
    error: str | None = None
