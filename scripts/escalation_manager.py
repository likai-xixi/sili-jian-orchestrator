from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import read_json, read_text, utc_now, write_json, write_text
from validate_gates import validate as validate_gates


def add_finding(
    findings: list[dict[str, Any]],
    code: str,
    severity: str,
    message: str,
    source: str,
    action: str,
) -> None:
    findings.append(
        {
            "code": code,
            "severity": severity,
            "message": message,
            "source": source,
            "recommended_action": action,
        }
    )


def non_none_value(value: str) -> bool:
    normalized = value.strip().lower()
    return bool(normalized) and normalized not in {"none", "n/a", "na", "closed"}


def collect_state_findings(state: dict[str, Any], findings: list[dict[str, Any]]) -> None:
    for blocker in state.get("blockers", []):
        add_finding(
            findings,
            "state_blocker",
            "error",
            f"state blocker: {blocker}",
            "ai/state/orchestrator-state.json",
            "Clear the blocker or replan the current workflow step before resuming autonomous execution.",
        )

    last_dispatch = state.get("last_dispatch_batch", {}).get("items", [])
    for item in last_dispatch:
        status = str(item.get("status", ""))
        if status in {"failed", "queued-awaiting-command-config"}:
            add_finding(
                findings,
                "dispatch_issue",
                "error" if status == "failed" else "warning",
                f"dispatch issue: {item.get('step_id') or item.get('task_id')} -> {status}",
                "ai/state/orchestrator-state.json:last_dispatch_batch",
                "Repair transport configuration or re-dispatch the blocked step.",
            )


def collect_inbox_findings(project_root: Path, findings: list[dict[str, Any]]) -> None:
    inbox_summary = read_json(project_root / "ai" / "reports" / "inbox-watch-summary.json")
    if inbox_summary.get("failed_count"):
        add_finding(
            findings,
            "inbox_failures",
            "error",
            f"inbox processing failures: {inbox_summary.get('failed_count')}",
            "ai/reports/inbox-watch-summary.json",
            "Inspect failed inbox payloads and repair completion formatting before continuing.",
        )


def collect_evidence_findings(project_root: Path, findings: list[dict[str, Any]]) -> None:
    evidence = read_json(project_root / "ai" / "reports" / "evidence-summary.json")
    if evidence.get("recommendation") == "BLOCKER":
        for blocker in evidence.get("blockers", []):
            add_finding(
                findings,
                "evidence_blocker",
                "error",
                f"evidence blocker: {blocker}",
                "ai/reports/evidence-summary.json",
                "Resolve the failing verification before resuming the runtime loop.",
            )

    provider_summary = read_json(project_root / "ai" / "reports" / "provider-evidence-summary.json")
    for kind, payload in provider_summary.get("results", {}).items():
        status = str(payload.get("status", "SKIPPED"))
        summary = str(payload.get("summary", "")).strip()
        provider = str(payload.get("provider", "provider"))
        if status == "FAIL":
            add_finding(
                findings,
                f"{kind}_provider_failure",
                "error",
                f"{kind} provider failure from {provider}: {summary or 'provider reported failure'}",
                "ai/reports/provider-evidence-summary.json",
                f"Investigate the {kind} provider run and update the project reports once the external signal is green.",
            )
        elif status == "PASS_WITH_WARNING":
            add_finding(
                findings,
                f"{kind}_provider_warning",
                "warning",
                f"{kind} provider warning from {provider}: {summary or 'provider reported a non-final state'}",
                "ai/reports/provider-evidence-summary.json",
                f"Review the {kind} provider state before approving the next workflow transition.",
            )


def collect_gate_findings(project_root: Path, state: dict[str, Any], findings: list[dict[str, Any]]) -> None:
    gate_report = validate_gates(project_root)
    if gate_report.get("release_stage") and not gate_report.get("final_gate_passed"):
        add_finding(
            findings,
            "final_gate_failed",
            "error",
            "final gate failed during release-stage workflow",
            "ai/reports/gate-report.md",
            "Read gate-report.md and repair the failing final gate before continuing.",
        )
    elif not gate_report.get("phase_gate_passed") and str(state.get("current_status", "")).lower() in {"department-review", "final-audit", "accepted"}:
        add_finding(
            findings,
            "phase_gate_failed",
            "error",
            "phase gate failed during review-stage workflow",
            "ai/reports/gate-report.md",
            "Repair the missing review-stage artifacts or failing conclusions before continuing.",
        )


def collect_review_loop_findings(project_root: Path, state: dict[str, Any], findings: list[dict[str, Any]]) -> None:
    current_status = str(state.get("current_status", "")).strip().lower()
    if current_status == "cabinet-review":
        add_finding(
            findings,
            "cabinet_replan_required",
            "warning",
            "cross-review loop exceeded the pre-cabinet limit and now requires cabinet replan",
            "ai/state/orchestrator-state.json",
            "Route the batch through neige and duchayuan for replan before resuming implementation.",
        )
    elif current_status == "await-customer-decision":
        source = "ai/reports/customer-decision-required.md"
        if not (project_root / "ai" / "reports" / "customer-decision-required.md").exists():
            source = "ai/state/orchestrator-state.json"
        add_finding(
            findings,
            "customer_decision_required",
            "error",
            "customer decision required after post-cabinet review limit exceeded",
            source,
            "Send the customer decision report, explain the unresolved issues, and wait for explicit direction before resuming.",
        )


