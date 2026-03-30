from __future__ import annotations

from pathlib import Path
from typing import Any

from common import (
    HANDOFF_DIRS,
    TEST_DIRS,
    extract_conclusion,
    extract_field_value,
    inspect_project,
    read_json,
    read_text,
    utc_now,
    write_json,
    write_text,
)
from completion_consumer import consume_completion
from recovery_summary import build_summary
from session_registry import load_registry
from workflow_engine import WorkflowStep


DEPARTMENT_ROLES = ["libu2", "hubu", "gongbu", "bingbu", "libu", "xingbu"]
CROSS_REVIEW_ROLES = [*DEPARTMENT_ROLES, "duchayuan"]
DEFAULT_REVIEW_CYCLE_LIMIT_BEFORE_CABINET = 4
DEFAULT_REVIEW_CYCLE_LIMIT_AFTER_CABINET = 2
FEATURE_DELIVERY_IMPLEMENTATION_STEPS = ["libu2-implementation", "hubu-implementation", "gongbu-implementation"]
FEATURE_DELIVERY_CROSS_REVIEW_STEPS = [
    "libu2-cross-review",
    "hubu-cross-review",
    "gongbu-cross-review",
    "bingbu-cross-review",
    "libu-cross-review",
    "xingbu-cross-review",
    "duchayuan-cross-review",
]
FEATURE_DELIVERY_REWORK_RESET_STEPS = [
    *FEATURE_DELIVERY_IMPLEMENTATION_STEPS,
    *FEATURE_DELIVERY_CROSS_REVIEW_STEPS,
    "department-review",
    "bingbu-testing",
    "libu-documentation",
    "xingbu-release-check",
    "final-audit",
    "release-prep",
    "update-state-and-run-summary",
]
FEATURE_DELIVERY_REPLAN_RESET_STEPS = [
    "confirm-or-replan",
    "plan-approval",
    *FEATURE_DELIVERY_REWORK_RESET_STEPS,
]

