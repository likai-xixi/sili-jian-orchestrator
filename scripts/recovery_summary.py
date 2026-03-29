from __future__ import annotations

import argparse
from pathlib import Path

from common import collect_role_handoffs, extract_conclusion, extract_section_items, latest_run_dir, read_json, read_text, write_text


def build_summary(project_root: Path) -> str:
    state_dir = project_root / "ai" / "state"
    reports_dir = project_root / "ai" / "reports"
    orchestrator = read_json(state_dir / "orchestrator-state.json")
    meta = read_json(state_dir / "project-meta.json")
    handoff_text = read_text(state_dir / "project-handoff.md")
    acceptance_text = read_text(reports_dir / "acceptance-report.md")
    approvals_text = read_text(reports_dir / "department-approval-matrix.md")
    tests_text = read_text(reports_dir / "test-report.md")
    latest_run = latest_run_dir(project_root)
    role_handoffs = collect_role_handoffs(project_root / "ai" / "handoff", orchestrator.get("active_tasks", []))
    completed = extract_section_items(handoff_text, "Completed")
    in_progress = extract_section_items(handoff_text, "In Progress")
    blocked = extract_section_items(handoff_text, "Blocked")
    plan_review = extract_conclusion(read_text(reports_dir / "architecture-review.md"), "Conclusion")
    result_audit = extract_conclusion(acceptance_text, "Final Conclusion")
    test_conclusion = extract_conclusion(tests_text, "Recommendation")
    approvals_recommendation = extract_conclusion(approvals_text, "Recommendation")

    def to_lines(items: list[str]) -> str:
        return "\n".join(f"  - {item}" for item in items) if items else "  - None"

    def handoff_lines(items: dict[str, list[str]]) -> str:
        if not items:
            return "  - None"
        lines: list[str] = []
        for role, entries in items.items():
            preview = ", ".join(entries[:3])
            lines.append(f"  - {role}: {preview}")
        return "\n".join(lines)

    return f"""# Recovery Summary

- Current project: {meta.get('project_name', project_root.name)}
- Project id: {meta.get('project_id', project_root.name)}
- Current phase: {orchestrator.get('current_phase', 'planning')}
- Current status: {orchestrator.get('current_status', 'draft')}
- Completed tasks:
{to_lines(completed)}
- In-progress tasks:
{to_lines(in_progress)}
- Blocked tasks:
{to_lines(blocked)}
- Latest plan review conclusion: {plan_review or 'None'}
- Latest result audit conclusion: {result_audit or 'None'}
- Latest department review recommendation: {approvals_recommendation or 'None'}
- Latest test conclusion: {test_conclusion or 'None'}
- Active role handoffs:
{handoff_lines(role_handoffs)}
- Current next_action: {orchestrator.get('next_action', 'bootstrap governance')}
- Next owner: {orchestrator.get('next_owner', 'orchestrator')}
- Latest run snapshot: {latest_run.name if latest_run else 'None'}
- Execution allowed: {orchestrator.get('execution_allowed', False)}
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a recovery summary for a governed project.")
    parser.add_argument("project_root", help="Target project root")
    parser.add_argument("--output", help="Output markdown path")
    args = parser.parse_args()

    summary = build_summary(Path(args.project_root).resolve())
    if args.output:
        write_text(Path(args.output), summary)
    else:
        print(summary)


if __name__ == "__main__":
    main()