def collect_approval_conflicts(project_root: Path, findings: list[dict[str, Any]]) -> None:
    matrix_text = read_text(project_root / "ai" / "reports" / "department-approval-matrix.md")
    if not matrix_text:
        return

    for raw_line in matrix_text.splitlines():
        line = raw_line.strip()
        lowered = line.lower()
        if lowered.startswith("- conflicts needing arbitration:"):
            value = line.split(":", 1)[1].strip() if ":" in line else ""
            if non_none_value(value):
                add_finding(
                    findings,
                    "approval_conflict",
                    "error",
                    f"approval conflict needs arbitration: {value}",
                    "ai/reports/department-approval-matrix.md",
                    "Escalate the conflicting reviewer feedback and obtain an explicit arbitration decision.",
                )
        elif lowered.startswith("- closure:"):
            value = line.split(":", 1)[1].strip() if ":" in line else ""
            if non_none_value(value):
                add_finding(
                    findings,
                    "approval_deadlock",
                    "warning",
                    f"approval closure not resolved: {value}",
                    "ai/reports/department-approval-matrix.md",
                    "Close the outstanding review loop or escalate it for final audit arbitration.",
                )


def collect_risk_findings(project_root: Path, findings: list[dict[str, Any]]) -> None:
    risk_text = read_text(project_root / "ai" / "state" / "risk-report.md")
    if not risk_text:
        return
    for raw_line in risk_text.splitlines():
        line = raw_line.strip()
        lowered = line.lower()
        if not line.startswith("- "):
            continue
        if any(token in lowered for token in ["schema", "migration", "breaking", "rollback"]) and any(
            token in lowered for token in ["high", "critical", "p0", "p1"]
        ):
            add_finding(
                findings,
                "high_risk_schema_change",
                "error",
                f"high-risk change noted in risk report: {line[2:].strip()}",
                "ai/state/risk-report.md",
                "Review the schema or rollout risk explicitly before allowing autonomous execution to continue.",
            )


def gather_escalation_findings(project_root: Path) -> list[dict[str, Any]]:
    state = read_json(project_root / "ai" / "state" / "orchestrator-state.json")
    findings: list[dict[str, Any]] = []
    collect_state_findings(state, findings)
    collect_inbox_findings(project_root, findings)
    collect_evidence_findings(project_root, findings)
    collect_gate_findings(project_root, state, findings)
    collect_review_loop_findings(project_root, state, findings)
    collect_approval_conflicts(project_root, findings)
    collect_risk_findings(project_root, findings)

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in findings:
        key = (item["code"], item["message"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def render_escalation_markdown(findings: list[dict[str, Any]], state: dict[str, Any]) -> str:
    reason_lines = []
    action_lines = []
    for item in findings:
        reason_lines.append(f"- [{item['severity']}] {item['message']} ({item['source']})")
        action_lines.append(f"- {item['recommended_action']}")
    reasons = "\n".join(reason_lines) if reason_lines else "- none"
    actions = "\n".join(dict.fromkeys(action_lines)) if action_lines else "- Monitor only; no escalation required."
    return f"""# Escalation Report

- created_at: {utc_now()}
- current_workflow: {state.get('current_workflow', 'unknown')}
- current_status: {state.get('current_status', 'unknown')}
- next_owner: {state.get('next_owner', 'orchestrator')}

## Reasons

{reasons}

## Recommended Parent Action

{actions}
"""


def generate_escalation(project_root: Path) -> dict:
    state = read_json(project_root / "ai" / "state" / "orchestrator-state.json")
    findings = gather_escalation_findings(project_root)
    reports_dir = project_root / "ai" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    severity_counts = {
        "error": sum(1 for item in findings if item["severity"] == "error"),
        "warning": sum(1 for item in findings if item["severity"] == "warning"),
    }
    payload = {
        "created_at": utc_now(),
        "status": "escalated" if findings else "clear",
        "items": [item["message"] for item in findings],
        "findings": findings,
        "severity_counts": severity_counts,
        "current_workflow": state.get("current_workflow", ""),
        "current_status": state.get("current_status", ""),
        "next_owner": state.get("next_owner", "orchestrator"),
    }
    write_json(reports_dir / "escalation-report.json", payload)
    write_text(reports_dir / "escalation-report.md", render_escalation_markdown(findings, state))
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a structured escalation report for parent-agent attention.")
    parser.add_argument("project_root", help="Target project root")
    args = parser.parse_args()

    payload = generate_escalation(Path(args.project_root).resolve())
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if payload["status"] == "escalated":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
