# Prozorro Source Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire prepared/mock/cache Prozorro data into the existing analyzer so Telegram can display the `Prozorro:` block without live API or Clarity parsing.

**Architecture:** Add a focused `app/services/prozorro_lookup.py` source adapter that reads injected prepared data or an optional local JSON cache, then delegates all normalization and scoring facts to `analyze_prozorro_data`. Update `app/bot.py` to run this lookup alongside the existing source lookups and attach the returned `ProzorroAnalysis` to `CompanyLookupResult`.

**Tech Stack:** Python, Pydantic models, existing aiogram bot pipeline, pytest/unittest.

---

## File Structure

- Create `app/services/prozorro_lookup.py`
  - Owns prepared/cache source loading only.
  - No risk scoring logic.
  - No live HTTP/API calls.
- Create `tests/test_prozorro_lookup.py`
  - Unit tests for source adapter behavior.
- Modify `app/bot.py`
  - Add injectable `prozorro_lookup`.
  - Attach `ProzorroAnalysis` to lookup result.
  - Update debug checked/unavailable source lists.
- Modify `tests/test_bot_responses.py`
  - Integration tests for Telegram output and saved diagnostics.

Existing dirty worktree warning:

- `README.md`, `app/services/risk_scoring.py`, `tests/test_bot_responses.py`, and `tests/test_risk_scoring.py` have pre-existing unstaged changes.
- Do not revert them.
- When committing, stage only the hunks/files created by the current task.

---

### Task 1: Prepared Prozorro Lookup Service

**Files:**
- Create: `app/services/prozorro_lookup.py`
- Create: `tests/test_prozorro_lookup.py`

- [ ] **Step 1: Write failing adapter tests**

Create `tests/test_prozorro_lookup.py` with:

```python
from __future__ import annotations

import json
import unittest
from unittest.mock import patch


class ProzorroLookupTests(unittest.TestCase):
    def test_default_lookup_returns_not_found_without_cache(self):
        from app.services.prozorro_lookup import lookup_prepared_prozorro

        with patch.dict("os.environ", {"PROZORRO_CACHE_PATH": ""}, clear=False):
            result = lookup_prepared_prozorro("12345678")

        self.assertEqual(result.status, "not_found")
        self.assertEqual(result.stats.procurements_count, 0)
        self.assertEqual(result.risk_flags, [])

    def test_lookup_analyzes_prepared_records_from_injected_source(self):
        from app.services.prozorro_lookup import lookup_prepared_prozorro

        result = lookup_prepared_prozorro(
            "12345678",
            source=lambda edrpou: [
                {
                    "id": "UA-TEST-1",
                    "participated": True,
                    "won": True,
                    "has_contract": True,
                    "contract_terminated": True,
                    "termination_reason": "Contract terminated by agreement.",
                }
            ],
        )

        self.assertEqual(result.status, "found")
        self.assertEqual(result.stats.procurements_count, 1)
        self.assertEqual(result.stats.terminated_contracts_count, 1)
        self.assertEqual([flag["type"] for flag in result.risk_flags], ["prozorro_termination_found"])

    def test_lookup_converts_source_exception_to_source_error(self):
        from app.services.prozorro_lookup import lookup_prepared_prozorro

        def failing_source(edrpou: str):
            raise OSError("cache unavailable")

        result = lookup_prepared_prozorro("12345678", source=failing_source)

        self.assertEqual(result.status, "source_error")
        self.assertIn("cache unavailable", result.error or "")
        self.assertEqual(result.risk_flags, [])

    def test_cache_file_source_returns_records_by_edrpou(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from app.services.prozorro_lookup import load_prozorro_cache_file

        with TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "prozorro-cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "12345678": [
                            {
                                "id": "UA-CACHE-1",
                                "participated": True,
                                "won": True,
                                "has_contract": True,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(load_prozorro_cache_file("12345678", cache_path)[0]["id"], "UA-CACHE-1")
            self.assertIsNone(load_prozorro_cache_file("87654321", cache_path))
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_prozorro_lookup.py -q
```

