from __future__ import annotations

import argparse
import json
from pathlib import Path

from automation_control import ensure_control_state
from build_dispatch_payload import build_prompt
from close_session import apply_close
from common import ensure_dual_review_state, read_json, require_valid_json, utc_now, write_json, write_text
from context_rollover import create_rollover
from openclaw_adapter import dispatch_payload
from orchestrator_local_steps import execute_local_step, is_local_orchestrator_step
from resource_requirements import evaluate_runtime_constraints, task_card_resource_context
from session_registry import ensure_registry_schema, session_reuse_decision, upsert_session
from task_rounds import record_round_progress
from validate_state import render_markdown as render_state_validation_markdown
from validate_state import validate as validate_state
from workflow_engine import WorkflowStep, ensure_workflow_progress, load_workflow, ready_steps


ROLE_ALLOWED_PATHS = {
    "orchestrator": "ai,state,docs,workflows,tests",
    "neige": "ai/state,docs,references,workflows",
    "duchayuan": "ai/reports,ai/state,docs",
    "libu2": "src,server,services,api,lib,tests/unit",
    "hubu": "db,migrations,sql,schemas,tests/integration",
    "gongbu": "src,app,web,components,pages,tests/e2e",
    "bingbu": "tests,ai/reports,package.json,pyproject.toml",
    "libu": "docs,README.md,CHANGELOG.md,ai/reports,ai/handoff",
    "xingbu": ".github,deploy,infra,scripts,ai/reports",
}

ROLE_TESTING = {
    "libu2": "unit and service regression",
    "hubu": "integration and data consistency",
    "gongbu": "ui smoke and e2e",
    "bingbu": "full regression and gate verification",
    "libu": "documentation consistency check",
    "xingbu": "build, release, rollback verification",
}


DEFAULT_COMPLETION_SCHEMA_VERSION = "v1"
VALID_SKILL_POLICIES = {"required", "optional", "forbidden"}
ROLE_SKILL_POLICY = {
    "orchestrator": "optional",
    "neige": "required",
    "duchayuan": "required",
    "libu2": "required",
    "hubu": "required",
    "gongbu": "required",
    "bingbu": "required",
    "libu": "required",
    "xingbu": "required",
}
ROLE_REQUIRED_SKILLS = {
    "neige": ["neige-governance"],
    "duchayuan": ["duchayuan-audit"],
    "libu2": ["libu2-implementation"],
    "hubu": ["hubu-data"],
    "gongbu": ["gongbu-frontend"],
    "bingbu": ["bingbu-testing"],
    "libu": ["libu-docs"],
    "xingbu": ["xingbu-release"],
}


DISPATCHED_ENVELOPE_STATUSES = {"queued", "sent"}
ACTIVE_TASK_STATUSES = {"in-progress", "queued", "active", "waiting", "paused", "blocked", "rework", "redesign"}
FORMAL_DEPARTMENT_REVIEW_GUARD_CODES = {
    "department_review_before_cross_reviews_complete",
    "missing_department_approval_matrix",
    "incomplete_department_review_sources",
    "missing_skill_usage_trace",
    "skill_policy_violation",
    "forbidden_skill_used",
    "invalid_completion_payload",
}
STATE_VALIDATION_GUARD_REASONS = {
    "department_review_before_cross_reviews_complete": "Formal department-review evidence is incomplete.",
    "missing_department_approval_matrix": "Formal department-review evidence is incomplete.",
    "incomplete_department_review_sources": "Formal department-review evidence is incomplete.",
    "missing_skill_usage_trace": "Skill usage trace evidence is missing for the latest completion.",
    "skill_policy_violation": "Skill usage policy violations are blocking autonomous execution.",
    "forbidden_skill_used": "A forbidden skill usage record was detected and blocked by policy.",
    "invalid_completion_payload": "Completion payload validation failed and requires repair before continuing.",
}


def slugify(text: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in text).strip("-")


def next_task_id(step: WorkflowStep) -> str:
    stamp = utc_now().replace(":", "").replace("+00:00", "Z")
    return f"{step.id.upper().replace('-', '_')}-{stamp}"


