from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from common import ensure_dual_review_state, next_step_guidance, read_json, require_valid_json, utc_now, write_json, write_text
from session_registry import ensure_registry_schema, upsert_session
from workflow_engine import ensure_workflow_progress


COMPLETED_STATUSES = {"completed", "done", "pass", "passed", "approved"}
BLOCKED_STATUSES = {"blocked", "fail", "failed", "rework", "redesign"}
VALID_EXECUTION_MODES = {"skill", "direct"}
VALID_SKILL_POLICIES = {"required", "optional", "forbidden"}
DEFAULT_COMPLETION_SCHEMA_VERSION = "v1"


def normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        values = value
    else:
        text = str(value).strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1]
        values = text.split(",")
    normalized = [str(item).strip().strip("'\"") for item in values]
    return [item for item in normalized if item and item.lower() not in {"none", "n/a", "na"}]


def normalize_skill_policy(value: Any, default: str = "optional") -> str:
    normalized = str(value or "").strip().lower()
    if normalized in VALID_SKILL_POLICIES:
        return normalized
    fallback = str(default).strip().lower()
    return fallback if fallback in VALID_SKILL_POLICIES else "optional"


def skill_usage_report_json_path(project_root: Path) -> Path:
    return project_root / "ai" / "reports" / "agent-skill-usage.json"


def skill_usage_report_markdown_path(project_root: Path) -> Path:
    return project_root / "ai" / "reports" / "agent-skill-usage.md"