LOCAL_STEP_IDS = {
    "identify-project",
    "bootstrap-governance",
    "create-run-snapshot",
    "intake-feature",
    "inspect-governance",
    "backfill-governance",
    "read-recovery-entry",
    "read-latest-reports",
    "read-active-handoffs",
    "produce-recovery-summary",
    "department-review",
    "collect-department-approvals",
    "update-state-and-handoff",
    "update-state-and-run-summary",
}
IMPLEMENTATION_MANIFESTS = [
    "package.json",
    "pnpm-workspace.yaml",
    "turbo.json",
    "pyproject.toml",
    "requirements.txt",
    "Cargo.toml",
    "go.mod",
]
IMPLEMENTATION_ROOTS = ["src", "app", "server", "api", "services", "lib", "components", "pages", "db", "docs", "tests"]
IMPLEMENTATION_SAMPLE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".cs", ".sql", ".md"}
IMPLEMENTATION_IGNORES = {"ai", ".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}


def slugify(text: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in text).strip("-")


def is_local_orchestrator_step(step: WorkflowStep) -> bool:
    return step.agent_id == "orchestrator" and step.id in LOCAL_STEP_IDS


def state_path(project_root: Path) -> Path:
    return project_root / "ai" / "state" / "orchestrator-state.json"


def meta_path(project_root: Path) -> Path:
    return project_root / "ai" / "state" / "project-meta.json"


def review_controls_path(project_root: Path) -> Path:
    return project_root / "ai" / "state" / "review-controls.json"


def reports_dir(project_root: Path) -> Path:
    path = project_root / "ai" / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_governance_surface(project_root: Path) -> None:
    (project_root / "docs").mkdir(parents=True, exist_ok=True)
    for name in TEST_DIRS:
        (project_root / "tests" / name).mkdir(parents=True, exist_ok=True)
    for role in HANDOFF_DIRS:
        (project_root / "ai" / "handoff" / role / "active").mkdir(parents=True, exist_ok=True)


def determine_intent(current_workflow: str) -> str:
    if current_workflow == "takeover-project":
        return "mid-stream-takeover"
    if current_workflow == "feature-delivery":
        return "new-feature"
    return "new-project"


def render_start_here(project_root: Path, state: dict[str, Any]) -> str:
    sync_review_controls(project_root, state)
    meta = read_json(meta_path(project_root))
    return f"""# START_HERE

## Project

- Project name: {meta.get('project_name', project_root.name)}
- Project id: {meta.get('project_id', project_root.name)}

## Current Effective Versions

- Project version: 0.1.0
- Architecture version: 0.1.0
- Task tree version: 0.1.0
- Release version: not released

## Current Stage

- Stage: {state.get('current_status', 'draft')}
- Workflow: {state.get('current_workflow', 'new-project')}
- Mainline status: {str(state.get('mainline_status', 'not-started')).replace('-', ' ')}
- Immediate execution allowed: {'yes' if state.get('execution_allowed') else 'no'}
- Immediate testing allowed: {'yes' if state.get('testing_allowed') else 'no'}
- Release allowed: {'yes' if state.get('release_allowed') else 'no'}
- Resource gap count: {len(state.get('resource_gaps', [])) if isinstance(state.get('resource_gaps'), list) else 0}
- Resource gap report: {state.get('resource_gap_report_path') or 'pending'}

## Current Control Summary

- Highest priority: {state.get('priority_top', 'P1')}
- Blocker level: {state.get('blocker_level', 'none')}
- Next owner: {state.get('next_owner', 'orchestrator')}
- Current batch: {state.get('current_phase', 'planning')}
- Review phase: {state.get('review_phase', 'normal-review')}
- Review rounds before cabinet: {state.get('review_cycle_count_before_cabinet', 0)} / {state.get('review_cycle_limit_before_cabinet', DEFAULT_REVIEW_CYCLE_LIMIT_BEFORE_CABINET)}
- Review rounds after cabinet: {state.get('review_cycle_count_after_cabinet', 0)} / {state.get('review_cycle_limit_after_cabinet', DEFAULT_REVIEW_CYCLE_LIMIT_AFTER_CABINET)}

## Current Next Action

- {state.get('next_action', 'Review project state and continue the workflow.')}

## Recovery Reading Order

1. `ai/state/START_HERE.md`
2. `ai/state/project-meta.json`
3. `ai/state/project-handoff.md`
4. `ai/state/orchestrator-state.json`
5. `ai/state/task-tree.json`
6. recent reports
7. latest run snapshot
8. active role handoffs
"""


def render_project_handoff(project_root: Path, state: dict[str, Any]) -> str:
    sync_review_controls(project_root, state)
    reports = reports_dir(project_root)
    return f"""# Project Handoff

## Current Summary

- Status: {state.get('current_status', 'draft')}
- Current phase: {state.get('current_phase', 'planning')}
- Current workflow: {state.get('current_workflow', 'new-project')}
- Main objective: {state.get('primary_goal', 'advance the governed workflow')}
- Next action: {state.get('next_action', 'review state and continue')}
- Next owner: {state.get('next_owner', 'orchestrator')}
- Highest priority: {state.get('priority_top', 'P1')}
- Blocker level: {state.get('blocker_level', 'none')}
- Mainline status: {state.get('mainline_status', 'not-started')}
- Review phase: {state.get('review_phase', 'normal-review')}
- Review escalation level: {state.get('review_escalation_level', 'none')}
- Review rounds before cabinet: {state.get('review_cycle_count_before_cabinet', 0)} / {state.get('review_cycle_limit_before_cabinet', DEFAULT_REVIEW_CYCLE_LIMIT_BEFORE_CABINET)}
- Review rounds after cabinet: {state.get('review_cycle_count_after_cabinet', 0)} / {state.get('review_cycle_limit_after_cabinet', DEFAULT_REVIEW_CYCLE_LIMIT_AFTER_CABINET)}
- Latest plan review conclusion: {extract_conclusion(read_text(reports / 'architecture-review.md'), 'Conclusion') or 'pending'}
- Latest result audit conclusion: {extract_conclusion(read_text(reports / 'acceptance-report.md'), 'Final Conclusion') or 'pending'}
- Latest test conclusion: {extract_conclusion(read_text(reports / 'test-report.md'), 'Recommendation') or 'pending'}
- Resource gap count: {len(state.get('resource_gaps', [])) if isinstance(state.get('resource_gaps'), list) else 0}
- Resource gap report: {state.get('resource_gap_report_path') or 'pending'}

## Completed

- {', '.join(state.get('workflow_progress', {}).get('completed_steps', [])[-3:]) or 'None'}

## In Progress

- {', '.join(task.get('workflow_step_id') or task.get('task_id') for task in state.get('active_tasks', [])) or 'None'}

## Blocked

- {', '.join(str(item) for item in state.get('blockers', [])) or 'None'}

## Notes For Next Round

- Continue from `{state.get('current_workflow', 'new-project')}` and obey the current reports and handoffs.
"""


def sync_state_views(project_root: Path, state: dict[str, Any]) -> None:
    write_text(project_root / "ai" / "state" / "START_HERE.md", render_start_here(project_root, state))
    write_text(project_root / "ai" / "state" / "project-handoff.md", render_project_handoff(project_root, state))


def write_project_identity(project_root: Path, state: dict[str, Any]) -> dict[str, Any]:
    info = inspect_project(project_root, intent=determine_intent(str(state.get("current_workflow", ""))))
    project_meta = {
        "project_name": info.get("project_name", project_root.name),
        "project_id": info.get("project_id", project_root.name),
        "project_root": str(project_root.resolve()),
        "mode": info.get("mode", "project_mode"),
        "scenario": info.get("scenario", "new-project"),
        "updated_at": utc_now(),
    }
    write_json(meta_path(project_root), project_meta)
    write_json(reports_dir(project_root) / "project-inspection.json", info)
    write_text(
        reports_dir(project_root) / "project-inspection.md",
        "# Project Inspection\n\n"
        f"- scenario: {info.get('scenario', 'unknown')}\n"
        f"- mode: {info.get('mode', 'unknown')}\n"
        f"- next_action: {info.get('next_action', 'review project state')}\n"
        f"- execution_ready: {'yes' if info.get('execution_ready') else 'no'}\n",
    )
    return info


def create_snapshot(project_root: Path, label: str) -> str:
    run_id = f"{utc_now().replace(':', '').replace('+00:00', 'Z')}-{slugify(label)}"
    run_dir = project_root / "ai" / "runs" / run_id
    steps_dir = run_dir / "steps"
    steps_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        run_dir / "metadata.json",
        {
            "run_id": run_id,
            "label": label,
            "created_at": utc_now(),
            "project_root": str(project_root.resolve()),
        },
    )
    write_text(
        run_dir / "summary.md",
        f"""# Run Summary

- Run id: {run_id}
- Label: {label}
- Created at: {utc_now()}
- Main objective: local orchestrator execution
- Next action: continue the current workflow
""",
    )
    return run_id


