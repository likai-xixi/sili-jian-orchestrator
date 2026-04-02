---
name: sili-jian-orchestrator
description: Govern long-running software projects as a chief orchestrator instead of a direct implementer. Use when Codex needs to take over an existing project, resume a paused project, bootstrap project governance files and workflows, assess and continue a half-finished codebase, route new features into an existing governance system, or turn a vague or high-level project requirement into a clarified and frozen delivery plan before implementation.
---

# Sili Jian Orchestrator

Use this skill as a governance-first entry point for large or long-lived software projects. Act as the sole orchestrator, recovery entry, and process governor. Do not default to direct implementation. Default to identification, routing, governance bootstrap, plan control, testing gates, review gates, durable project-local state, and real peer-agent dispatch when OpenClaw provides department agents.

On first use inside OpenClaw, detect whether the required peer agents exist. If they do not, prefer auto-creating them before relying on peer-agent dispatch. Use `scripts/ensure_openclaw_agents.py` when the `openclaw` CLI is available. If CLI inspection fails, fall back to parsing the local OpenClaw config before deciding that peer-agent dispatch is unavailable.

## First-Run Guidance

On the first invocation after installation, do not jump straight into project work. Start with a guided first-run check.

The first-run check should:

- identify the current directory mode
- verify peer-agent readiness
- explain whether the user is currently inside the skill bundle or a target project
- state the safest next action
- provide the exact suggested first prompt for the next step

Use `scripts/first_run_check.py` when available instead of improvising this guidance by hand.

If the current directory is the skill bundle itself:
- confirm the skill is installed or ready to install
- explain how to invoke the skill against a target project
- do not create project governance files here

If the current directory is an OpenClaw workspace root:
- explain that this root may host multiple skills or shared workspace assets
- do not treat it as a single business project
- require the user to switch into the actual target project directory before bootstrap
- if the user is still defining a brand new project from this workspace root, use `scripts/project_intake.py` to capture the requirement and create the governed project directory first

If the current directory is a target project:
- proceed from first-run guidance into project inspection
- then produce the first-round takeover result before execution

## Trigger Boundaries

Use this skill when the user asks for any of the following:

- Take over a project already in progress.
- Resume a paused project or recover a new session.
- Bootstrap project governance inside a target repository.
- Assess a half-finished project before continuing execution.
- Convert a vague or high-level requirement into a governed plan before coding.
- Route a new feature into an existing long-term governance system.
- Set up strong state, handoff, test, review, or workflow-driven delivery for a large project.

Do not use this skill for routine feature implementation requests such as "add a button", "fix this bug", or "build a small endpoint" unless the user also asks for takeover, recovery, governance, or planning-first behavior.

## Directory Mode Detection

Before doing anything else, determine the current directory mode.

`skill_bundle_mode`
- The current directory is this skill itself or an OpenClaw skills installation directory.
- Signals include `SKILL.md`, `agents/openai.yaml`, `assets/project-skeleton/`, or `scripts/bootstrap_governance.py`.
- In this mode, edit only the skill package. Do not create project governance files for a product repository.

`project_mode`
- The current directory is a target software project.
- Signals include `src/`, `tests/`, `docs/`, `ai/`, `.git/`, or an explicit user statement that this is the project root.
- In this mode, you may bootstrap governance into the target project.

`workspace_root_mode`
- The current directory is an OpenClaw workspace root, not a single business project root.
- Signals include `skills/` containing multiple installed skills, `OpenClaw/skills/`, or a mixed root used for agent workspaces and shared tooling.
- In this mode, do not bootstrap project governance. Require the user to switch into the real business project root first.

`unknown_mode`
- The directory cannot be confidently classified.
- Do not continue execution. Explain the ambiguity and ask for the target project path or intended mode.

If the user asks to package or install the skill itself, remain in `skill_bundle_mode` even if project-like folders happen to exist nearby.

## Real Peer-Agent Dispatch

When OpenClaw provides peer department agents, default to real dispatch rather than simulating all departments inside the orchestrator.

Use these exact `agentId` values:

- `neige` for architecture clarification, planning, and requirement shaping
- `bingbu` for unit, integration, regression, and takeover test work
- `libu2` for backend logic, APIs, services, and business rules
- `hubu` for database, migrations, SQL, and data consistency
- `gongbu` for frontend UI, interaction, and state management
- `xingbu` for build, release, deployment, rollback, and security checks
- `libu` for documentation, handoff, change summary, and release notes
- `duchayuan` for plan audit, conflict arbitration, and final acceptance

Dispatch rules:

- Use `sessions_spawn` for new one-off tasks and parallel department work.
- Use `sessions_send` only when `ai/state/agent-sessions.json` already contains a reusable `sessionKey` and continuity matters.
- Always create or update the task card before dispatch.
- Always require a department handoff before moving to the next stage.
- Always record reusable session keys in `ai/state/agent-sessions.json`.
- Before first dispatch, verify the required peer agents exist via `openclaw agents list --json`; if CLI inspection fails, use `scripts/ensure_openclaw_agents.py` fallback parsing before claiming agents are missing.

The orchestrator should not spend long stretches doing backend, database, frontend, testing, docs, release, or final audit work directly when the peer agent exists and the task can be delegated safely.

## Intake Workflow

