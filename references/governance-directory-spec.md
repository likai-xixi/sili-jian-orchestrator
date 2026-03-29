# Governance Directory Specification

Governed projects should converge toward this structure:

```text
project-root/
|- src/
|- tests/
|  |- unit/
|  |- integration/
|  |- e2e/
|  |- regression/
|  |- contract/
|  `- fixtures/
|- workflows/
|  |- new-project.yaml
|  |- takeover-project.yaml
|  |- resume-orchestrator.yaml
|  |- feature-delivery.yaml
|  `- review-and-release.yaml
|- docs/
`- ai/
   |- state/
   |- handoff/
   |- reports/
   |- runs/
   |- prompts/
   `- logs/
```

## Non-Negotiable State Files

These files must exist before the project can claim durable governance:

- `ai/state/project-meta.json`
- `ai/state/START_HERE.md`
- `ai/state/project-handoff.md`
- `ai/state/orchestrator-state.json`
- `ai/state/task-tree.json`

## Non-Negotiable Reports

These files must exist before the project can claim test and review closure:

- `ai/reports/test-report.md`
- `ai/reports/department-approval-matrix.md`
- `ai/reports/acceptance-report.md`

## Recovery Requirement

Governed projects should preserve run snapshots under `ai/runs/<timestamp-run-id>/` with:

- `metadata.json`
- `steps/`
- `summary.md`