Expected: FAIL because `app.services.prozorro_lookup` does not exist.

- [ ] **Step 3: Implement the minimal service**

Create `app/services/prozorro_lookup.py`:

```python
from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.models.company_lookup import ProzorroAnalysis
from app.services.prozorro_analysis import analyze_prozorro_data


PreparedProzorroSource = Callable[[str], Any]
PROZORRO_CACHE_PATH_ENV = "PROZORRO_CACHE_PATH"


def lookup_prepared_prozorro(
    edrpou: str,
    *,
    source: PreparedProzorroSource | None = None,
    company_context: dict[str, Any] | None = None,
) -> ProzorroAnalysis:
    try:
        payload = source(edrpou) if source else load_prozorro_cache_file(edrpou)
    except Exception as exc:
        return analyze_prozorro_data({"error": str(exc)}, company_context=company_context)
    return analyze_prozorro_data(payload, company_context=company_context)


def load_prozorro_cache_file(edrpou: str, path: str | os.PathLike[str] | None = None) -> Any:
    raw_path = path if path is not None else os.environ.get(PROZORRO_CACHE_PATH_ENV, "")
    if not raw_path:
        return None
    cache_path = Path(raw_path).expanduser()
    if not cache_path.exists() or not cache_path.is_file():
        return None

    payload = json.loads(cache_path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, dict) and "items" in payload:
        by_edrpou = payload.get("items") or {}
        if isinstance(by_edrpou, dict):
            return by_edrpou.get(edrpou)
        return payload
    if isinstance(payload, dict):
        return payload.get(edrpou)
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_prozorro_lookup.py -q
```

Expected: `4 passed`.

- [ ] **Step 5: Commit Task 1**

Stage only Task 1 files:

```powershell
git -c safe.directory='C:/Users/bessp/Desktop/riskua_bot/riskua-kontragent-bot' add -- app/services/prozorro_lookup.py tests/test_prozorro_lookup.py
git -c safe.directory='C:/Users/bessp/Desktop/riskua_bot/riskua-kontragent-bot' commit -m "feat: add prepared prozorro lookup"
```

---

### Task 2: Bot Pipeline Integration

**Files:**
- Modify: `app/bot.py`
- Modify: `tests/test_bot_responses.py`

- [ ] **Step 1: Write failing pipeline tests**

Add these tests to `BotResponseTests` in `tests/test_bot_responses.py`, near existing `edrpou_handler` integration tests:

