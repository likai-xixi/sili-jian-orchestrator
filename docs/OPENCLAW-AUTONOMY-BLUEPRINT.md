# OpenClaw Autonomy Blueprint

This document describes the intended end-state for `sili-jian-orchestrator` when it runs as a real OpenClaw-backed chief orchestrator instead of a governance-only skill.

## Goal

The system should support this operating mode:

1. The parent agent behaves normally until the user explicitly invokes `sili-jian-orchestrator`.
2. The skill then boots or resumes an `orchestrator` child session.
3. The orchestrator session continuously reads workflow state, dispatches peer agents, collects completions, updates governance state, and rolls over when context limits approach.
4. The parent agent is only interrupted for high-risk escalation, missing capability, or explicit user approval.
5. The parent agent remains interactive even while the orchestrator is running in the background.
6. If the parent session itself rotates, the new parent session should be able to resume control immediately from the project-local state.

## Landed Runtime Components

The following runtime components are now implemented in `scripts/` and copied into target projects during `bootstrap_governance.py`:

- `session_registry.py`
  Persists extended session state such as `last_step_id`, `resume_prompt`, and `active_workflow`.
- `workflow_engine.py`
  Parses the repository workflow YAML and computes ready steps from `workflow_progress` plus `active_tasks`.
- `openclaw_adapter.py`
  Produces dispatch envelopes and supports two transports:
  - `outbox`
  - `command` via `OPENCLAW_SPAWN_COMMAND` / `OPENCLAW_SEND_COMMAND`
- `run_orchestrator.py`
  Runs one dispatch cycle, generates task cards, updates `active_tasks`, and writes an orchestrator dispatch plan.
- `completion_consumer.py`
  Consumes structured peer-agent completions and updates state, session registry, handoff, and workflow progress.
- `inbox_watcher.py`
  Consumes queued completion payloads from `ai/runtime/inbox/`, archives successes, and isolates failures.
- `context_rollover.py`
  Generates a structured rollover package and resume prompt when a session needs to rotate.
- `automation_control.py`
  Tracks `normal`, `armed`, `autonomous`, and `paused` modes so the parent agent can keep talking while the orchestrator runs in the background.
- `natural_language_control.py`
  Lets operators enter, pause, resume, inspect automation mode, or submit mid-flight changes with a single natural-language sentence. The canonical prefix is `司礼监：`.
- `change_request_control.py`
  Records mid-flight feature additions or modifications, updates requirements and task-tree state, and pauses autonomy when replanning is required.
- `replan_change_request.py`
  Freezes broad execution, shifts the project back into planning, and generates a replan packet for significant mid-flight changes.
- `runtime_loop.py`
  Runs the automated control loop across orchestrator dispatch, transport delivery, and inbox consumption.
- `orchestrator_local_steps.py`
  Executes the safe local `orchestrator` workflow steps in-process and syncs state, handoff, and summary views.
- `repo_command_detector.py` + `evidence_collector.py`
  Detect runnable project commands and materialize `test-report.md` / `gate-report.md` evidence during late workflow stages, including CI, release, and rollback probes when enabled.
- `provider_evidence.py`
  Collects provider-backed CI, release, and rollback evidence from structured JSON inputs or GitHub Actions via `gh` when configured.
- `runtime_environment.py`
  Auto-generates project-local runtime defaults, runtime-environment reports, and the fallback parent-attach bridge command when environment variables are missing.
- `host_interface_probe.py`
  Reads machine-visible OpenClaw host interfaces such as environment variables and host config files, then syncs discovered `spawn`, `send`, and `parent-attach` commands into the project-local runtime config.
- `environment_bootstrap.py`
  Auto-installs project dependencies such as `requirements.txt` or `package.json` dependencies, writes an environment-bootstrap report, and can optionally attempt configured host-side helper installers. It assumes the skill already runs inside an OpenClaw host and therefore does not try to install OpenClaw itself.
- `openclaw_runtime_bridge.py`
  Tries known OpenClaw parent-attach command variants so project-local automation can still attempt reattachment without a hand-written attach template.
- `escalation_manager.py`
  Produces structured escalation reports whenever transport, gate, provider evidence, approval conflicts, or risk signals require parent attention.
- `parent_session_recovery.py`
  Produces the parent-thread resume package, writes the reattach payload, and now auto-attempts parent-session reattach through either `OPENCLAW_PARENT_ATTACH_COMMAND` or the project-local runtime bridge.

