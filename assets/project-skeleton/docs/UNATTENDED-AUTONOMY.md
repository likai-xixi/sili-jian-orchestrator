# Unattended Autonomy

This note explains how the orchestrator behaves when autonomous mode is used as an unattended run.

## What Changed

- Autonomous mode can use project-level defaults instead of a single hard-coded cycle.
- Session rotation is configurable per agent.
- Runtime loops retry ordinary operational failures for a bounded number of cycles.
- Customer-decision checkpoints freeze tasks, sessions, and execution gates before the loop stops.
- Successful cycles can create git checkpoint commits automatically.

## Main Settings

These values live in `ai/state/orchestrator-state.json`:

- `autonomous_runtime_max_cycles`
- `autonomous_max_dispatch`
- `autonomous_failure_streak_limit`
- `autonomous_idle_streak_limit`
- `autonomous_auto_commit_enabled`
- `autonomous_auto_commit_push`
- `autonomous_stop_on_customer_decision`
- `session_rotation_policy`

## Configure It

```bash
python ai/tools/configure_autonomy.py <project-root> --max-cycles 999 --max-dispatch 7 --failure-streak-limit 3 --idle-streak-limit 2 --agent-id libu2 --completion-limit 2 --dispatch-limit 3
```
