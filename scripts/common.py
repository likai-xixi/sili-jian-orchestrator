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
    "review-controls.json",
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
    "current-implementation-summary.md",
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
POSITIVE_GATE_VALUES = {"yes", "approved", "confirm", "confirmed", "pass", "pass-with-warning", "allow", "true", "done"}
NOT_APPLICABLE_GATE_VALUES = {"n-a", "n/a", "na", "not-applicable", "not applicable"}
TRUE_VALUES = {"1", "true", "yes", "y", "on"}
FALSE_VALUES = {"0", "false", "no", "n", "off", ""}


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


def parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in TRUE_VALUES:
            return True
        if normalized in FALSE_VALUES:
            return False
        return default
    if value is None:
        return default
    return bool(value)


def read_json_with_status(path: Path) -> tuple[dict[str, Any], str, str | None]:
    if not path.exists():
        return {}, "missing", None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig")), "ok", None
    except json.JSONDecodeError as exc:
        return {}, "invalid", str(exc)


def preserve_invalid_json(path: Path) -> Path:
    timestamp = utc_now().replace(":", "").replace("+00:00", "Z")
    backup_path = path.with_name(f"{path.name}.corrupt-{timestamp}.bak")
    backup_path.write_text(path.read_text(encoding="utf-8-sig"), encoding="utf-8")
    return backup_path


