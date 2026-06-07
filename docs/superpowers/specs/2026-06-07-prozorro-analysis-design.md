# Prozorro Analysis Design

## Мета

Додати до RiskUA перший етап Prozorro-аналізу для оцінки контрагента за ЄДРПОУ: внутрішню модель даних, нормалізацію, поведінковий аналіз закупівель, risk flags, пояснення для звіту і тести.

Перший етап не підключає live API Prozorro, Clarity-парсинг або інші мережеві джерела. Алгоритм має однаково працювати з даними з моків, кешу, майбутнього Prozorro API, Clarity або іншого адаптера.

## Головні принципи

- Сам факт участі компанії в Prozorro не є ризиком.
- Нуль перемог не підвищує score без інших негативних фактів.
- Ризик додається тільки за конкретну негативну поведінкову ознаку.
- Однакові ризики з різних джерел не дублюються.
- Якщо Prozorro-дані порожні, недоступні або часткові, score не підвищується без негативного факту.
- Отримання даних і оцінка ризиків розділені архітектурно.
- `app/services/prozorro_analysis.py` відповідає за поведінковий аналіз закупівель.
- `app/services/risk_scoring.py` тільки зважує отримані flags за загальними правилами RiskUA.

## Обраний підхід

Обрано підхід B: окремий сервіс `app/services/prozorro_analysis.py`.

Цей підхід не перевантажує `app/bot.py`, не змішує Telegram-логіку з комплаєнс-аналізом і залишає scoring незалежним від конкретного джерела даних. У майбутньому live API Prozorro, Clarity або інше джерело будуть окремими адаптерами, які приводять дані до внутрішньої структури.

## Моделі даних

Додати в `app/models/company_lookup.py` три Pydantic-моделі.

### `ProzorroProcurement`

Описує одну закупівлю або договірну подію, де фігурує компанія:

- `procurement_id: str | None`
- `url: str | None`
- `title: str | None`
- `cpv_code: str | None`
- `cpv_name: str | None`
- `procedure_type: str | None`
- `status: str | None`
- `expected_value_uah: float | None`
- `bid_value_uah: float | None`
- `contract_value_uah: float | None`
- `buyer_name: str | None`
- `buyer_edrpou: str | None`
- `participants_count: int | None`
- `participated: bool`
- `won: bool`
- `disqualified: bool`
- `disqualification_reason: str | None`
- `has_contract: bool`
- `contract_completed: bool`
- `contract_terminated: bool`
- `termination_reason: str | None`
- `complaints_count: int`
- `supplier_related_complaints_count: int`
- `amendments_count: int`
- `contract_amount_change_uah: float | None`
- `contract_amount_change_percent: float | None`
- `date: str | None`
- `award_date: str | None`
- `contract_date: str | None`

Defaults should be conservative: booleans default to `False`, counts default to `0`, optional values default to `None`.

### `ProzorroStats`

Aggregated statistics over normalized procurements:

- `procurements_count: int`
- `participations_count: int`
- `wins_count: int`
- `contracts_count: int`
- `completed_contracts_count: int`
- `terminated_contracts_count: int`
- `disqualifications_count: int`
- `complaints_count: int`
- `supplier_related_complaints_count: int`
- `first_participation_date: str | None`
- `last_participation_date: str | None`
- `last_win_date: str | None`
- `win_rate_percent: float | None`
- `termination_rate_percent: float | None`
- `disqualification_rate_percent: float | None`
- `single_buyer_contract_share_percent: float | None`
- `single_buyer_value_share_percent: float | None`
- `low_competition_wins_count: int`
- `high_discount_bids_count: int`

Rates are `None` when the denominator is zero.

### `ProzorroAnalysis`

Result of the analyzer:

- `source: str = "prozorro_analysis"`
- `status: str` with values `found`, `not_found`, `partial`, `source_error`
- `stats: ProzorroStats`
- `procurements: list[ProzorroProcurement]`
- `risk_flags: list[dict[str, Any]]`
- `info_notes: list[str]`
- `summary: str | None`
- `parse_warnings: list[str]`
- `error: str | None`
- `checked_at: datetime`

Add `prozorro_analysis: ProzorroAnalysis | None = None` to `CompanyLookupResult`.

## Analyzer API

Create `app/services/prozorro_analysis.py` with one public entry point:

```python
def analyze_prozorro_data(
    data: list[dict[str, Any]] | dict[str, Any] | list[ProzorroProcurement] | None,
    *,
    company_context: dict[str, Any] | None = None,
) -> ProzorroAnalysis:
    ...
```

The analyzer accepts normalized model objects or raw dictionaries. Source-specific adapters can later prepare raw dicts, but this module must not fetch URLs, parse Clarity HTML, or depend on a live API.

`company_context` may include:

- `edrpou`
- `company_name`
- `main_activity_code`
- `main_activity_name`
- `additional_activities`

## Normalization Rules

The analyzer should normalize common aliases from future sources:

- procurement id: `procurement_id`, `id`, `tender_id`
- title: `title`, `name`, `procurement_title`
- CPV: `cpv_code`, `cpv`, `classification_id`
- buyer: `buyer_name`, `procuring_entity`, `buyer`
- buyer EDRPOU: `buyer_edrpou`, `buyer_identifier`, `buyer_code`
- expected value: `expected_value_uah`, `expected_value`, `value`
- bid value: `bid_value_uah`, `bid_value`, `proposal_value`
- contract value: `contract_value_uah`, `contract_value`, `award_value`
- dates: `date`, `award_date`, `contract_date`

Unknown fields are ignored. Invalid numeric values become `None`; invalid counts become `0`; missing booleans become `False`.

## Risk Flags

Add these new definitions to `app/services/risk_scoring.py`:

- `multiple_prozorro_terminations_found` - 35 - Кілька розірвань договорів у Prozorro
- `frequent_prozorro_disqualifications` - 20 - Часті відхилення в Prozorro
- `problematic_documents_found` - 35 - Проблемні/недостовірні документи
- `qualification_mismatch_found` - 20 - Невідповідність кваліфікаційним вимогам
- `single_buyer_concentration` - 15 - Значна концентрація договорів на одному замовнику
- `low_competition_wins` - 15 - Перемоги у закупівлях з низькою конкуренцією
- `frequent_contract_changes` - 10 - Часті зміни договорів у Prozorro
- `substantial_contract_amount_increase` - 20 - Суттєве збільшення суми договорів у Prozorro
- `possible_prozorro_dumping` - 10 - Можливий демпінг у Prozorro
- `supplier_related_prozorro_complaints` - 15 - Скарги в Prozorro, пов'язані з постачальником

Use existing flags when the Prozorro fact maps to an existing RiskUA risk:

- `prozorro_termination_found` - 25
- `contract_nonperformance_case` - 40
- `kved_mismatch` - 20
- `tax_debt_found` - 25
- `large_tax_debt_found` - 45
- `bankruptcy_found` - 90
- `sanctions_found` - 90

## Behavioral Rules

### Presence in Prozorro

If procurements exist, add no risk. Add an info note:

`Компанія фігурує у публічних закупівлях. Сам факт участі не є ризиком, але дозволяє оцінити досвід, дисципліну та виконання договорів.`

### Participations Without Wins

If participations are at least `3` and wins are `0`, add no risk. Add an info note:

`Компанія брала участь у закупівлях, але перемог не має. Це не підтверджує успішний досвід виконання державних контрактів.`

### Contract Terminations

If at least one contract is terminated, add `prozorro_termination_found`.

If terminated contracts are at least `2` or termination rate is at least `30%`, add `multiple_prozorro_terminations_found`.

If a termination reason mentions non-performance, missed deadlines, quality issues, refusal to supply, or similar contract discipline issues, also add `contract_nonperformance_case`.

### Frequent Disqualifications

If disqualifications are at least `3` or disqualification rate is greater than `50%`, add `frequent_prozorro_disqualifications`.

Map disqualification reasons to existing or new risks:

- tax debt markers -> `tax_debt_found`
- large tax debt markers -> `large_tax_debt_found`
- bankruptcy markers -> `bankruptcy_found`
- sanctions markers -> `sanctions_found`
- false or unreliable documents markers -> `problematic_documents_found`
- qualification mismatch markers -> `qualification_mismatch_found`

### CPV Versus KVED

Compare CPV code/name and procurement title with `main_activity_code`, `main_activity_name`, and `additional_activities` from `company_context`.

If most procurements clearly do not match the company's activities, add `kved_mismatch`. If matching is uncertain, add only an info note and no risk.

The first implementation should use conservative keyword groups, not an over-broad classifier. It should avoid risk when there is no confident mismatch.

### Single Buyer Concentration

