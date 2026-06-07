# Prozorro Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first-stage Prozorro analysis layer: internal data models, source-independent analyzer, risk flags, scoring integration, report block, and tests.

**Architecture:** Keep data acquisition separate from analysis. `app/services/prozorro_analysis.py` accepts normalized models or raw dictionaries and returns `ProzorroAnalysis`; `app/services/risk_scoring.py` only knows about canonical risk flags and weights; `app/bot.py` carries analysis results into summaries and user-facing text.

**Tech Stack:** Python 3, Pydantic models in `app/models/company_lookup.py`, unittest tests under `tests/`, existing RiskUA scoring helpers.

---

## File Structure

- Modify: `app/models/company_lookup.py`
  - Add `ProzorroProcurement`, `ProzorroStats`, `ProzorroAnalysis`.
  - Add `prozorro_analysis: ProzorroAnalysis | None = None` to `CompanyLookupResult`.
- Create: `app/services/prozorro_analysis.py`
  - Normalize raw dicts and model objects.
  - Calculate statistics.
  - Produce behavioral risk flags and info notes.
- Modify: `app/services/risk_scoring.py`
  - Add new Prozorro risk definitions.
  - Keep existing dedupe behavior unchanged.
- Modify: `app/bot.py`
  - Include `lookup_result.prozorro_analysis.risk_flags` in collected risk flags.
  - Include Prozorro in source snapshots and source labels.
  - Render a separate `Prozorro` report block.
- Create: `tests/test_prozorro_analysis.py`
  - Cover analyzer behavior and source-independent normalization.
- Modify: `tests/test_risk_scoring.py`
  - Cover new risk weights and dedupe with existing flags.
- Modify: `tests/test_bot_responses.py`
  - Cover summary integration and report rendering.

Before starting implementation, run:

```powershell
git -c safe.directory='C:/Users/bessp/Desktop/riskua_bot/riskua-kontragent-bot' status --short
```

Expected: there may already be unrelated modified files. Do not revert or rewrite unrelated user changes.

---

### Task 1: Models And Neutral Analyzer Base

**Files:**
- Modify: `app/models/company_lookup.py`
- Create: `app/services/prozorro_analysis.py`
- Create: `tests/test_prozorro_analysis.py`

- [ ] **Step 1: Write failing tests for model defaults, empty data, and participations without wins**

Create `tests/test_prozorro_analysis.py` with:

```python
import unittest


class ProzorroAnalysisTests(unittest.TestCase):
    def flag_types(self, analysis):
        return [flag["type"] for flag in analysis.risk_flags]

    def test_empty_or_unavailable_data_adds_no_risk(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        analysis = analyze_prozorro_data(None)

        self.assertEqual(analysis.status, "not_found")
        self.assertEqual(analysis.stats.procurements_count, 0)
        self.assertEqual(analysis.risk_flags, [])
        self.assertIn("Prozorro-дані відсутні або не передані", analysis.summary)

    def test_participations_without_wins_adds_note_but_no_risk(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        analysis = analyze_prozorro_data(
            [
                {"id": "UA-1", "participated": True, "won": False, "date": "2025-01-10"},
                {"id": "UA-2", "participated": True, "won": False, "date": "2025-02-10"},
                {"id": "UA-3", "participated": True, "won": False, "date": "2025-03-10"},
            ]
        )

        self.assertEqual(analysis.status, "found")
        self.assertEqual(analysis.stats.procurements_count, 3)
        self.assertEqual(analysis.stats.participations_count, 3)
        self.assertEqual(analysis.stats.wins_count, 0)
        self.assertEqual(analysis.stats.win_rate_percent, 0.0)
        self.assertEqual(self.flag_types(analysis), [])
        self.assertTrue(any("перемог не має" in note for note in analysis.info_notes))
        self.assertTrue(any("Сам факт участі не є ризиком" in note for note in analysis.info_notes))

    def test_raw_aliases_are_normalized(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        analysis = analyze_prozorro_data(
            {
                "items": [
                    {
                        "tender_id": "UA-ALIAS-1",
                        "name": "Поставка паперу",
                        "classification_id": "30190000-7",
                        "procuring_entity": "Школа N1",
                        "buyer_identifier": "11111111",
                        "value": "100000",
                        "proposal_value": "90000",
                        "award_value": "90000",
                        "participants_count": "2",
                        "participated": True,
                        "won": True,
                        "has_contract": True,
                        "contract_completed": True,
                        "award_date": "2025-05-10",
                    }
                ]
            }
        )

        procurement = analysis.procurements[0]
        self.assertEqual(procurement.procurement_id, "UA-ALIAS-1")
        self.assertEqual(procurement.title, "Поставка паперу")
        self.assertEqual(procurement.cpv_code, "30190000-7")
        self.assertEqual(procurement.buyer_name, "Школа N1")
        self.assertEqual(procurement.buyer_edrpou, "11111111")
        self.assertEqual(procurement.expected_value_uah, 100000.0)
        self.assertEqual(procurement.bid_value_uah, 90000.0)
        self.assertEqual(procurement.contract_value_uah, 90000.0)
        self.assertEqual(procurement.participants_count, 2)
        self.assertEqual(analysis.stats.wins_count, 1)
        self.assertEqual(analysis.stats.completed_contracts_count, 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
pytest tests/test_prozorro_analysis.py -q
```

Expected: FAIL because `app.services.prozorro_analysis` and Prozorro models do not exist.

- [ ] **Step 3: Add Prozorro models**

In `app/models/company_lookup.py`, add `ProzorroProcurement`, `ProzorroStats`, and `ProzorroAnalysis` after `CourtData` and before `RiskInput`:

```python
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
```

Then add this field to `CompanyLookupResult` near the other source fields:

```python
    prozorro_analysis: ProzorroAnalysis | None = None
```

- [ ] **Step 4: Add neutral analyzer implementation**

Create `app/services/prozorro_analysis.py` with:

```python
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.models.company_lookup import ProzorroAnalysis, ProzorroProcurement, ProzorroStats


SOURCE = "prozorro_analysis"
PRESENCE_NOTE = (
    "Компанія фігурує у публічних закупівлях. Сам факт участі не є ризиком, "
    "але дозволяє оцінити досвід, дисципліну та виконання договорів."
)
NO_WINS_NOTE = (
    "Компанія брала участь у закупівлях, але перемог не має. Це не підтверджує "
    "успішний досвід виконання державних контрактів."
)


def analyze_prozorro_data(
    data: list[dict[str, Any]] | dict[str, Any] | list[ProzorroProcurement] | None,
    *,
    company_context: dict[str, Any] | None = None,
) -> ProzorroAnalysis:
    checked_at = datetime.now(UTC)
    procurements, warnings, source_error = normalize_procurements(data)
    if source_error:
        return ProzorroAnalysis(
            status="source_error",
            summary="Prozorro-дані недоступні. Score не підвищено.",
            parse_warnings=warnings,
            error=source_error,
            checked_at=checked_at,
        )
    if not procurements:
        return ProzorroAnalysis(
            status="not_found",
            summary="Prozorro-дані відсутні або не передані. Score не підвищено.",
            parse_warnings=warnings,
            checked_at=checked_at,
        )

    stats = calculate_stats(procurements)
    notes = [PRESENCE_NOTE]
    if stats.participations_count >= 3 and stats.wins_count == 0:
        notes.append(NO_WINS_NOTE)

    return ProzorroAnalysis(
        status="partial" if warnings else "found",
        stats=stats,
        procurements=procurements,
        risk_flags=[],
        info_notes=notes,
        summary=build_summary(stats),
        parse_warnings=warnings,
        checked_at=checked_at,
    )


def normalize_procurements(data: Any) -> tuple[list[ProzorroProcurement], list[str], str | None]:
    warnings: list[str] = []
    if data is None:
        return [], warnings, None
    if isinstance(data, dict) and data.get("error"):
        return [], warnings, str(data.get("error"))
    raw_items = data.get("items") if isinstance(data, dict) else data
    if raw_items is None:
        return [], warnings, None
    if not isinstance(raw_items, list):
        return [], ["Prozorro payload is not a list"], None

    procurements: list[ProzorroProcurement] = []
    for index, item in enumerate(raw_items):
        try:
            if isinstance(item, ProzorroProcurement):
                procurements.append(item)
            elif isinstance(item, dict):
                procurements.append(normalize_procurement_dict(item))
            else:
                warnings.append(f"Prozorro item #{index + 1} has unsupported type")
        except (TypeError, ValueError) as exc:
            warnings.append(f"Prozorro item #{index + 1} skipped: {exc}")
    return procurements, warnings, None


def normalize_procurement_dict(item: dict[str, Any]) -> ProzorroProcurement:
    return ProzorroProcurement(
        procurement_id=first_text(item, "procurement_id", "id", "tender_id"),
        url=first_text(item, "url", "link"),
        title=first_text(item, "title", "name", "procurement_title"),
        cpv_code=first_text(item, "cpv_code", "cpv", "classification_id"),
        cpv_name=first_text(item, "cpv_name", "classification_description"),
        procedure_type=first_text(item, "procedure_type", "procurement_method_type"),
        status=first_text(item, "status"),
        expected_value_uah=first_float(item, "expected_value_uah", "expected_value", "value"),
        bid_value_uah=first_float(item, "bid_value_uah", "bid_value", "proposal_value"),
        contract_value_uah=first_float(item, "contract_value_uah", "contract_value", "award_value"),
        buyer_name=first_text(item, "buyer_name", "procuring_entity", "buyer"),
        buyer_edrpou=first_text(item, "buyer_edrpou", "buyer_identifier", "buyer_code"),
        participants_count=first_int(item, "participants_count", "number_of_bids"),
        participated=first_bool(item, "participated"),
        won=first_bool(item, "won"),
        disqualified=first_bool(item, "disqualified"),
        disqualification_reason=first_text(item, "disqualification_reason", "rejection_reason"),
        has_contract=first_bool(item, "has_contract"),
        contract_completed=first_bool(item, "contract_completed"),
        contract_terminated=first_bool(item, "contract_terminated"),
        termination_reason=first_text(item, "termination_reason"),
        complaints_count=first_int(item, "complaints_count") or 0,
        supplier_related_complaints_count=first_int(item, "supplier_related_complaints_count") or 0,
        amendments_count=first_int(item, "amendments_count") or 0,
        contract_amount_change_uah=first_float(item, "contract_amount_change_uah"),
        contract_amount_change_percent=first_float(item, "contract_amount_change_percent"),
        date=first_text(item, "date"),
        award_date=first_text(item, "award_date"),
        contract_date=first_text(item, "contract_date"),
    )


def calculate_stats(procurements: list[ProzorroProcurement]) -> ProzorroStats:
    participations = [item for item in procurements if item.participated]
    wins = [item for item in procurements if item.won]
    contracts = [item for item in procurements if item.has_contract]
    terminated = [item for item in contracts if item.contract_terminated]
    disqualified = [item for item in procurements if item.disqualified]
    participation_dates = sorted(date for item in participations if (date := item.date or item.award_date or item.contract_date))
    win_dates = sorted(date for item in wins if (date := item.award_date or item.date or item.contract_date))
    return ProzorroStats(
        procurements_count=len(procurements),
        participations_count=len(participations),
        wins_count=len(wins),
        contracts_count=len(contracts),
        completed_contracts_count=len([item for item in contracts if item.contract_completed]),
        terminated_contracts_count=len(terminated),
        disqualifications_count=len(disqualified),
        complaints_count=sum(item.complaints_count for item in procurements),
        supplier_related_complaints_count=sum(item.supplier_related_complaints_count for item in procurements),
        first_participation_date=participation_dates[0] if participation_dates else None,
        last_participation_date=participation_dates[-1] if participation_dates else None,
        last_win_date=win_dates[-1] if win_dates else None,
        win_rate_percent=rate(len(wins), len(participations)),
        termination_rate_percent=rate(len(terminated), len(contracts)),
        disqualification_rate_percent=rate(len(disqualified), len(participations)),
    )


def build_summary(stats: ProzorroStats) -> str:
    return (
        f"Prozorro: участей {stats.participations_count}, перемог {stats.wins_count}, "
        f"договорів {stats.contracts_count}, розірвань {stats.terminated_contracts_count}."
    )


def first_text(item: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def first_float(item: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = item.get(key)
        if value in (None, ""):
            continue
        try:
            return float(str(value).replace(" ", "").replace(",", "."))
        except ValueError:
            return None
    return None


def first_int(item: dict[str, Any], *keys: str) -> int | None:
    value = first_float(item, *keys)
    return int(value) if value is not None else None


def first_bool(item: dict[str, Any], *keys: str) -> bool:
    for key in keys:
        value = item.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes", "так"}:
                return True
            if lowered in {"false", "0", "no", "ні"}:
                return False
    return False


def rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100, 2)
```