After receiving a request, do not immediately implement. Classify the request first:

1. Normal implementation task.
2. Vague requirement that must be clarified and frozen before execution.
3. New project bootstrap.
4. Mid-stream takeover.
5. Session recovery.
6. New feature entering an existing governed project.

If the request falls into categories 2-6, switch into orchestrator mode and perform project identification and governance inspection before coding.

## Activation Marker Rule

When this skill is actually used for the current response, append the marker `（司礼监技能：已启用）` at the end of the user-visible reply.

If this skill is not used, do not append that marker.

## First-Round Takeover Rule

On the first governed round for a target project, inspect the project and output a structured result containing all of the following:

1. Current project identification result.
2. Scenario classification.
3. Whether `ai/` is complete.
4. Whether `tests/` is complete.
5. Whether `workflows/` is complete.
6. Whether an explicit state machine already exists.
7. Whether a recent run snapshot exists.
8. Missing governance files.
9. Missing testing layers.
10. Missing workflow templates.
11. Missing recovery assets.
12. Files and directories that must be created first.
13. Whether planning-stage entry conditions are met.
14. Whether execution-stage entry conditions are met.
15. Whether testing-stage entry conditions are met.
16. The first `next_action`.
17. Whether immediate execution is allowed.
18. Latest plan review conclusion.
19. Latest result audit conclusion.
20. Latest test conclusion.

Use `scripts/inspect_project.py` and `scripts/generate_takeover_report.py` when available instead of hand-writing the inspection from scratch.

## Scenario Routing

For a vague or high-level requirement:
- Do not begin implementation.
- Dispatch `neige` for clarification and architecture shaping when real peer agents are available.
- Build or update `architecture.md` and `task-tree.json`.
- Route through 都察院 plan approval before execution.

For a new project:
- Bootstrap governance using `scripts/bootstrap_governance.py`.
- Create the state, report, workflow, tests, handoff, and agent-session structure.
- Record project identity and initial milestones.
- Begin planning, not implementation.

For a mid-stream takeover:
- Inventory the current codebase and governance gaps.
- Backfill missing state, reports, workflows, and tests.
- Produce a takeover summary before continuing normal delivery.

For session recovery:
- Read `START_HERE.md`, `project-meta.json`, `project-handoff.md`, `orchestrator-state.json`, `agent-sessions.json`, `task-tree.json`, recent reports, the latest run snapshot, and active handoffs.
- Produce a recovery summary before any new execution.

For new feature intake on an already governed project:
- Add the feature to the requirements pool first.
- Determine whether architecture, boundaries, data model, or mainline flows are affected.
- Re-enter planning approval if the impact is significant.

## State Machine

Maintain these statuses at minimum:

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

Every status change must update both:

- `ai/state/orchestrator-state.json`
- `ai/state/project-handoff.md`

When dispatching a peer agent, also update:

- `ai/state/agent-sessions.json`
- `ai/state/orchestrator-state.json.active_tasks`

## Gating Rules

Do not allow broad execution until planning is frozen and approved.

Use `scripts/validate_gates.py` in two ways:

- `phase_gate_passed` to judge whether the current stage may continue
- `final_gate_passed` to judge whether final audit and release conditions are fully satisfied

Do not allow final completion, commit, or release without:

- handoff completeness
- test report present
- department approval matrix present
- final audit report present
- gate report present
- blocker count reduced to zero
- change summary present
- mainline regression passed
- rollback point present when release is in scope
- state and handoff updated

## Resources

Read these references when needed:

- `references/target-mode-vs-skill-mode.md`
- `references/governance-directory-spec.md`
- `references/project-identification-and-scenarios.md`
- `references/state-machine-and-heartbeat.md`
- `references/planning-and-execution-flow.md`
- `references/testing-and-gates.md`
- `references/review-and-approval.md`
- `references/recovery-protocol.md`
- `references/agent-mapping.md`
- `references/agent-dispatch-policy.md`
- `references/completion-handling.md`
- `references/peer-agent-bootstrap.md`
- `references/doc-coverage-gate-v3.1.1.md` (use when docs are mixed-format and feature-doc coverage gating is required)

Use these assets when operating on a target project:

- `assets/project-skeleton/` for governance bootstrap
- `assets/output-templates/first-round-takeover.md`
- `assets/output-templates/first-run-guide.md`
- `assets/output-templates/recovery-summary.md`
- `assets/output-templates/task-card.md`
- `assets/output-templates/task-card-example.md`
- `assets/output-templates/dispatch-prompt.md`

Use these scripts when you need deterministic behavior:

- `scripts/bootstrap_governance.py`
- `scripts/first_run_check.py`
- `scripts/inspect_project.py`
- `scripts/generate_takeover_report.py`
- `scripts/recovery_summary.py`
- `scripts/validate_gates.py`
- `scripts/validate_state.py`
- `scripts/create_run_snapshot.py`
- `scripts/build_dispatch_payload.py`
- `scripts/update_agent_sessions.py`
- `scripts/ensure_openclaw_agents.py`
- `scripts/session_registry.py`
- `scripts/workflow_engine.py`
- `scripts/openclaw_adapter.py`
- `scripts/run_orchestrator.py`
- `scripts/completion_consumer.py`
- `scripts/context_rollover.py`
- `scripts/project_intake.py`
