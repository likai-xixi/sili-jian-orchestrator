from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from common import PASS_CONCLUSIONS, extract_conclusion, read_json, read_text


REVIEW_ROLES = ["libu2", "hubu", "gongbu", "bingbu", "libu", "xingbu"]


def contains_blocker(text: str) -> bool:
    pattern = re.compile(r"^\s*-?\s*(BLOCKER|FAIL|REWORK)\s*$", re.IGNORECASE)
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("## "):
            continue
        if "[fill here]" in stripped.lower() or "/" in stripped or "PASS_WITH_WARNING" in stripped.upper():
            continue
        if pattern.search(stripped):
            return True
    return False


def has_unresolved_placeholders(text: str) -> bool:
    lowered = text.lower()
    markers = ["[fill here]", "[gray / full / hotfix / rollback]", "passed:", "failed:", "skipped:"]
    return any(marker in lowered for marker in markers)


def has_department_matrix_coverage(text: str) -> bool:
    required = ["libu2:", "hubu:", "gongbu:", "bingbu:", "libu:", "xingbu:"]
    lowered = text.lower()
    return all(token in lowered for token in required)


def has_completed_department_reviews(text: str) -> bool:
    reviewer_sections = {
        "reviewer libu2": ["hubu", "gongbu", "bingbu", "libu", "xingbu"],
        "reviewer hubu": ["libu2", "gongbu", "bingbu", "libu", "xingbu"],
        "reviewer gongbu": ["libu2", "hubu", "bingbu", "libu", "xingbu"],
        "reviewer bingbu": ["libu2", "hubu", "gongbu", "libu", "xingbu"],
        "reviewer libu": ["libu2", "hubu", "gongbu", "bingbu", "xingbu"],
        "reviewer xingbu": ["libu2", "hubu", "gongbu", "bingbu", "libu"],
    }
    lines = text.splitlines()
    sections: dict[str, list[str]] = {}
    current = ""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            current = stripped[3:].strip().lower()
            sections[current] = []
            continue
        if current:
            sections.setdefault(current, []).append(stripped)

    valid_decisions = {"PASS", "REWORK", "BLOCKER", "SUGGESTION", "PASS_WITH_WARNING"}
    for reviewer, peers in reviewer_sections.items():
        section_lines = sections.get(reviewer, [])
        if not section_lines:
            return False
        for peer in peers:
            matching = [line for line in section_lines if line.lower().startswith(f"- {peer.lower()}:")]
            if not matching:
                return False
            value = matching[0].split(":", 1)[1].strip().upper()
            if not value or "/" in value or value not in valid_decisions:
                return False
        for field in ["- findings:", "- responses:", "- closure:"]:
            matches = [line for line in section_lines if line.lower().startswith(field)]
            if not matches:
                return False
            value = matches[0].split(":", 1)[1].strip()
            if not value or "/" in value:
                return False
    return True


def extract_gate_value(text: str, field_name: str) -> str:
    target = field_name.strip().lower() + ":"
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("- " + target):
            return stripped[len("- " + target):].strip().upper()
    return ""


def render_markdown(report: dict) -> str:
    lines = [
        "# Gate Validation Report",
        "",
        f"- project_root: {report.get('project_root', '')}",
        f"- current_phase: {report.get('current_phase', '')}",
        f"- current_status: {report.get('current_status', '')}",
        f"- phase_gate_passed: {'yes' if report.get('phase_gate_passed') else 'no'}",
        f"- final_gate_passed: {'yes' if report.get('final_gate_passed') else 'no'}",
        f"- release_stage: {'yes' if report.get('release_stage') else 'no'}",
        "",
        "## Blockers",
        "",
    ]
    blockers = report.get("blocker_sources", [])
    if blockers:
        lines.extend(f"- {item}" for item in blockers)
    else:
        lines.append("- none")
    lines.extend(["", "## Placeholder Sources", ""])
    placeholders = report.get("placeholder_sources", [])
    if placeholders:
        lines.extend(f"- {item}" for item in placeholders)
    else:
        lines.append("- none")
    return "\n".join(lines).rstrip() + "\n"