```python
    async def test_edrpou_handler_shows_prozorro_from_injected_lookup(self):
        from app.bot import edrpou_handler
        from app.models.clarity import ClarityData
        from app.models.company_lookup import CompanyData, CompanyLookupResult, ProzorroAnalysis, ProzorroStats

        message = FakeMessage("12345678", user_id=777)
        saved_results: list[CompanyLookupResult] = []

        def found_lookup(edrpou: str) -> CompanyLookupResult:
            return CompanyLookupResult(
                status="found",
                edrpou=edrpou,
                company_data=CompanyData(short_name='ТОВ "ПРОЗОРО"', edrpou=edrpou),
            )

        def found_clarity_lookup(edrpou: str) -> ClarityData:
            return ClarityData(source_url=f"https://clarity-project.info/edr/{edrpou}", status="found", edrpou=edrpou)

        def prepared_prozorro_lookup(edrpou: str) -> ProzorroAnalysis:
            return ProzorroAnalysis(
                status="found",
                stats=ProzorroStats(
                    procurements_count=2,
                    participations_count=2,
                    wins_count=1,
                    contracts_count=1,
                    terminated_contracts_count=0,
                    last_participation_date="2026-01-10",
                ),
                summary="Prozorro: участей 2, перемог 1, договорів 1, розірвань 0.",
                info_notes=["Сам факт участі не є ризиком."],
            )

        await edrpou_handler(
            message,
            lookup=found_lookup,
            clarity_lookup=found_clarity_lookup,
            youcontrol_lookup=no_youcontrol_lookup,
            debtors_lookup=no_debtors_lookup,
            tax_lookup=no_tax_lookup,
            domain_reputation_lookup=no_domain_reputation_lookup,
            contacts_lookup=no_contacts_lookup,
            prozorro_lookup=prepared_prozorro_lookup,
            save=lambda result, user_id: saved_results.append(result),
        )

        self.assertIn("Prozorro:", message.answers[1])
        self.assertIn("Участей: 2", message.answers[1])
        self.assertIn("Перемог: 1", message.answers[1])
        self.assertIn("Остання участь: 2026-01-10", message.answers[1])
        self.assertIn("Джерела: Opendatabot, Clarity, Prozorro", message.answers[1])
        self.assertEqual(saved_results[0].prozorro_analysis.status, "found")

    async def test_edrpou_handler_keeps_score_when_prozorro_source_errors(self):
        from app.bot import edrpou_handler
        from app.models.clarity import ClarityData
        from app.models.company_lookup import CompanyData, CompanyLookupResult, ProzorroAnalysis

        message = FakeMessage("12345678", user_id=777)
        saved_results: list[CompanyLookupResult] = []

        def found_lookup(edrpou: str) -> CompanyLookupResult:
            return CompanyLookupResult(
                status="found",
                edrpou=edrpou,
                company_data=CompanyData(short_name='ТОВ "ПРОЗОРО"', edrpou=edrpou),
            )

        def found_clarity_lookup(edrpou: str) -> ClarityData:
            return ClarityData(source_url=f"https://clarity-project.info/edr/{edrpou}", status="found", edrpou=edrpou)

        def failed_prozorro_lookup(edrpou: str) -> ProzorroAnalysis:
            return ProzorroAnalysis(
                status="source_error",
                error="cache_unavailable",
                risk_flags=[{"type": "multiple_prozorro_terminations_found"}],
            )

        await edrpou_handler(
            message,
            lookup=found_lookup,
            clarity_lookup=found_clarity_lookup,
            youcontrol_lookup=no_youcontrol_lookup,
            debtors_lookup=no_debtors_lookup,
            tax_lookup=no_tax_lookup,
            domain_reputation_lookup=no_domain_reputation_lookup,
            contacts_lookup=no_contacts_lookup,
            prozorro_lookup=failed_prozorro_lookup,
            save=lambda result, user_id: saved_results.append(result),
        )

        self.assertEqual(saved_results[0].risk_summary.score, 0)
        self.assertNotIn("multiple_prozorro_terminations_found", [reason["type"] for reason in saved_results[0].risk_summary.reasons])
```

Add this direct pipeline test near other source lookup tests:

```python
    async def test_run_source_lookups_attaches_prozorro_analysis(self):
        from app.bot import run_source_lookups
        from app.models.clarity import ClarityData
        from app.models.company_lookup import CompanyData, CompanyLookupResult, ProzorroAnalysis, ProzorroStats

        def found_lookup(edrpou: str) -> CompanyLookupResult:
            return CompanyLookupResult(
                status="found",
                edrpou=edrpou,
                company_data=CompanyData(short_name='ТОВ "ПРОЗОРО"', edrpou=edrpou),
            )

        def found_clarity_lookup(edrpou: str) -> ClarityData:
            return ClarityData(source_url=f"https://clarity-project.info/edr/{edrpou}", status="found", edrpou=edrpou)

        def prepared_prozorro_lookup(edrpou: str) -> ProzorroAnalysis:
            return ProzorroAnalysis(status="found", stats=ProzorroStats(procurements_count=3))

        result, *_ = await run_source_lookups(
            "12345678",
            found_lookup,
            found_clarity_lookup,
            no_youcontrol_lookup,
            no_debtors_lookup,
            no_tax_lookup,
            no_domain_reputation_lookup,
            no_contacts_lookup,
            analysis_timeout=1,
            prozorro_lookup=prepared_prozorro_lookup,
        )

        self.assertEqual(result.prozorro_analysis.status, "found")
        self.assertEqual(result.prozorro_analysis.stats.procurements_count, 3)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_bot_responses.py -k "prozorro or run_source_lookups_attaches" -q
```

