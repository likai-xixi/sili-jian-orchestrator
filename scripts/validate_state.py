from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import read_json, read_text, text_has_placeholders


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


def extract_markdown_value(markdown: str, label: str) -> str:
    prefix = f"- {label}:"
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped[len(prefix):].strip()
    return ""


def normalize(value: str) -> str:
    return " ".join(value.strip().lower().replace("_", "-").split())


def render_markdown(report: dict) -> str:
    findings = report.get("findings", [])
    errors = [item for item in findings if item.get("severity") == "error"]
    warnings = [item for item in findings if item.get("severity") == "warning"]
    notes = [item for item in findings if item.get("severity") not in {"error", "warning"}]

    lines = [
        "# State Validation Report",
        "",
        f"- project_root: {report.get('project_root', '')}",
        f"- state_consistent: {'yes' if report.get('state_consistent') else 'no'}",
        f"- current_phase: {report.get('current_phase', '')}",
        f"- current_status: {report.get('current_status', '')}",
        f"- current_workflow: {report.get('current_workflow', '')}",
        f"- active_task_count: {report.get('active_task_count', 0)}",
        f"- finding_count: {len(findings)}",
        f"- error_count: {len(errors)}",
        f"- warning_count: {len(warnings)}",
        "",
    ]

    def append_group(title: str, items: list[dict]) -> None:
        lines.append(f"## {title}")
        lines.append("")
        if not items:
            lines.append("- none")
            lines.append("")
            return
        for item in items:
            lines.append(f"- `{item.get('code', 'unknown')}`: {item.get('message', '')}")
        lines.append("")

    append_group("Errors", errors)
    append_group("Warnings", warnings)
    append_group("Notes", notes)
    return "\n".join(lines).rstrip() + "\n"