def review_limit_value(state: dict[str, Any], field_name: str, default: int) -> int:
    raw = state.get(field_name, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return value if value > 0 else default


def ensure_review_controls(state: dict[str, Any]) -> None:
    state["review_cycle_limit_before_cabinet"] = review_limit_value(
        state,
        "review_cycle_limit_before_cabinet",
        DEFAULT_REVIEW_CYCLE_LIMIT_BEFORE_CABINET,
    )
    state["review_cycle_limit_after_cabinet"] = review_limit_value(
        state,
        "review_cycle_limit_after_cabinet",
        DEFAULT_REVIEW_CYCLE_LIMIT_AFTER_CABINET,
    )
    state["review_cycle_count_before_cabinet"] = max(0, int(state.get("review_cycle_count_before_cabinet", 0) or 0))
    state["review_cycle_count_after_cabinet"] = max(0, int(state.get("review_cycle_count_after_cabinet", 0) or 0))
    state.setdefault("review_phase", "normal-review")
    state.setdefault("review_escalation_level", "none")
    state.setdefault("review_last_blockers", [])
    state.setdefault("review_last_blocker_categories", [])
    state.setdefault("review_last_recommendation", "pending")
    state.setdefault("cabinet_replan_triggered", False)


def sync_review_controls(project_root: Path, state: dict[str, Any]) -> None:
    ensure_review_controls(state)
    payload = read_json(review_controls_path(project_root))
    if payload:
        state["review_cycle_limit_before_cabinet"] = review_limit_value(
            payload,
            "review_cycle_limit_before_cabinet",
            state["review_cycle_limit_before_cabinet"],
        )
        state["review_cycle_limit_after_cabinet"] = review_limit_value(
            payload,
            "review_cycle_limit_after_cabinet",
            state["review_cycle_limit_after_cabinet"],
        )
    write_json(
        review_controls_path(project_root),
        {
            "review_cycle_limit_before_cabinet": state["review_cycle_limit_before_cabinet"],
            "review_cycle_limit_after_cabinet": state["review_cycle_limit_after_cabinet"],
            "updated_at": utc_now(),
        },
    )


def reset_workflow_steps(state: dict[str, Any], step_ids: list[str]) -> None:
    progress = state.setdefault("workflow_progress", {})
    for bucket in ["completed_steps", "blocked_steps", "dispatched_steps"]:
        progress.setdefault(bucket, [])
        progress[bucket] = [item for item in progress.get(bucket, []) if str(item) not in step_ids]
    state["active_tasks"] = [
        task for task in state.get("active_tasks", []) if str(task.get("workflow_step_id") or "") not in step_ids
    ]


def classify_blocker_item(text: str) -> str:
    lowered = text.strip().lower()
    if any(token in lowered for token in ["api", "interface", "contract"]):
        return "interface-contract"
    if any(token in lowered for token in ["schema", "migration", "db", "data"]):
        return "schema-data"
    if any(token in lowered for token in ["requirement", "scope", "acceptance", "customer"]):
        return "requirement-scope"
    if any(token in lowered for token in ["release", "rollback", "deploy", "mainline"]):
        return "release-risk"
    if any(token in lowered for token in ["test", "coverage", "regression", "qa"]):
        return "test-coverage"
    if any(token in lowered for token in ["ui", "page", "flow", "frontend", "screen"]):
        return "ui-flow"
    if any(token in lowered for token in ["dependency", "handoff", "coordination", "reviewer"]):
        return "dependency-coordination"
    return "general-review"


def blocker_categories(blockers: list[str]) -> list[str]:
    categories: list[str] = []
    for item in blockers:
        category = classify_blocker_item(item)
        if category not in categories:
            categories.append(category)
    return categories


def matrix_review_snapshot(project_root: Path) -> dict[str, Any]:
    matrix_text = read_text(reports_dir(project_root) / "department-approval-matrix.md")
    recommendation = extract_conclusion(matrix_text, "Recommendation").upper() or "PENDING"
    blockers_raw = extract_field_value(matrix_text, "blockers")
    blockers = [
        item.strip()
        for item in blockers_raw.split(",")
        if item.strip() and item.strip().lower() not in {"none", "n/a", "na"}
    ]
    categories_raw = extract_field_value(matrix_text, "blocker categories")
    categories = [
        item.strip()
        for item in categories_raw.split(",")
        if item.strip() and item.strip().lower() not in {"none", "n/a", "na"}
    ]
    if not categories:
        categories = blocker_categories(blockers)
    return {
        "recommendation": recommendation,
        "blockers": blockers,
        "categories": categories,
        "matrix_text": matrix_text,
    }


def append_review_history(project_root: Path, state: dict[str, Any], review_report: dict[str, Any], outcome: str) -> None:
    reports = reports_dir(project_root)
    history_path = reports / "review-history.json"
    existing = read_json(history_path)
    entries = existing.get("entries", []) if isinstance(existing, dict) else []
    entry = {
        "created_at": utc_now(),
        "workflow": state.get("current_workflow", "feature-delivery"),
        "review_phase": state.get("review_phase", "normal-review"),
        "review_cycle_count_before_cabinet": state.get("review_cycle_count_before_cabinet", 0),
        "review_cycle_limit_before_cabinet": state.get(
            "review_cycle_limit_before_cabinet", DEFAULT_REVIEW_CYCLE_LIMIT_BEFORE_CABINET
        ),
        "review_cycle_count_after_cabinet": state.get("review_cycle_count_after_cabinet", 0),
        "review_cycle_limit_after_cabinet": state.get(
            "review_cycle_limit_after_cabinet", DEFAULT_REVIEW_CYCLE_LIMIT_AFTER_CABINET
        ),
        "recommendation": review_report.get("recommendation", "PENDING"),
        "blockers": review_report.get("blockers", []),
        "categories": review_report.get("categories", []),
        "outcome": outcome,
    }
    entries.append(entry)
    payload = {"entries": entries}
    write_json(history_path, payload)
    lines = ["# Review History", ""]
    for item in entries:
        lines.extend(
            [
                f"## {item['created_at']}",
                "",
                f"- workflow: {item['workflow']}",
                f"- review_phase: {item['review_phase']}",
                f"- before_cabinet_rounds: {item['review_cycle_count_before_cabinet']} / {item['review_cycle_limit_before_cabinet']}",
                f"- after_cabinet_rounds: {item['review_cycle_count_after_cabinet']} / {item['review_cycle_limit_after_cabinet']}",
                f"- recommendation: {item['recommendation']}",
                f"- blocker categories: {', '.join(item['categories']) if item['categories'] else 'none'}",
                f"- outcome: {item['outcome']}",
                "- blockers:",
            ]
        )
        if item["blockers"]:
            lines.extend(f"  - {blocker}" for blocker in item["blockers"])
        else:
            lines.append("  - none")
        lines.append("")
    write_text(reports / "review-history.md", "\n".join(lines))


def write_cabinet_replan_report(project_root: Path, state: dict[str, Any], review_report: dict[str, Any]) -> None:
    reports = reports_dir(project_root)
    payload = {
        "created_at": utc_now(),
        "current_workflow": state.get("current_workflow", "feature-delivery"),
        "review_cycle_count_before_cabinet": state.get("review_cycle_count_before_cabinet", 0),
        "review_cycle_limit_before_cabinet": state.get(
            "review_cycle_limit_before_cabinet", DEFAULT_REVIEW_CYCLE_LIMIT_BEFORE_CABINET
        ),
        "recommendation": review_report.get("recommendation", "PENDING"),
        "blockers": review_report.get("blockers", []),
        "categories": review_report.get("categories", []),
        "next_owner": "neige",
        "next_action": "Replan with neige and duchayuan before implementation resumes.",
    }
    write_json(reports / "cabinet-replan-report.json", payload)
    write_text(
        reports / "cabinet-replan-report.md",
        "\n".join(
            [
                "# Cabinet Replan Report",
                "",
                f"- created_at: {payload['created_at']}",
                f"- current_workflow: {payload['current_workflow']}",
                f"- review_rounds_before_cabinet: {payload['review_cycle_count_before_cabinet']} / {payload['review_cycle_limit_before_cabinet']}",
                f"- recommendation: {payload['recommendation']}",
                f"- blocker categories: {', '.join(payload['categories']) if payload['categories'] else 'none'}",
                f"- next_owner: {payload['next_owner']}",
                f"- next_action: {payload['next_action']}",
                "",
                "## Problems Requiring Cabinet Replan",
                "",
                *([f"- {item}" for item in payload["blockers"]] if payload["blockers"] else ["- none"]),
            ]
        ),
    )


def render_customer_decision_required_markdown(project_root: Path, state: dict[str, Any], review_report: dict[str, Any]) -> str:
    options = [
        "选项 A：缩小本轮范围，只保留核心目标继续。",
        "选项 B：重新确认需求与验收标准，再开启新一轮规划。",
        "选项 C：暂停当前批次，待条件成熟后再恢复。",
        "选项 D：终止当前批次。",
    ]
    blockers = review_report.get("blockers") or ["当前联审问题仍未收敛。"]
    categories = review_report.get("categories") or blocker_categories(blockers)
    return "\n".join(
        [
            "# Customer Decision Required",
            "",
            "## 当前背景",
            "",
            f"- 当前工作流: {state.get('current_workflow', 'feature-delivery')}",
            f"- 当前阶段: {state.get('current_phase', 'customer-decision')}",
            f"- 当前状态: {state.get('current_status', 'await-customer-decision')}",
            f"- 主目标: {state.get('primary_goal', 'resolve the current governed delivery batch')}",
            f"- 已完成一次内阁重规划: {'yes' if state.get('cabinet_replan_triggered') else 'no'}",
            "",
            "## 当前结论",
            "",
            "- 本轮在内阁重规划后仍未通过审查。",
            "- 已超过当前允许的第二阶段审查上限。",
            "- 团队不建议继续按当前方案直接推进开发。",
            "",
            "## 当前关键问题",
            "",
            f"- 问题分类: {', '.join(categories) if categories else 'general-review'}",
            *[f"- {item}" for item in blockers],
            "",
            "## 风险说明",
            "",
            "- 若继续按当前方案推进，范围、质量和交付节奏将继续失控。",
            "- 当前实现与目标边界仍未稳定，继续投入会放大返工和回滚风险。",
            "",
            "## 已做过的处理",
            "",
            f"- 第一阶段联审轮次: {state.get('review_cycle_count_before_cabinet', 0)} / {state.get('review_cycle_limit_before_cabinet', DEFAULT_REVIEW_CYCLE_LIMIT_BEFORE_CABINET)}",
            f"- 第二阶段联审轮次: {state.get('review_cycle_count_after_cabinet', 0)} / {state.get('review_cycle_limit_after_cabinet', DEFAULT_REVIEW_CYCLE_LIMIT_AFTER_CABINET)}",
            f"- 最近联审结论: {review_report.get('recommendation', 'PENDING')}",
            "- 已进行一次内阁重规划并重新进入审查。",
            "",
            "## 建议选项",
            "",
            *[f"- {item}" for item in options],
            "",
            "## 请客户确认",
            "",
            "- 请明确选择下一步方向，再恢复项目推进。",
        ]
    ) + "\n"


def customer_decision_options(state: dict[str, Any], review_report: dict[str, Any]) -> list[dict[str, str]]:
    blockers = review_report.get("blockers", [])
    blocker_summary = blockers[0] if blockers else "The current plan is still failing review after the cabinet replan."
    return [
        {
            "id": "option-a",
            "title": "Reduce scope",
            "summary": "Drop non-critical items from the current batch and continue only with the smallest shippable slice.",
            "tradeoff": "Delivery stays moving, but some requested outcomes are deferred.",
        },
        {
            "id": "option-b",
            "title": "Reconfirm requirement and acceptance",
            "summary": f"Re-open the plan boundary around: {blocker_summary}",
            "tradeoff": "Most reliable path when the goal or acceptance changed, but it requires another planning pass.",
        },
        {
            "id": "option-c",
            "title": "Pause the batch",
            "summary": "Freeze the current delivery batch until dependencies, evidence, or business timing become clearer.",
            "tradeoff": "Lowest immediate risk, but no further delivery progress happens until the pause is lifted.",
        },
        {
            "id": "option-d",
            "title": "Terminate the batch",
            "summary": "End the current delivery batch and archive the unfinished scope.",
            "tradeoff": "Stops further investment entirely and may require a fresh intake later.",
        },
    ]


def render_customer_decision_required_markdown_v2(state: dict[str, Any], review_report: dict[str, Any]) -> str:
    blockers = review_report.get("blockers") or ["The current review issues are still unresolved."]
    categories = review_report.get("categories") or blocker_categories(blockers)
    options = customer_decision_options(state, review_report)
    option_lines = "\n\n".join(
        "\n".join(
            [
                f"### {item['id'].upper()} {item['title']}",
                f"- summary: {item['summary']}",
                f"- tradeoff: {item['tradeoff']}",
            ]
        )
        for item in options
    )
    return "\n".join(
        [
            "# Customer Decision Required",
            "",
            "## Current Context",
            "",
            "- 当前批次",
            "- legacy_label: 褰撳墠鎵规",
            f"- current_workflow: {state.get('current_workflow', 'feature-delivery')}",
            f"- current_phase: {state.get('current_phase', 'customer-decision')}",
            f"- current_status: {state.get('current_status', 'await-customer-decision')}",
            f"- primary_goal: {state.get('primary_goal', 'resolve the current governed delivery batch')}",
            f"- cabinet_replan_already_used: {'yes' if state.get('cabinet_replan_triggered') else 'no'}",
            "",
            "## Why Automation Stopped",
            "",
            "- The batch still failed review after the cabinet replan.",
            "- The post-cabinet review limit has been exhausted.",
            "- The orchestrator will not continue execution until the customer picks a direction.",
            "",
            "## Key Problems",
            "",
            f"- blocker_categories: {', '.join(categories) if categories else 'general-review'}",
            *[f"- {item}" for item in blockers],
            "",
            "## Risk",
            "",
            "- Continuing without a decision would increase rework, quality drift, and release risk.",
            "- The current implementation boundary is not stable enough for unattended execution.",
            "",
            "## What Has Already Been Tried",
            "",
            f"- review_rounds_before_cabinet: {state.get('review_cycle_count_before_cabinet', 0)} / {state.get('review_cycle_limit_before_cabinet', DEFAULT_REVIEW_CYCLE_LIMIT_BEFORE_CABINET)}",
            f"- review_rounds_after_cabinet: {state.get('review_cycle_count_after_cabinet', 0)} / {state.get('review_cycle_limit_after_cabinet', DEFAULT_REVIEW_CYCLE_LIMIT_AFTER_CABINET)}",
            f"- latest_review_recommendation: {review_report.get('recommendation', 'PENDING')}",
            "- One cabinet replan has already been executed and reviewed again.",
            "",
            "## Guided Options",
            "",
            option_lines,
            "",
            "## What To Confirm",
            "",
            "- Choose one option explicitly, then the orchestrator can thaw the frozen work and continue.",
        ]
    ) + "\n"


def write_customer_decision_required_report(project_root: Path, state: dict[str, Any], review_report: dict[str, Any]) -> None:
    reports = reports_dir(project_root)
    payload = {
        "created_at": utc_now(),
        "current_workflow": state.get("current_workflow", "feature-delivery"),
        "current_phase": state.get("current_phase", "customer-decision"),
        "current_status": state.get("current_status", "await-customer-decision"),
        "review_cycle_count_before_cabinet": state.get("review_cycle_count_before_cabinet", 0),
        "review_cycle_limit_before_cabinet": state.get(
            "review_cycle_limit_before_cabinet", DEFAULT_REVIEW_CYCLE_LIMIT_BEFORE_CABINET
        ),
        "review_cycle_count_after_cabinet": state.get("review_cycle_count_after_cabinet", 0),
        "review_cycle_limit_after_cabinet": state.get(
            "review_cycle_limit_after_cabinet", DEFAULT_REVIEW_CYCLE_LIMIT_AFTER_CABINET
        ),
        "review_recommendation": review_report.get("recommendation", "PENDING"),
        "problems": review_report.get("blockers", []),
        "categories": review_report.get("categories", []),
        "options": customer_decision_options(state, review_report),
    }
    write_json(reports / "customer-decision-required.json", payload)
    write_text(
        reports / "customer-decision-required.md",
        render_customer_decision_required_markdown_v2(state, review_report),
    )


def apply_feature_delivery_review_state(project_root: Path, state: dict[str, Any]) -> None:
    sync_review_controls(project_root, state)
    review_report = matrix_review_snapshot(project_root)
    blockers = review_report.get("blockers", [])
    categories = review_report.get("categories", [])
    recommendation = review_report.get("recommendation", "PENDING")
    state["review_last_blockers"] = blockers
    state["review_last_blocker_categories"] = categories
    state["review_last_recommendation"] = recommendation

    if recommendation in {"PASS", "PASS_WITH_WARNING"} and not blockers:
        append_review_history(project_root, state, review_report, "passed-to-testing")
        state["current_phase"] = "department-review"
        state["current_status"] = "department-review"
        state["execution_allowed"] = True
        state["testing_allowed"] = False
        state["release_allowed"] = False
        state["blockers"] = []
        state["blocker_level"] = "none"
        state["review_escalation_level"] = "none"
        state["next_action"] = "Dispatch formal testing after the six-department review and duchayuan direct review close."
        state["next_owner"] = "bingbu"
        return

    after_cabinet = bool(state.get("cabinet_replan_triggered"))
    if after_cabinet:
        state["review_cycle_count_after_cabinet"] = int(state.get("review_cycle_count_after_cabinet", 0) or 0) + 1
        current_count = state["review_cycle_count_after_cabinet"]
        current_limit = state["review_cycle_limit_after_cabinet"]
    else:
        state["review_cycle_count_before_cabinet"] = int(state.get("review_cycle_count_before_cabinet", 0) or 0) + 1
        current_count = state["review_cycle_count_before_cabinet"]
        current_limit = state["review_cycle_limit_before_cabinet"]

    if current_count <= current_limit:
        append_review_history(project_root, state, review_report, "rework-required")
        reset_workflow_steps(state, FEATURE_DELIVERY_REWORK_RESET_STEPS)
        state["current_phase"] = "implementation"
        state["current_status"] = "review-rework"
        state["execution_allowed"] = True
        state["testing_allowed"] = False
        state["release_allowed"] = False
        state["blockers"] = []
        state["blocker_level"] = "medium"
        state["review_escalation_level"] = "none"
        state["next_action"] = (
            f"Repair review findings and rerun the current implementation batch "
            f"({current_count}/{current_limit} review rounds used in this phase)."
        )
        state["next_owner"] = "orchestrator"
        return

    if not after_cabinet:
        append_review_history(project_root, state, review_report, "escalated-to-cabinet")
        reset_workflow_steps(state, FEATURE_DELIVERY_REPLAN_RESET_STEPS)
        state["cabinet_replan_triggered"] = True
        state["review_phase"] = "cabinet-replan-review"
        state["review_escalation_level"] = "cabinet"
        state["review_cycle_count_after_cabinet"] = 0
        state["current_phase"] = "planning"
        state["current_status"] = "cabinet-review"
        state["execution_allowed"] = False
        state["testing_allowed"] = False
        state["release_allowed"] = False
        state["blockers"] = []
        state["blocker_level"] = "high"
        state["next_action"] = "Review loop exceeded the pre-cabinet limit. Replan with neige and duchayuan before implementation resumes."
        state["next_owner"] = "neige"
        write_cabinet_replan_report(project_root, state, review_report)
        return

    append_review_history(project_root, state, review_report, "customer-decision-required")
    state["review_phase"] = "await-customer-decision"
    state["review_escalation_level"] = "customer"
    state["current_phase"] = "customer-decision"
    state["current_status"] = "await-customer-decision"
    state["execution_allowed"] = False
    state["testing_allowed"] = False
    state["release_allowed"] = False
    state["blockers"] = ["Customer decision required after post-cabinet review limit exceeded."]
    state["blocker_level"] = "high"
    state["next_action"] = "Send the customer decision report, explain the unresolved problems, and wait for explicit direction."
    state["next_owner"] = "orchestrator"
    write_customer_decision_required_report(project_root, state, review_report)


def top_level_implementation_roots(project_root: Path) -> list[str]:
    return [name for name in IMPLEMENTATION_ROOTS if (project_root / name).exists()]


def representative_implementation_files(project_root: Path, limit: int = 12) -> list[str]:
    samples: list[str] = []
    for file_path in sorted(project_root.rglob("*")):
        if not file_path.is_file():
            continue
        relative = file_path.relative_to(project_root)
        if any(part in IMPLEMENTATION_IGNORES for part in relative.parts):
            continue
        if file_path.suffix.lower() not in IMPLEMENTATION_SAMPLE_SUFFIXES:
            continue
        samples.append(relative.as_posix())
        if len(samples) >= limit:
            break
    return samples


def build_current_implementation_summary(project_root: Path) -> None:
    manifests = [name for name in IMPLEMENTATION_MANIFESTS if (project_root / name).exists()]
    roots = top_level_implementation_roots(project_root)
    samples = representative_implementation_files(project_root)
    project_has_code = any(name in roots for name in ["src", "app", "server", "api", "services", "lib", "components", "pages", "db"])
    status_line = (
        "Existing implementation detected and summarized for customer confirmation."
        if project_has_code or manifests or samples
        else "No existing implementation detected yet; this project currently starts from an empty baseline."
    )
    lines = [
        "# Current Implementation Summary",
        "",
        "## Status",
        "",
        f"- {status_line}",
        "",
        "## Observed Surface",
        "",
        f"- top-level implementation roots: {', '.join(roots) if roots else 'none'}",
        f"- manifests and entrypoints: {', '.join(manifests) if manifests else 'none'}",
        "",
        "## Representative Files",
        "",
    ]
    if samples:
        lines.extend(f"- {item}" for item in samples)
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Customer Review Checklist",
            "",
            "- customer reviewed current implementation baseline: pending",
            "- keep / retire / adjust decisions: pending",
        ]
    )
    write_text(reports_dir(project_root) / "current-implementation-summary.md", "\n".join(lines))


