from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import parse_bool, require_valid_json, utc_now, write_json, write_text


VALID_POLICIES = {"block", "mock", "skip"}
VALID_DUE_STAGES = {"immediate", "testing", "release"}
VALID_SCOPE_LEVELS = {"task", "milestone", "module", "project"}
VALID_RESOURCE_CATEGORIES = {"credential", "real-api", "account", "permission", "device", "sandbox", "other"}
OPEN_RESOURCE_STATUSES = {"open", "deferred", "retest-pending"}

RESOURCE_DEFAULTS = {
    "resource_policy": {
        "default_policy": "mock",
        "categories": {
            "credential": "mock",
            "real-api": "mock",
            "account": "skip",
            "permission": "skip",
            "device": "skip",
            "sandbox": "mock",
            "other": "mock",
        },
        "release_requires_real_validation": True,
    },
    "resource_gaps": [],
    "resource_gap_history": [],
    "resource_gap_report_path": None,
}


def state_path(project_root: Path) -> Path:
    return project_root / "ai" / "state" / "orchestrator-state.json"


def reports_dir(project_root: Path) -> Path:
    path = project_root / "ai" / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value))


def ensure_resource_state(state: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    changed = False
    for key, value in RESOURCE_DEFAULTS.items():
        if key not in state:
            state[key] = _clone(value)
            changed = True

    policy = state.get("resource_policy")
    if not isinstance(policy, dict):
        policy = _clone(RESOURCE_DEFAULTS["resource_policy"])
        state["resource_policy"] = policy
        changed = True
    if str(policy.get("default_policy", "")).strip().lower() not in VALID_POLICIES:
        policy["default_policy"] = RESOURCE_DEFAULTS["resource_policy"]["default_policy"]
        changed = True
    categories = policy.get("categories")
    if not isinstance(categories, dict):
        categories = {}
        policy["categories"] = categories
        changed = True
    for category, default_policy in RESOURCE_DEFAULTS["resource_policy"]["categories"].items():
        normalized = str(categories.get(category, default_policy) or default_policy).strip().lower()
        if normalized not in VALID_POLICIES:
            normalized = default_policy
        if categories.get(category) != normalized:
            categories[category] = normalized
            changed = True
    normalized_release_validation = parse_bool(policy.get("release_requires_real_validation", True), default=True)
    if policy.get("release_requires_real_validation") != normalized_release_validation:
        policy["release_requires_real_validation"] = normalized_release_validation
        changed = True

    gaps = state.get("resource_gaps")
    if not isinstance(gaps, list):
        state["resource_gaps"] = []
        gaps = state["resource_gaps"]
        changed = True
    history = state.get("resource_gap_history")
    if not isinstance(history, list):
        state["resource_gap_history"] = []
        changed = True

    for gap in gaps:
        if not isinstance(gap, dict):
            continue
        policy_value = str(gap.get("policy", "")).strip().lower()
        if policy_value not in VALID_POLICIES:
            gap["policy"] = policy.get("default_policy", "mock")
            changed = True
        due_stage = str(gap.get("due_stage", "")).strip().lower()
        if due_stage not in VALID_DUE_STAGES:
            gap["due_stage"] = "immediate" if gap.get("policy") == "block" else "release"
            changed = True
        scope_level = str(gap.get("scope_level", "")).strip().lower()
        if scope_level not in VALID_SCOPE_LEVELS:
            gap["scope_level"] = "project"
            changed = True
        category = str(gap.get("category", "")).strip().lower()
        if category not in VALID_RESOURCE_CATEGORIES:
            gap["category"] = "other"
            changed = True
        status = str(gap.get("status", "")).strip().lower()
        if not status:
            gap["status"] = "open" if gap.get("policy") == "block" else "deferred"
            changed = True
        gap.setdefault("real_validation_required", bool(gap.get("policy") in {"mock", "skip"}))
        gap.setdefault("retest_required", False)
        gap.setdefault("retest_status", "not-required")
        gap.setdefault("scope_label", "")
        gap.setdefault("notes", "")
        gap.setdefault("resolution_summary", "")
        gap.setdefault("created_at", utc_now())
        gap.setdefault("updated_at", gap.get("created_at"))
        gap.setdefault("resolved_at", None)
        gap.setdefault("retested_at", None)
        gap.setdefault("supplied_by", None)
        if "module_id" not in gap:
            gap["module_id"] = None
            changed = True
        if "milestone_id" not in gap:
            gap["milestone_id"] = None
            changed = True
    return state, changed


def load_state(project_root: Path) -> dict[str, Any]:
    payload = require_valid_json(state_path(project_root), "ai/state/orchestrator-state.json")
    payload, changed = ensure_resource_state(payload)
    if changed:
        write_json(state_path(project_root), payload)
    return payload


def save_state(project_root: Path, state: dict[str, Any]) -> None:
    ensure_resource_state(state)
    write_json(state_path(project_root), state)


def effective_policy(state: dict[str, Any], category: str, explicit_policy: str | None = None) -> str:
    normalized = str(explicit_policy or "").strip().lower()
    if normalized in VALID_POLICIES:
        return normalized
    policy = state.get("resource_policy") if isinstance(state.get("resource_policy"), dict) else {}
    categories = policy.get("categories") if isinstance(policy.get("categories"), dict) else {}
    category_policy = str(categories.get(category, "")).strip().lower()
    if category_policy in VALID_POLICIES:
        return category_policy
    default_policy = str(policy.get("default_policy", "mock")).strip().lower()
    return default_policy if default_policy in VALID_POLICIES else "mock"


def _find_gap(state: dict[str, Any], gap_id: str) -> dict[str, Any]:
    for gap in state.get("resource_gaps", []):
        if isinstance(gap, dict) and str(gap.get("gap_id") or "") == gap_id:
            return gap
    raise ValueError(f"Unknown resource gap: {gap_id}")


def _open_gap_with_same_identity(
    state: dict[str, Any],
    resource_name: str,
    category: str,
    scope_level: str,
    scope_label: str,
) -> dict[str, Any] | None:
    for gap in state.get("resource_gaps", []):
        if not isinstance(gap, dict):
            continue
        if str(gap.get("status") or "").strip().lower() == "closed":
            continue
        if (
            str(gap.get("resource_name") or "") == resource_name
            and str(gap.get("category") or "") == category
            and str(gap.get("scope_level") or "") == scope_level
            and str(gap.get("scope_label") or "") == scope_label
        ):
            return gap
    return None


def _history_append(state: dict[str, Any], gap_id: str, action: str, summary: str) -> None:
    history = state.get("resource_gap_history")
    if not isinstance(history, list):
        history = []
        state["resource_gap_history"] = history
    history.append(
        {
            "gap_id": gap_id,
            "action": action,
            "summary": summary,
            "created_at": utc_now(),
        }
    )


def _gap_slug(resource_name: str) -> str:
    token = "".join(ch.lower() if ch.isalnum() else "-" for ch in resource_name).strip("-")
    return token or "resource-gap"


def stage_flags(state: dict[str, Any]) -> dict[str, bool]:
    current_status = str(state.get("current_status", "")).strip().lower()
    current_phase = str(state.get("current_phase", "")).strip().lower()
    release_allowed = parse_bool(state.get("release_allowed", False), default=False)
    testing_stage = current_status in {"testing", "department-review", "final-audit", "accepted", "committed", "archived"}
    release_stage = release_allowed or current_status in {"final-audit", "accepted", "committed", "archived"} or current_phase == "release"
    return {
        "testing_stage": testing_stage,
        "release_stage": release_stage,
    }


def gap_due_now(gap: dict[str, Any], state: dict[str, Any]) -> bool:
    status = str(gap.get("status", "")).strip().lower()
    if status not in OPEN_RESOURCE_STATUSES:
        return False
    due_stage = str(gap.get("due_stage", "release")).strip().lower()
    if due_stage == "immediate":
        return True
    flags = stage_flags(state)
    if due_stage == "testing":
        return flags["testing_stage"]
    return flags["release_stage"]


def summary(project_root: Path, state: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = state or load_state(project_root)
    payload, _ = ensure_resource_state(payload)
    policy = payload.get("resource_policy") if isinstance(payload.get("resource_policy"), dict) else {}
    release_requires_real_validation = parse_bool(policy.get("release_requires_real_validation", True), default=True)
    gaps = [dict(gap) for gap in payload.get("resource_gaps", []) if isinstance(gap, dict)]
    blocking_open = [gap for gap in gaps if str(gap.get("policy")) == "block" and str(gap.get("status")) in OPEN_RESOURCE_STATUSES]
    deferred_validation = [gap for gap in gaps if str(gap.get("policy")) in {"mock", "skip"} and str(gap.get("status")) in OPEN_RESOURCE_STATUSES]
    due_now = [gap for gap in gaps if gap_due_now(gap, payload)]
    retest_pending = [gap for gap in gaps if str(gap.get("status")) == "retest-pending"]
    release_validation_pending = [
        gap
        for gap in due_now
        if (
            (str(gap.get("policy")) in {"mock", "skip"} or str(gap.get("status")) == "retest-pending")
            and (str(gap.get("due_stage")) != "release" or release_requires_real_validation)
        )
    ]
    requires_user_input = bool(blocking_open or release_validation_pending)
    if blocking_open:
        message = "Required external resources are missing and currently configured to block autonomous execution."
    elif release_validation_pending:
        message = "Deferred real-resource validation must be completed before the current gate can pass."
    else:
        message = "No unresolved resource gap requires user input right now."
    return {
        "project_root": str(project_root.resolve()),
        "current_phase": payload.get("current_phase", ""),
        "current_status": payload.get("current_status", ""),
        "resource_gap_count": len(gaps),
        "blocking_gap_count": len(blocking_open),
        "deferred_gap_count": len(deferred_validation),
        "retest_pending_count": len(retest_pending),
        "due_now_count": len(due_now),
        "requires_user_input": requires_user_input,
        "message": message,
        "blocking_gaps": blocking_open,
        "deferred_gaps": deferred_validation,
        "due_now_gaps": due_now,
        "retest_pending_gaps": retest_pending,
        "release_validation_pending": release_validation_pending,
    }


def render_markdown(report: dict[str, Any]) -> str:
    def render_gap_lines(gaps: list[dict[str, Any]]) -> list[str]:
        if not gaps:
            return ["- none"]
        lines: list[str] = []
        for gap in gaps:
            lines.append(
                "- "
                + f"{gap.get('gap_id')}: {gap.get('resource_name')} | category={gap.get('category')} | "
                + f"policy={gap.get('policy')} | status={gap.get('status')} | due_stage={gap.get('due_stage')} | "
                + f"scope={gap.get('scope_level')}:{gap.get('scope_label') or 'n/a'}"
            )
            notes = str(gap.get("notes") or "").strip()
            if notes:
                lines.append(f"  notes: {notes}")
            resolution = str(gap.get("resolution_summary") or "").strip()
            if resolution:
                lines.append(f"  resolution: {resolution}")
        return lines

    lines = [
        "# Resource Gap Report",
        "",
        f"- project_root: {report.get('project_root', '')}",
        f"- current_phase: {report.get('current_phase', '')}",
        f"- current_status: {report.get('current_status', '')}",
        f"- resource_gap_count: {report.get('resource_gap_count', 0)}",
        f"- blocking_gap_count: {report.get('blocking_gap_count', 0)}",
        f"- deferred_gap_count: {report.get('deferred_gap_count', 0)}",
        f"- retest_pending_count: {report.get('retest_pending_count', 0)}",
        f"- due_now_count: {report.get('due_now_count', 0)}",
        f"- requires_user_input: {'yes' if report.get('requires_user_input') else 'no'}",
        f"- message: {report.get('message', '')}",
        "",
        "## Blocking Gaps",
        "",
        *render_gap_lines(report.get("blocking_gaps", [])),
        "",
        "## Due Now",
        "",
        *render_gap_lines(report.get("due_now_gaps", [])),
        "",
        "## Deferred Real Validation",
        "",
        *render_gap_lines(report.get("deferred_gaps", [])),
        "",
        "## Retest Pending",
        "",
        *render_gap_lines(report.get("retest_pending_gaps", [])),
    ]
    return "\n".join(lines).rstrip() + "\n"


def write_report(project_root: Path, state: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = state or load_state(project_root)
    report = summary(project_root, payload)
    report_path_json = reports_dir(project_root) / "resource-gap-report.json"
    report_path_md = reports_dir(project_root) / "resource-gap-report.md"
    write_json(report_path_json, report)
    write_text(report_path_md, render_markdown(report))
    payload["resource_gap_report_path"] = str(report_path_md.resolve())
    save_state(project_root, payload)
    report["report_path"] = str(report_path_md.resolve())
    return report


def task_card_resource_context(project_root: Path, state: dict[str, Any] | None = None) -> str:
    payload = state or load_state(project_root)
    active_gaps = [
        gap
        for gap in payload.get("resource_gaps", [])
        if isinstance(gap, dict) and str(gap.get("status", "")).strip().lower() in OPEN_RESOURCE_STATUSES
    ]
    if not active_gaps:
        return "none"
    lines = []
    for gap in active_gaps:
        lines.append(
            f"{gap.get('resource_name')} | category={gap.get('category')} | policy={gap.get('policy')} | "
            f"status={gap.get('status')} | due_stage={gap.get('due_stage')} | scope={gap.get('scope_level')}:{gap.get('scope_label') or 'n/a'}"
        )
    return "\n".join(lines)


def evaluate_runtime_constraints(project_root: Path, state: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = state or load_state(project_root)
    report = write_report(project_root, payload)
    if not report.get("requires_user_input"):
        return {
            "status": "ok",
            "code": "",
            "message": report.get("message", ""),
            "report_path": report.get("report_path", ""),
            "gaps": [],
        }
    due_now = report.get("due_now_gaps", [])
    if report.get("blocking_gaps"):
        return {
            "status": "resource-input-required",
            "code": "resource_input_required",
            "message": report.get("message", ""),
            "report_path": report.get("report_path", ""),
            "gaps": due_now or report.get("blocking_gaps", []),
        }
    return {
        "status": "resource-retest-required",
        "code": "resource_input_required",
        "message": report.get("message", ""),
        "report_path": report.get("report_path", ""),
        "gaps": due_now,
    }


def configure_policy(
    project_root: Path,
    default_policy: str | None = None,
    category_policies: dict[str, str] | None = None,
    release_requires_real_validation: bool | None = None,
) -> dict[str, Any]:
    state = load_state(project_root)
    policy = state["resource_policy"]
    if default_policy:
        normalized = default_policy.strip().lower()
        if normalized not in VALID_POLICIES:
            raise ValueError(f"Unsupported default policy: {default_policy}")
        policy["default_policy"] = normalized
    if category_policies:
        for category, raw_policy in category_policies.items():
            normalized_category = str(category).strip().lower()
            if normalized_category not in VALID_RESOURCE_CATEGORIES:
                raise ValueError(f"Unsupported resource category: {category}")
            normalized_policy = str(raw_policy).strip().lower()
            if normalized_policy not in VALID_POLICIES:
                raise ValueError(f"Unsupported resource policy: {raw_policy}")
            policy.setdefault("categories", {})[normalized_category] = normalized_policy
    if release_requires_real_validation is not None:
        policy["release_requires_real_validation"] = bool(release_requires_real_validation)
    save_state(project_root, state)
    report = write_report(project_root, state)
    return {
        "project_root": str(project_root.resolve()),
        "resource_policy": policy,
        "report_path": report.get("report_path", ""),
    }


def record_gap(
    project_root: Path,
    resource_name: str,
    category: str = "other",
    policy: str | None = None,
    due_stage: str | None = None,
    scope_level: str = "project",
    scope_label: str = "",
    notes: str = "",
    module_id: str | None = None,
    milestone_id: str | None = None,
) -> dict[str, Any]:
    normalized_name = resource_name.strip()
    if not normalized_name:
        raise ValueError("resource_name is required")
    normalized_category = category.strip().lower() or "other"
    if normalized_category not in VALID_RESOURCE_CATEGORIES:
        raise ValueError(f"Unsupported resource category: {category}")
    normalized_scope = scope_level.strip().lower() or "project"
    if normalized_scope not in VALID_SCOPE_LEVELS:
        raise ValueError(f"Unsupported scope level: {scope_level}")

    state = load_state(project_root)
    chosen_policy = effective_policy(state, normalized_category, explicit_policy=policy)
    chosen_due_stage = (due_stage or ("immediate" if chosen_policy == "block" else "release")).strip().lower()
    if chosen_due_stage not in VALID_DUE_STAGES:
        raise ValueError(f"Unsupported due stage: {due_stage}")

    existing = _open_gap_with_same_identity(state, normalized_name, normalized_category, normalized_scope, scope_label.strip())
    now = utc_now()
    if existing:
        existing["policy"] = chosen_policy
        existing["due_stage"] = chosen_due_stage
        existing["status"] = "open" if chosen_policy == "block" else "deferred"
        existing["notes"] = notes.strip()
        existing["updated_at"] = now
        existing["module_id"] = module_id
        existing["milestone_id"] = milestone_id
        existing["real_validation_required"] = chosen_policy in {"mock", "skip"}
        existing["retest_required"] = False
        existing["retest_status"] = "not-required"
        existing["resolution_summary"] = ""
        existing["resolved_at"] = None
        existing["retested_at"] = None
        gap = existing
        _history_append(state, str(gap.get("gap_id")), "updated", f"Updated resource gap `{normalized_name}` with policy `{chosen_policy}`.")
    else:
        gap_id = f"{_gap_slug(normalized_name)}-{now.replace(':', '').replace('+00:00', 'Z')}"
        gap = {
            "gap_id": gap_id,
            "resource_name": normalized_name,
            "category": normalized_category,
            "policy": chosen_policy,
            "due_stage": chosen_due_stage,
            "scope_level": normalized_scope,
            "scope_label": scope_label.strip(),
            "module_id": module_id,
            "milestone_id": milestone_id,
            "status": "open" if chosen_policy == "block" else "deferred",
            "notes": notes.strip(),
            "real_validation_required": chosen_policy in {"mock", "skip"},
            "retest_required": False,
            "retest_status": "not-required",
            "resolution_summary": "",
            "created_at": now,
            "updated_at": now,
            "resolved_at": None,
            "retested_at": None,
            "supplied_by": None,
        }
        state.setdefault("resource_gaps", []).append(gap)
        _history_append(state, gap_id, "recorded", f"Recorded resource gap `{normalized_name}` with policy `{chosen_policy}`.")
    save_state(project_root, state)
    report = write_report(project_root, state)
    return {
        "project_root": str(project_root.resolve()),
        "gap": gap,
        "report_path": report.get("report_path", ""),
    }


def resolve_gap(
    project_root: Path,
    gap_id: str,
    resolution_summary: str,
    supplied_by: str = "user",
    require_retest: bool | None = None,
) -> dict[str, Any]:
    state = load_state(project_root)
    gap = _find_gap(state, gap_id)
    needs_retest = bool(require_retest) if require_retest is not None else bool(gap.get("real_validation_required"))
    gap["resolution_summary"] = resolution_summary.strip() or "Resource supplied."
    gap["supplied_by"] = supplied_by
    gap["resolved_at"] = utc_now()
    gap["updated_at"] = gap["resolved_at"]
    gap["retest_required"] = needs_retest
    if needs_retest:
        gap["status"] = "retest-pending"
        gap["retest_status"] = "pending"
    else:
        gap["status"] = "closed"
        gap["retest_status"] = "not-required"
        gap["retested_at"] = gap["resolved_at"]
    _history_append(
        state,
        gap_id,
        "resolved",
        f"Resource `{gap.get('resource_name')}` was supplied by `{supplied_by}`. Retest required: {'yes' if needs_retest else 'no'}.",
    )
    save_state(project_root, state)
    report = write_report(project_root, state)
    return {
        "project_root": str(project_root.resolve()),
        "gap": gap,
        "report_path": report.get("report_path", ""),
    }


def complete_retest(project_root: Path, gap_id: str, outcome: str = "pass", summary_text: str = "") -> dict[str, Any]:
    normalized_outcome = outcome.strip().lower()
    if normalized_outcome not in {"pass", "fail"}:
        raise ValueError("Outcome must be `pass` or `fail`.")
    state = load_state(project_root)
    gap = _find_gap(state, gap_id)
    now = utc_now()
    gap["updated_at"] = now
    gap["retested_at"] = now
    if normalized_outcome == "pass":
        gap["status"] = "closed"
        gap["retest_status"] = "passed"
        gap["resolution_summary"] = summary_text.strip() or gap.get("resolution_summary") or "Real-resource retest passed."
    else:
        gap["status"] = "open" if gap.get("policy") == "block" else "deferred"
        gap["retest_status"] = "failed"
        gap["resolution_summary"] = summary_text.strip() or "Real-resource retest failed and needs another repair round."
    _history_append(
        state,
        gap_id,
        "retested",
        f"Resource `{gap.get('resource_name')}` real-resource retest outcome: `{normalized_outcome}`.",
    )
    save_state(project_root, state)
    report = write_report(project_root, state)
    return {
        "project_root": str(project_root.resolve()),
        "gap": gap,
        "report_path": report.get("report_path", ""),
    }


def _category_policy_args(parser: argparse.ArgumentParser) -> None:
    for category in sorted(VALID_RESOURCE_CATEGORIES):
        parser.add_argument(f"--{category}-policy", choices=sorted(VALID_POLICIES), help=f"Policy override for {category}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Track missing external resources and their block/mock/skip policies.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    configure_parser = subparsers.add_parser("configure-policy", help="Configure default resource policies")
    configure_parser.add_argument("project_root")
    configure_parser.add_argument("--default-policy", choices=sorted(VALID_POLICIES))
    _category_policy_args(configure_parser)
    configure_parser.add_argument("--release-requires-real-validation", choices=["yes", "no"])

    record_parser = subparsers.add_parser("record-gap", help="Record a missing external resource")
    record_parser.add_argument("project_root")
    record_parser.add_argument("--resource-name", required=True)
    record_parser.add_argument("--category", default="other", choices=sorted(VALID_RESOURCE_CATEGORIES))
    record_parser.add_argument("--policy", choices=sorted(VALID_POLICIES))
    record_parser.add_argument("--due-stage", choices=sorted(VALID_DUE_STAGES))
    record_parser.add_argument("--scope-level", default="project", choices=sorted(VALID_SCOPE_LEVELS))
    record_parser.add_argument("--scope-label", default="")
    record_parser.add_argument("--module-id")
    record_parser.add_argument("--milestone-id")
    record_parser.add_argument("--notes", default="")

    resolve_parser = subparsers.add_parser("resolve-gap", help="Mark a missing resource as supplied")
    resolve_parser.add_argument("project_root")
    resolve_parser.add_argument("--gap-id", required=True)
    resolve_parser.add_argument("--summary", default="")
    resolve_parser.add_argument("--supplied-by", default="user")
    resolve_parser.add_argument("--require-retest", choices=["yes", "no"])

    retest_parser = subparsers.add_parser("complete-retest", help="Close or reopen a resource gap after real-resource retest")
    retest_parser.add_argument("project_root")
    retest_parser.add_argument("--gap-id", required=True)
    retest_parser.add_argument("--outcome", default="pass", choices=["pass", "fail"])
    retest_parser.add_argument("--summary", default="")

    summary_parser = subparsers.add_parser("summary", help="Render the current resource gap summary")
    summary_parser.add_argument("project_root")

    args = parser.parse_args()
    project_root = Path(args.project_root).resolve()

    if args.command == "configure-policy":
        category_policies = {}
        for category in VALID_RESOURCE_CATEGORIES:
            value = getattr(args, f"{category}_policy".replace("-", "_"))
            if value:
                category_policies[category] = value
        payload = configure_policy(
            project_root,
            default_policy=args.default_policy,
            category_policies=category_policies,
            release_requires_real_validation=(
                None
                if args.release_requires_real_validation is None
                else args.release_requires_real_validation == "yes"
            ),
        )
    elif args.command == "record-gap":
        payload = record_gap(
            project_root,
            resource_name=args.resource_name,
            category=args.category,
            policy=args.policy,
            due_stage=args.due_stage,
            scope_level=args.scope_level,
            scope_label=args.scope_label,
            notes=args.notes,
            module_id=args.module_id,
            milestone_id=args.milestone_id,
        )
    elif args.command == "resolve-gap":
        payload = resolve_gap(
            project_root,
            gap_id=args.gap_id,
            resolution_summary=args.summary,
            supplied_by=args.supplied_by,
            require_retest=None if args.require_retest is None else args.require_retest == "yes",
        )
    elif args.command == "complete-retest":
        payload = complete_retest(project_root, gap_id=args.gap_id, outcome=args.outcome, summary_text=args.summary)
    else:
        payload = write_report(project_root)
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
