# State Machine And Heartbeat

## Required Statuses

Use these statuses at minimum:

- `draft`
- `planning`
- `department-approval`
- `plan-approved`
- `executing`
- `self-check`
- `testing`
- `department-review`
- `final-audit`
- `accepted`
- `committed`
- `archived`
- `blocked`
- `stuck`
- `rework`
- `redesign`
- `cancelled`
- `superseded`
- `deferred`

## Heartbeat Rules

Each orchestrated round should record:

- the single main objective
- the reason this round matters
- the highest-priority task
- current blocker level
- current mainline status
- the next action
- the next owner

## Update Discipline

Every meaningful state transition should update both:

- `ai/state/orchestrator-state.json`
- `ai/state/project-handoff.md`

When a governed round creates a durable checkpoint, also update:

- `ai/runs/<run-id>/summary.md`

Do not rely on chat memory as the only state carrier.