def validate(project_root: Path) -> dict:
    state_dir = project_root / "ai" / "state"
    reports_dir = project_root / "ai" / "reports"

    state = read_json(state_dir / "orchestrator-state.json")
    current_status = str(state.get("current_status", "draft")).lower()
    current_phase = str(state.get("current_phase", "planning")).lower()
    release_allowed = state.get("release_allowed", False)

    handoff_ok = (state_dir / "project-handoff.md").exists()
    test_ok = (reports_dir / "test-report.md").exists()
    matrix_ok = (reports_dir / "department-approval-matrix.md").exists()
    acceptance_ok = (reports_dir / "acceptance-report.md").exists()
    change_ok = (reports_dir / "change-summary.md").exists()
    gate_ok = (reports_dir / "gate-report.md").exists()

    test_text = read_text(reports_dir / "test-report.md")
    matrix_text = read_text(reports_dir / "department-approval-matrix.md")
    acceptance_text = read_text(reports_dir / "acceptance-report.md")
    gate_text = read_text(reports_dir / "gate-report.md")

    blocker_sources = []
    placeholder_sources = []
    for name in ["test-report.md", "department-approval-matrix.md", "acceptance-report.md", "change-summary.md", "gate-report.md"]:
        text = read_text(reports_dir / name)
        if text and contains_blocker(text):
            blocker_sources.append(name)
        if text and has_unresolved_placeholders(text):
            placeholder_sources.append(name)

    test_conclusion = extract_conclusion(test_text, "Recommendation").upper()
    matrix_recommendation = extract_conclusion(matrix_text, "Recommendation").upper()
    acceptance_conclusion = extract_conclusion(acceptance_text, "Final Conclusion").upper()
    gate_recommendation = extract_conclusion(gate_text, "Recommendation").upper()
    matrix_complete = has_department_matrix_coverage(matrix_text) and has_completed_department_reviews(matrix_text)
    mainline_regression = extract_gate_value(gate_text, "mainline regression passed")
    rollback_point = extract_gate_value(gate_text, "rollback point available")

    review_stage = current_status in {"department-review", "final-audit", "accepted", "committed", "archived"}
    testing_stage = current_status in {"testing", "department-review", "final-audit", "accepted", "committed", "archived"}
    planning_stage = current_phase in {"planning", "department-approval", "plan-approved"} or current_status in {
        "draft",
        "planning",
        "department-approval",
        "plan-approved",
    }
    release_stage = release_allowed or current_status in {"final-audit", "accepted", "committed", "archived"}

    phase_gate_passed = (
        handoff_ok
        and not blocker_sources
        and (
            planning_stage
            or (
                testing_stage
                and test_ok
                and "test-report.md" not in placeholder_sources
                and test_conclusion in PASS_CONCLUSIONS
            )
        )
    )
    final_gate_passed = (
        all([handoff_ok, test_ok, matrix_ok, acceptance_ok, change_ok, gate_ok])
        and not blocker_sources
        and not placeholder_sources
        and matrix_complete
        and test_conclusion in PASS_CONCLUSIONS
        and matrix_recommendation in PASS_CONCLUSIONS
        and acceptance_conclusion in {"PASS", "PASS_WITH_WARNING"}
        and gate_recommendation in {"PASS", "PASS_WITH_WARNING"}
        and mainline_regression == "YES"
        and rollback_point == "YES"
        and review_stage
    )

    return {
        "project_root": str(project_root.resolve()),
        "handoff_present": handoff_ok,
        "test_report_present": test_ok,
        "approval_matrix_present": matrix_ok,
        "acceptance_report_present": acceptance_ok,
        "change_summary_present": change_ok,
        "gate_report_present": gate_ok,
        "current_phase": state.get("current_phase", "planning"),
        "current_status": state.get("current_status", "draft"),
        "blocker_sources": blocker_sources,
        "placeholder_sources": placeholder_sources,
        "matrix_complete": matrix_complete,
        "review_roles": REVIEW_ROLES,
        "test_conclusion": test_conclusion,
        "matrix_recommendation": matrix_recommendation,
        "acceptance_conclusion": acceptance_conclusion,
        "gate_recommendation": gate_recommendation,
        "mainline_regression": mainline_regression,
        "rollback_point_available": rollback_point,
        "release_allowed": release_allowed,
        "phase_gate_passed": phase_gate_passed,
        "release_stage": release_stage,
        "final_gate_passed": final_gate_passed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate project-local governance gates.")
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