def build_takeover_report(project_root: Path) -> None:
    info = inspect_project(project_root, intent="mid-stream-takeover")
    lines = [
        "# First-Round Takeover Result",
        "",
        f"- Project root: {info.get('project_root', str(project_root))}",
        f"- Scenario: {info.get('scenario', 'mid-stream-takeover')}",
        f"- Missing state files: {', '.join(info.get('missing_state_files', [])) or 'none'}",
        f"- Missing report files: {', '.join(info.get('missing_report_files', [])) or 'none'}",
        f"- Missing test layers: {', '.join(info.get('missing_test_layers', [])) or 'none'}",
        f"- Current implementation summary ready: {'yes' if info.get('implementation_summary_ready') else 'no'}",
        f"- Customer acknowledged current implementation baseline: {'yes' if info.get('customer_acknowledged_implementation') else 'no'}",
        f"- Customer confirmed requirement and scope: {'yes' if info.get('customer_confirmed_requirement') else 'no'}",
        f"- Approved to start development: {'yes' if info.get('development_approved') else 'no'}",
        f"- Next action: {info.get('next_action', 'repair governance and continue planning')}",
    ]
    write_text(reports_dir(project_root) / "takeover-report.md", "\n".join(lines))
    write_json(reports_dir(project_root) / "takeover-report.json", info)


