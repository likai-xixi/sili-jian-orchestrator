from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from common import PASS_CONCLUSIONS, extract_conclusion, extract_field_value, read_json, read_text


REVIEW_ROLES = ["libu2", "hubu", "gongbu", "bingbu", "libu", "xingbu"]
OPTIONAL_REVIEW_ROLES = ["duchayuan"]
EMPTY_VALUES = {"", "none", "n/a", "na"}
AFFIRMATIVE_VALUES = {"yes", "true", "pass", "passed", "0", "zero", "none"}


def normalize_field_value(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("- "):
        return stripped[2:].strip()
    return stripped


def extract_field_values(text: str, field_name: str) -> list[str]:
    target = f"- {field_name.strip().lower()}:"
    lines = text.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.lower().startswith(target):
            continue

        values: list[str] = []
        inline_value = normalize_field_value(stripped[len(target):].strip())
        if inline_value:
            values.append(inline_value)

        for follow in lines[index + 1 :]:
            follow_text = follow.rstrip()
            follow_stripped = follow_text.strip()
            if not follow_stripped:
                continue
            if follow_text.startswith("  ") or follow_text.startswith("\t"):
                values.append(normalize_field_value(follow_stripped))
                continue
            break
        return values
    return []


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
    values = extract_field_values(text, field_name)
    if not values:
        return False
    for value in values:
        lowered = value.lower()
        if "[fill here]" in lowered or " / " in value:
            continue
        if lowered not in EMPTY_VALUES:
            return True
    return False


def field_is_not_affirmative(text: str, field_name: str) -> bool:
    values = extract_field_values(text, field_name)
    if not values:
        return False
    value = values[0]
    lowered = value.lower()
    if "[fill here]" in lowered or " / " in value:
        return False
    return lowered not in AFFIRMATIVE_VALUES


def has_unresolved_placeholders(text: str) -> bool:
    lines = text.splitlines()
    for index, line in enumerate(lines):
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
            if " / " in field_value:
                return True
            if field_value:
                continue

            has_continuation = False
            for follow in lines[index + 1 :]:
                follow_text = follow.rstrip()
                follow_stripped = follow_text.strip()
                if not follow_stripped:
                    continue
                if follow_text.startswith("  ") or follow_text.startswith("\t"):
                    has_continuation = True
                    if " / " in follow_stripped:
                        return True
                    continue
                break
            if not has_continuation:
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
        f"reviewer {reviewer}": [peer for peer in REVIEW_ROLES if peer != reviewer] for reviewer in REVIEW_ROLES
    }
    optional_sections = {
        f"reviewer {reviewer}": [peer for peer in REVIEW_ROLES if peer != reviewer] for reviewer in OPTIONAL_REVIEW_ROLES
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
        section_text = "\n".join(section_lines)
        for field in ["findings", "responses", "closure"]:
            values = extract_field_values(section_text, field)
            if not values:
                return False
            for value in values:
                if not value or "/" in value:
                    return False
    for reviewer, peers in optional_sections.items():
        section_lines = sections.get(reviewer, [])
        if not section_lines:
            continue
        for peer in peers:
            matching = [line for line in section_lines if line.lower().startswith(f"- {peer.lower()}:")]
            if not matching:
                return False
            value = matching[0].split(":", 1)[1].strip().upper()
            if not value or "/" in value or value not in valid_decisions:
                return False
        section_text = "\n".join(section_lines)
        for field in ["findings", "responses", "closure"]:
            values = extract_field_values(section_text, field)
            if not values:
                return False
            for value in values:
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
    release_stage = release_allowed or current_status in {"accepted", "committed", "archived"}
    review_stage = current_status in {"department-review", "final-audit", "accepted", "committed", "archived"}
    testing_stage = current_status in {"testing", "department-review", "final-audit", "accepted", "committed", "archived"}
    planning_stage = current_phase in {"planning", "department-approval", "plan-approved"} or current_status in {
        "draft",
        "planning",
        "department-approval",
        "plan-approved",
    }

    testing_gate_ready = test_ok and "test-report.md" not in placeholder_sources and test_conclusion in PASS_CONCLUSIONS
    review_gate_ready = (
        matrix_ok
        and "department-approval-matrix.md" not in placeholder_sources
        and matrix_complete
        and matrix_recommendation in PASS_CONCLUSIONS
    )
    release_artifacts_ready = (
        acceptance_ok
        and change_ok
        and gate_ok
        and "acceptance-report.md" not in placeholder_sources
        and "change-summary.md" not in placeholder_sources
        and "gate-report.md" not in placeholder_sources
    )

    phase_gate_passed = (
        state_readable
        and
        handoff_ok
        and not blocker_sources
        and (
            planning_stage
            or (
                testing_stage
                and testing_gate_ready
                and (not review_stage or review_gate_ready)
                and (not release_stage or release_artifacts_ready)
            )
        )
    )
    rollback_ready = (not release_allowed) or rollback_point == "YES"
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
        and rollback_ready
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
