# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- **Breaking:** the handler returns `batchItemFailures` instead of raising when a report fails, so only the failed record (and those after it) are retried. The event source mapping must set `FunctionResponseTypes: [ReportBatchItemFailures]` or failures are silently dropped. The response no longer includes `statusCode`
- **Breaking:** renamed environment variable `DEDUPE_TABLE` to `PROCESSED_REPORTS_TABLE_NAME` (same name as the aggregates and social-bot consumers; each still points at its own table)
- CI/CD aligned with `cta-smoking-report-aggregates`: `ci.yml` (ruff + pytest, reusable), deploy gated on CI in a `production` environment, actions pinned to commit SHAs, AWS role/region/function name read from repo **variables** instead of secrets (`production` environment must exist)
- Tests moved to pytest at the repo root; added `requirements-dev.txt`; Dependabot now covers `pip` and `github-actions`
- Support the new per-car-and-line reports table schema (`carNumberLine` key; no `date`/`reportId`)
- `MODIFY` stream events with a changed `reportedAt` are now treated as new reports; `REMOVE` and unchanged `MODIFY` events are ignored
- Records with a missing or malformed `reportedAt` are skipped instead of failing the batch
- Log/error identifiers use `carNumberLine#reportedAt` instead of `reportId`

### Added
- Idempotency: a receipt (`reportKey` = `carNumberLine#reportedAt`, 7-day `ttl`) is conditionally written to the table named by the required `PROCESSED_REPORTS_TABLE_NAME` env var (e.g. `processed-cta-smoking-submissions`) before submitting; already-claimed reports are skipped, and the receipt is deleted if the submit fails so retries still work
- Unit tests (`pytest`)

## [1.2.0] - 2026-03-25

### Fixed
- Station names for same-line collisions (Harlem, Western on the Blue Line) now resolve to their branch-qualified names (e.g. "Harlem (O'Hare Branch)") so the CTA virtual agent accepts them. Previously, sending the bare name caused the chatbot to reject the input and return no direction chips, failing the report.
- `station_descriptive_name` lookup now falls back to `station_name` if the field is absent from a record, preventing a `KeyError` when the stations API response omits the field (e.g. when `$select` is used in `STATIONS_URL`)

## [1.1.0] - 2026-03-25

### Changed
- `CTA_API_URL`, `STATIONS_URL`, and `CTA_AUTHORIZATION` are now read from environment variables instead of being hardcoded

## [1.0.0] - 2026-03-25

### Added
- Lambda handler triggered by DynamoDB stream `INSERT` events
- Multi-step chatbot session flow to submit "Smoking on a train" reports to CTA
- Station name resolution via Chicago Open Data Portal with in-memory caching
- Direction chip parsing from Dialogflow `detect-intent` responses
- Apostrophe-normalized direction matching for terminal station names
- Support for all eight CTA rail lines (Red, Blue, Brown, Green, Orange, Purple, Pink, Yellow)
- Batch error aggregation with retry-triggering `RuntimeError` on partial failures

[Unreleased]: https://github.com/lbkulinski/cta-smoking-report-submitter/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/lbkulinski/cta-smoking-report-submitter/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/lbkulinski/cta-smoking-report-submitter/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/lbkulinski/cta-smoking-report-submitter/releases/tag/v1.0.0