def planning_follow_up(info: dict[str, Any]) -> str:
    actions: list[str] = []
    if not info.get("architecture_ready"):
        actions.append("write architecture.md with the approved system design")
    if not info.get("task_tree_ready"):
        actions.append("write task-tree.json with the approved execution breakdown")
    if info.get("implementation_baseline_required") and not info.get("implementation_summary_ready"):
        actions.append("write current-implementation-summary.md from the existing codebase")
    if info.get("implementation_baseline_required") and not info.get("customer_acknowledged_implementation"):
        actions.append("send the current implementation summary to the customer and record acknowledgement")
    if not info.get("plan_review_passed"):
        actions.append("complete architecture-review.md with a PASS-level document review result")
    if not info.get("customer_confirmed_requirement"):
        actions.append("capture the customer-confirmed requirement and scope in task-intake.md")
    if not info.get("frozen_requirement_present"):
        actions.append("freeze the approved requirement in task-intake.md")
    if not info.get("development_approved"):
        actions.append("record explicit customer approval to start development")
    return actions[0] if actions else "Continue the governed workflow."


def planning_guided_options(info: dict[str, Any]) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    if not info.get("architecture_ready") or not info.get("task_tree_ready"):
        options.append(
            {
                "id": "option-a",
                "title": "Finish the planning package",
                "summary": "Complete architecture.md, task-tree.json, and plan review before any execution starts.",
                "tradeoff": "Safest path for unattended delivery, but it delays implementation until the planning surface is complete.",
            }
        )
    if info.get("implementation_baseline_required") and (
        not info.get("implementation_summary_ready") or not info.get("customer_acknowledged_implementation")
    ):
        options.append(
            {
                "id": "option-b",
                "title": "Freeze the current baseline first",
                "summary": "Summarize the existing implementation, have the customer acknowledge it, then convert requirements into the next batch plan.",
                "tradeoff": "Best for takeover projects, but it adds a confirmation checkpoint before planning can finish.",
            }
        )
    if not info.get("customer_confirmed_requirement") or not info.get("development_approved"):
        options.append(
            {
                "id": "option-c",
                "title": "Clarify scope with the customer",
                "summary": "Stop expanding the plan until the requirement boundary, acceptance criteria, and permission to start are all explicit.",
                "tradeoff": "Removes ambiguity, but requires a customer reply before autonomy can continue.",
            }
        )
    if not options:
        options.append(
            {
                "id": "option-a",
                "title": "Continue the governed workflow",
                "summary": "The planning surface is already coherent; continue through the normal plan approval flow.",
                "tradeoff": "No special intervention required.",
            }
        )
    return options