def render_skill_usage_markdown(payload: dict[str, Any]) -> str:
    items = payload.get("items", [])
    lines = [
        "# Agent Skill Usage",
        "",
        f"- updated_at: {payload.get('updated_at', '')}",
        f"- total_entries: {payload.get('totals', {}).get('total', 0)}",
        f"- compliant_entries: {payload.get('totals', {}).get('compliant', 0)}",
        f"- violation_entries: {payload.get('totals', {}).get('violations', 0)}",
        "",
        "## Entries",
        "",
    ]
    if not items:
        lines.append("- none")
        return "\n".join(lines) + "\n"
    for item in items[-120:]:
        compliance = "compliant" if item.get("compliant", False) else "violation"
        lines.extend(
            [
                f"### {item.get('task_id') or 'UNKNOWN'} / {item.get('agent_id') or 'unknown'}",
                "",
                f"- recorded_at: {item.get('recorded_at', '')}",
                f"- workflow_step_id: {item.get('workflow_step_id', '')}",
                f"- skill_policy: {item.get('skill_policy', 'optional')}",
                f"- execution_mode: {item.get('execution_mode', '')}",
                f"- skills_used: {', '.join(item.get('skills_used', [])) or 'none'}",
                f"- evidence_refs: {', '.join(item.get('evidence_refs', [])) or 'none'}",
                f"- status: {compliance}",
                f"- violation_reason: {item.get('violation_reason') or 'none'}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def append_skill_usage_entry(
    project_root: Path,
    *,
    payload: dict[str, Any],
    skill_policy: str,
    required_skills: list[str],
    completion_schema_version: str,
    execution_mode: str,
    skills_used: list[str],
    evidence_refs: list[str],
    compliant: bool,
    violation_code: str | None = None,
    violation_reason: str | None = None,
    source: str = "completion_consumer",
) -> dict[str, Any]:
    report_path = skill_usage_report_json_path(project_root)
    report = read_json(report_path)
    items = report.get("items", []) if isinstance(report.get("items"), list) else []
    entry = {
        "entry_id": f"{utc_now()}::{payload.get('agent_id') or payload.get('role') or 'unknown'}::{payload.get('task_id') or 'UNKNOWN'}",
        "recorded_at": utc_now(),
        "agent_id": str(payload.get("agent_id") or payload.get("role") or "").strip(),
        "task_id": str(payload.get("task_id") or "").strip(),
        "workflow_step_id": str(payload.get("workflow_step_id") or "").strip(),
        "status": str(payload.get("status") or "").strip(),
        "summary": str(payload.get("summary") or "").strip(),
        "skill_policy": normalize_skill_policy(skill_policy),
        "required_skills": required_skills,
        "completion_schema_version": completion_schema_version or "",
        "execution_mode": execution_mode,
        "skills_used": skills_used,
        "evidence_refs": evidence_refs,
        "compliant": bool(compliant),
        "violation_code": violation_code or "",
        "violation_reason": violation_reason or "",
        "source": source,
    }
    items.append(entry)
    trimmed_items = items[-400:]
    totals = {
        "total": len(trimmed_items),
        "compliant": sum(1 for item in trimmed_items if bool(item.get("compliant"))),
        "violations": sum(1 for item in trimmed_items if not bool(item.get("compliant"))),
    }
    output = {
        "updated_at": utc_now(),
        "schema_version": "v1",
        "items": trimmed_items,
        "totals": totals,
    }
    write_json(report_path, output)
    write_text(skill_usage_report_markdown_path(project_root), render_skill_usage_markdown(output))
    return entry


def completion_policy_context(matching_task: dict[str, Any] | None) -> dict[str, Any]:
    task_payload = matching_task or {}
    required_skills = normalize_string_list(task_payload.get("required_skills"))
    policy = normalize_skill_policy(task_payload.get("skill_policy"), default=("required" if required_skills else "optional"))
    schema = str(task_payload.get("completion_schema_version") or "").strip()
    strict_protocol = bool(schema or task_payload.get("skill_policy") or required_skills)
    return {
        "skill_policy": policy,
        "required_skills": required_skills,
        "completion_schema_version": schema or (DEFAULT_COMPLETION_SCHEMA_VERSION if strict_protocol else ""),
        "strict_protocol": strict_protocol,
    }


def validate_completion_payload(
    payload: dict[str, Any],
    *,
    expected_workflow_step_id: str,
    skill_policy: str,
    required_skills: list[str],
    completion_schema_version: str,
    strict_protocol: bool,
) -> dict[str, Any]:
    task_id = str(payload.get("task_id") or "").strip()
    workflow_step_id = str(payload.get("workflow_step_id") or "").strip()
    status = str(payload.get("status") or "").strip()
    summary = str(payload.get("summary") or "").strip()
    schema_version = str(payload.get("completion_schema_version") or "").strip()
    trace = payload.get("execution_trace")

    if strict_protocol:
        required_fields = {
            "task_id": task_id,
            "workflow_step_id": workflow_step_id,
            "status": status,
            "summary": summary,
            "completion_schema_version": schema_version,
        }
        for field_name, value in required_fields.items():
            if not value:
                return {"valid": False, "code": "missing_completion_field", "error": f"Missing required completion field: {field_name}"}
        if not isinstance(trace, dict):
            return {"valid": False, "code": "missing_skill_usage_trace", "error": "Missing required completion field: execution_trace"}

    if expected_workflow_step_id and workflow_step_id and workflow_step_id != expected_workflow_step_id:
        return {
            "valid": False,
            "code": "completion_workflow_step_mismatch",
            "error": f"Completion workflow_step_id `{workflow_step_id}` does not match active task workflow_step_id `{expected_workflow_step_id}`.",
        }

    if completion_schema_version and schema_version and schema_version != completion_schema_version:
        return {
            "valid": False,
            "code": "completion_schema_version_mismatch",
            "error": f"Completion schema version `{schema_version}` does not match `{completion_schema_version}`.",
        }

    normalized_trace = trace if isinstance(trace, dict) else {}
    execution_mode = str(normalized_trace.get("execution_mode") or "").strip().lower()
    skills_used = normalize_string_list(normalized_trace.get("skills_used"))
    evidence_refs = normalize_string_list(normalized_trace.get("evidence_refs"))

    if strict_protocol:
        if execution_mode not in VALID_EXECUTION_MODES:
            return {
                "valid": False,
                "code": "invalid_execution_mode",
                "error": f"execution_trace.execution_mode must be one of {sorted(VALID_EXECUTION_MODES)}.",
            }
        if not isinstance(normalized_trace.get("skills_used"), list):
            return {
                "valid": False,
                "code": "missing_skill_usage_trace",
                "error": "execution_trace.skills_used must be a list.",
            }
        if not isinstance(normalized_trace.get("evidence_refs"), list):
            return {
                "valid": False,
                "code": "missing_skill_usage_trace",
                "error": "execution_trace.evidence_refs must be a list.",
            }
        if skill_policy == "required":
            if not skills_used:
                return {
                    "valid": False,
                    "code": "skill_policy_violation",
                    "error": "skill_policy=required but execution_trace.skills_used is empty.",
                }
            if execution_mode != "skill":
                return {
                    "valid": False,
                    "code": "skill_policy_violation",
                    "error": "skill_policy=required but execution_trace.execution_mode is not `skill`.",
                }
            missing_required = [skill for skill in required_skills if skill not in skills_used]
            if missing_required:
                return {
                    "valid": False,
                    "code": "skill_policy_violation",
                    "error": "skill_policy=required but required_skills are missing: " + ", ".join(missing_required),
                }
        if skill_policy == "forbidden" and skills_used:
            return {
                "valid": False,
                "code": "forbidden_skill_used",
                "error": "skill_policy=forbidden but execution_trace.skills_used is not empty.",
            }
    else:
        if execution_mode and execution_mode not in VALID_EXECUTION_MODES:
            execution_mode = ""

    return {
        "valid": True,
        "code": "",
        "error": "",
        "task_id": task_id,
        "workflow_step_id": workflow_step_id,
        "status": status,
        "summary": summary,
        "completion_schema_version": schema_version,
        "execution_mode": execution_mode,
        "skills_used": skills_used,
        "evidence_refs": evidence_refs,
    }


def handoff_root(project_root: Path) -> Path:
    return (project_root / "ai" / "handoff").resolve()


def handoff_path_for(project_root: Path, payload: dict[str, Any]) -> Path:
    role = str(payload.get("agent_id") or payload.get("role") or "orchestrator")
    task_id = str(payload.get("task_id") or "UNKNOWN")
    explicit = str(payload.get("handoff_path") or "").strip()
    if explicit:
        candidate = Path(explicit)
        if not candidate.is_absolute():
            candidate = project_root / candidate
    else:
        candidate = project_root / "ai" / "handoff" / role / "active" / f"{task_id}.md"
    candidate = candidate.resolve()
    try:
        candidate.relative_to(handoff_root(project_root))
    except ValueError as exc:
        raise ValueError(f"handoff_path escapes ai/handoff root: {explicit or candidate}") from exc
    return candidate


def render_handoff(payload: dict[str, Any], handoff_path: Path) -> str:
    files_touched = payload.get("files_touched") or payload.get("artifacts") or []
    blockers = payload.get("blockers") or []
    if isinstance(files_touched, list):
        touched_value = ", ".join(str(item) for item in files_touched) if files_touched else "none"
    else:
        touched_value = str(files_touched)
    if isinstance(blockers, list):
        blocker_value = ", ".join(str(item) for item in blockers) if blockers else "none"
    else:
        blocker_value = str(blockers)
    return f"""# Role Handoff

- title: {payload.get('title') or payload.get('summary') or payload.get('workflow_step_id') or handoff_path.stem}
- status: {payload.get('status', 'completed')}
- task_id: {payload.get('task_id', '')}
- workflow_step_id: {payload.get('workflow_step_id', '')}
- task_round_id: {payload.get('task_round_id', '')}
- summary: {payload.get('summary', '')}
- files_touched: {touched_value}
- blockers: {blocker_value}
- next_reviewer: {payload.get('next_reviewer') or payload.get('return_to') or 'orchestrator'}
- role: {payload.get('agent_id') or payload.get('role') or 'orchestrator'}
- updated_at: {utc_now()}
"""


def blocker_items_for_task(task: dict[str, Any]) -> list[str]:
    raw = task.get("blockers") or []
    values = raw if isinstance(raw, list) else [raw]
    normalized = [str(item).strip() for item in values if str(item).strip() and str(item).strip().lower() != "none"]
    if normalized:
        return normalized
    role = str(task.get("role") or "agent").strip() or "agent"
    step_id = str(task.get("workflow_step_id") or task.get("task_id") or "current task").strip() or "current task"
    return [f"{role} blocked on {step_id}."]


def active_blocker_items(active_tasks: list[dict[str, Any]]) -> list[str]:
    items: list[str] = []
    for task in active_tasks:
        status = str(task.get("status", "")).strip().lower()
        if status not in BLOCKED_STATUSES:
            continue
        items.extend(blocker_items_for_task(task))
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


def fallback_status_after_unblock(state: dict[str, Any]) -> str:
    previous = str(state.get("status_before_blocked") or "").strip().lower()
    if previous and previous != "blocked":
        return previous
    phase = str(state.get("current_phase") or "").strip().lower()
    if phase and phase != "blocked":
        return phase
    return "executing" if state.get("active_tasks") else "planning"


def find_matching_active_task(
    active_tasks: list[dict[str, Any]], task_id: str, agent_id: str, step_id: str
) -> tuple[int | None, dict[str, Any] | None]:
    if task_id:
        for index, task in enumerate(active_tasks):
            if str(task.get("task_id") or "").strip() == task_id:
                return index, dict(task)
        return None, None
    if not step_id:
        return None, None
    candidates = [
        (index, dict(task))
        for index, task in enumerate(active_tasks)
        if str(task.get("workflow_step_id") or "").strip() == step_id
        and str(task.get("role") or "").strip() == agent_id
    ]
    if len(candidates) == 1:
        return candidates[0]
    return None, None


def consume_completion(project_root: Path, payload: dict[str, Any], allow_untracked_completion: bool = False) -> dict[str, Any]:
    payload = dict(payload)
    registry = ensure_registry_schema(project_root)
    state_path = project_root / "ai" / "state" / "orchestrator-state.json"
    state = require_valid_json(state_path, "ai/state/orchestrator-state.json")
    progress = ensure_workflow_progress(state)
    handoff_path = handoff_path_for(project_root, payload)

    agent_id = str(payload.get("agent_id") or payload.get("role") or "orchestrator")
    session_record = dict(registry.get(agent_id, {}))
    task_id = str(payload.get("task_id") or "").strip()
    step_id = str(payload.get("workflow_step_id") or "").strip()
    status = str(payload.get("status", "completed")).strip().lower()
    blockers = payload.get("blockers") or []

    active_tasks = list(state.get("active_tasks", []))
    matching_index, matching_task = find_matching_active_task(active_tasks, task_id, agent_id, step_id)
    policy_context = completion_policy_context(matching_task)
    if not step_id and matching_task is not None and not policy_context["strict_protocol"]:
        step_id = str(matching_task.get("workflow_step_id") or "").strip()
        if step_id:
            payload["workflow_step_id"] = step_id
    if matching_task is None and not allow_untracked_completion:
        raise ValueError(
            f"Completion payload does not match any active task for agent `{agent_id}`"
            + (f" and task `{task_id}`." if task_id else ".")
        )
    if matching_task is not None:
        expected_role = str(matching_task.get("role") or "").strip()
        expected_step_id = str(matching_task.get("workflow_step_id") or "").strip()
        if expected_role and expected_role != agent_id:
            raise ValueError(
                f"Completion agent `{agent_id}` does not match active task role `{expected_role}` for `{task_id or step_id}`."
            )
        if step_id and expected_step_id and expected_step_id != step_id:
            raise ValueError(
                f"Completion workflow_step_id `{step_id}` does not match active task workflow_step_id `{expected_step_id}`."
            )
    expected_step_id = str(matching_task.get("workflow_step_id") or "").strip() if matching_task is not None else step_id
    validation = validate_completion_payload(
        payload,
        expected_workflow_step_id=expected_step_id,
        skill_policy=policy_context["skill_policy"],
        required_skills=policy_context["required_skills"],
        completion_schema_version=policy_context["completion_schema_version"],
        strict_protocol=policy_context["strict_protocol"],
    )
    if not validation["valid"]:
        append_skill_usage_entry(
            project_root,
            payload=payload,
            skill_policy=policy_context["skill_policy"],
            required_skills=policy_context["required_skills"],
            completion_schema_version=policy_context["completion_schema_version"],
            execution_mode=str((payload.get("execution_trace") or {}).get("execution_mode") or ""),
            skills_used=normalize_string_list((payload.get("execution_trace") or {}).get("skills_used")),
            evidence_refs=normalize_string_list((payload.get("execution_trace") or {}).get("evidence_refs")),
            compliant=False,
            violation_code=validation.get("code") or "skill_policy_violation",
            violation_reason=validation["error"],
            source="completion_consumer_validation",
        )
        raise ValueError(validation["error"])
    payload["completion_schema_version"] = validation.get("completion_schema_version") or policy_context["completion_schema_version"]
    payload["execution_trace"] = {
        "execution_mode": validation.get("execution_mode", ""),
        "skills_used": validation.get("skills_used", []),
        "evidence_refs": validation.get("evidence_refs", []),
    }
    if matching_task is not None:
        matching_task["status"] = status
        matching_task["workflow_step_id"] = step_id or expected_step_id
        if matching_task.get("task_round_id") and not payload.get("task_round_id"):
            payload["task_round_id"] = matching_task.get("task_round_id")
        matching_task["handoff_path"] = str(handoff_path.relative_to(project_root)).replace("\\", "/")
        matching_task["blockers"] = blockers if blockers else []
        updated_active = [task for index, task in enumerate(active_tasks) if index != matching_index]
        if status not in COMPLETED_STATUSES:
            updated_active.append(matching_task)
        state["active_tasks"] = updated_active
    else:
        state["active_tasks"] = active_tasks
        if allow_untracked_completion and status not in COMPLETED_STATUSES:
            state.setdefault("active_tasks", []).append(
                {
                    "task_id": task_id or step_id or "UNKNOWN",
                    "role": agent_id,
                    "status": status,
                    "handoff_path": str(handoff_path.relative_to(project_root)).replace("\\", "/"),
                    "workflow_step_id": step_id,
                    "task_round_id": payload.get("task_round_id"),
                    "blockers": blockers if blockers else [],
                }
            )

    if step_id:
        for bucket in ["completed_steps", "blocked_steps", "dispatched_steps"]:
            progress[bucket] = [item for item in progress.get(bucket, []) if str(item) != step_id]
        if status in COMPLETED_STATUSES:
            progress["completed_steps"].append(step_id)
        elif status in BLOCKED_STATUSES:
            progress["blocked_steps"].append(step_id)

    blocker_items = active_blocker_items(state.get("active_tasks", []))
    if blocker_items:
        state["blockers"] = blocker_items
        state["blocker_level"] = "high"
        if str(state.get("current_status") or "").strip().lower() != "blocked":
            state["status_before_blocked"] = state.get("current_status") or state.get("current_phase") or "executing"
        state["current_status"] = "blocked"
        state["next_action"] = "Resolve remaining blockers before dispatching the next step."
        state["next_owner"] = "orchestrator"
    else:
        state["blockers"] = []
        state["blocker_level"] = "none"
        if str(state.get("current_status") or "").strip().lower() == "blocked":
            state["current_status"] = fallback_status_after_unblock(state)
        state.pop("status_before_blocked", None)
        state["next_action"] = f"Review completion from {agent_id} and dispatch the next ready step."
        state["next_owner"] = "orchestrator"

    ensure_dual_review_state(state)

    state["last_completion"] = {
        "agent_id": agent_id,
        "task_id": task_id,
        "workflow_step_id": step_id,
        "task_round_id": payload.get("task_round_id"),
        "status": status,
        "summary": payload.get("summary", ""),
        "completion_schema_version": payload.get("completion_schema_version", ""),
        "execution_mode": payload.get("execution_trace", {}).get("execution_mode", ""),
        "skills_used": payload.get("execution_trace", {}).get("skills_used", []),
        "evidence_refs": payload.get("execution_trace", {}).get("evidence_refs", []),
        "skill_policy": policy_context["skill_policy"],
        "required_skills": policy_context["required_skills"],
        "updated_at": utc_now(),
    }
    audit_entry = append_skill_usage_entry(
        project_root,
        payload=payload,
        skill_policy=policy_context["skill_policy"],
        required_skills=policy_context["required_skills"],
        completion_schema_version=payload.get("completion_schema_version", ""),
        execution_mode=payload.get("execution_trace", {}).get("execution_mode", ""),
        skills_used=normalize_string_list(payload.get("execution_trace", {}).get("skills_used")),
        evidence_refs=normalize_string_list(payload.get("execution_trace", {}).get("evidence_refs")),
        compliant=True,
        source="completion_consumer",
    )
    state["last_completion"]["skill_audit_recorded"] = True
    state["last_completion"]["skill_audit_compliant"] = True
    state["last_completion"]["skill_audit_entry_id"] = audit_entry.get("entry_id")
    write_json(state_path, state)

    write_text(handoff_path, render_handoff(payload, handoff_path))

    upsert_session(
        project_root,
        agent_id,
        session_key=payload.get("session_key"),
        status=(
            "blocked"
            if status in BLOCKED_STATUSES
            else ("waiting" if payload.get("session_key") or session_record.get("session_key") else "idle")
        ),
        last_task_id=task_id or None,
        last_step_id=step_id or None,
        handoff_path=str(handoff_path.relative_to(project_root)).replace("\\", "/"),
        blocked_reason=", ".join(str(item) for item in blockers) if status in BLOCKED_STATUSES and blockers else None,
        active_workflow=state.get("current_workflow"),
        completion_count=int(session_record.get("completion_count") or 0) + 1,
        consecutive_invalid_completions=0,
        drift_status="clear",
        rebuild_required=False,
        rebuild_reason=None,
        clear_fields=["last_invalid_completion_at", "last_invalid_completion_reason", "blocked_reason"]
        if status not in BLOCKED_STATUSES
        else ["last_invalid_completion_at", "last_invalid_completion_reason"],
    )
    guidance = next_step_guidance(state)

    return {
        "agent_id": agent_id,
        "task_id": task_id,
        "workflow_step_id": step_id,
        "status": status,
        "handoff_path": str(handoff_path),
        "next_owner": state.get("next_owner", ""),
        "next_action": state.get("next_action", ""),
        "requires_confirmation": guidance["requires_confirmation"],
        "continuation_mode": guidance["continuation_mode"],
        "next_step_hint": guidance["human_hint"],
        "next_step_summary": guidance["summary"],
        "skill_audit_entry_id": audit_entry.get("entry_id"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Consume a peer-agent completion payload and update project state.")
    parser.add_argument("project_root", help="Target project root")
    parser.add_argument("completion_file", help="JSON file containing the completion payload")
    parser.add_argument("--archive", action="store_true", help="Move the input file into ai/runtime/inbox/processed after consumption")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    completion_file = Path(args.completion_file).resolve()
    payload = json.loads(completion_file.read_text(encoding="utf-8"))
    result = consume_completion(project_root, payload)

    if args.archive:
        processed_dir = project_root / "ai" / "runtime" / "inbox" / "processed"
        processed_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(completion_file), str(processed_dir / completion_file.name))

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
