from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import extract_field_value, read_json, read_text, text_has_placeholders


WORKFLOW_STEP_IDS = {
    "new-project": {
        "identify-project",
        "bootstrap-governance",
        "create-run-snapshot",
        "freeze-initial-plan",
        "plan-audit",
        "update-state-and-handoff",
    },
    "takeover-project": {
        "identify-project",
        "inspect-governance",
        "backfill-governance",
        "planning-repair",
        "backfill-tests",
        "update-state-and-handoff",
    },
    "resume-orchestrator": {
        "load-recovery-entry",
        "load-state-and-reports",
        "summarize-recovery",
        "resume-next-action",
    },
    "feature-delivery": {
        "plan-approved-batch",
        "libu2-implementation",
        "hubu-data-work",
        "gongbu-ui-work",
        "bingbu-test-pass",
        "libu-documentation",
        "xingbu-release-check",
        "department-review",
        "duchayuan-final-audit",
        "state-and-summary-update",
    },
}


def normalize(value: str) -> str:
    return " ".join(value.strip().lower().replace("_", "-").split())


def render_markdown(report: dict) -> str:
    findings = report.get("findings", [])
    errors = [item for item in findings if item.get("severity") == "error"]
    warnings = [item for item in findings if item.get("severity") == "warning"]

    lines = [
        "# State Validation Report",
        "",
        f"- project_root: {report.get('project_root', '')}",
        f"- state_consistent: {'yes' if report.get('state_consistent') else 'no'}",
        f"- current_phase: {report.get('current_phase', '')}",
        f"- current_status: {report.get('current_status', '')}",
        f"- current_workflow: {report.get('current_workflow', '')}",
        f"- active_task_count: {report.get('active_task_count', 0)}",
        "",
        "## Errors",
        "",
    ]
    if errors:
        lines.extend(f"- `{item['code']}`: {item['message']}" for item in errors)
    else:
        lines.append("- none")
    lines.extend(["", "## Warnings", ""])
    if warnings:
        lines.extend(f"- `{item['code']}`: {item['message']}" for item in warnings)
    else:
        lines.append("- none")
    return "\n".join(lines).rstrip() + "\n"


