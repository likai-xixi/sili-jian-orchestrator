# Anti-Drift Runbook

Read this before autonomous execution, session recovery, or peer-agent dispatch.

## Required Reads

- `ai/state/START_HERE.md`
- `ai/state/project-handoff.md`
- `ai/state/orchestrator-state.json`
- `ai/state/agent-sessions.json`
- `docs/ANTI-DRIFT-RUNBOOK.md`

## Rules

1. Work only on the current workflow step.
2. Stay inside the task card's allowed paths.
3. Do not skip planning, review, gate, or handoff requirements.
4. If state, handoff, or requirements conflict, stop and report blockers.
5. If context feels stale, request rollover instead of guessing.
