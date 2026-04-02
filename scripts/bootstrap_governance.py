from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from common import TEST_DIRS, ensure_dual_review_state, project_has_existing_context, read_json, read_text, write_json, write_text
from sync_project_tools import assert_project_tools_synced


TEXT_EXTENSIONS = {".md", ".json", ".yaml", ".yml"}
RUNTIME_TOOL_FILES = [
    "build_dispatch_payload.py",
    "recovery_summary.py",
    "automation_control.py",
    "configure_autonomy.py",
    "change_request_control.py",
    "close_session.py",
    "git_autocommit.py",
    "natural_language_control.py",
    "replan_change_request.py",
    "provider_evidence.py",
    "host_interface_probe.py",
    "runtime_environment.py",
    "runtime_guardrails.py",
    "environment_bootstrap.py",
    "openclaw_runtime_bridge.py",
    "repo_command_detector.py",
    "evidence_collector.py",
    "escalation_manager.py",
    "parent_session_recovery.py",
    "session_registry.py",
    "workflow_engine.py",
    "openclaw_adapter.py",
    "completion_consumer.py",
    "inbox_watcher.py",
    "orchestrator_local_steps.py",
    "context_rollover.py",
    "run_orchestrator.py",
    "runtime_loop.py",
    "task_rounds.py",
    "resource_requirements.py",
    "project_intake.py",
    "configure_review_controls.py",
    "resume_customer_decision.py",
]


def render_template(text: str, project_name: str, project_id: str) -> str:
    normalized = text.lstrip("\ufeff")
    return normalized.replace("{{PROJECT_NAME}}", project_name).replace("{{PROJECT_ID}}", project_id)


def replace_line(text: str, prefix: str, new_line: str) -> str:
    lines = text.splitlines()
    replaced = False
    for idx, line in enumerate(lines):
        if line.startswith(prefix):
            lines[idx] = new_line
            replaced = True
            break
    if not replaced:
        lines.append(new_line)
    return "\n".join(lines) + "\n"


def detect_bootstrap_scenario(project_root: Path, explicit: str) -> str:
    if explicit and explicit != "auto":
        return explicit
    if project_has_existing_context(project_root):
        return "mid-stream-takeover"
    if (project_root / "ai").exists() or (project_root / "workflows").exists() or (project_root / "tests").exists():
        return "mid-stream-takeover"
    return "new-project"


def ensure_test_layers(project_root: Path) -> None:
    tests_root = project_root / "tests"
    tests_root.mkdir(parents=True, exist_ok=True)
    for name in TEST_DIRS:
        (tests_root / name).mkdir(parents=True, exist_ok=True)


def install_runtime_tools(skill_root: Path, project_root: Path, force: bool) -> None:
    tools_dir = project_root / "ai" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    for name in RUNTIME_TOOL_FILES:
        source = skill_root / "scripts" / name
        target = tools_dir / name
        if target.exists() and not force:
            continue
        shutil.copy2(source, target)


