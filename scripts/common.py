from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_FILES = [
    "project-meta.json",
    "START_HERE.md",
    "task-intake.md",
    "project-handoff.md",
    "orchestrator-state.json",
    "agent-sessions.json",
    "architecture.md",
    "task-tree.json",
    "risk-report.md",
    "recovery-plan.md",
    "project-takeover.md",
    "gate-rules.md",
    "approval-policy.md",
    "doc-index.md",
    "requirements-pool.md",
    "current-milestones.md",
    "tech-debt.md",
    "architecture-principles.md",
    "testing-guidelines.md",
]

REPORT_FILES = [
    "architecture-review.md",
    "acceptance-report.md",
    "gate-report.md",
    "test-report.md",
    "department-approval-matrix.md",
    "change-summary.md",
    "postmortem.md",
]

WORKFLOW_FILES = [
    "new-project.yaml",
    "takeover-project.yaml",
    "resume-orchestrator.yaml",
    "feature-delivery.yaml",
    "review-and-release.yaml",
]

TEST_DIRS = ["unit", "integration", "e2e", "regression", "contract", "fixtures"]

HANDOFF_DIRS = [
    "orchestrator",
    "neige",
    "duchayuan",
    "libu2",
    "hubu",
    "gongbu",
    "bingbu",
    "libu",
    "xingbu",
]

