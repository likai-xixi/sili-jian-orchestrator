from __future__ import annotations

import argparse
import json
from pathlib import Path

from automation_control import ensure_control_state
from build_dispatch_payload import build_prompt
from common import read_json, require_valid_json, utc_now, write_json, write_text
from context_rollover import create_rollover
from openclaw_adapter import dispatch_payload
from orchestrator_local_steps import execute_local_step, is_local_orchestrator_step
from session_registry import ensure_registry_schema, reusable_session_key, upsert_session
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


DISPATCHED_ENVELOPE_STATUSES = {"queued", "sent"}


def slugify(text: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in text).strip("-")


def next_task_id(step: WorkflowStep) -> str:
    stamp = utc_now().replace(":", "").replace("+00:00", "Z")
    return f"{step.id.upper().replace('-', '_')}-{stamp}"


def task_card_text(step: WorkflowStep, task_id: str, session_key: str | None = None) -> str:
    dispatch_mode = "send" if session_key else "spawn"
    handoff_path = f"ai/handoff/{step.role}/active/{task_id}.md"
    goal = f"Execute workflow step `{step.id}` for governed delivery."
    acceptance = "Produce the required outputs, update the handoff, and report blockers explicitly."
    expected = ", ".join(step.outputs) if step.outputs else "updated handoff and step completion summary"
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
- workflow_step_id: {step.id}
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


def run(project_root: Path, max_dispatch: int = 3, transport: str | None = None) -> dict:
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
    if str(state.get("current_status", "")).strip().lower() == "await-customer-decision":
        report_path = project_root / "ai" / "reports" / "customer-decision-required.md"
        return {
            "status": "customer-decision-required",
            "message": "Customer decision is required before autonomous execution can continue.",
            "report_path": str(report_path.resolve()) if report_path.exists() else "",
        }
    workflow = load_workflow(project_root)
    progress = ensure_workflow_progress(state)
    candidates = ready_steps(workflow, state)[:max_dispatch]

    runtime_prompts = project_root / "ai" / "prompts" / "dispatch"
    runtime_prompts.mkdir(parents=True, exist_ok=True)

    dispatches: list[dict] = []
    accepted_dispatches: list[dict] = []
    local_results: list[dict] = []
    if not candidates:
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
            state = read_json(state_path)
            progress = ensure_workflow_progress(state)
            continue

        session_key = reusable_session_key(project_root, step.agent_id, workflow_name=workflow.name)
        card_path = runtime_prompts / f"{slugify(task_id)}.md"
        write_text(card_path, task_card_text(step, task_id, session_key=session_key))
        _, payload = build_payload_from_card(card_path)
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
            }
        )
        if step.id not in progress["dispatched_steps"]:
            progress["dispatched_steps"].append(step.id)
        upsert_session(
            project_root,
            step.agent_id,
            session_key=session_key,
            status="active",
            last_task_id=task_id,
            last_step_id=step.id,
            handoff_path=handoff_relative,
            active_workflow=state.get("current_workflow"),
        )
        accepted_dispatches.append(dispatch_record)

    if accepted_dispatches:
        state["next_owner"] = "orchestrator" if len(accepted_dispatches) > 1 else accepted_dispatches[0]["role"]
        state["next_action"] = "Await completion from dispatched workflow steps and consume them via completion_consumer.py."
    elif local_results:
        state = read_json(state_path)
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
        "status": "dispatched" if accepted_dispatches else ("local-progress" if local_results else "pending-transport"),
        "workflow": workflow.name,
        "dispatch_count": len(accepted_dispatches),
        "attempted_dispatch_count": len(dispatches),
        "local_completion_count": len(local_results),
        "dispatches": dispatches,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one orchestrator dispatch cycle for the current workflow.")
    parser.add_argument("project_root", help="Target project root")
    parser.add_argument("--max-dispatch", type=int, default=3, help="Maximum number of ready steps to dispatch in one cycle")
    parser.add_argument("--transport", choices=["outbox", "command"], help="Override the dispatch transport")
    args = parser.parse_args()

    payload = run(Path(args.project_root).resolve(), max_dispatch=args.max_dispatch, transport=args.transport)
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
