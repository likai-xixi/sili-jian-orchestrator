from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import ensure_handoff_stub, read_json, read_text, text_has_placeholders, write_text
from validate_state import validate


def replace_markdown_value(markdown: str, label: str, value: str) -> str:
    prefix = f"- {label}:"
    lines = markdown.splitlines()
    replaced = False
    for index, line in enumerate(lines):
        if line.strip().startswith(prefix):
            lines[index] = f"- {label}: {value}"
            replaced = True
            break
    if not replaced:
        insert_at = 1 if lines and lines[0].startswith("#") else 0
        lines.insert(insert_at, f"- {label}: {value}")
    return "\n".join(lines).rstrip() + "\n"


def sync_start_here(start_here_path: Path, orchestrator: dict) -> bool:
    text = read_text(start_here_path)
    if not text:
        return False
    updated = replace_markdown_value(text, "Stage", str(orchestrator.get("current_status", "draft")))
    updated = replace_markdown_value(updated, "Workflow", str(orchestrator.get("current_workflow", "")))
    updated = replace_markdown_value(updated, "Next owner", str(orchestrator.get("next_owner", "orchestrator")))
    if updated != text:
        write_text(start_here_path, updated)
        return True
    return False


def sync_project_handoff(project_handoff_path: Path, orchestrator: dict) -> bool:
    text = read_text(project_handoff_path)
    if not text:
        return False
    updated = replace_markdown_value(text, "Status", str(orchestrator.get("current_status", "draft")))
    updated = replace_markdown_value(updated, "Current phase", str(orchestrator.get("current_phase", "planning")))
    updated = replace_markdown_value(updated, "Current workflow", str(orchestrator.get("current_workflow", "")))
    updated = replace_markdown_value(updated, "Next owner", str(orchestrator.get("next_owner", "orchestrator")))
    if updated != text:
        write_text(project_handoff_path, updated)
        return True
    return False


def repair_active_handoffs(project_root: Path, orchestrator: dict) -> list[str]:
    created: list[str] = []
    for task in orchestrator.get("active_tasks", []):
        handoff_path = str(task.get("handoff_path", "")).strip()
        if not handoff_path:
            continue
        candidate = Path(handoff_path)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        if candidate.exists():
            continue
        card = {
            "task_id": str(task.get("task_id", "")),
            "target_agent": str(task.get("role", "")),
            "title": str(task.get("title", task.get("task_id", ""))),
            "goal": str(task.get("summary", task.get("title", "Pending task execution."))),
            "handoff_path": handoff_path,
            "workflow_step_id": str(task.get("workflow_step_id", "")),
            "downstream_reviewers": "orchestrator",
            "allowed_paths": "[fill here]",
        }
        ensured = ensure_handoff_stub(project_root, handoff_path, card)
        created.append(str(ensured))
    return created


def archive_legacy_state(state_dir: Path) -> bool:
    legacy = state_dir / "orchestrator_state.json"
    canonical = state_dir / "orchestrator-state.json"
    if not legacy.exists():
        return False
    if canonical.exists():
        legacy.unlink()
        return True
    legacy.rename(canonical)
    return True


def repair_project_takeover(project_root: Path, orchestrator: dict) -> bool:
    if str(orchestrator.get("current_workflow", "")).strip() != "takeover-project":
        return False
    takeover_path = project_root / "ai" / "state" / "project-takeover.md"
    text = read_text(takeover_path)
    if text and not text_has_placeholders(text):
        return False
    project_name = project_root.name
    write_text(
        takeover_path,
        f"""# Project Takeover

- Project: {project_name}
- Original condition: Existing software project discovered during governance takeover.
- Governance gaps: State files, recovery entry, reports, workflows, and test layers required backfill.
- Mainline status: Mainline still needs structured assessment after governance bootstrap.
- Immediate risks: State drift and missing recovery/handoff artifacts can block safe execution.
- Takeover verdict: Proceed in `mid-stream-takeover` mode.
""",
    )
    return True


def repair(project_root: Path) -> dict:
    state_dir = project_root / "ai" / "state"
    orchestrator = read_json(state_dir / "orchestrator-state.json")
    if not orchestrator:
        raise SystemExit("Missing or unreadable ai/state/orchestrator-state.json")

    changes: list[str] = []
    if sync_start_here(state_dir / "START_HERE.md", orchestrator):
        changes.append("Synchronized START_HERE.md with orchestrator-state.json")
    if sync_project_handoff(state_dir / "project-handoff.md", orchestrator):
        changes.append("Synchronized project-handoff.md with orchestrator-state.json")

    for handoff in repair_active_handoffs(project_root, orchestrator):
        changes.append(f"Created missing handoff stub: {handoff}")

    if archive_legacy_state(state_dir):
        changes.append("Removed or merged legacy ai/state/orchestrator_state.json")

    if repair_project_takeover(project_root, orchestrator):
        changes.append("Backfilled project-takeover.md for takeover workflow")

    report = validate(project_root)
    return {
        "project_root": str(project_root.resolve()),
        "changes": changes,
        "state_consistent": report.get("state_consistent", False),
        "finding_count": len(report.get("findings", [])),
        "findings": report.get("findings", []),
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# State Repair Report",
        "",
        f"- project_root: {report.get('project_root', '')}",
        f"- state_consistent_after_repair: {'yes' if report.get('state_consistent') else 'no'}",
        f"- finding_count_after_repair: {report.get('finding_count', 0)}",
        "",
        "## Applied Changes",
        "",
    ]
    changes = report.get("changes", [])
    if changes:
        lines.extend(f"- {change}" for change in changes)
    else:
        lines.append("- none")
    lines.extend(["", "## Remaining Findings", ""])
    findings = report.get("findings", [])
    if findings:
        lines.extend(f"- `{item.get('code', 'unknown')}`: {item.get('message', '')}" for item in findings)
    else:
        lines.append("- none")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair common state and handoff consistency issues for a governed project.")
    parser.add_argument("project_root", help="Target project root")
    parser.add_argument("--format", choices=["json", "markdown"], default="json", help="Output format")
    parser.add_argument("--output", help="Optional output path")
    args = parser.parse_args()

    report = repair(Path(args.project_root).resolve())
    payload = render_markdown(report) if args.format == "markdown" else json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(payload if payload.endswith("\n") else payload + "\n", encoding="utf-8")
    else:
        print(payload)


if __name__ == "__main__":
    main()
