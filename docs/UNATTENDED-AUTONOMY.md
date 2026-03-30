# Unattended Autonomy

This note explains how the orchestrator now behaves when autonomous mode is used as an unattended run.

## What Changed

- Entering autonomous mode can now use project-level defaults instead of a hard-coded single cycle.
- Session rotation is configurable per agent, so long-lived child sessions can be retired automatically after a chosen number of completions or dispatches.
- Runtime loops retry ordinary operational failures for a bounded number of cycles instead of stopping immediately.
- If the project reaches a true customer-decision checkpoint, the orchestrator freezes tasks, sessions, and execution gates together before stopping.
- Successful runtime cycles can create a git checkpoint commit automatically.

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

Use the helper below inside a governed project:

```bash
python ai/tools/configure_autonomy.py <project-root> --max-cycles 999 --max-dispatch 7 --failure-streak-limit 3 --idle-streak-limit 2 --agent-id libu2 --completion-limit 2 --dispatch-limit 3
```

Examples:

- Rotate `libu2` after `2` completed task rounds:

```bash
python ai/tools/configure_autonomy.py <project-root> --agent-id libu2 --completion-limit 2
```

- Rotate `gongbu` after `3` dispatches:

```bash
python ai/tools/configure_autonomy.py <project-root> --agent-id gongbu --dispatch-limit 3
```

- Disable automatic commits:

```bash
python ai/tools/configure_autonomy.py <project-root> --no-auto-commit
```

## Automatic Commits

When automatic commits are enabled, each runtime cycle with real progress will call:

- `ai/tools/git_autocommit.py`

That helper stages project-root changes, creates a checkpoint commit, and writes:

- `ai/reports/auto-commit.json`
- `ai/reports/auto-commit.md`

## Decision Stops

The orchestrator now treats these as user-decision checkpoints:

- customer decision required after post-review exhaustion
- unresolved approval conflicts that require arbitration
- unresolved approval deadlocks

When one of those appears during autonomous execution, the orchestrator:

1. switches to `automation_mode=paused`
2. pauses active tasks and child sessions
3. disables `execution_allowed`, `testing_allowed`, and `release_allowed`
4. records the decision report path when available

## Guided Planning

When scope is unclear, planning is now meant to surface multiple guided options instead of a single blunt next step. This applies to:

- change-request replans
- customer-decision reports
- project intake option selection