PASS_CONCLUSIONS = {"PASS", "PASS_WITH_WARNING", "YES", "APPROVED", "ALLOW"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig") if path.exists() else ""


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {}


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def text_has_placeholders(text: str) -> bool:
    lowered = text.lower()
    markers = [
        "[fill here]",
        "[define the problem]",
        "[define the primary user or system path]",
        "[list major risks]",
        "[list milestone-level acceptance criteria]",
        "[new incoming requirements]",
        "[approved for current delivery]",
        "[deferred or postponed]",
        "[gray / full / hotfix / rollback]",
    ]
    return any(marker in lowered for marker in markers)


def task_tree_ready(path: Path) -> bool:
    payload = read_json(path)
    if not payload:
        return False
    return any(payload.get(key) for key in ("mainline", "current_batch", "tasks"))


def extract_section_items(markdown: str, heading: str) -> list[str]:
    lines = markdown.splitlines()
    capture = False
    items: list[str] = []
    target = heading.strip().lower()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            capture = stripped[3:].strip().lower() == target
            continue
        if not capture:
            continue
        if stripped.startswith("- "):
            item = stripped[2:].strip()
            if item and item.lower() != "none":
                items.append(item)
    return items


def collect_role_handoffs(handoff_root: Path, active_tasks: list[dict[str, Any]] | None = None) -> dict[str, list[str]]:
    results: dict[str, list[str]] = {}
    if not handoff_root.exists():
        return results
    project_root = handoff_root.parent.parent
    allowed_paths = set()
    for task in active_tasks or []:
        handoff_path = task.get("handoff_path")
        if not handoff_path:
            continue
        candidate = Path(handoff_path)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        allowed_paths.add(candidate.resolve().as_posix())
    for role_dir in sorted(entry for entry in handoff_root.iterdir() if entry.is_dir()):
        role_items: list[str] = []
        active_dir = role_dir / "active"
        candidates = sorted(active_dir.glob("*.md")) if active_dir.exists() else sorted(role_dir.glob("*.md"))
        for file_path in candidates:
            if file_path.stem.upper() == "TEMPLATE":
                continue
            if allowed_paths and file_path.resolve().as_posix() not in allowed_paths:
                continue
            text = read_text(file_path)
            summary = extract_field_value(text, "title") or extract_field_value(text, "status") or file_path.stem
            role_items.append(summary or file_path.stem)
        if role_items:
            results[role_dir.name] = role_items
    return results


def extract_field_value(markdown: str, field_name: str) -> str:
    target = field_name.strip().lower() + ":"
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("- " + target):
            return stripped[len("- " + target):].strip()
        if stripped.lower().startswith(target):
            return stripped[len(target):].strip()
    return ""


def extract_conclusion(markdown: str, heading: str) -> str:
    lines = markdown.splitlines()
    capture = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            capture = stripped[3:].strip().lower() == heading.strip().lower()
            continue
        if not capture or not stripped:
            continue
        if stripped.startswith("- "):
            value = stripped[2:].strip()
            if value and " / " not in value and "[fill here]" not in value.lower():
                return value
        if " / " not in stripped and "[fill here]" not in stripped.lower():
            return stripped
    return ""


def is_workspace_root(path: Path) -> bool:
    skills_dir = path / "skills"
    if skills_dir.exists() and skills_dir.is_dir():
        skill_entries = list(skills_dir.glob("*/SKILL.md"))
        if skill_entries:
            return True
    if (path / "OpenClaw" / "skills").exists():
        return True
    return False


def scenario_from_intent(intent: str, project_root: Path) -> str:
    normalized = intent.strip().lower()
    if normalized and normalized != "auto":
        return normalized.replace("_", "-")
    if detect_directory_mode(project_root) == "workspace_root_mode":
        return "workspace-root"
    state = read_json(project_root / "ai" / "state" / "orchestrator-state.json")
    current_status = str(state.get("current_status", "")).lower()
    current_workflow = str(state.get("current_workflow", "")).lower()
    if not (project_root / "ai").exists() and not (project_root / "tests").exists() and not (project_root / "workflows").exists():
        return "new-project"
    if current_workflow == "new-project" and current_status in {"draft", "planning", "department-approval", "plan-approved"}:
        return "new-project"
    if current_workflow == "feature-delivery":
        return "new-feature"
    if latest_run_dir(project_root) is not None:
        return "session-recovery"
    return "mid-stream-takeover"


def detect_directory_mode(path: Path) -> str:
    if (path / "SKILL.md").exists() and (path / "agents" / "openai.yaml").exists():
        return "skill_bundle_mode"
    if (path / "assets" / "project-skeleton").exists() and (path / "scripts" / "bootstrap_governance.py").exists():
        return "skill_bundle_mode"
    if is_workspace_root(path):
        return "workspace_root_mode"
    if (path / ".git").exists() or (path / "src").exists() or (path / "ai").exists() or (path / "tests").exists():
        return "project_mode"
    return "unknown_mode"


def latest_run_dir(project_root: Path) -> Path | None:
    runs_dir = project_root / "ai" / "runs"
    if not runs_dir.exists():
        return None
    run_dirs = [entry for entry in runs_dir.iterdir() if entry.is_dir()]
    if not run_dirs:
        return None
    return sorted(run_dirs)[-1]


def inspect_project(project_root: Path, intent: str = "auto") -> dict[str, Any]:
    mode = detect_directory_mode(project_root)
    state_dir = project_root / "ai" / "state"
    reports_dir = project_root / "ai" / "reports"
    workflows_dir = project_root / "workflows"
    tests_dir = project_root / "tests"
    handoff_dir = project_root / "ai" / "handoff"
    top_level_required = ["docs"]

    missing_state_files = [name for name in STATE_FILES if not (state_dir / name).exists()]
    missing_report_files = [name for name in REPORT_FILES if not (reports_dir / name).exists()]
    missing_workflows = [name for name in WORKFLOW_FILES if not (workflows_dir / name).exists()]
    missing_test_layers = [name for name in TEST_DIRS if not (tests_dir / name).exists()]
    missing_handoff_dirs = [name for name in HANDOFF_DIRS if not (handoff_dir / name).exists()]
    missing_top_level_dirs = [name for name in top_level_required if not (project_root / name).exists()]

    orchestrator_state = read_json(state_dir / "orchestrator-state.json")
    project_meta = read_json(state_dir / "project-meta.json")
    latest_run = latest_run_dir(project_root)
    architecture_text = read_text(state_dir / "architecture.md")
    task_intake_text = read_text(state_dir / "task-intake.md")
    handoff_text = read_text(state_dir / "project-handoff.md")
    acceptance_text = read_text(reports_dir / "acceptance-report.md")
    test_text = read_text(reports_dir / "test-report.md")

    frozen_requirement_present = "Frozen requirement:" in task_intake_text and "[fill here after planning approval]" not in task_intake_text.lower()
    architecture_ready = bool(architecture_text) and not text_has_placeholders(architecture_text)
    task_tree_is_ready = task_tree_ready(state_dir / "task-tree.json")
    core_state_exists = not missing_state_files[:5]
    plan_review = extract_conclusion(read_text(reports_dir / "architecture-review.md"), "Conclusion")
    final_audit = extract_conclusion(acceptance_text, "Final Conclusion")
    test_recommendation = extract_conclusion(test_text, "Recommendation")

    execution_allowed = bool(orchestrator_state.get("execution_allowed", False))
    testing_allowed = bool(orchestrator_state.get("testing_allowed", False))
    release_allowed = bool(orchestrator_state.get("release_allowed", False))
    scenario = scenario_from_intent(intent, project_root)
    planning_ready = mode == "project_mode" and core_state_exists and architecture_ready and task_tree_is_ready and frozen_requirement_present
    execution_ready = mode == "project_mode" and planning_ready and execution_allowed and orchestrator_state.get("current_status") in {
        "plan-approved",
        "executing",
        "self-check",
        "testing",
        "department-review",
        "final-audit",
        "accepted",
        "committed",
        "archived",
    }
    testing_ready = mode == "project_mode" and execution_ready and testing_allowed and "test-report.md" not in missing_report_files and not text_has_placeholders(test_text)

    return {
        "project_root": str(project_root.resolve()),
        "project_name": project_meta.get("project_name") or project_root.name,
        "project_id": project_meta.get("project_id") or project_root.name,
        "mode": mode,
        "scenario": scenario,
        "ai_exists": (project_root / "ai").exists(),
        "tests_exists": tests_dir.exists(),
        "workflows_exists": workflows_dir.exists(),
        "state_machine_exists": bool(orchestrator_state),
        "recent_run_exists": latest_run is not None,
        "recent_run_id": latest_run.name if latest_run else None,
        "missing_state_files": missing_state_files,
        "missing_report_files": missing_report_files,
        "missing_workflows": missing_workflows,
        "missing_test_layers": missing_test_layers,
        "missing_handoff_dirs": missing_handoff_dirs,
        "missing_top_level_dirs": missing_top_level_dirs,
        "planning_ready": planning_ready,
        "execution_ready": execution_ready,
        "testing_ready": testing_ready,
        "current_status": orchestrator_state.get("current_status", "draft"),
        "next_action": orchestrator_state.get("next_action", "bootstrap governance"),
        "next_owner": orchestrator_state.get("next_owner", "orchestrator"),
        "plan_review_conclusion": plan_review,
        "final_audit_conclusion": final_audit,
        "test_conclusion": test_recommendation,
        "completed_items": extract_section_items(handoff_text, "Completed"),
        "in_progress_items": extract_section_items(handoff_text, "In Progress"),
        "blocked_items": extract_section_items(handoff_text, "Blocked"),
        "mainline_status": orchestrator_state.get("mainline_status", ""),
        "release_allowed": release_allowed,
        "updated_at": utc_now(),
    }


def list_markdown_summary(items: list[str], empty_message: str = "None") -> str:
    if not items:
        return empty_message
    return "\n".join(f"- {item}" for item in items)