If contracts are at least `5` and one buyer accounts for at least `80%` of contract count or contract value, add `single_buyer_concentration`.

Add an explanatory note that concentration can be normal for a specialized supplier but should be checked manually.

### Low Competition Wins

If wins are at least `5` and at least `60%` of wins have `participants_count <= 1`, add `low_competition_wins`.

### Frequent Contract Changes

If contracts with amendments are frequent, add `frequent_contract_changes`.

Threshold: at least `5` contracts and average amendments per contract at least `3`, or at least `10` total amendments.

If any contract amount increased by at least `20%` through changes, add `substantial_contract_amount_increase`.

### Possible Dumping

If at least `2` bids are at least `50%` lower than expected value, add `possible_prozorro_dumping`. One isolated bid must not add risk.

### Complaints

Complaints do not automatically increase score.

If `supplier_related_complaints_count > 0`, add `supplier_related_prozorro_complaints`.

### Old Procurements

If the last participation is more than `3` years before `checked_at`, add an info note:

`Остання знайдена участь у Prozorro була давно, тому цей сигнал має обмежену актуальність.`

Do not change score because data is old.

### Empty, Missing, or Unavailable Data

If data is `None`, empty, unavailable, or marked as source error, return an analysis with no risk flags and a neutral summary. This must not increase score.

## Integration With Risk Summary

Update `collect_source_risk_flags` in `app/bot.py` to accept `prozorro_analysis` and append `prozorro_analysis.risk_flags`.

Each Prozorro flag should include:

- `type`
- `source: "prozorro_analysis"`
- `status: "found"`
- `confidence`
- `raw_text`
- optional `matched_pattern`
- optional `match_type`

Deduplication remains in `calculate_final_risk`, so if Prozorro and another source produce the same canonical flag, the weight is counted once and sources are merged.

Update `build_risk_summary`, `with_source_diagnostics`, and `build_sources_snapshot` to carry `prozorro_analysis` without requiring any live fetch.

## Telegram Report

Add a separate `Prozorro` block to the user report when `CompanyLookupResult.prozorro_analysis` is present.

The block should show:

- total procurements
- participations
- wins
- contracts
- completed contracts
- terminated contracts
- disqualifications
- win rate
- termination rate
- disqualification rate
- last participation date
- last win date
- summary
- info notes

The report must state that participation itself is not a risk when procurements exist without negative facts.

If there are no Prozorro data, the normal report should not become noisier. A missing optional source should not alarm the user.

## Error Handling

- Analyzer errors should become `status="partial"` or `status="source_error"` with `parse_warnings` or `error`.
- Errors must not produce positive risk flags by themselves.
- Partially valid rows should be analyzed; invalid rows should be skipped with a parse warning.
- Missing CPV/KVED data should avoid `kved_mismatch` and add an uncertainty note only when enough context exists to explain the limitation.

## Testing

Add focused tests for `app/services/prozorro_analysis.py` and integration tests for risk scoring/report behavior.

Required scenarios:

- participations exist, wins are `0`, score is not increased
- one terminated contract adds `prozorro_termination_found`
- multiple terminated contracts add `multiple_prozorro_terminations_found`
- termination due to non-performance also adds `contract_nonperformance_case`
- frequent disqualifications add `frequent_prozorro_disqualifications`
- disqualification reasons map to tax debt, large tax debt, bankruptcy, sanctions
- false documents map to `problematic_documents_found`
- qualification issues map to `qualification_mismatch_found`
- clear CPV/KVED mismatch adds `kved_mismatch`
- uncertain CPV/KVED matching adds no risk
- single buyer concentration adds `single_buyer_concentration`
- low competition wins add `low_competition_wins`
- frequent amendments add `frequent_contract_changes`
- substantial contract amount increase adds `substantial_contract_amount_increase`
- repeated deep discounts add `possible_prozorro_dumping`
- one deep discount does not add risk
- supplier-related complaints add `supplier_related_prozorro_complaints`
- generic complaints do not add risk
- old procurements add an info note and no risk
- empty or unavailable data add no risk
- duplicate flags from Prozorro and another source count once in final score
- Telegram report includes the Prozorro block when analysis exists

## Out of Scope For First Stage

- Live Prozorro API integration.
- Clarity HTML parsing for detailed Prozorro tables.
- Network retries, pagination, or rate limiting.
- Persistent cache schema.
- ML or external classifier for CPV/KVED matching.

These belong to the second stage after the internal model and scoring behavior are stable.