def apply_takeover_defaults(project_root: Path) -> None:
    state_dir = project_root / "ai" / "state"
    orchestrator_state_path = state_dir / "orchestrator-state.json"
    handoff_path = state_dir / "project-handoff.md"
    start_here_path = state_dir / "START_HERE.md"
    takeover_path = state_dir / "project-takeover.md"

    orchestrator_state = read_json(orchestrator_state_path)
    if orchestrator_state:
        ensure_dual_review_state(orchestrator_state)
        orchestrator_state["current_phase"] = "planning"
        orchestrator_state["current_status"] = "draft"
        orchestrator_state["current_workflow"] = "takeover-project"
        orchestrator_state["primary_goal"] = (
            "Backfill governance, freeze the current implementation baseline, review planning docs, "
            "and obtain customer confirmation before development."
        )
        orchestrator_state["next_action"] = (
            "Inspect the existing project, write current-implementation-summary.md, then align requirements "
            "with the customer before freezing the takeover plan."
        )
        orchestrator_state["next_owner"] = "orchestrator"
        orchestrator_state["active_tasks"] = [
            {
                "task_id": "TAKEOVER-ASSESSMENT",
                "role": "orchestrator",
                "status": "in-progress",
                "handoff_path": "ai/handoff/orchestrator/active/TAKEOVER-ASSESSMENT.md",
            }
        ]
        orchestrator_state["last_heartbeat_goal"] = "Backfill governance and establish a customer-confirmed takeover baseline."
        orchestrator_state["last_heartbeat_reason"] = (
            "This is an in-progress project, so the current implementation and next-scope documents must be "
            "reviewed and confirmed before execution."
        )
        write_json(orchestrator_state_path, orchestrator_state)

    handoff_text = read_text(handoff_path)
    if handoff_text:
        handoff_text = replace_line(handoff_text, "- Current workflow:", "- Current workflow: takeover-project")
        handoff_text = replace_line(
            handoff_text,
            "- Main objective:",
            "- Main objective: freeze the current implementation baseline, align scope with the customer, and then approve development",
        )
        handoff_text = replace_line(
            handoff_text,
            "- Next action:",
            "- Next action: inspect current implementation, produce implementation summary, then repair architecture plus task tree",
        )
        handoff_text = replace_line(handoff_text, "- Next owner:", "- Next owner: orchestrator")
        handoff_text = replace_line(
            handoff_text,
            "- Governance skeleton created",
            "- Governance skeleton created, takeover mode activated, and customer confirmation gate enabled",
        )
        handoff_text = replace_line(handoff_text, "- Initial planning", "- Takeover assessment, implementation summary, and planning repair")
        write_text(handoff_path, handoff_text)

    start_here_text = read_text(start_here_path)
    if start_here_text:
        start_here_text = replace_line(start_here_text, "- Workflow:", "- Workflow: takeover-project")
        start_here_text = replace_line(start_here_text, "- Next owner:", "- Next owner: orchestrator")
        start_here_text = replace_line(start_here_text, "- Current batch:", "- Current batch: takeover repair")
        start_here_text = replace_line(
            start_here_text,
            "- Freeze the minimum approved baseline, complete document review, and obtain customer confirmation before implementation.",
            "- Backfill governance, inspect the existing system, summarize the current implementation, and obtain customer confirmation before implementation.",
        )
        write_text(start_here_path, start_here_text)

    write_text(
        takeover_path,
        """# Project Takeover

## Takeover Context

- Original condition: Existing project detected; governance coverage is incomplete and must be backfilled before execution resumes.
- Governance gaps: Missing or partial state files, reports, workflow templates, test structure, and recovery artifacts.
- Current implementation summary shared with customer: pending
- Mainline status: Unknown until architecture and task-tree are reconstructed from the current codebase and docs.
- Immediate risks: State drift, missing handoff continuity, missing test baseline, and incorrect workflow selection.

## Takeover Verdict

- Proceed in `mid-stream-takeover` mode.
- Backfill governance first.
- Freeze current implementation scope first, then architecture and task tree before execution.
- Capture explicit customer confirmation on current behavior and approved next scope before execution.
""",
    )

    takeover_handoff = project_root / "ai" / "handoff" / "orchestrator" / "active" / "TAKEOVER-ASSESSMENT.md"
    if not takeover_handoff.exists():
        write_text(
            takeover_handoff,
            """# Role Handoff

- title: Takeover assessment and planning repair
- status: in-progress
- task_id: TAKEOVER-ASSESSMENT
- workflow_step_id: inspect-governance
- summary: Inspect the existing project, summarize the current implementation, backfill governance gaps, and establish the first takeover planning baseline.
- files_touched: ai/reports/current-implementation-summary.md, ai/state/project-takeover.md, ai/state/architecture.md, ai/state/task-tree.json, ai/state/project-handoff.md
- blockers: none
- next_reviewer: neige
- updated_at: [fill here]
""",
        )


def apply_scenario_defaults(project_root: Path, scenario: str) -> None:
    if scenario == "mid-stream-takeover":
        apply_takeover_defaults(project_root)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap governance files into a target project.")
    parser.add_argument("project_root", help="Target project root")
    parser.add_argument("--project-name", help="Explicit project name to write into templates")
    parser.add_argument("--project-id", help="Explicit project id to write into templates")
    parser.add_argument(
        "--scenario",
        default="auto",
        choices=["auto", "new-project", "mid-stream-takeover"],
        help="Bootstrap scenario used to apply scenario-specific state defaults",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing files")
    parser.add_argument("--skill-root", default=Path(__file__).resolve().parent.parent, help="Skill root path")
    args = parser.parse_args()

    skill_root = Path(args.skill_root).resolve()
    project_root = Path(args.project_root).resolve()
    skeleton_root = skill_root / "assets" / "project-skeleton"
    project_name = args.project_name or project_root.name
    project_id = args.project_id or project_root.name
    scenario = detect_bootstrap_scenario(project_root, args.scenario)

    assert_project_tools_synced(skill_root)

    project_root.mkdir(parents=True, exist_ok=True)
    for item in skeleton_root.rglob("*"):
        relative = item.relative_to(skeleton_root)
        target = project_root / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if target.exists() and not args.force:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if item.suffix.lower() in TEXT_EXTENSIONS:
            rendered = render_template(item.read_text(encoding="utf-8"), project_name, project_id)
            write_text(target, rendered)
        else:
            shutil.copy2(item, target)

    ensure_test_layers(project_root)
    install_runtime_tools(skill_root, project_root, args.force)
    apply_scenario_defaults(project_root, scenario)
    print(f"Bootstrapped governance into {project_root} with scenario={scenario}")


if __name__ == "__main__":
    main()