## Runtime Data Flow

1. `run_orchestrator.py` loads the current workflow from `workflows/<current_workflow>.yaml`.
2. `workflow_engine.py` computes ready steps from:
   - `ai/state/orchestrator-state.json`
   - `workflow_progress.completed_steps`
   - `workflow_progress.dispatched_steps`
   - `active_tasks`
3. `automation_control.py` decides whether the runtime remains in `normal`, `armed`, `autonomous`, or `paused`.
4. Each ready step becomes a task card under `ai/prompts/dispatch/`.
5. `openclaw_adapter.py` writes a dispatch envelope into `ai/runtime/outbox/`.
6. `openclaw_adapter.py --drain-outbox` or `runtime_loop.py` delivers queued envelopes to the configured OpenClaw command bridge.
7. The peer completion is written back as JSON into `ai/runtime/inbox/`.
8. `inbox_watcher.py` consumes queued completions through `completion_consumer.py`.
9. `completion_consumer.py` updates:
   - `ai/state/orchestrator-state.json`
   - `ai/state/agent-sessions.json`
   - `ai/handoff/<role>/active/*.md`
10. When no ready step is available or context must rotate, `context_rollover.py` writes:
    - `ai/reports/orchestrator-rollover.md`
    - `ai/reports/orchestrator-rollover.json`
11. When the user pauses the loop, `automation_control.py` writes:
    - `ai/reports/automation-control.md`
    - `ai/reports/automation-control.json`
    - `ai/reports/pause-report.md`
    - `ai/reports/pause-report.json`
12. When provider-backed CI or deployment evidence is configured, `provider_evidence.py` writes:
    - `ai/reports/provider-evidence-summary.json`
13. `runtime_environment.py` writes:
    - `ai/reports/runtime-environment.json`
    - `ai/runtime/runtime-config.json`
14. `host_interface_probe.py` writes:
    - `ai/reports/host-interface-probe.json`
15. `environment_bootstrap.py` writes:
    - `ai/reports/environment-bootstrap.json`
16. When a new feature or scope change arrives mid-flight, `change_request_control.py` writes:
    - `ai/reports/cr-*.md`
    - `ai/reports/cr-*.json`
17. When the change requires replanning, `replan_change_request.py` writes:
    - `ai/reports/replan-cr-*.md`
    - `ai/reports/replan-cr-*.json`

## Current OpenClaw Boundary

This repository does not ship an embedded OpenClaw daemon. Instead, it uses a transport boundary:

- If `openclaw` is not present, dispatches are still materialized in `ai/runtime/outbox/`.
- If the runtime environment knows the actual OpenClaw spawn/send commands, it can configure:
  - `OPENCLAW_SPAWN_COMMAND`
  - `OPENCLAW_SEND_COMMAND`

The command transport is intentionally externalized so the skill can remain portable across OpenClaw runtime variants.

## Remaining Work For Full Autonomy

The project is not yet at full end-to-end autonomy. These items are still required:

1. Expand provider evidence beyond JSON and GitHub Actions into richer deployment and rollout signals.
2. Expand escalation generation further for multi-provider rollout conflicts and deeper approval-policy automation.
3. Integrate parent-session reattachment directly with the real OpenClaw parent runtime instead of the current command-driven auto-reattach bridge.

## Operator Commands

Recommended command sequence inside a governed project:

```bash
python ai/tools/session_registry.py <project-root> --ensure-schema
python ai/tools/natural_language_control.py <project-root> "司礼监：进入自动模式"
python ai/tools/natural_language_control.py <project-root> "司礼监：把登录流程改成短信验证码 + 邮箱验证码双通道"
python ai/tools/automation_control.py <project-root> --mode autonomous --actor user --reason "Start autonomous loop"
python ai/tools/runtime_loop.py <project-root> --transport outbox
python ai/tools/provider_evidence.py <project-root>
python ai/tools/openclaw_adapter.py <project-root> --drain-outbox
python ai/tools/inbox_watcher.py <project-root>
python ai/tools/context_rollover.py <project-root> --agent-id orchestrator
python ai/tools/automation_control.py <project-root> --mode paused --actor user --reason "Need clarification" --resume-action "Continue the current workflow step"
python ai/tools/run_project_guard.py <project-root>
```

## Immediate Next Milestone

The next concrete milestone is:

`deeper provider adapters + real parent-runtime reattach`

That milestone turns the current runtime from a provider-aware orchestrator loop into a more production-native one.