- [ ] **Step 5: Run test to verify it passes**

Run:

```powershell
pytest tests/test_prozorro_analysis.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit task**

```powershell
git -c safe.directory='C:/Users/bessp/Desktop/riskua_bot/riskua-kontragent-bot' add app/models/company_lookup.py app/services/prozorro_analysis.py tests/test_prozorro_analysis.py
git -c safe.directory='C:/Users/bessp/Desktop/riskua_bot/riskua-kontragent-bot' commit -m "feat: add prozorro analysis models"
```

---

### Task 2: Prozorro Risk Definitions In Scoring

**Files:**
- Modify: `app/services/risk_scoring.py`
- Modify: `tests/test_risk_scoring.py`

- [ ] **Step 1: Write failing tests for new flag weights**

Append to `RiskScoringTests` in `tests/test_risk_scoring.py`:

```python
    def test_prozorro_specific_flags_have_expected_weights(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk(
            [
                {"type": "multiple_prozorro_terminations_found", "source": "prozorro_analysis"},
                {"type": "frequent_prozorro_disqualifications", "source": "prozorro_analysis"},
                {"type": "single_buyer_concentration", "source": "prozorro_analysis"},
            ]
        )

        self.assertEqual(
            [reason["type"] for reason in result["reasons"]],
            [
                "multiple_prozorro_terminations_found",
                "frequent_prozorro_disqualifications",
                "single_buyer_concentration",
            ],
        )
        self.assertEqual([reason["weight"] for reason in result["reasons"]], [35, 20, 15])
        self.assertEqual(result["score"], 65)

    def test_all_new_prozorro_flags_are_known(self):
        from app.services.risk_scoring import calculate_final_risk

        flags = [
            "problematic_documents_found",
            "qualification_mismatch_found",
            "low_competition_wins",
            "frequent_contract_changes",
            "substantial_contract_amount_increase",
            "possible_prozorro_dumping",
            "supplier_related_prozorro_complaints",
        ]

        result = calculate_final_risk([{"type": flag, "source": "prozorro_analysis"} for flag in flags])

        self.assertEqual([reason["type"] for reason in result["reasons"]], flags)
        self.assertEqual([reason["weight"] for reason in result["reasons"]], [35, 20, 15, 10, 20, 10, 15])
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
pytest tests/test_risk_scoring.py::RiskScoringTests::test_prozorro_specific_flags_have_expected_weights tests/test_risk_scoring.py::RiskScoringTests::test_all_new_prozorro_flags_are_known -q
```

Expected: FAIL because unknown risk types are ignored.

- [ ] **Step 3: Add risk definitions**

In `app/services/risk_scoring.py`, add these entries to `RISK_FLAG_DEFINITIONS` near `prozorro_termination_found`:

```python
    "multiple_prozorro_terminations_found": {
        "weight": 35,
        "label_uk": "Кілька розірвань договорів у Prozorro",
        "description": "Знайдено кілька розірвань договорів або високу частку розірваних договорів у Prozorro.",
    },
    "frequent_prozorro_disqualifications": {
        "weight": 20,
        "label_uk": "Часті відхилення в Prozorro",
        "description": "Компанію часто відхиляли в закупівлях або частка відхилень є високою.",
    },
    "problematic_documents_found": {
        "weight": 35,
        "label_uk": "Проблемні/недостовірні документи",
        "description": "У причинах відхилення знайдено ознаки проблемних, недостовірних або неналежних документів.",
    },
    "qualification_mismatch_found": {
        "weight": 20,
        "label_uk": "Невідповідність кваліфікаційним вимогам",
        "description": "У Prozorro є ознаки невідповідності кваліфікаційним вимогам закупівлі.",
    },
    "single_buyer_concentration": {
        "weight": 15,
        "label_uk": "Значна концентрація договорів на одному замовнику",
        "description": "Значна частина договорів або суми договорів припадає на одного замовника.",
    },
    "low_competition_wins": {
        "weight": 15,
        "label_uk": "Перемоги у закупівлях з низькою конкуренцією",
        "description": "Компанія часто перемагала у закупівлях з одним учасником або дуже низькою конкуренцією.",
    },
    "frequent_contract_changes": {
        "weight": 10,
        "label_uk": "Часті зміни договорів у Prozorro",
        "description": "За договорами знайдено багато додаткових угод або часті зміни умов.",
    },
    "substantial_contract_amount_increase": {
        "weight": 20,
        "label_uk": "Суттєве збільшення суми договорів у Prozorro",
        "description": "Через зміни договору сума суттєво збільшувалась.",
    },
    "possible_prozorro_dumping": {
        "weight": 10,
        "label_uk": "Можливий демпінг у Prozorro",
        "description": "Компанія неодноразово подавала пропозиції суттєво нижче очікуваної вартості.",
    },
    "supplier_related_prozorro_complaints": {
        "weight": 15,
        "label_uk": "Скарги в Prozorro, пов'язані з постачальником",
        "description": "Знайдено скарги, які прямо стосуються компанії, її документів або дій.",
    },
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
pytest tests/test_risk_scoring.py::RiskScoringTests::test_prozorro_specific_flags_have_expected_weights tests/test_risk_scoring.py::RiskScoringTests::test_all_new_prozorro_flags_are_known -q
```

Expected: PASS.

- [ ] **Step 5: Commit task**

```powershell
git -c safe.directory='C:/Users/bessp/Desktop/riskua_bot/riskua-kontragent-bot' add app/services/risk_scoring.py tests/test_risk_scoring.py
git -c safe.directory='C:/Users/bessp/Desktop/riskua_bot/riskua-kontragent-bot' commit -m "feat: add prozorro risk weights"
```

---

### Task 3: Terminations And Disqualification Mapping

**Files:**
- Modify: `app/services/prozorro_analysis.py`
- Modify: `tests/test_prozorro_analysis.py`

- [ ] **Step 1: Write failing tests for terminations and disqualifications**

Append to `ProzorroAnalysisTests`:

```python
    def test_one_terminated_contract_adds_existing_termination_flag(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        analysis = analyze_prozorro_data(
            [
                {
                    "id": "UA-T-1",
                    "participated": True,
                    "won": True,
                    "has_contract": True,
                    "contract_terminated": True,
                    "contract_value": 100000,
                }
            ]
        )

        self.assertEqual(self.flag_types(analysis), ["prozorro_termination_found"])

    def test_multiple_terminated_contracts_adds_stronger_flag(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        analysis = analyze_prozorro_data(
            [
                {"id": "UA-T-1", "participated": True, "won": True, "has_contract": True, "contract_terminated": True},
                {"id": "UA-T-2", "participated": True, "won": True, "has_contract": True, "contract_terminated": True},
            ]
        )

        self.assertEqual(
            self.flag_types(analysis),
            ["prozorro_termination_found", "multiple_prozorro_terminations_found"],
        )

    def test_nonperformance_termination_maps_to_contract_nonperformance(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        analysis = analyze_prozorro_data(
            [
                {
                    "id": "UA-T-1",
                    "participated": True,
                    "won": True,
                    "has_contract": True,
                    "contract_terminated": True,
                    "termination_reason": "Постачальник відмовився від поставки та порушив строки виконання договору",
                }
            ]
        )

        self.assertEqual(
            self.flag_types(analysis),
            ["prozorro_termination_found", "contract_nonperformance_case"],
        )

    def test_frequent_disqualifications_adds_risk(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        analysis = analyze_prozorro_data(
            [
                {"id": "UA-D-1", "participated": True, "disqualified": True},
                {"id": "UA-D-2", "participated": True, "disqualified": True},
                {"id": "UA-D-3", "participated": True, "disqualified": True},
                {"id": "UA-D-4", "participated": True, "disqualified": False},
            ]
        )

        self.assertIn("frequent_prozorro_disqualifications", self.flag_types(analysis))

    def test_disqualification_reasons_map_to_existing_and_new_risks(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        analysis = analyze_prozorro_data(
            [
                {"id": "UA-R-1", "participated": True, "disqualified": True, "disqualification_reason": "наявний податковий борг"},
                {"id": "UA-R-2", "participated": True, "disqualified": True, "disqualification_reason": "значний податковий борг понад 100000 грн"},
                {"id": "UA-R-3", "participated": True, "disqualified": True, "disqualification_reason": "учасник перебуває у процедурі банкрутства"},
                {"id": "UA-R-4", "participated": True, "disqualified": True, "disqualification_reason": "застосовано санкції"},
                {"id": "UA-R-5", "participated": True, "disqualified": True, "disqualification_reason": "недостовірні документи"},
                {"id": "UA-R-6", "participated": True, "disqualified": True, "disqualification_reason": "невідповідність кваліфікаційним вимогам"},
            ]
        )

        self.assertIn("tax_debt_found", self.flag_types(analysis))
        self.assertIn("large_tax_debt_found", self.flag_types(analysis))
        self.assertIn("bankruptcy_found", self.flag_types(analysis))
        self.assertIn("sanctions_found", self.flag_types(analysis))
        self.assertIn("problematic_documents_found", self.flag_types(analysis))
        self.assertIn("qualification_mismatch_found", self.flag_types(analysis))
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
pytest tests/test_prozorro_analysis.py -q
```

Expected: FAIL because analyzer still returns no behavioral flags.

- [ ] **Step 3: Implement termination and disqualification flags**

In `app/services/prozorro_analysis.py`, add constants after `NO_WINS_NOTE`:

```python
NONPERFORMANCE_MARKERS = (
    "невикон",
    "порушив строк",
    "порушення строк",
    "якіст",
    "відмовився",
    "відмова від поставки",
    "не постав",
)
DISQUALIFICATION_REASON_FLAGS = (
    (("значний податковий борг", "суттєвий податковий борг", "податковий борг понад"), "large_tax_debt_found"),
    (("податковий борг", "заборгованість з подат"), "tax_debt_found"),
    (("банкрут",), "bankruptcy_found"),
    (("санкц",), "sanctions_found"),
    (("недостовір", "підроб", "фальш", "неналежн"), "problematic_documents_found"),
    (("кваліфікаційн", "не відповідає вимог", "невідповідність вимог"), "qualification_mismatch_found"),
)
```

Replace the risk flag assignment in `analyze_prozorro_data`:

```python
    risk_flags = build_risk_flags(procurements, stats)

    return ProzorroAnalysis(
        status="partial" if warnings else "found",
        stats=stats,
        procurements=procurements,
        risk_flags=risk_flags,
        info_notes=notes,
        summary=build_summary(stats),
        parse_warnings=warnings,
        checked_at=checked_at,
    )
```

Add helper functions:

```python
def build_risk_flags(procurements: list[ProzorroProcurement], stats: ProzorroStats) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    terminated = [item for item in procurements if item.has_contract and item.contract_terminated]
    if terminated:
        flags.append(risk_flag("prozorro_termination_found", "Виявлено розірвання договору в Prozorro."))
    if len(terminated) >= 2 or ((stats.termination_rate_percent or 0) >= 30 and len(terminated) >= 1):
        flags.append(risk_flag("multiple_prozorro_terminations_found", "Виявлено кілька розірвань договорів або високу частку розірвань у Prozorro."))
    if any(text_has_marker(item.termination_reason, NONPERFORMANCE_MARKERS) for item in terminated):
        flags.append(risk_flag("contract_nonperformance_case", "Причина розірвання пов'язана з невиконанням, строками або якістю."))

    if stats.disqualifications_count >= 3 or (stats.disqualification_rate_percent or 0) > 50:
        flags.append(risk_flag("frequent_prozorro_disqualifications", "Компанію часто відхиляли в закупівлях."))
    for item in procurements:
        if not item.disqualified:
            continue
        for markers, flag_type in DISQUALIFICATION_REASON_FLAGS:
            if text_has_marker(item.disqualification_reason, markers):
                flags.append(risk_flag(flag_type, item.disqualification_reason or "Причина відхилення в Prozorro"))
    return dedupe_flags(flags)


def risk_flag(flag_type: str, raw_text: str, *, confidence: str = "medium", matched_pattern: str | None = None) -> dict[str, Any]:
    return {
        "type": flag_type,
        "source": SOURCE,
        "status": "found",
        "confidence": confidence,
        "raw_text": raw_text,
        "matched_pattern": matched_pattern or flag_type,
        "match_type": "positive_match",
    }


def dedupe_flags(flags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for flag in flags:
        deduped.setdefault(str(flag["type"]), flag)
    return list(deduped.values())


def text_has_marker(text: str | None, markers: tuple[str, ...]) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in markers)
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
pytest tests/test_prozorro_analysis.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit task**

```powershell
git -c safe.directory='C:/Users/bessp/Desktop/riskua_bot/riskua-kontragent-bot' add app/services/prozorro_analysis.py tests/test_prozorro_analysis.py
git -c safe.directory='C:/Users/bessp/Desktop/riskua_bot/riskua-kontragent-bot' commit -m "feat: map prozorro negative facts to risks"
```

---

### Task 4: Behavioral Soft Signals And Notes

**Files:**
- Modify: `app/services/prozorro_analysis.py`
- Modify: `tests/test_prozorro_analysis.py`

- [ ] **Step 1: Write failing tests for soft signals**

Append to `ProzorroAnalysisTests`:

```python
    def test_clear_cpv_kved_mismatch_adds_existing_kved_risk(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        analysis = analyze_prozorro_data(
            [
                {"id": "UA-C-1", "participated": True, "title": "Медичне обладнання", "cpv_code": "33100000-1", "cpv_name": "Медичне обладнання"},
                {"id": "UA-C-2", "participated": True, "title": "Лабораторне обладнання", "cpv_code": "38000000-5", "cpv_name": "Лабораторне обладнання"},
                {"id": "UA-C-3", "participated": True, "title": "Медичні матеріали", "cpv_code": "33140000-3", "cpv_name": "Медичні матеріали"},
            ],
            company_context={"main_activity_name": "Оптова торгівля паливом", "additional_activities": []},
        )

        self.assertIn("kved_mismatch", self.flag_types(analysis))

    def test_uncertain_cpv_kved_match_adds_note_without_risk(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        analysis = analyze_prozorro_data(
            [{"id": "UA-C-1", "participated": True, "title": "Послуги", "cpv_name": "Різні послуги"}],
            company_context={"main_activity_name": "Неспеціалізована оптова торгівля"},
        )

        self.assertNotIn("kved_mismatch", self.flag_types(analysis))
        self.assertTrue(any("відповідність CPV" in note for note in analysis.info_notes))

    def test_single_buyer_concentration_adds_soft_risk(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        analysis = analyze_prozorro_data(
            [
                {"id": f"UA-B-{index}", "participated": True, "won": True, "has_contract": True, "buyer_edrpou": "11111111", "contract_value": 1000}
                for index in range(5)
            ]
        )

        self.assertIn("single_buyer_concentration", self.flag_types(analysis))
        self.assertTrue(any("одним замовником" in note for note in analysis.info_notes))

    def test_low_competition_wins_adds_soft_risk(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        analysis = analyze_prozorro_data(
            [
                {"id": f"UA-L-{index}", "participated": True, "won": True, "has_contract": True, "participants_count": 1}
                for index in range(5)
            ]
        )

        self.assertIn("low_competition_wins", self.flag_types(analysis))

    def test_contract_amendments_and_amount_increase_add_risks(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        analysis = analyze_prozorro_data(
            [
                {"id": f"UA-A-{index}", "participated": True, "won": True, "has_contract": True, "amendments_count": 3}
                for index in range(5)
            ]
            + [
                {"id": "UA-A-INC", "participated": True, "won": True, "has_contract": True, "contract_amount_change_percent": 25}
            ]
        )

        self.assertIn("frequent_contract_changes", self.flag_types(analysis))
        self.assertIn("substantial_contract_amount_increase", self.flag_types(analysis))

    def test_repeated_deep_discounts_add_dumping_but_one_case_does_not(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        one_case = analyze_prozorro_data(
            [{"id": "UA-DUMP-1", "participated": True, "expected_value": 100000, "proposal_value": 49000}]
        )
        repeated = analyze_prozorro_data(
            [
                {"id": "UA-DUMP-1", "participated": True, "expected_value": 100000, "proposal_value": 49000},
                {"id": "UA-DUMP-2", "participated": True, "expected_value": 200000, "proposal_value": 90000},
            ]
        )

        self.assertNotIn("possible_prozorro_dumping", self.flag_types(one_case))
        self.assertIn("possible_prozorro_dumping", self.flag_types(repeated))

    def test_supplier_related_complaints_add_risk_but_generic_complaints_do_not(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        generic = analyze_prozorro_data([{"id": "UA-G", "participated": True, "complaints_count": 3}])
        supplier_related = analyze_prozorro_data([{"id": "UA-S", "participated": True, "supplier_related_complaints_count": 1}])

        self.assertNotIn("supplier_related_prozorro_complaints", self.flag_types(generic))
        self.assertIn("supplier_related_prozorro_complaints", self.flag_types(supplier_related))

    def test_old_procurements_add_note_without_risk(self):
        from app.services.prozorro_analysis import analyze_prozorro_data

        analysis = analyze_prozorro_data([{"id": "UA-OLD", "participated": True, "date": "2020-01-01"}])

        self.assertEqual(self.flag_types(analysis), [])
        self.assertTrue(any("була давно" in note for note in analysis.info_notes))
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
pytest tests/test_prozorro_analysis.py -q
```

Expected: FAIL because soft-signal logic is not implemented.

- [ ] **Step 3: Implement soft-signal statistics and flags**

In `app/services/prozorro_analysis.py`, add these imports and constants:

```python
from datetime import UTC, datetime, date

ACTIVITY_KEYWORDS = {
    "fuel": ("палив", "бензин", "дизель", "нафт", "газ"),
    "medical": ("медич", "лікар", "фармац", "лаборатор", "обладнання мед"),
    "it": ("програм", "комп'ют", "комп’ют", "сервер", "інформаційн"),
    "construction": ("будів", "ремонт", "реконструкц", "дорог"),
}
CPV_GROUP_KEYWORDS = {
    "medical": ("331", "336", "851"),
    "it": ("302", "324", "488", "722"),
    "construction": ("450", "451", "452", "453", "454"),
    "fuel": ("091", "092"),
}
CONCENTRATION_NOTE = (
    "Компанія значну частину договорів має з одним замовником. Це може бути нормально "
    "для спеціалізованого постачальника, але потребує додаткової перевірки."
)
UNCERTAIN_KVED_NOTE = "Відповідність CPV закупівель і КВЕД компанії не вдалося впевнено визначити."
OLD_PROCUREMENTS_NOTE = "Остання знайдена участь у Prozorro була давно, тому цей сигнал має обмежену актуальність."
```

In `calculate_stats`, before the `return ProzorroStats(` statement, compute concentration and behavioral counts:

```python
    buyer_contract_counts: dict[str, int] = {}
    buyer_contract_values: dict[str, float] = {}
    for item in contracts:
        buyer_key = item.buyer_edrpou or item.buyer_name
        if not buyer_key:
            continue
        buyer_contract_counts[buyer_key] = buyer_contract_counts.get(buyer_key, 0) + 1
        buyer_contract_values[buyer_key] = buyer_contract_values.get(buyer_key, 0.0) + (item.contract_value_uah or 0.0)
    total_contract_value = sum(item.contract_value_uah or 0.0 for item in contracts)
    low_competition_wins = [item for item in wins if item.participants_count is not None and item.participants_count <= 1]
    high_discount_bids = [
        item
        for item in procurements
        if item.expected_value_uah and item.bid_value_uah is not None and item.bid_value_uah <= item.expected_value_uah * 0.5
    ]
```

Then include these `ProzorroStats` fields:

```python
        single_buyer_contract_share_percent=rate(max(buyer_contract_counts.values(), default=0), len(contracts)),
        single_buyer_value_share_percent=rate_float(max(buyer_contract_values.values(), default=0.0), total_contract_value),
        low_competition_wins_count=len(low_competition_wins),
        high_discount_bids_count=len(high_discount_bids),
```

Add `rate_float`:

```python
def rate_float(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100, 2)
```

Update `analyze_prozorro_data` after creating `notes`:

```python
    add_context_notes(notes, procurements, stats, checked_at, company_context or {})
```

Update `build_risk_flags` before `return dedupe_flags(flags)`:

```python
    if (stats.single_buyer_contract_share_percent or 0) >= 80 and stats.contracts_count >= 5:
        flags.append(risk_flag("single_buyer_concentration", "80%+ договорів припадає на одного замовника."))
    elif (stats.single_buyer_value_share_percent or 0) >= 80 and stats.contracts_count >= 5:
        flags.append(risk_flag("single_buyer_concentration", "80%+ суми договорів припадає на одного замовника."))

    if stats.wins_count >= 5 and rate(stats.low_competition_wins_count, stats.wins_count) and rate(stats.low_competition_wins_count, stats.wins_count) >= 60:
        flags.append(risk_flag("low_competition_wins", "60%+ перемог відбулися за низької конкуренції."))

    total_amendments = sum(item.amendments_count for item in procurements if item.has_contract)
    if stats.contracts_count >= 5 and (total_amendments >= 10 or total_amendments / stats.contracts_count >= 3):
        flags.append(risk_flag("frequent_contract_changes", "Знайдено часті додаткові угоди за договорами Prozorro."))

    if any((item.contract_amount_change_percent or 0) >= 20 for item in procurements if item.has_contract):
        flags.append(risk_flag("substantial_contract_amount_increase", "Сума договору збільшувалась на 20% або більше."))

    if stats.high_discount_bids_count >= 2:
        flags.append(risk_flag("possible_prozorro_dumping", "Знайдено повторні пропозиції на 50%+ нижче очікуваної вартості."))

    if stats.supplier_related_complaints_count > 0:
        flags.append(risk_flag("supplier_related_prozorro_complaints", "Скарги прямо стосуються постачальника або його документів."))
```

After `build_risk_flags`, add context helpers:

```python
def add_context_notes(
    notes: list[str],
    procurements: list[ProzorroProcurement],
    stats: ProzorroStats,
    checked_at: datetime,
    company_context: dict[str, Any],
) -> None:
    if stats.contracts_count >= 5 and (
        (stats.single_buyer_contract_share_percent or 0) >= 80
        or (stats.single_buyer_value_share_percent or 0) >= 80
    ):
        notes.append(CONCENTRATION_NOTE)
    if is_old_participation(stats.last_participation_date, checked_at):
        notes.append(OLD_PROCUREMENTS_NOTE)
    if company_context and kved_match_status(procurements, company_context) == "uncertain":
        notes.append(UNCERTAIN_KVED_NOTE)


def is_old_participation(last_date: str | None, checked_at: datetime) -> bool:
    parsed = parse_iso_date(last_date)
    if parsed is None:
        return False
    return (checked_at.date() - parsed).days > 365 * 3


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None
```

Extend `build_risk_flags` signature and call:

```python
def build_risk_flags(
    procurements: list[ProzorroProcurement],
    stats: ProzorroStats,
    company_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
```

Call it as:

```python
    risk_flags = build_risk_flags(procurements, stats, company_context or {})
```

Inside `build_risk_flags`, before concentration logic:

```python
    if kved_match_status(procurements, company_context or {}) == "mismatch":
        flags.append(risk_flag("kved_mismatch", "Предмети закупівель явно не відповідають діяльності компанії."))
```

Add KVED helpers:

```python
def kved_match_status(procurements: list[ProzorroProcurement], company_context: dict[str, Any]) -> str:
    company_groups = activity_groups(
        " ".join(
            str(value or "")
            for value in [
                company_context.get("main_activity_code"),
                company_context.get("main_activity_name"),
                " ".join(company_context.get("additional_activities") or []),
            ]
        )
    )
    procurement_groups = [
        group
        for item in procurements
        if (group := procurement_group(item)) is not None
    ]
    if not company_groups or not procurement_groups:
        return "uncertain"
    mismatches = [group for group in procurement_groups if group not in company_groups]
    if len(mismatches) / len(procurement_groups) > 0.5:
        return "mismatch"
    return "match"


def activity_groups(text: str) -> set[str]:
    lowered = text.lower()
    return {
        group
        for group, markers in ACTIVITY_KEYWORDS.items()
        if any(marker in lowered for marker in markers)
    }


def procurement_group(item: ProzorroProcurement) -> str | None:
    code = (item.cpv_code or "").strip()
    for group, prefixes in CPV_GROUP_KEYWORDS.items():
        if any(code.startswith(prefix) for prefix in prefixes):
            return group
    groups = activity_groups(" ".join([item.title or "", item.cpv_name or ""]))
    if len(groups) == 1:
        return next(iter(groups))
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
pytest tests/test_prozorro_analysis.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit task**

```powershell
git -c safe.directory='C:/Users/bessp/Desktop/riskua_bot/riskua-kontragent-bot' add app/services/prozorro_analysis.py tests/test_prozorro_analysis.py
git -c safe.directory='C:/Users/bessp/Desktop/riskua_bot/riskua-kontragent-bot' commit -m "feat: add prozorro behavioral signals"
```

---

### Task 5: Risk Summary Integration And Deduplication

**Files:**
- Modify: `app/bot.py`
- Modify: `tests/test_bot_responses.py`
- Modify: `tests/test_risk_scoring.py`

- [ ] **Step 1: Write failing integration tests**

Append to `RiskScoringTests` in `tests/test_risk_scoring.py`:

```python
    def test_prozorro_duplicate_existing_flag_counts_once(self):
        from app.services.risk_scoring import calculate_final_risk

        result = calculate_final_risk(
            [
                {"type": "tax_debt_found", "source": "prozorro_analysis"},
                {"type": "tax_debt_found", "source": "tax"},
            ]
        )

        self.assertEqual(result["score"], 25)
        self.assertEqual(len(result["reasons"]), 1)
        self.assertEqual(result["reasons"][0]["sources"], ["prozorro_analysis", "tax"])
```

Append to `BotResponseTests` in `tests/test_bot_responses.py`:

```python
    def test_build_risk_summary_includes_prozorro_analysis_flags(self):
        from app.bot import build_risk_summary
        from app.models.company_lookup import CompanyLookupResult, ProzorroAnalysis, ProzorroStats

        result = CompanyLookupResult(
            status="found",
            edrpou="12345678",
            prozorro_analysis=ProzorroAnalysis(
                status="found",
                stats=ProzorroStats(procurements_count=1),
                risk_flags=[
                    {
                        "type": "prozorro_termination_found",
                        "source": "prozorro_analysis",
                        "status": "found",
                        "confidence": "medium",
                        "raw_text": "Виявлено розірвання договору в Prozorro.",
                    }
                ],
            ),
        )

        summary = build_risk_summary(result, None)

        self.assertEqual(summary.score, 25)
        self.assertEqual(summary.reasons[0]["type"], "prozorro_termination_found")
        self.assertEqual(summary.reasons[0]["sources"], ["prozorro_analysis"])

    def test_build_sources_snapshot_includes_prozorro_analysis(self):
        from app.bot import build_sources_snapshot
        from app.models.company_lookup import CompanyLookupResult, ProzorroAnalysis, ProzorroStats

        analysis = ProzorroAnalysis(status="found", stats=ProzorroStats(procurements_count=2))
        result = CompanyLookupResult(status="found", edrpou="12345678", prozorro_analysis=analysis)

        sources = build_sources_snapshot(result, None, None)

        self.assertEqual(sources["prozorro"]["status"], "found")
        self.assertEqual(sources["prozorro"]["stats"]["procurements_count"], 2)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
pytest tests/test_risk_scoring.py::RiskScoringTests::test_prozorro_duplicate_existing_flag_counts_once tests/test_bot_responses.py::BotResponseTests::test_build_risk_summary_includes_prozorro_analysis_flags tests/test_bot_responses.py::BotResponseTests::test_build_sources_snapshot_includes_prozorro_analysis -q
```

Expected: risk-scoring dedupe test should already pass or fail only if sources differ; bot integration tests should FAIL because `collect_source_risk_flags` and `build_sources_snapshot` do not include Prozorro yet.

- [ ] **Step 3: Include Prozorro flags in risk collection**

In `app/bot.py`, add this block in `collect_source_risk_flags` after domain reputation flags and before company status flags:

```python
    prozorro_analysis = result.prozorro_analysis
    if prozorro_analysis:
        for flag in prozorro_analysis.risk_flags:
            prepared_flag = dict(flag)
            prepared_flag.setdefault("source", "prozorro_analysis")
            prepared_flag.setdefault("status", "found")
            prepared_flag.setdefault("confidence", "medium")
            flags.append(prepared_flag)
```

- [ ] **Step 4: Include Prozorro in sources snapshot**

In `build_sources_snapshot`, add before `sources["contact_sources"]`:

```python
    sources["prozorro"] = result.prozorro_analysis.model_dump(mode="json") if result.prozorro_analysis else None
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```powershell
pytest tests/test_risk_scoring.py::RiskScoringTests::test_prozorro_duplicate_existing_flag_counts_once tests/test_bot_responses.py::BotResponseTests::test_build_risk_summary_includes_prozorro_analysis_flags tests/test_bot_responses.py::BotResponseTests::test_build_sources_snapshot_includes_prozorro_analysis -q
```

Expected: PASS.

- [ ] **Step 6: Commit task**

```powershell
git -c safe.directory='C:/Users/bessp/Desktop/riskua_bot/riskua-kontragent-bot' add app/bot.py tests/test_bot_responses.py tests/test_risk_scoring.py
git -c safe.directory='C:/Users/bessp/Desktop/riskua_bot/riskua-kontragent-bot' commit -m "feat: include prozorro analysis in risk summary"
```

---

### Task 6: Telegram Prozorro Report Block

**Files:**
- Modify: `app/bot.py`
- Modify: `tests/test_bot_responses.py`

- [ ] **Step 1: Write failing report tests**

Append to `BotResponseTests`:

```python
    def test_found_company_response_shows_prozorro_block_when_analysis_exists(self):
        from app.bot import build_edrpou_response
        from app.models.company_lookup import CompanyData, CompanyLookupResult, ProzorroAnalysis, ProzorroStats

        response = build_edrpou_response(
            "12345678",
            CompanyLookupResult(
                status="found",
                edrpou="12345678",
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou="12345678", status="Зареєстровано"),
                prozorro_analysis=ProzorroAnalysis(
                    status="found",
                    stats=ProzorroStats(
                        procurements_count=4,
                        participations_count=4,
                        wins_count=0,
                        contracts_count=0,
                        completed_contracts_count=0,
                        terminated_contracts_count=0,
                        disqualifications_count=0,
                        win_rate_percent=0.0,
                        last_participation_date="2025-03-10",
                    ),
                    info_notes=[
                        "Компанія фігурує у публічних закупівлях. Сам факт участі не є ризиком, але дозволяє оцінити досвід, дисципліну та виконання договорів.",
                        "Компанія брала участь у закупівлях, але перемог не має. Це не підтверджує успішний досвід виконання державних контрактів.",
                    ],
                    summary="Prozorro: участей 4, перемог 0, договорів 0, розірвань 0.",
                ),
            ),
        )

        self.assertIn("Prozorro:", response)
        self.assertIn("Участей: 4", response)
        self.assertIn("Перемог: 0", response)
        self.assertIn("Договорів: 0", response)
        self.assertIn("Остання участь: 2025-03-10", response)
        self.assertIn("Сам факт участі не є ризиком", response)
        self.assertIn("Джерела: Opendatabot, Prozorro", response)

    def test_found_company_response_omits_prozorro_block_when_analysis_missing(self):
        from app.bot import build_edrpou_response
        from app.models.company_lookup import CompanyData, CompanyLookupResult

        response = build_edrpou_response(
            "12345678",
            CompanyLookupResult(
                status="found",
                edrpou="12345678",
                company_data=CompanyData(short_name="ТОВ «ПРИКЛАД»", edrpou="12345678", status="Зареєстровано"),
            ),
        )

        self.assertNotIn("Prozorro:", response)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
pytest tests/test_bot_responses.py::BotResponseTests::test_found_company_response_shows_prozorro_block_when_analysis_exists tests/test_bot_responses.py::BotResponseTests::test_found_company_response_omits_prozorro_block_when_analysis_missing -q
```

Expected: first test FAILS because the report block and source label are not rendered yet.

- [ ] **Step 3: Render Prozorro block**

In `format_found_company`, after financial lines:

```python
    prozorro_lines = build_prozorro_lines(lookup_result.prozorro_analysis)
    if prozorro_lines:
        lines.extend(["", "Prozorro:", *prozorro_lines])
```

Add helper functions near `format_tenders`:

```python
def build_prozorro_lines(prozorro_analysis) -> list[str]:
    if not prozorro_analysis or prozorro_analysis.status == "not_found":
        return []
    stats = prozorro_analysis.stats
    lines = [
        f"Закупівель: {stats.procurements_count}",
        f"Участей: {stats.participations_count}",
        f"Перемог: {stats.wins_count}",
        f"Договорів: {stats.contracts_count}",
        f"Виконаних договорів: {stats.completed_contracts_count}",
        f"Розірваних договорів: {stats.terminated_contracts_count}",
        f"Відхилень: {stats.disqualifications_count}",
    ]
    lines.extend(optional_percent_field("Відсоток перемог", stats.win_rate_percent))
    lines.extend(optional_percent_field("Відсоток розірвань", stats.termination_rate_percent))
    lines.extend(optional_percent_field("Відсоток відхилень", stats.disqualification_rate_percent))
    lines.extend(optional_field("Остання участь", stats.last_participation_date))
    lines.extend(optional_field("Остання перемога", stats.last_win_date))
    if prozorro_analysis.summary:
        lines.append(prozorro_analysis.summary)
    for note in prozorro_analysis.info_notes:
        lines.append(f"• {note}")
    if prozorro_analysis.status in {"partial", "source_error"}:
        lines.append("Дані Prozorro часткові або недоступні, тому висновок потребує ручної перевірки.")
    return lines


def optional_percent_field(label: str, value: float | None) -> list[str]:
    if value is None:
        return []
    return [f"{label}: {value:g}%"]
```

- [ ] **Step 4: Include Prozorro in source labels**

In `format_sources`, add a parameter:

```python
    prozorro_included: bool = False,
```

Then append source:

```python
    if prozorro_included:
        sources.append("Prozorro")
```

In the `format_sources` call inside `format_found_company`, pass:

```python
                prozorro_included=bool(lookup_result.prozorro_analysis and lookup_result.prozorro_analysis.status in {"found", "partial"}),
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```powershell
pytest tests/test_bot_responses.py::BotResponseTests::test_found_company_response_shows_prozorro_block_when_analysis_exists tests/test_bot_responses.py::BotResponseTests::test_found_company_response_omits_prozorro_block_when_analysis_missing -q
```

Expected: PASS.

- [ ] **Step 6: Commit task**

```powershell
git -c safe.directory='C:/Users/bessp/Desktop/riskua_bot/riskua-kontragent-bot' add app/bot.py tests/test_bot_responses.py
git -c safe.directory='C:/Users/bessp/Desktop/riskua_bot/riskua-kontragent-bot' commit -m "feat: show prozorro analysis in reports"
```

---

### Task 7: Full Verification

**Files:**
- No planned code edits unless verification exposes a regression.

- [ ] **Step 1: Run focused test suite**

Run:

```powershell
pytest tests/test_prozorro_analysis.py tests/test_risk_scoring.py tests/test_bot_responses.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full test suite**

Run:

```powershell
pytest -q
```

Expected: PASS.

- [ ] **Step 3: Check repository diff**

Run:

```powershell
git -c safe.directory='C:/Users/bessp/Desktop/riskua_bot/riskua-kontragent-bot' status --short
git -c safe.directory='C:/Users/bessp/Desktop/riskua_bot/riskua-kontragent-bot' diff --check
```

Expected: no whitespace errors. Status may include unrelated pre-existing user changes; do not modify them.

- [ ] **Step 4: Commit any verification fix**

If Task 7 required a code fix, commit only the files changed by that fix:

```powershell
git -c safe.directory='C:/Users/bessp/Desktop/riskua_bot/riskua-kontragent-bot' add app/models/company_lookup.py app/services/prozorro_analysis.py app/services/risk_scoring.py app/bot.py tests/test_prozorro_analysis.py tests/test_risk_scoring.py tests/test_bot_responses.py
git -c safe.directory='C:/Users/bessp/Desktop/riskua_bot/riskua-kontragent-bot' commit -m "test: verify prozorro analysis behavior"
```

Expected: commit succeeds only if there were verification fixes to commit.

---

## Coverage Checklist

- Internal normalized data model: Task 1.
- Analyzer accepts raw dicts and model objects: Task 1.
- Empty, missing, unavailable data do not increase score: Task 1.
- Participation without wins does not increase score: Task 1.
- New risk weights: Task 2.
- One and multiple terminations: Task 3.
- Contract non-performance mapping: Task 3.
- Frequent disqualifications and reason mapping: Task 3.
- CPV/KVED mismatch and uncertainty: Task 4.
- Single buyer concentration: Task 4.
- Low competition wins: Task 4.
- Frequent amendments and amount increase: Task 4.
- Possible dumping: Task 4.
- Supplier-related complaints only: Task 4.
- Old procurements note: Task 4.
- Dedupe with existing flags: Task 5.
- Risk summary integration: Task 5.
- Sources snapshot: Task 5.
- Telegram report block: Task 6.
- Focused and full verification: Task 7.