def write_planning_options_report(project_root: Path, info: dict[str, Any]) -> None:
    options = planning_guided_options(info)
    content = [
        "# Planning Options",
        "",
        f"- current_status: {info.get('current_status', 'draft')}",
        f"- planning_ready: {'yes' if info.get('planning_ready') else 'no'}",
        f"- next_action: {info.get('next_action', 'continue planning')}",
        "",
        "## Guided Options",
        "",
    ]
    for item in options:
        content.extend(
            [
                f"### {item['id'].upper()} {item['title']}",
                f"- summary: {item['summary']}",
                f"- tradeoff: {item['tradeoff']}",
                "",
            ]
        )
    write_text(reports_dir(project_root) / "planning-options.md", "\n".join(content).rstrip() + "\n")


def build_department_matrix(project_root: Path, state: dict[str, Any], step_id: str) -> None:
    sync_review_controls(project_root, state)
    handoff_root = project_root / "ai" / "handoff"
    registry = load_registry(project_root, ensure_defaults=True)
    blockers: list[str] = []
    warnings: list[str] = []
    sections: list[str] = [
        "# Department Approval Matrix",
        "",
        "## Round",
        "",
        f"- {step_id}",
        "",
        "## Scope",
        "",
        f"- workflow: {state.get('current_workflow', 'feature-delivery')}",
        f"- review_phase: {state.get('review_phase', 'normal-review')}",
        f"- review_rounds_before_cabinet: {state.get('review_cycle_count_before_cabinet', 0)} / {state.get('review_cycle_limit_before_cabinet', DEFAULT_REVIEW_CYCLE_LIMIT_BEFORE_CABINET)}",
        f"- review_rounds_after_cabinet: {state.get('review_cycle_count_after_cabinet', 0)} / {state.get('review_cycle_limit_after_cabinet', DEFAULT_REVIEW_CYCLE_LIMIT_AFTER_CABINET)}",
        "",
    ]
    review_roles = CROSS_REVIEW_ROLES if step_id == "department-review" and state.get("current_workflow") == "feature-delivery" else DEPARTMENT_ROLES
    for reviewer in review_roles:
        sections.extend([f"## Reviewer {reviewer}", ""])
        findings: list[str] = []
        for peer in review_roles:
            if peer == reviewer:
                continue
            session = registry.get(peer, {}) if isinstance(registry, dict) else {}
            handoff_value = str(session.get("handoff_path") or "").strip()
            if not handoff_value:
                sections.append(f"- {peer}: BLOCKER")
                findings.append(f"missing current handoff from {peer}")
                blockers.append(f"missing current handoff from {peer}")
                continue
            candidate = Path(handoff_value)
            if not candidate.is_absolute():
                candidate = project_root / candidate
            candidate = candidate.resolve()
            try:
                candidate.relative_to(handoff_root.resolve())
            except ValueError:
                sections.append(f"- {peer}: BLOCKER")
                findings.append(f"{peer} reported an invalid handoff path")
                blockers.append(f"{peer} reported an invalid handoff path")
                continue
            if not candidate.exists():
                sections.append(f"- {peer}: BLOCKER")
                findings.append(f"missing current handoff from {peer}")
                blockers.append(f"missing current handoff from {peer}")
                continue
            text = read_text(candidate)
            role_status = extract_field_value(text, "status").lower() or "completed"
            role_blockers = extract_field_value(text, "blockers").lower()
            if role_status in {"blocked", "failed", "rework", "redesign"} or (role_blockers and role_blockers != "none"):
                blocker_note = f"{peer} blockers: {role_blockers}" if role_blockers and role_blockers != "none" else f"{peer} reported blockers"
                sections.append(f"- {peer}: BLOCKER")
                findings.append(blocker_note)
                blockers.append(blocker_note)
            else:
                sections.append(f"- {peer}: PASS")
        sections.append(f"- findings: {', '.join(sorted(set(findings))) if findings else 'none'}")
        sections.append("- responses: none")
        sections.append(f"- closure: {'closed' if not findings else 'open'}")
        sections.append("")

    recommendation = "PASS" if not blockers else "BLOCKER"
    categories = blocker_categories(sorted(set(blockers)))
    sections.extend(
        [
            "## Aggregated Issues",
            "",
            f"- blockers: {', '.join(sorted(set(blockers))) if blockers else 'none'}",
            f"- blocker categories: {', '.join(categories) if categories else 'none'}",
            f"- warnings: {', '.join(sorted(set(warnings))) if warnings else 'none'}",
            "- suggestions: none",
            "- conflicts needing arbitration: none",
            "",
            "## Recommendation",
            "",
            f"- {recommendation}",
        ]
    )
    write_text(reports_dir(project_root) / "department-approval-matrix.md", "\n".join(sections))