def validate(project_root: Path) -> dict:
    state_dir = project_root / "ai" / "state"
    handoff_root = project_root / "ai" / "handoff"

    orchestrator_path = state_dir / "orchestrator-state.json"
    start_here_path = state_dir / "START_HERE.md"
    handoff_path = state_dir / "project-handoff.md"
    takeover_path = state_dir / "project-takeover.md"
    legacy_orchestrator_path = state_dir / "orchestrator_state.json"

    orchestrator = read_json(orchestrator_path)
    start_here_text = read_text(start_here_path)
    handoff_text = read_text(handoff_path)
    takeover_text = read_text(takeover_path)
    current_workflow = normalize(str(orchestrator.get("current_workflow", ""))) if orchestrator else ""
    current_status = normalize(str(orchestrator.get("current_status", ""))) if orchestrator else ""
    next_owner = normalize(str(orchestrator.get("next_owner", ""))) if orchestrator else ""

    findings: list[dict[str, str]] = []

    if not orchestrator:
        findings.append(
            {
                "code": "missing_orchestrator_state",
                "severity": "error",
                "message": "ai/state/orchestrator-state.json is missing or unreadable.",
            }
        )

    if not start_here_text:
        findings.append(
            {
                "code": "missing_start_here",
                "severity": "error",
                "message": "ai/state/START_HERE.md is missing.",
            }
        )

    if not handoff_text:
        findings.append(
            {
                "code": "missing_project_handoff",
                "severity": "error",
                "message": "ai/state/project-handoff.md is missing.",
            }
        )

    if legacy_orchestrator_path.exists():
        findings.append(
            {
                "code": "duplicate_orchestrator_state",
                "severity": "warning",
                "message": "Found legacy ai/state/orchestrator_state.json alongside ai/state/orchestrator-state.json.",
            }
        )

    if orchestrator and start_here_text:
        workflow_state = normalize(str(orchestrator.get("current_workflow", "")))
        workflow_start_here = normalize(extract_markdown_value(start_here_text, "Workflow"))
        if workflow_state and workflow_start_here and workflow_state != workflow_start_here:
            findings.append(
                {
                    "code": "workflow_mismatch_start_here",
                    "severity": "error",
                    "message": f"START_HERE workflow '{workflow_start_here}' does not match orchestrator-state workflow '{workflow_state}'.",
                }
            )

        status_state = normalize(str(orchestrator.get("current_status", "")))
        status_start_here = normalize(extract_markdown_value(start_here_text, "Stage"))
        if status_state and status_start_here and status_state != status_start_here:
            findings.append(
                {
                    "code": "status_mismatch_start_here",
                    "severity": "error",
                    "message": f"START_HERE stage '{status_start_here}' does not match orchestrator-state status '{status_state}'.",
                }
            )

        next_owner_state = normalize(str(orchestrator.get("next_owner", "")))
        next_owner_start_here = normalize(extract_markdown_value(start_here_text, "Next owner"))
        if next_owner_state and next_owner_start_here and next_owner_state != next_owner_start_here:
            findings.append(
                {
                    "code": "next_owner_mismatch_start_here",
                    "severity": "warning",
                    "message": f"START_HERE next owner '{next_owner_start_here}' does not match orchestrator-state next owner '{next_owner_state}'.",
                }
            )

    if orchestrator and handoff_text:
        workflow_state = normalize(str(orchestrator.get("current_workflow", "")))
        workflow_handoff = normalize(extract_markdown_value(handoff_text, "Current workflow"))
        if workflow_state and workflow_handoff and workflow_state != workflow_handoff:
            findings.append(
                {
                    "code": "workflow_mismatch_handoff",
                    "severity": "error",
                    "message": f"project-handoff workflow '{workflow_handoff}' does not match orchestrator-state workflow '{workflow_state}'.",
                }
            )

        phase_state = normalize(str(orchestrator.get("current_phase", "")))
        phase_handoff = normalize(extract_markdown_value(handoff_text, "Current phase"))
        if phase_state and phase_handoff and phase_state != phase_handoff:
            findings.append(
                {
                    "code": "phase_mismatch_handoff",
                    "severity": "error",
                    "message": f"project-handoff phase '{phase_handoff}' does not match orchestrator-state phase '{phase_state}'.",
                }
            )

        status_state = normalize(str(orchestrator.get("current_status", "")))
        status_handoff = normalize(extract_markdown_value(handoff_text, "Status"))
        if status_state and status_handoff and status_state != status_handoff:
            findings.append(
                {
                    "code": "status_mismatch_handoff",
                    "severity": "error",
                    "message": f"project-handoff status '{status_handoff}' does not match orchestrator-state status '{status_state}'.",
                }
            )

        next_owner_state = normalize(str(orchestrator.get("next_owner", "")))
        next_owner_handoff = normalize(extract_markdown_value(handoff_text, "Next owner"))
        if next_owner_state and next_owner_handoff and next_owner_state != next_owner_handoff:
            findings.append(
                {
                    "code": "next_owner_mismatch_handoff",
                    "severity": "warning",
                    "message": f"project-handoff next owner '{next_owner_handoff}' does not match orchestrator-state next owner '{next_owner_state}'.",
                }
            )

    in_progress_roles: list[str] = []
    for task in orchestrator.get("active_tasks", []) if orchestrator else []:
        task_id = str(task.get("task_id", "")).strip()
        role = str(task.get("role", "")).strip()
        task_status = normalize(str(task.get("status", "")))
        handoff_ref = str(task.get("handoff_path", "")).strip()
        if not task_id:
            findings.append(
                {
                    "code": "active_task_missing_id",
                    "severity": "error",
                    "message": "An active task is missing task_id.",
                }
            )
            continue
        if not handoff_ref:
            findings.append(
                {
                    "code": "active_task_missing_handoff",
                    "severity": "error",
                    "message": f"Active task '{task_id}' is missing handoff_path.",
                }
            )
            continue

        handoff_path = Path(handoff_ref)
        if not handoff_path.is_absolute():
            handoff_path = project_root / handoff_path

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
        handoff_task_id = extract_markdown_value(handoff_text, "task_id")
        if handoff_task_id and normalize(handoff_task_id) != normalize(task_id):
            findings.append(
                {
                    "code": "active_task_handoff_id_mismatch",
                    "severity": "error",
                    "message": f"Handoff task_id '{handoff_task_id}' does not match active task '{task_id}'.",
                }
            )

        if role:
            handoff_role = extract_markdown_value(handoff_text, "role")
            if handoff_role and normalize(handoff_role) != normalize(role):
                findings.append(
                    {
                        "code": "active_task_handoff_role_mismatch",
                        "severity": "warning",
                        "message": f"Handoff role '{handoff_role}' does not match active task role '{role}'.",
                    }
                )

        handoff_status = normalize(extract_markdown_value(handoff_text, "status"))
        if task_status and handoff_status and handoff_status != task_status:
            findings.append(
                {
                    "code": "active_task_handoff_status_mismatch",
                    "severity": "warning",
                    "message": f"Handoff status '{handoff_status}' does not match active task status '{task_status}' for '{task_id}'.",
                }
            )

        workflow_step_id = normalize(extract_markdown_value(handoff_text, "workflow_step_id") or str(task.get("workflow_step_id", "")))
        allowed_steps = WORKFLOW_STEP_IDS.get(current_workflow)
        if workflow_step_id and allowed_steps and workflow_step_id not in allowed_steps:
            findings.append(
                {
                    "code": "workflow_step_not_in_current_workflow",
                    "severity": "warning",
                    "message": f"Workflow step '{workflow_step_id}' does not belong to current workflow '{current_workflow}'.",
                }
            )

        if task_status == "in-progress" and role:
            in_progress_roles.append(normalize(role))

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

    unique_in_progress_roles = sorted(set(role for role in in_progress_roles if role))
    if next_owner and unique_in_progress_roles and next_owner not in unique_in_progress_roles:
        findings.append(
            {
                "code": "next_owner_not_in_progress_role",
                "severity": "warning",
                "message": f"next_owner '{next_owner}' does not match the current in-progress role(s): {', '.join(unique_in_progress_roles)}.",
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

    state_ok = not any(item["severity"] == "error" for item in findings)
    return {
        "project_root": str(project_root.resolve()),
        "state_consistent": state_ok,
        "current_phase": orchestrator.get("current_phase", "") if orchestrator else "",
        "current_status": orchestrator.get("current_status", "") if orchestrator else "",
        "current_workflow": orchestrator.get("current_workflow", "") if orchestrator else "",
        "active_task_count": len(orchestrator.get("active_tasks", [])) if orchestrator else 0,
        "findings": findings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate state, handoff, and active-task consistency for a governed project.")
    parser.add_argument("project_root", help="Target project root")
    parser.add_argument("--format", choices=["json", "markdown"], default="json", help="Output format")
    parser.add_argument("--output", help="Optional JSON output path")
    args = parser.parse_args()

    report = validate(Path(args.project_root).resolve())
    if args.format == "markdown":
        payload = render_markdown(report)
    else:
        payload = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(payload if payload.endswith("\n") else payload + "\n", encoding="utf-8")
    else:
        print(payload)


if __name__ == "__main__":
    main()
