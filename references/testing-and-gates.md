# Testing And Gates

## Required Test Layers

Governed projects should maintain:

- `tests/unit/`
- `tests/integration/`
- `tests/e2e/`
- `tests/regression/`
- `tests/contract/`
- `tests/fixtures/`

## Required Report

Maintain `ai/reports/test-report.md` with at least:

- round id
- target under test
- scope
- test types covered
- passed count
- failed count
- skipped count
- blockers
- warnings
- recommendation on final audit
- recommendation on release

## Gate Failure Conditions

Do not allow completion, commit, or release if any of the following are missing:

- handoff evidence
- test report
- department approval matrix
- acceptance report
- change summary

## Minimum Testing Rule For Takeovers

When taking over an existing project, establish at minimum:

- a runnable test structure
- a mainline regression baseline
- a fresh takeover-era test report