def normalize_skill_policy(value: str | None, default: str = "optional") -> str:
    normalized = str(value or "").strip().lower()
    if normalized in VALID_SKILL_POLICIES:
        return normalized
    fallback = str(default or "optional").strip().lower()
    return fallback if fallback in VALID_SKILL_POLICIES else "optional"


def role_skill_requirements(role: str) -> tuple[str, list[str]]:
    normalized_role = str(role).strip().lower()
    policy = normalize_skill_policy(ROLE_SKILL_POLICY.get(normalized_role), default="optional")
    required_skills = [str(item).strip() for item in ROLE_REQUIRED_SKILLS.get(normalized_role, []) if str(item).strip()]
    if policy == "required" and not required_skills:
        required_skills = [f"{normalized_role}-workflow-skill"] if normalized_role else []
    return policy, required_skills


def parse_card_list(value: str | None) -> list[str]:
    raw = str(value or "").strip()
    if not raw or raw.lower() == "none":
        return []
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    items = [item.strip().strip("'\"") for item in raw.split(",")]
    return [item for item in items if item]


def guard_reason_from_findings(findings: list[dict]) -> str:
    reasons: list[str] = []
    for item in findings:
        code = str(item.get("code") or "").strip()
        mapped = STATE_VALIDATION_GUARD_REASONS.get(code, "State validation guard blocked autonomous execution.")
        if mapped not in reasons:
            reasons.append(mapped)
    if not reasons:
        return "State validation guard blocked autonomous execution."
    if len(reasons) == 1:
        return reasons[0]
    return "Multiple state-validation guards are active: " + "; ".join(reasons)


def task_card_text(
    project_root: Path,
    step: WorkflowStep,
    task_id: str,
    session_key: str | None = None,
    task_round_id: str | None = None,
) -> str:
    dispatch_mode = "send" if session_key else "spawn"
    skill_policy, required_skills = role_skill_requirements(step.role)
    required_skills_value = ", ".join(required_skills) if required_skills else "none"
    handoff_path = f"ai/handoff/{step.role}/active/{task_id}.md"
    goal = f"Execute workflow step `{step.id}` for governed delivery."
    required_reads = "\n".join(
        [
            "ai/state/START_HERE.md",
            "ai/state/project-handoff.md",
            "docs/ANTI-DRIFT-RUNBOOK.md",
        ]
    )
    anti_drift_protocol = "\n".join(
        [
            "Stay inside allowed_paths and the current workflow_step_id.",
            "Do not widen scope or skip plan, review, or gate stages.",
            "If requirements, state, or handoff conflict, stop and report blockers instead of guessing.",
        ]
    )
    acceptance = "Produce the required outputs, update the handoff, and report blockers explicitly."
    expected = ", ".join(step.outputs) if step.outputs else "updated handoff and step completion summary"
    resource_constraints = task_card_resource_context(project_root)
    return f"""# Task Card

- task_id: {task_id}
- target_agent: {step.role}
- target_agent_id: {step.agent_id}
- dispatch_mode: {dispatch_mode}
- cleanup_policy: {'keep' if session_key else 'delete'}
- session_key: {session_key or ''}
- return_to: orchestrator
- title: Workflow step {step.id}
- goal:
  {goal}
- required_reads:
  {required_reads}
- anti_drift_protocol:
  {anti_drift_protocol}
- allowed_paths: {ROLE_ALLOWED_PATHS.get(step.role, 'src,tests,docs,ai')}
- forbidden_paths: .git,.env,node_modules,__pycache__
- dependencies:
  {', '.join(step.depends_on) if step.depends_on else 'none'}
- acceptance:
  {acceptance}
- handoff_path: {handoff_path}
- expected_output:
  {expected}
- review_required: yes
- upstream_dependencies:
  {', '.join(step.depends_on) if step.depends_on else 'none'}
- downstream_reviewers:
  orchestrator
- testing_requirement:
  {ROLE_TESTING.get(step.role, 'follow project testing guidelines')}
- resource_constraints:
  {resource_constraints}
- workflow_step_id: {step.id}
- task_round_id: {task_round_id or ''}
- skill_policy: {skill_policy}
- required_skills: {required_skills_value}
- completion_schema_version: {DEFAULT_COMPLETION_SCHEMA_VERSION}
- priority: P1
"""