Expected: FAIL because `edrpou_handler` and `run_source_lookups` do not accept `prozorro_lookup`.

- [ ] **Step 3: Implement bot integration**

In `app/bot.py`, add imports:

```python
from app.services.prozorro_lookup import lookup_prepared_prozorro
```

Update `run_source_lookups` signature:

```python
async def run_source_lookups(
    edrpou: str,
    lookup: Callable[[str], CompanyLookupResult],
    clarity_lookup: Callable[[str], ClarityData],
    youcontrol_lookup: Callable[[str], dict] = fetch_youcontrol_company,
    debtors_lookup: Callable[[str], dict | None] = fetch_debtors_registry,
    tax_lookup: Callable[[str], dict | None] = fetch_tax_status,
    domain_reputation_lookup: Callable[[str | None, dict | None], dict | None] = fetch_domain_reputation,
    contacts_lookup: Callable[[str, dict | None], dict | None] = fetch_company_contacts_async,
    website_url: str | None = None,
    analysis_timeout: float = ANALYSIS_TIMEOUT_SECONDS,
    prozorro_lookup: Callable[[str], ProzorroAnalysis] = lookup_prepared_prozorro,
) -> tuple[CompanyLookupResult, ClarityData | None, dict | None, dict | None, dict | None, dict | None, dict | None]:
```

Inside `run_source_lookups`, create and wait on `prozorro_task` with the first batch:

```python
    prozorro_task = asyncio.create_task(asyncio.to_thread(prozorro_lookup, edrpou))
    await asyncio.wait(
        {lookup_task, clarity_task, youcontrol_task, debtors_task, tax_task, prozorro_task},
        timeout=analysis_timeout,
    )
```

After `result = completed_lookup_result(...)`, attach the completed Prozorro analysis:

```python
    prozorro_analysis = completed_prozorro_result(prozorro_task, edrpou)
    result = result.model_copy(update={"prozorro_analysis": prozorro_analysis})
```

Cancel unfinished first-batch tasks including `prozorro_task`:

```python
    for task in (lookup_task, clarity_task, youcontrol_task, debtors_task, tax_task, prozorro_task):
        if not task.done():
            task.cancel()
```

Add helper near the other `completed_*_result` helpers:

```python
def completed_prozorro_result(
    task: asyncio.Task[ProzorroAnalysis],
    edrpou: str,
) -> ProzorroAnalysis:
    if task.cancelled() or not task.done():
        return ProzorroAnalysis(status="source_error", error="analysis_timeout")
    try:
        return task.result()
    except Exception:
        logging.exception("Prozorro lookup failed for EDRPOU %s", edrpou)
        return ProzorroAnalysis(status="source_error", error="lookup_failed")
```

Update `debug_handler` and `edrpou_handler` signatures to accept:

```python
    prozorro_lookup: Callable[[str], ProzorroAnalysis] = lookup_prepared_prozorro,
```

Pass it into `run_source_lookups` by keyword:

```python
        analysis_timeout=analysis_timeout,
        prozorro_lookup=prozorro_lookup,
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_bot_responses.py -k "prozorro or run_source_lookups_attaches" -q
```

Expected: PASS.

- [ ] **Step 5: Run broader bot/scoring regression tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_bot_responses.py tests/test_prozorro_lookup.py tests/test_prozorro_analysis.py tests/test_risk_scoring.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit Task 2**

Stage only Task 2 files:

```powershell
git -c safe.directory='C:/Users/bessp/Desktop/riskua_bot/riskua-kontragent-bot' add -- app/bot.py tests/test_bot_responses.py
git -c safe.directory='C:/Users/bessp/Desktop/riskua_bot/riskua-kontragent-bot' commit -m "feat: wire prozorro lookup into bot pipeline"
```

---

### Task 3: Debug Source Visibility

**Files:**
- Modify: `app/bot.py`
- Modify: `tests/test_bot_responses.py`

- [ ] **Step 1: Write failing debug tests**

Add tests near `build_debug_payload` or saved-source tests:

```python
    def test_debug_payload_lists_prozorro_source(self):
        from app.bot import build_debug_payload, with_source_diagnostics
        from app.models.company_lookup import CompanyLookupResult, ProzorroAnalysis, ProzorroStats

        result = CompanyLookupResult(
            status="found",
            edrpou="12345678",
            prozorro_analysis=ProzorroAnalysis(status="found", stats=ProzorroStats(procurements_count=2)),
        )

        payload = build_debug_payload(with_source_diagnostics(result, None))

        self.assertIn("prozorro", payload["sources_checked"])

    def test_debug_payload_lists_unavailable_prozorro_source(self):
        from app.bot import build_debug_payload, with_source_diagnostics
        from app.models.company_lookup import CompanyLookupResult, ProzorroAnalysis

        result = CompanyLookupResult(
            status="found",
            edrpou="12345678",
            prozorro_analysis=ProzorroAnalysis(status="source_error", error="cache_unavailable"),
        )

        payload = build_debug_payload(with_source_diagnostics(result, None))

        self.assertIn("prozorro", payload["sources_unavailable"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_bot_responses.py -k "debug_payload_lists_prozorro" -q
```

Expected: FAIL because `checked_sources` and `unavailable_sources` do not include `prozorro`.

- [ ] **Step 3: Implement debug source visibility**

In `checked_sources`, add:

```python
    prozorro = sources.get("prozorro") or {}
    if prozorro and prozorro.get("status") in {"found", "partial"}:
        checked.append("prozorro")
```

In `unavailable_sources`, add:

```python
    prozorro = sources.get("prozorro") or {}
    if prozorro and prozorro.get("status") == "source_error":
        unavailable.append("prozorro")
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_bot_responses.py -k "debug_payload_lists_prozorro" -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

Stage only Task 3 files:

```powershell
git -c safe.directory='C:/Users/bessp/Desktop/riskua_bot/riskua-kontragent-bot' add -- app/bot.py tests/test_bot_responses.py
git -c safe.directory='C:/Users/bessp/Desktop/riskua_bot/riskua-kontragent-bot' commit -m "feat: include prozorro in debug sources"
```

---

### Task 4: Final Verification

**Files:**
- No planned code changes.

- [ ] **Step 1: Run targeted Prozorro integration suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_prozorro_lookup.py tests/test_prozorro_analysis.py tests/test_risk_scoring.py tests/test_bot_responses.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run full test suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Run whitespace check**

Run:

```powershell
git -c safe.directory='C:/Users/bessp/Desktop/riskua_bot/riskua-kontragent-bot' diff --check
```

Expected: exit 0. Existing LF-to-CRLF warnings may appear for dirty files; whitespace errors must not.

- [ ] **Step 4: Review status**

Run:

```powershell
git -c safe.directory='C:/Users/bessp/Desktop/riskua_bot/riskua-kontragent-bot' status --short --branch
```

Expected: only pre-existing unrelated dirty files remain, unless this task intentionally changed additional files.

- [ ] **Step 5: Request final code review**

Dispatch a reviewer over the adapter/integration commits and require checks for:

- no live API/Clarity parser;
- source adapter does not score directly;
- no score increase for `not_found` or `source_error`;
- Telegram output includes `Prozorro:` from prepared data;
- default no-cache behavior remains safe.
