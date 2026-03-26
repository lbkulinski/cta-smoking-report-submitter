# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/lbkulinski/cta-smoking-report-submitter/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/lbkulinski/cta-smoking-report-submitter/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/lbkulinski/cta-smoking-report-submitter/releases/tag/v1.0.0