def apply_post_completion_state(project_root: Path, step: WorkflowStep) -> None:
    path = state_path(project_root)
    state = read_json(path)
    sync_review_controls(project_root, state)
    workflow = str(state.get("current_workflow", ""))
    if step.id == "identify-project":
        state["next_action"] = "Bootstrap governance checks and prepare the first run snapshot."
        state["next_owner"] = "orchestrator"
    elif step.id in {"bootstrap-governance", "backfill-governance"}:
        state["next_action"] = "Create a fresh run snapshot and continue planning."
        state["next_owner"] = "orchestrator"
    elif step.id == "create-run-snapshot":
        state["next_action"] = "Dispatch the planning owner to freeze the initial plan."
        state["next_owner"] = "neige"
    elif step.id == "inspect-governance":
        state["next_action"] = "Backfill the missing governance surface before planning repair."
        state["next_owner"] = "orchestrator"
    elif step.id == "read-recovery-entry":
        state["next_action"] = "Read the latest reports before producing the recovery summary."
        state["next_owner"] = "orchestrator"
    elif step.id == "read-latest-reports":
        state["next_action"] = "Read active handoffs and session state."
        state["next_owner"] = "orchestrator"
    elif step.id == "read-active-handoffs":
        state["next_action"] = "Produce the recovery summary and decide the next governed action."
        state["next_owner"] = "orchestrator"
    elif step.id == "produce-recovery-summary":
        state["next_action"] = "Review the recovery summary and choose the next governed workflow."
        state["next_owner"] = "orchestrator"
    elif step.id == "intake-feature":
        state["current_phase"] = "planning"
        state["current_status"] = "planning"
        state["review_phase"] = "normal-review"
        state["review_escalation_level"] = "none"
        state["review_cycle_count_before_cabinet"] = 0
        state["review_cycle_count_after_cabinet"] = 0
        state["cabinet_replan_triggered"] = False
        state["review_last_blockers"] = []
        state["review_last_recommendation"] = "pending"
        state["next_action"] = "Dispatch plan impact review and freeze the updated scope."
        state["next_owner"] = "neige"
    elif step.id in {"department-review", "collect-department-approvals"}:
        if workflow == "feature-delivery" and step.id == "department-review":
            apply_feature_delivery_review_state(project_root, state)
        else:
            state["current_phase"] = "department-review"
            state["current_status"] = "department-review"
            state["next_action"] = "Dispatch the final audit with the latest matrix and reports."
            state["next_owner"] = "duchayuan"
    elif step.id in {"update-state-and-handoff", "update-state-and-run-summary"}:
        if workflow in {"new-project", "takeover-project"}:
            info = inspect_project(project_root, intent=determine_intent(workflow))
            if info.get("planning_ready"):
                state["current_workflow"] = "feature-delivery"
                state["current_phase"] = "planning"
                state["current_status"] = "plan-approved"
                state["review_phase"] = "normal-review"
                state["review_escalation_level"] = "none"
                state["review_cycle_count_before_cabinet"] = 0
                state["review_cycle_count_after_cabinet"] = 0
                state["cabinet_replan_triggered"] = False
                state["review_last_blockers"] = []
                state["review_last_recommendation"] = "pending"
                state["execution_allowed"] = True
                state["testing_allowed"] = False
                state["release_allowed"] = False
                state["next_action"] = "Dispatch the first implementation batch under feature-delivery."
                state["next_owner"] = "orchestrator"
            else:
                state["current_phase"] = "planning"
                state["current_status"] = "draft"
                state["execution_allowed"] = False
                state["testing_allowed"] = False
                state["release_allowed"] = False
                options = planning_guided_options(info)
                if len(options) > 1 or any(item.get("id") != "option-a" for item in options):
                    write_planning_options_report(project_root, info)
                    state["next_action"] = (
                        "Review ai/reports/planning-options.md, choose the most suitable planning route, and then continue with the first required action: "
                        + planning_follow_up(info)
                    )
                else:
                    state["next_action"] = planning_follow_up(info)
                state["next_owner"] = "orchestrator"
        elif workflow == "resume-orchestrator":
            state["next_action"] = "Review the recovery summary and choose the next governed workflow."
            state["next_owner"] = "orchestrator"
        else:
            state["current_phase"] = "final-audit"
            state["current_status"] = "accepted"
            state["execution_allowed"] = True
            state["testing_allowed"] = True
            state["next_action"] = "Run project guard and decide whether to commit or release."
            state["next_owner"] = "orchestrator"
    sync_state_views(project_root, state)
    write_json(path, state)


