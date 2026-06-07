# Prozorro Source Adapter Design

## Goal

Make the Telegram bot show the already implemented Prozorro analysis block by wiring prepared Prozorro data into the existing internal analyzer.

This stage must not fetch live Prozorro API data and must not parse Clarity HTML. It only introduces a source adapter that can read prepared/mock/cache data and pass it into `analyze_prozorro_data`.

## Non-Goals

- No live Prozorro API requests.
- No Clarity scraping.
- No browser automation.
- No changes to Prozorro scoring weights.
- No changes to the behavioral risk algorithm except integration safeguards if tests expose a bug.

## Architecture

Add a small service module:

`app/services/prozorro_lookup.py`

Responsibilities:

- Accept an EDRPOU.
- Load prepared Prozorro procurement data from an injectable source.
- Normalize/analyze that data using `app.services.prozorro_analysis.analyze_prozorro_data`.
- Return a `ProzorroAnalysis`.
- Convert source errors into `ProzorroAnalysis(status="source_error")`.
- Return `ProzorroAnalysis(status="not_found")` when no prepared records exist.

The service must not know how risk scoring works. It only produces `ProzorroAnalysis`.

## Source Shape

The adapter should support these input forms:

- `None` for no data.
- `{"items": [...]}` for prepared data.
- `{"error": "..."}` for source failure.
- `list[dict]` for direct normalized/mock items.
- `list[ProzorroProcurement]` for already normalized model instances.

These forms are already accepted by `analyze_prozorro_data`, so the adapter should avoid reimplementing normalization.

## Telegram Integration

Update `run_source_lookups` in `app/bot.py` to accept an injectable `prozorro_lookup` callable.

The Telegram runtime flow should be:

1. Existing company lookup runs as today.
2. Prepared Prozorro source lookup runs by EDRPOU.
3. The returned `ProzorroAnalysis` is attached to `CompanyLookupResult.prozorro_analysis`.
4. Existing report formatting displays the `Prozorro:` block when the analysis is reportable.
5. Existing scoring consumes Prozorro flags only for `found` or `partial`.

The integration should preserve current behavior when no prepared Prozorro data is configured.

## Prepared Data Source

For this stage, provide a default no-data source so production behavior is safe:

- If no mock/cache source is configured, return `not_found`.
- Tests can inject a source function returning prepared data.

An optional local JSON-file source may be added if it stays simple and testable. If added, it should be opt-in through settings or a function parameter, not a required runtime dependency.

## User-Facing Behavior

When prepared data exists, Telegram should show the current `Prozorro:` block:

- закупівель;
- участей;
- перемог;
- договорів;
- завершених договорів;
- розірваних договорів;
- дискваліфікацій;
- rates and dates when available;
- summary;
- informational notes.

When no prepared data exists:

- do not add risk score;
- do not show misleading risk facts;
- either omit the block or show only a safe unavailable/note state if the integration explicitly returns `source_error`.

## Error Handling

- Source exceptions become `ProzorroAnalysis(status="source_error")`.
- Source timeouts must not increase score.
- `not_found` and `source_error` flags must not enter scoring.
- The bot response must still be generated if the Prozorro source fails.

## Testing

Add tests for:

- prepared Prozorro data appears in Telegram output;
- no prepared data preserves current Telegram output and score;
- source error does not increase score;
- injected prepared data with a negative fact affects score through existing flags;
- `run_source_lookups` attaches returned `ProzorroAnalysis` to `CompanyLookupResult`;
- existing Prozorro analyzer/scoring/report tests still pass.

## Acceptance Criteria

- Telegram can display a `Prozorro:` block from injected prepared data.
- No live API or Clarity parser is added.
- Existing risk scoring remains source-agnostic.
- Absence or failure of Prozorro data does not increase score.
- Tests cover the integration path end to end with prepared data.
