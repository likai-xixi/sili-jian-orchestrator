# Next Thread Handoff

This file is the starting point for the next development thread.

## What Has Been Landed

The repository now includes a first real OpenClaw-oriented runtime backbone:

- `scripts/session_registry.py`
- `scripts/workflow_engine.py`
- `scripts/openclaw_adapter.py`
- `scripts/run_orchestrator.py`
- `scripts/completion_consumer.py`
- `scripts/inbox_watcher.py`
- `scripts/context_rollover.py`
- `scripts/automation_control.py`
- `scripts/change_request_control.py`
- `scripts/replan_change_request.py`
- `scripts/natural_language_control.py`
- `scripts/runtime_loop.py`
- `scripts/orchestrator_local_steps.py`
- `scripts/repo_command_detector.py`
- `scripts/provider_evidence.py`
- `scripts/evidence_collector.py`
- `scripts/escalation_manager.py`
- `scripts/parent_session_recovery.py`

Bootstrap now also installs these runtime tools into target projects via `scripts/bootstrap_governance.py`.

The project skeleton now includes:

- expanded `ai/state/agent-sessions.json`
- `workflow_progress` in `ai/state/orchestrator-state.json`
- automation control defaults in `ai/state/orchestrator-state.json`
- `assets/project-skeleton/ai/runtime/README.md`

## What Works Today

Today the system can:

1. Backfill a richer session registry.
2. Parse workflow YAML and compute ready steps.
3. Generate dispatch task cards for ready steps.
4. Materialize dispatch envelopes into `ai/runtime/outbox/`.
5. Drain queued envelopes through the command-bridge transport.
6. Consume structured completions from `ai/runtime/inbox/` automatically.
7. Update:
   - state
   - workflow progress
   - handoff
   - session registry
8. Generate a rollover package and resume prompt for the orchestrator session.
9. Keep the parent agent interactive while the orchestrator loop only runs when `automation_mode=autonomous`.
10. Persist pause and resume intent into state, session registry, handoff, and dedicated reports.
11. Prefer provider-backed CI, release, and rollback evidence over local shell commands when configured.
12. Escalate provider failures, approval conflicts, and high-risk schema changes with structured parent actions.
13. Enter, pause, resume, inspect automation mode, and submit change requests from a single natural-language control sentence.
14. Use a canonical fixed prefix, `司礼监：`, for the natural-language control entrypoint.
15. Automatically freeze execution and generate a replan packet when a significant change request arrives mid-flight.

## What Does Not Work Yet

These pieces are still missing for true full automation:

1. Provider evidence currently supports JSON-backed inputs and GitHub Actions via `gh`, but richer deployment providers still need adapters.
2. Escalation now covers provider failures, approval conflicts, and schema risk, but it still needs deeper approval-policy automation and rollout-specific policies.
3. Parent-thread recovery now auto-attempts command-driven reattach, host_interface_probe auto-reads machine-visible OpenClaw interfaces into runtime config, runtime_loop auto-generates a project-local runtime bridge, and runtime_loop auto-installs project dependencies through environment bootstrap, but it still needs real OpenClaw parent-runtime reattachment instead of the current command bridge.

## Recommended Next Thread Goal

Build the next autonomy layer:

1. Expand provider evidence beyond JSON and GitHub Actions into richer deployment adapters.
2. Enrich escalation policy further for multi-provider rollout conflicts and approval-policy automation.
3. Replace the current command-driven auto-reattach bridge with a real OpenClaw parent-runtime attach path.

## Suggested Implementation Order

1. Expand `scripts/provider_evidence.py`
   - add more deployment and rollout providers
   - keep the normalized evidence contract stable
2. Expand `scripts/evidence_collector.py`
   - consume richer provider evidence in reports and recommendations
3. Expand `scripts/escalation_manager.py`
   - add rollout-specific escalation policy and approval-policy automation
4. Extend `scripts/parent_session_recovery.py`
   - replace the command-driven auto-reattach bridge with actual OpenClaw parent-runtime child-session reattachment

## How To Start Next Time

If you open a new thread in this repository, start here:

1. Read this file.
2. Read [OPENCLAW-AUTONOMY-BLUEPRINT.md](/C:/Users/11131/Desktop/auto%20agent/sili-jian-orchestrator/docs/OPENCLAW-AUTONOMY-BLUEPRINT.md).
3. Read:
   - [automation_control.py](/C:/Users/11131/Desktop/auto%20agent/sili-jian-orchestrator/scripts/automation_control.py)
   - [runtime_loop.py](/C:/Users/11131/Desktop/auto%20agent/sili-jian-orchestrator/scripts/runtime_loop.py)
   - [run_orchestrator.py](/C:/Users/11131/Desktop/auto%20agent/sili-jian-orchestrator/scripts/run_orchestrator.py)
   - [completion_consumer.py](/C:/Users/11131/Desktop/auto%20agent/sili-jian-orchestrator/scripts/completion_consumer.py)
4. Run:
   - `python scripts/run_repo_ci.py`
5. Then implement richer provider adapters and real OpenClaw parent-runtime reattachment as the next milestone.

## Notes About The Local Environment

In the current development environment, `openclaw` CLI is not available in `PATH`.

That means:

- the runtime currently falls back to `outbox` transport by default
- command transport only becomes active when runtime command templates are configured

This is expected and does not block continued development of the orchestration layer.