def validate(project_root: Path) -> dict:
    state_dir = project_root / "ai" / "state"

    orchestrator = read_json(state_dir / "orchestrator-state.json")
    start_here_text = read_text(state_dir / "START_HERE.md")
    handoff_text = read_text(state_dir / "project-handoff.md")
    takeover_text = read_text(state_dir / "project-takeover.md")
    findings: list[dict[str, str]] = []

    if not orchestrator:
        findings.append(
            {"code": "missing_orchestrator_state", "severity": "error", "message": "ai/state/orchestrator-state.json is missing or unreadable."}
        )

    if not start_here_text:
        findings.append({"code": "missing_start_here", "severity": "error", "message": "ai/state/START_HERE.md is missing."})

    if not handoff_text:
        findings.append({"code": "missing_project_handoff", "severity": "error", "message": "ai/state/project-handoff.md is missing."})

    legacy_state = state_dir / "orchestrator_state.json"
    if legacy_state.exists():
        findings.append(
            {
                "code": "duplicate_orchestrator_state",
                "severity": "warning",
                "message": "Found legacy ai/state/orchestrator_state.json alongside ai/state/orchestrator-state.json.",
            }
        )

    current_workflow = normalize(str(orchestrator.get("current_workflow", ""))) if orchestrator else ""
    current_status = normalize(str(orchestrator.get("current_status", ""))) if orchestrator else ""
    next_owner = normalize(str(orchestrator.get("next_owner", ""))) if orchestrator else ""

    if orchestrator and start_here_text:
        if normalize(extract_field_value(start_here_text, "Workflow")) not in {"", current_workflow}:
            findings.append(
                {
                    "code": "workflow_mismatch_start_here",
                    "severity": "error",
                    "message": "START_HERE workflow does not match orchestrator-state workflow.",
                }
            )
        if normalize(extract_field_value(start_here_text, "Stage")) not in {"", current_status}:
            findings.append(
                {
                    "code": "status_mismatch_start_here",
                    "severity": "error",
                    "message": "START_HERE stage does not match orchestrator-state status.",
                }
            )
        owner = normalize(extract_field_value(start_here_text, "Next owner"))
        if owner and owner != next_owner:
            findings.append(
                {
                    "code": "next_owner_mismatch_start_here",
                    "severity": "warning",
                    "message": "START_HERE next owner does not match orchestrator-state next owner.",
                }
            )

    if orchestrator and handoff_text:
        if normalize(extract_field_value(handoff_text, "Current workflow")) not in {"", current_workflow}:
            findings.append(
                {
                    "code": "workflow_mismatch_handoff",
                    "severity": "error",
                    "message": "project-handoff workflow does not match orchestrator-state workflow.",
                }
            )
        if normalize(extract_field_value(handoff_text, "Status")) not in {"", current_status}:
            findings.append(
                {
                    "code": "status_mismatch_handoff",
                    "severity": "error",
                    "message": "project-handoff status does not match orchestrator-state status.",
                }
            )
        owner = normalize(extract_field_value(handoff_text, "Next owner"))
        if owner and owner != next_owner:
            findings.append(
                {
                    "code": "next_owner_mismatch_handoff",
                    "severity": "warning",
                    "message": "project-handoff next owner does not match orchestrator-state next owner.",
                }
            )

    in_progress_roles: list[str] = []
    for task in orchestrator.get("active_tasks", []) if orchestrator else []:
        task_id = str(task.get("task_id", "")).strip()
        role = normalize(str(task.get("role", "")))
        status = normalize(str(task.get("status", "")))
        handoff_ref = str(task.get("handoff_path", "")).strip()
        workflow_step = normalize(str(task.get("workflow_step_id", "")))
        if not task_id:
            findings.append({"code": "active_task_missing_id", "severity": "error", "message": "An active task is missing task_id."})
            continue
        if not handoff_ref:
            findings.append({"code": "active_task_missing_handoff", "severity": "error", "message": f"Active task '{task_id}' is missing handoff_path."})
            continue
        handoff_path = project_root / handoff_ref if not Path(handoff_ref).is_absolute() else Path(handoff_ref)
        if not handoff_path.exists():
            findings.append(
                {
                    "code": "active_task_handoff_missing_file",
                    "severity": "error",
                    "message": f"Active task '{task_id}' points to a missing handoff file: {handoff_path}.",
                }
            )
            continue
        handoff_text = read_text(handoff_path)
        handoff_task_id = extract_field_value(handoff_text, "task_id")
        if handoff_task_id and normalize(handoff_task_id) != normalize(task_id):
            findings.append(
                {
                    "code": "active_task_handoff_id_mismatch",
                    "severity": "error",
                    "message": f"Handoff task_id '{handoff_task_id}' does not match active task '{task_id}'.",
                }
            )
        handoff_role = normalize(extract_field_value(handoff_text, "role"))
        if handoff_role and handoff_role != role:
            findings.append(
                {
                    "code": "active_task_handoff_role_mismatch",
                    "severity": "warning",
                    "message": f"Handoff role '{handoff_role}' does not match active task role '{role}'.",
                }
            )
        handoff_status = normalize(extract_field_value(handoff_text, "status"))
        if handoff_status and handoff_status != status:
            findings.append(
                {
                    "code": "active_task_handoff_status_mismatch",
                    "severity": "warning",
                    "message": f"Handoff status '{handoff_status}' does not match active task status '{status}' for '{task_id}'.",
                }
            )
        allowed_steps = WORKFLOW_STEP_IDS.get(current_workflow)
        if workflow_step and allowed_steps and workflow_step not in allowed_steps:
            findings.append(
                {
                    "code": "workflow_step_not_in_current_workflow",
                    "severity": "warning",
                    "message": f"Workflow step '{workflow_step}' does not belong to current workflow '{current_workflow}'.",
                }
            )
        if status == "in-progress" and role:
            in_progress_roles.append(role)

    if current_workflow == "takeover-project":
        if not takeover_text:
            findings.append(
                {
                    "code": "missing_project_takeover",
                    "severity": "error",
                    "message": "Current workflow is takeover-project but ai/state/project-takeover.md is missing.",
                }
            )
        elif text_has_placeholders(takeover_text):
            findings.append(
                {
                    "code": "project_takeover_still_template",
                    "severity": "error",
                    "message": "project-takeover.md still contains placeholder content in takeover mode.",
                }
            )

    unique_roles = sorted(set(in_progress_roles))
    if next_owner and unique_roles and next_owner not in unique_roles:
        findings.append(
            {
                "code": "next_owner_not_in_progress_role",
                "severity": "warning",
                "message": f"next_owner '{next_owner}' does not match the current in-progress role(s): {', '.join(unique_roles)}.",
            }
        )

    execution_allowed = bool(orchestrator.get("execution_allowed", False)) if orchestrator else False
    testing_allowed = bool(orchestrator.get("testing_allowed", False)) if orchestrator else False
    release_allowed = bool(orchestrator.get("release_allowed", False)) if orchestrator else False
    if execution_allowed and current_status in {"draft", "planning", "department-approval"}:
        findings.append(
            {
                "code": "execution_allowed_too_early",
                "severity": "error",
                "message": f"execution_allowed is true while current_status is still '{current_status}'.",
            }
        )
    if testing_allowed and not execution_allowed:
        findings.append(
            {
                "code": "testing_allowed_without_execution",
                "severity": "warning",
                "message": "testing_allowed is true while execution_allowed is false.",
            }
        )
    if release_allowed and not testing_allowed:
        findings.append(
            {
                "code": "release_allowed_without_testing",
                "severity": "warning",
                "message": "release_allowed is true while testing_allowed is false.",
            }
        )

    return {
        "project_root": str(project_root.resolve()),
        "state_consistent": not any(item["severity"] == "error" for item in findings),
        "current_phase": orchestrator.get("current_phase", "") if orchestrator else "",
        "current_status": orchestrator.get("current_status", "") if orchestrator else "",
        "current_workflow": orchestrator.get("current_workflow", "") if orchestrator else "",
        "active_task_count": len(orchestrator.get("active_tasks", [])) if orchestrator else 0,
        "findings": findings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate project-local governance state.")
    parser.add_argument("project_root")
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    parser.add_argument("--output")
    args = parser.parse_args()

    report = validate(Path(args.project_root).resolve())
    payload = render_markdown(report) if args.format == "markdown" else json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(payload if payload.endswith("\n") else payload + "\n", encoding="utf-8")
    else:
        print(payload)


if __name__ == "__main__":
    main()