def execute_local_step(project_root: Path, step: WorkflowStep, task_id: str) -> dict[str, Any]:
    ensure_governance_surface(project_root)
    state = read_json(state_path(project_root))
    step_summary = f"Locally executed orchestrator step `{step.id}`."
    if step.id == "identify-project":
        info = write_project_identity(project_root, state)
        state.update(
            {
                "project_id": info.get("project_id", project_root.name),
                "project_name": info.get("project_name", project_root.name),
                "primary_goal": state.get("primary_goal", "Establish governed project structure and freeze the initial plan."),
            }
        )
        write_json(state_path(project_root), state)
        sync_state_views(project_root, state)
        step_summary = f"Inspected the project and refreshed project-meta for `{info.get('project_id', project_root.name)}`."
    elif step.id in {"bootstrap-governance", "backfill-governance"}:
        ensure_governance_surface(project_root)
        sync_state_views(project_root, state)
        step_summary = "Verified governance directories, tests, and handoff roots."
    elif step.id == "create-run-snapshot":
        run_id = create_snapshot(project_root, step.id)
        state["current_run_id"] = run_id
        write_json(state_path(project_root), state)
        step_summary = f"Created run snapshot `{run_id}`."
    elif step.id == "inspect-governance":
        build_current_implementation_summary(project_root)
        build_takeover_report(project_root)
        step_summary = "Generated the current implementation summary and the first-round takeover governance report."
    elif step.id == "read-recovery-entry":
        step_summary = "Read the project recovery entry points and current orchestrator state."
    elif step.id == "read-latest-reports":
        step_summary = "Reviewed the latest reports to rebuild recovery context."
    elif step.id == "read-active-handoffs":
        step_summary = "Reviewed active role handoffs and session state."
    elif step.id == "produce-recovery-summary":
        summary = build_summary(project_root)
        write_text(reports_dir(project_root) / "recovery-summary.md", summary)
        step_summary = "Generated the recovery summary for the parent controller."
    elif step.id == "intake-feature":
        write_text(
            reports_dir(project_root) / "feature-intake.md",
            "# Feature Intake\n\n"
            f"- created_at: {utc_now()}\n"
            f"- workflow: {state.get('current_workflow', 'feature-delivery')}\n"
            f"- primary_goal: {state.get('primary_goal', 'review incoming work')}\n",
        )
        step_summary = "Captured the current feature intake and queued planning review."
    elif step.id in {"department-review", "collect-department-approvals"}:
        build_department_matrix(project_root, state, step.id)
        step_summary = "Aggregated the latest six-department review handoffs and duchayuan review into the approval matrix."
    elif step.id in {"update-state-and-handoff", "update-state-and-run-summary"}:
        sync_state_views(project_root, state)
        write_text(
            reports_dir(project_root) / "run-summary.md",
            "# Run Summary\n\n"
            f"- workflow: {state.get('current_workflow', 'unknown')}\n"
            f"- completed_at: {utc_now()}\n"
            f"- completed_steps: {', '.join(state.get('workflow_progress', {}).get('completed_steps', [])) or 'none'}\n",
        )
        step_summary = "Refreshed orchestrator state views and run summary."

    handoff_relative = f"ai/handoff/orchestrator/active/{task_id}.md"
    result = consume_completion(
        project_root,
        {
            "agent_id": "orchestrator",
            "task_id": task_id,
            "workflow_step_id": step.id,
            "status": "completed",
            "summary": step_summary,
            "handoff_path": handoff_relative,
        },
        allow_untracked_completion=True,
    )
    apply_post_completion_state(project_root, step)
    return {
        "task_id": task_id,
        "step_id": step.id,
        "role": step.role,
        "status": "local-completed",
        "handoff_path": result["handoff_path"],
        "summary": step_summary,
    }