def require_valid_json(path: Path, description: str) -> dict[str, Any]:
    payload, status, error = read_json_with_status(path)
    if status != "invalid":
        return payload
    backup_path = preserve_invalid_json(path)
    raise ValueError(
        f"{description} is invalid JSON and was preserved at {backup_path}. "
        f"Repair the file before continuing. Parse error: {error}"
    )


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _normalize_review_result(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    return normalized if normalized in {"PASS", "FAIL"} else ""


def sync_dual_review_conflict_state(state: dict[str, Any]) -> dict[str, Any]:
    pass_1 = _normalize_review_result(state.get("review_pass_1"))
    pass_2 = _normalize_review_result(state.get("review_pass_2"))
    has_pair = bool(pass_1 and pass_2)
    mismatch = has_pair and pass_1 != pass_2

    if mismatch:
        state["review_conflict"] = True
        state["review_arbitration_required"] = True
        if str(state.get("review_arbitration_status") or "").strip().lower() != "resolved":
            state["review_arbitration_status"] = "pending"

    arbitration_required = bool(state.get("review_arbitration_required", False))
    arbitration_status = str(state.get("review_arbitration_status") or "").strip().lower()
    arbitration_evidence = str(state.get("review_arbitration_evidence") or "").strip()
    arbitration_resolved = arbitration_status == "resolved" and bool(arbitration_evidence)

    if arbitration_required:
        if arbitration_resolved:
            state["review_conflict"] = False
        else:
            state["review_conflict"] = True
            if not arbitration_status:
                state["review_arbitration_status"] = "pending"

    return state


def ensure_dual_review_state(state: dict[str, Any]) -> dict[str, Any]:
    state.setdefault("dual_review_enabled", False)
    state.setdefault("review_pass_1", None)
    state.setdefault("review_pass_2", None)
    state.setdefault("review_conflict", False)
    state.setdefault("review_run_id", "")
    state.setdefault("review_commit_sha", "")
    state.setdefault("review_arbitration_required", False)
    state.setdefault("review_arbitration_status", "")
    state.setdefault("review_arbitration_evidence", "")
    state.setdefault("review_arbitrated_by", "")
    state.setdefault("review_arbitrated_at", "")
    state.setdefault("review_arbitration_note", "")
    return sync_dual_review_conflict_state(state)


def next_step_guidance(state: dict[str, Any], automation_mode: str | None = None) -> dict[str, Any]:
    next_owner = str(state.get("next_owner", "")).strip()
    next_action = str(state.get("next_action", "")).strip()
    current_status = str(state.get("current_status", "")).strip().lower()
    current_phase = str(state.get("current_phase", "")).strip().lower()
    mode = str(automation_mode or state.get("automation_mode", "normal")).strip().lower() or "normal"
    requires_confirmation = current_status in {"await-customer-decision", "customer-decision"} or any(
        token in next_action.lower() for token in ("choose", "confirm", "decision required", "wait for explicit direction")
    )
    if requires_confirmation:
        continuation_mode = "wait-human-approval"
    elif mode == "autonomous":
        continuation_mode = "auto-continue"
    else:
        continuation_mode = "manual-trigger-required"
    if requires_confirmation:
        human_hint = (
            f"Waiting on your decision. Review the report and confirm how {next_owner or 'the orchestrator'} should proceed."
        )
    elif current_status in {"blocked", "review-rework", "rework", "redesign"}:
        human_hint = (
            f"Execution hit an issue. Ask {next_owner or 'the orchestrator'} to fix the blockers first, then rerun the current batch."
        )
    elif current_status == "department-review":
        human_hint = (
            f"Review evidence is ready. Let {next_owner or 'the next reviewer'} continue only after the current review package is confirmed complete."
        )
    elif continuation_mode == "auto-continue":
        human_hint = f"No manual approval needed. {next_owner or 'The orchestrator'} can continue automatically."
    else:
        human_hint = f"Manual trigger needed. Ask {next_owner or 'the orchestrator'} to do the next step when you're ready."
    summary_parts = [part for part in [f"next_owner={next_owner or 'orchestrator'}", f"next_action={next_action or 'review state and continue'}"] if part]
    if current_phase or current_status:
        summary_parts.append(f"stage={current_phase or current_status}/{current_status or current_phase}")
    return {
        "next_owner": next_owner,
        "next_action": next_action,
        "requires_confirmation": requires_confirmation,
        "continuation_mode": continuation_mode,
        "human_hint": human_hint,
        "summary": "; ".join(summary_parts),
    }


def resolve_project_root(start: Path) -> Path:
    candidate = start.resolve()
    if candidate.is_file():
        candidate = candidate.parent
    for current in [candidate, *candidate.parents]:
        if (current / "ai" / "state").exists() or (current / "workflows").exists():
            return current
    return candidate


def ensure_handoff_stub(project_root: Path, handoff_path: str, card: dict[str, str]) -> Path:
    root = project_root.resolve()
    candidate = Path(handoff_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"handoff_path escapes project root: {handoff_path}") from exc
    candidate.parent.mkdir(parents=True, exist_ok=True)
    if candidate.exists():
        return candidate

    role = card.get("target_agent") or card.get("target_agent_id") or "department"
    summary = card.get("goal") or card.get("expected_output") or card.get("title") or "Pending task execution."
    touched = card.get("allowed_paths") or "[fill here]"
    next_reviewer = card.get("downstream_reviewers") or "orchestrator"
    write_text(
        candidate,
        f"""# Role Handoff

- title: {card.get('title', '')}
- status: in-progress
- task_id: {card.get('task_id', '')}
- workflow_step_id: {card.get('workflow_step_id', '')}
- summary: {summary}
- files_touched: {touched}
- blockers: none
- next_reviewer: {next_reviewer}
- role: {role}
- updated_at: [fill here]
""",
    )
    return candidate


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


def extract_section_text(markdown: str, heading: str) -> str:
    lines = markdown.splitlines()
    capture = False
    target = heading.strip().lower()
    captured: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            if capture:
                break
            capture = stripped[3:].strip().lower() == target
            continue
        if capture:
            captured.append(line)
    return "\n".join(captured).strip()


def normalize_gate_value(value: str) -> str:
    lowered = value.strip().lower().replace("_", "-")
    return " ".join(lowered.split())


def gate_is_positive(value: str) -> bool:
    normalized = normalize_gate_value(value)
    return normalized in POSITIVE_GATE_VALUES or normalized.upper() in PASS_CONCLUSIONS


def gate_is_positive_or_not_applicable(value: str) -> bool:
    normalized = normalize_gate_value(value)
    return gate_is_positive(value) or normalized in NOT_APPLICABLE_GATE_VALUES


def section_has_substantive_content(markdown: str, heading: str) -> bool:
    section = extract_section_text(markdown, heading)
    if not section or text_has_placeholders(section):
        return False
    content_lines = [line.strip("- ").strip() for line in section.splitlines() if line.strip()]
    meaningful = " ".join(content_lines).strip()
    return bool(meaningful) and meaningful.lower() not in {"none", "pending", "n/a"}


def task_intake_review_status(task_intake_text: str) -> dict[str, bool]:
    return {
        "raw_requirement_present": section_has_substantive_content(task_intake_text, "Raw Requirement"),
        "current_implemented_scope_present": section_has_substantive_content(task_intake_text, "Current Implemented Scope"),
        "confirmed_requirement_present": section_has_substantive_content(task_intake_text, "Confirmed Requirement"),
        "frozen_requirement_present": section_has_substantive_content(task_intake_text, "Frozen Requirement"),
        "customer_acknowledged_implementation": gate_is_positive_or_not_applicable(
            extract_field_value(task_intake_text, "Customer acknowledged current implementation baseline")
        ),
        "customer_confirmed_requirement": gate_is_positive(
            extract_field_value(task_intake_text, "Customer confirmed requirement and scope")
        ),
        "development_approved": gate_is_positive(extract_field_value(task_intake_text, "Approved to start development")),
    }


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


def project_has_existing_context(project_root: Path) -> bool:
    docs_dir = project_root / "docs"
    if docs_dir.exists():
        doc_count = sum(1 for path in docs_dir.rglob("*.md") if path.is_file())
        if doc_count >= 3:
            return True
    context_dir = project_root / "ai" / "context"
    if context_dir.exists():
        context_count = sum(1 for path in context_dir.rglob("*.md") if path.is_file())
        if context_count >= 2:
            return True
    for marker in ["package.json", "pnpm-workspace.yaml", "turbo.json", "src"]:
        if (project_root / marker).exists():
            return True
    return False


def takeover_file_ready(project_root: Path) -> bool:
    takeover_text = read_text(project_root / "ai" / "state" / "project-takeover.md")
    if not takeover_text:
        return False
    return not text_has_placeholders(takeover_text) and "Proceed in `mid-stream-takeover` mode." in takeover_text


def scenario_from_intent(intent: str, project_root: Path) -> str:
    normalized = intent.strip().lower()
    if normalized and normalized != "auto":
        return normalized.replace("_", "-")
    if detect_directory_mode(project_root) == "workspace_root_mode":
        return "workspace-root"

    state = read_json(project_root / "ai" / "state" / "orchestrator-state.json")
    current_status = str(state.get("current_status", "")).lower()
    current_workflow = str(state.get("current_workflow", "")).lower()
    has_existing_context = project_has_existing_context(project_root)

    if not (project_root / "ai").exists() and not (project_root / "tests").exists() and not (project_root / "workflows").exists():
        return "new-project"
    if current_workflow == "takeover-project":
        return "mid-stream-takeover"
    if current_workflow == "resume-orchestrator":
        return "session-recovery"
    if takeover_file_ready(project_root):
        return "mid-stream-takeover"
    if has_existing_context and current_workflow != "feature-delivery":
        return "mid-stream-takeover"
    if current_workflow == "new-project" and current_status in {"draft", "planning", "department-approval", "plan-approved"}:
        return "new-project"
    if latest_run_dir(project_root) is not None:
        return "session-recovery"
    if current_workflow == "feature-delivery":
        return "new-feature"
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
    implementation_summary_text = read_text(reports_dir / "current-implementation-summary.md")

    task_intake_status = task_intake_review_status(task_intake_text)
    architecture_ready = bool(architecture_text) and not text_has_placeholders(architecture_text)
    task_tree_is_ready = task_tree_ready(state_dir / "task-tree.json")
    core_state_exists = not missing_state_files[:6]
    plan_review = extract_conclusion(read_text(reports_dir / "architecture-review.md"), "Conclusion")
    plan_review_passed = gate_is_positive(plan_review)
    final_audit = extract_conclusion(acceptance_text, "Final Conclusion")
    test_recommendation = extract_conclusion(test_text, "Recommendation")

    execution_allowed = parse_bool(orchestrator_state.get("execution_allowed", False), default=False)
    testing_allowed = parse_bool(orchestrator_state.get("testing_allowed", False), default=False)
    release_allowed = parse_bool(orchestrator_state.get("release_allowed", False), default=False)
    scenario = scenario_from_intent(intent, project_root)
    implementation_baseline_required = scenario == "mid-stream-takeover" and project_has_existing_context(project_root)
    implementation_summary_ready = (not implementation_baseline_required) or (
        bool(implementation_summary_text) and not text_has_placeholders(implementation_summary_text)
    )
    planning_ready = (
        mode == "project_mode"
        and core_state_exists
        and architecture_ready
        and task_tree_is_ready
        and task_intake_status["frozen_requirement_present"]
        and plan_review_passed
        and task_intake_status["customer_confirmed_requirement"]
        and task_intake_status["development_approved"]
        and implementation_summary_ready
        and (not implementation_baseline_required or task_intake_status["customer_acknowledged_implementation"])
    )
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
        "plan_review_passed": plan_review_passed,
        "architecture_ready": architecture_ready,
        "task_tree_ready": task_tree_is_ready,
        "implementation_baseline_required": implementation_baseline_required,
        "implementation_summary_ready": implementation_summary_ready,
        "raw_requirement_present": task_intake_status["raw_requirement_present"],
        "confirmed_requirement_present": task_intake_status["confirmed_requirement_present"],
        "frozen_requirement_present": task_intake_status["frozen_requirement_present"],
        "customer_acknowledged_implementation": task_intake_status["customer_acknowledged_implementation"],
        "customer_confirmed_requirement": task_intake_status["customer_confirmed_requirement"],
        "development_approved": task_intake_status["development_approved"],
        "updated_at": utc_now(),
    }


def list_markdown_summary(items: list[str], empty_message: str = "None") -> str:
    if not items:
        return empty_message
    return "\n".join(f"- {item}" for item in items)