def build_payload_from_card(card_path: Path) -> tuple[dict, dict]:
    from build_dispatch_payload import parse_task_card, validate_agent_id

    card = parse_task_card(card_path)
    agent_id = validate_agent_id(card.get("target_agent_id") or card.get("target_agent"))
    mode = card.get("dispatch_mode", "spawn").strip() or "spawn"
    session_key = card.get("session_key", "").strip()
    if mode == "send" and not session_key:
        mode = "spawn"
    if mode == "spawn":
        payload = {
            "task": build_prompt(card),
            "runtime": "subagent",
            "agentId": agent_id,
            "mode": "run",
            "cleanup": "keep" if card.get("cleanup_policy", "").lower() == "keep" else "delete",
        }
    else:
        payload = {
            "sessionKey": session_key,
            "agentId": agent_id,
            "message": build_prompt(card),
        }
    return card, payload


def active_task_count(state: dict) -> int:
    return sum(1 for task in state.get("active_tasks", []) if str(task.get("status", "")).strip().lower() in ACTIVE_TASK_STATUSES)


def pending_outbox_count(project_root: Path) -> int:
    outbox_dir = project_root / "ai" / "runtime" / "outbox"
    if not outbox_dir.exists():
        return 0
    return sum(1 for path in outbox_dir.glob("*.json") if path.is_file())


def formal_department_review_guard(project_root: Path) -> dict[str, Any] | None:
    report = validate_state(project_root)
    findings = [item for item in report.get("findings", []) if item.get("code") in FORMAL_DEPARTMENT_REVIEW_GUARD_CODES]
    if not findings:
        return None
    reports_dir = project_root / "ai" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at": utc_now(),
        "status": "blocked",
        "reason": guard_reason_from_findings(findings),
        "findings": findings,
        "state_validation": report,
    }
    json_path = reports_dir / "department-review-source-guard.json"
    md_path = reports_dir / "department-review-source-guard.md"
    write_json(json_path, payload)
    lines = [
        "# State Validation Guard",
        "",
        f"- created_at: {payload['created_at']}",
        f"- status: {payload['status']}",
        f"- reason: {payload['reason']}",
        "",
        "## Blocking Findings",
        "",
    ]
    lines.extend(f"- `{item.get('code', 'unknown')}`: {item.get('message', '')}" for item in findings)
    lines.extend(["", "## Full State Validation", "", render_state_validation_markdown(report).rstrip()])
    write_text(md_path, "\n".join(lines))
    payload["report_path"] = str(md_path.resolve())
    payload["report_path_json"] = str(json_path.resolve())
    return payload


