# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0]

First release.

### Added

- `api_contract` management command with `generate`, `sync`, `check` and
  `diff` actions.
- OpenAPI generation through drf-spectacular, with normalization for
  byte-stable output and structural validation before anything is written.
- Postman Collection v2.1 generation, grouped by OpenAPI tag, with
  deterministic ids and placeholder examples.
- Synchronization that merges into an existing collection and preserves
  scripts, custom headers, parameter values, request bodies, response examples
  and manual requests.
- Endpoint identity based on method and path, with `operationId` and contract
  fingerprints used to follow renames.
- Rename detection with a confidence score, applying confident matches and
  reporting uncertain ones for review.
- Archiving instead of deletion for endpoints that leave the API, with opt-in
  cleanup through `REMOVE_DELETED_ENDPOINTS`.
- Breaking change classification, and `FAIL_ON_BREAKING_CHANGE` to stop a run
  when one is found.
- `--dry-run` on every action.
- Atomic writes, so a failure never leaves a partial contract.

[Unreleased]: https://github.com/OJESH-DHK/django-api-contract/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/OJESH-DHK/django-api-contract/releases/tag/v0.1.0
