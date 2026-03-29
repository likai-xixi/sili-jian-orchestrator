from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from common import PASS_CONCLUSIONS, extract_conclusion, extract_field_value, read_json, read_text


REVIEW_ROLES = ["libu2", "hubu", "gongbu", "bingbu", "libu", "xingbu"]
EMPTY_VALUES = {"", "none", "n/a", "na"}
AFFIRMATIVE_VALUES = {"yes", "true", "pass", "passed", "0", "zero", "none"}


def contains_blocker(text: str) -> bool:
    pattern = re.compile(r"^\s*-?\s*(BLOCKER|FAIL|REWORK)\s*$", re.IGNORECASE)
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("## "):
            continue
        if "[fill here]" in stripped.lower():
            continue
        if "/" in stripped:
            continue
        if "PASS_WITH_WARNING" in stripped.upper():
            continue
        if pattern.search(stripped):
            return True
    return False


def section_has_items(text: str, heading: str) -> bool:
    capture = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            capture = stripped[3:].strip().lower() == heading.strip().lower()
            continue
        if not capture or not stripped:
            continue
        if stripped.startswith("- "):
            value = stripped[2:].strip()
            if value and value.lower() not in {"none", "n/a", "na"}:
                return True
        elif stripped.lower() not in {"none", "n/a", "na"}:
            return True
    return False


def field_has_items(text: str, field_name: str) -> bool:
    value = extract_field_value(text, field_name).strip()
    if not value:
        return False
    lowered = value.lower()
    if "[fill here]" in lowered or " / " in value:
        return False
    return lowered not in EMPTY_VALUES


def field_is_not_affirmative(text: str, field_name: str) -> bool:
    value = extract_field_value(text, field_name).strip()
    if not value:
        return False
    lowered = value.lower()
    if "[fill here]" in lowered or " / " in value:
        return False
    return lowered not in AFFIRMATIVE_VALUES


def has_unresolved_placeholders(text: str) -> bool:
    for line in text.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if "[fill here]" in lowered or "[gray / full / hotfix / rollback]" in lowered:
            return True
        if not stripped.startswith("- "):
            continue
        value = stripped[2:].strip()
        if not value:
            continue
        if ":" in value:
            _, field_value = value.split(":", 1)
            field_value = field_value.strip()
            if not field_value or " / " in field_value:
                return True
            continue
        if " / " in value:
            return True
    return False


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


def validate(project_root: Path) -> dict:
    state_dir = project_root / "ai" / "state"
    reports_dir = project_root / "ai" / "reports"

    state_path = state_dir / "orchestrator-state.json"
    state = read_json(state_path)
    state_present = state_path.exists()
    state_readable = state_present and bool(state)
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
        if text and (
            contains_blocker(text)
            or section_has_items(text, "Blockers")
            or field_has_items(text, "blockers")
            or field_is_not_affirmative(text, "blocker count zero")
        ):
            blocker_sources.append(name)
        if text and has_unresolved_placeholders(text):
            placeholder_sources.append(name)

    test_conclusion = extract_conclusion(test_text, "Recommendation").upper()
    matrix_recommendation = extract_conclusion(matrix_text, "Recommendation").upper()
    acceptance_conclusion = extract_conclusion(acceptance_text, "Final Conclusion").upper()
    matrix_complete = has_department_matrix_coverage(matrix_text) and has_completed_department_reviews(matrix_text)
    gate_recommendation = extract_conclusion(gate_text, "Recommendation").upper()
    mainline_regression = extract_gate_value(gate_text, "mainline regression passed")
    rollback_point = extract_gate_value(gate_text, "rollback point available")
    release_stage = release_allowed or current_status in {"final-audit", "accepted", "committed", "archived"}
    review_stage = current_status in {"department-review", "final-audit", "accepted", "committed", "archived"}
    testing_stage = current_status in {"testing", "department-review", "final-audit", "accepted", "committed", "archived"}
    planning_stage = current_phase in {"planning", "department-approval", "plan-approved"} or current_status in {
        "draft",
        "planning",
        "department-approval",
        "plan-approved",
    }

    phase_gate_passed = (
        state_readable
        and
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
    )
    if not review_stage:
        final_gate_passed = False

    return {
        "project_root": str(project_root.resolve()),
        "state_present": state_present,
        "state_readable": state_readable,
        "handoff_present": handoff_ok,
        "test_report_present": test_ok,
        "approval_matrix_present": matrix_ok,
        "acceptance_report_present": acceptance_ok,
        "change_summary_present": change_ok,
        "gate_report_present": gate_ok,
        "execution_allowed": state.get("execution_allowed", False),
        "current_status": state.get("current_status", "draft"),
        "current_phase": state.get("current_phase", "planning"),
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
    parser = argparse.ArgumentParser(description="Validate governance gates for a target project.")
    parser.add_argument("project_root", help="Target project root")
    parser.add_argument("--output", help="Optional JSON output path")
    args = parser.parse_args()

    payload = json.dumps(validate(Path(args.project_root).resolve()), indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)


if __name__ == "__main__":
    main()