def run(project_root: Path, max_dispatch: int = 7, transport: str | None = None) -> dict:
    control = ensure_control_state(project_root)
    if control.get("automation_mode") == "paused":
        return {
            "status": "paused",
            "message": "Automation is paused. Resume autonomy before dispatching new work.",
            "automation_mode": "paused",
        }

    ensure_registry_schema(project_root)
    state_path = project_root / "ai" / "state" / "orchestrator-state.json"
    state = require_valid_json(state_path, "ai/state/orchestrator-state.json")
    ensure_dual_review_state(state)
    if str(state.get("current_status", "")).strip().lower() == "await-customer-decision":
        report_path = project_root / "ai" / "reports" / "customer-decision-required.md"
        return {
            "status": "customer-decision-required",
            "message": "Customer decision is required before autonomous execution can continue.",
            "report_path": str(report_path.resolve()) if report_path.exists() else "",
        }
    review_guard = formal_department_review_guard(project_root)
    if review_guard is not None:
        return {
            "status": "state-validation-blocked",
            "message": review_guard["reason"],
            "report_path": review_guard["report_path"],
            "finding_codes": [item.get("code", "") for item in review_guard["findings"]],
        }
    resource_gate = evaluate_runtime_constraints(project_root, state)
    if resource_gate.get("status") != "ok":
        return {
            "status": "resource-input-required",
            "message": resource_gate.get("message", ""),
            "report_path": resource_gate.get("report_path", ""),
        }
    workflow = load_workflow(project_root)
    progress = ensure_workflow_progress(state)
    round_state = record_round_progress(project_root, state)
    task_round_id = str(round_state.get("current_round_id") or "")
    candidates = ready_steps(workflow, state)[:max_dispatch]

    runtime_prompts = project_root / "ai" / "prompts" / "dispatch"
    runtime_prompts.mkdir(parents=True, exist_ok=True)

    dispatches: list[dict] = []
    accepted_dispatches: list[dict] = []
    local_results: list[dict] = []
    rollover_blockers: list[dict] = []
    if not candidates:
        waiting_tasks = active_task_count(state)
        queued_dispatches = pending_outbox_count(project_root)
        if waiting_tasks or queued_dispatches:
            state["next_owner"] = "orchestrator"
            if waiting_tasks and queued_dispatches:
                state["next_action"] = "Await completion from active tasks and delivery of pending dispatch envelopes before dispatching the next step."
            elif waiting_tasks:
                state["next_action"] = "Await completion from active tasks before dispatching the next step."
            else:
                state["next_action"] = "Deliver pending dispatch envelopes before dispatching the next step."
            write_json(state_path, state)
            return {
                "status": "waiting-on-active-work",
                "message": "No ready workflow steps yet. Waiting for active work to finish before dispatching more.",
                "active_task_count": waiting_tasks,
                "pending_dispatch_count": queued_dispatches,
                "workflow": workflow.name,
            }
        rollover = create_rollover(project_root)
        return {
            "status": "idle",
            "message": "No ready workflow steps. Generated rollover package instead.",
            "rollover_report": str((project_root / "ai" / "reports" / "orchestrator-rollover.md").resolve()),
            "resume_prompt": rollover.get("resume_prompt", ""),
        }

    for step in candidates:
        task_id = next_task_id(step)
        if is_local_orchestrator_step(step):
            local_result = execute_local_step(project_root, step, task_id)
            dispatches.append(local_result)
            local_results.append(local_result)
            state = require_valid_json(state_path, "ai/state/orchestrator-state.json")
            progress = ensure_workflow_progress(state)
            continue

        reuse = session_reuse_decision(project_root, step.agent_id, workflow_name=workflow.name)
        if reuse.get("should_retire") and reuse.get("record", {}).get("session_key"):
            close_payload = apply_close(
                project_root,
                step.agent_id,
                f"Automatic session rollover before `{step.id}`: {reuse.get('reason', 'reuse budget exceeded')}.",
                force_native=True,
            )
            if not close_payload.get("retired"):
                dispatch_record = {
                    "task_id": task_id,
                    "step_id": step.id,
                    "role": step.role,
                    "card_path": None,
                    "dispatch_id": "",
                    "transport": "native-close",
                    "status": "session-rollover-blocked",
                    "reason": close_payload.get("native_close_blocked_reason")
                    or f"Unable to safely retire the existing `{step.agent_id}` session.",
                }
                dispatches.append(dispatch_record)
                rollover_blockers.append(dispatch_record)
                continue
            reuse = session_reuse_decision(project_root, step.agent_id, workflow_name=workflow.name)
        session_key = str(reuse.get("session_key") or "") or None
        card_path = runtime_prompts / f"{slugify(task_id)}.md"
        write_text(
            card_path,
            task_card_text(project_root, step, task_id, session_key=session_key, task_round_id=task_round_id or None),
        )
        card, payload = build_payload_from_card(card_path)
        mode = "send" if session_key else "spawn"
        envelope = dispatch_payload(project_root, payload, mode, step.agent_id, task_card=card_path, transport=transport)

        dispatch_record = {
            "task_id": task_id,
            "step_id": step.id,
            "role": step.role,
            "card_path": str(card_path),
            "dispatch_id": envelope["dispatch_id"],
            "transport": envelope["transport"],
            "status": envelope["status"],
        }
        dispatches.append(dispatch_record)

        if envelope["status"] not in DISPATCHED_ENVELOPE_STATUSES:
            continue

        handoff_relative = f"ai/handoff/{step.role}/active/{task_id}.md"
        state.setdefault("active_tasks", []).append(
            {
                "task_id": task_id,
                "role": step.role,
                "status": "in-progress",
                "handoff_path": handoff_relative,
                "workflow_step_id": step.id,
                "task_round_id": task_round_id or None,
                "skill_policy": normalize_skill_policy(card.get("skill_policy"), default=ROLE_SKILL_POLICY.get(step.role, "optional")),
                "required_skills": parse_card_list(card.get("required_skills")),
                "completion_schema_version": str(card.get("completion_schema_version") or DEFAULT_COMPLETION_SCHEMA_VERSION),
            }
        )
        if step.id not in progress["dispatched_steps"]:
            progress["dispatched_steps"].append(step.id)
        existing_record = ensure_registry_schema(project_root).get(step.agent_id, {})
        upsert_session(
            project_root,
            step.agent_id,
            session_key=session_key,
            status="active",
            last_task_id=task_id,
            last_step_id=step.id,
            handoff_path=handoff_relative,
            active_workflow=state.get("current_workflow"),
            dispatch_count=int(existing_record.get("dispatch_count") or 0) + 1,
            consecutive_invalid_completions=0 if not session_key else int(existing_record.get("consecutive_invalid_completions") or 0),
            drift_status="clear" if not session_key else str(existing_record.get("drift_status") or "clear"),
            rebuild_required=False if not session_key else bool(existing_record.get("rebuild_required")),
            rebuild_reason=None if not session_key else existing_record.get("rebuild_reason"),
            last_rebuild_at=utc_now() if reuse.get("should_retire") else existing_record.get("last_rebuild_at"),
            clear_fields=["last_invalid_completion_at", "last_invalid_completion_reason"] if not session_key else None,
        )
        accepted_dispatches.append(dispatch_record)

    if accepted_dispatches:
        state["next_owner"] = "orchestrator" if len(accepted_dispatches) > 1 else accepted_dispatches[0]["role"]
        state["next_action"] = "Await completion from dispatched workflow steps and consume them via completion_consumer.py."
    elif local_results:
        state = require_valid_json(state_path, "ai/state/orchestrator-state.json")
    elif rollover_blockers:
        blocked_roles = ", ".join(sorted({item["role"] for item in rollover_blockers}))
        state["next_owner"] = "orchestrator"
        state["next_action"] = (
            f"Session rollover is blocked for {blocked_roles}. Resolve native close issues before dispatching replacement work."
        )
    else:
        state["next_owner"] = "orchestrator"
        state["next_action"] = "Dispatch transport did not accept any workflow steps. Fix the transport and rerun run_orchestrator.py."
    state["last_dispatch_batch"] = {
        "created_at": utc_now(),
        "items": dispatches,
    }
    write_json(state_path, state)

    reports_dir = project_root / "ai" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    write_json(reports_dir / "orchestrator-dispatch-plan.json", {"workflow": workflow.name, "dispatches": dispatches})
    write_text(
        reports_dir / "orchestrator-dispatch-plan.md",
        "# Orchestrator Dispatch Plan\n\n"
        + "\n".join(f"- {item['step_id']} -> {item['role']} ({item['status']})" for item in dispatches)
        + "\n",
    )

    return {
        "status": (
            "dispatched"
            if accepted_dispatches
            else ("local-progress" if local_results else ("session-rollover-blocked" if rollover_blockers else "pending-transport"))
        ),
        "workflow": workflow.name,
        "dispatch_count": len(accepted_dispatches),
        "attempted_dispatch_count": len(dispatches),
        "local_completion_count": len(local_results),
        "dispatches": dispatches,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one orchestrator dispatch cycle for the current workflow.")
    parser.add_argument("project_root", help="Target project root")
    parser.add_argument("--max-dispatch", type=int, default=7, help="Maximum number of ready steps to dispatch in one cycle")
    parser.add_argument("--transport", choices=["outbox", "command"], help="Override the dispatch transport")
    args = parser.parse_args()

    payload = run(Path(args.project_root).resolve(), max_dispatch=args.max_dispatch, transport=args.transport)
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
