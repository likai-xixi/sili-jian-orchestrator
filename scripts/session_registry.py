from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import HANDOFF_DIRS, read_json, require_valid_json, utc_now, write_json
from runtime_guardrails import session_completion_limit, session_dispatch_limit, session_reuse_budget_decision


SESSION_DEFAULTS = {
    "session_key": None,
    "status": "idle",
    "last_task_id": None,
    "last_step_id": None,
    "last_heartbeat_at": None,
    "handoff_path": None,
    "resume_prompt": None,
    "active_workflow": None,
    "blocked_reason": None,
    "dispatch_count": 0,
    "completion_count": 0,
    "task_round_count": 0,
    "consecutive_invalid_completions": 0,
    "last_invalid_completion_at": None,
    "last_invalid_completion_reason": None,
    "drift_status": "clear",
    "rebuild_required": False,
    "rebuild_reason": None,
    "last_rebuild_at": None,
    "last_rollover_at": None,
}


def registry_path(project_root: Path) -> Path:
    return project_root / "ai" / "state" / "agent-sessions.json"


def default_agent_ids() -> list[str]:
    return ["orchestrator", *HANDOFF_DIRS[1:]]


def normalize_record(agent_id: str, record: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {"agent_id": agent_id, **SESSION_DEFAULTS}
    payload.update(record or {})
    payload["agent_id"] = agent_id
    return payload


def ensure_registry_schema(project_root: Path, agent_ids: list[str] | None = None) -> dict[str, Any]:
    path = registry_path(project_root)
    payload = require_valid_json(path, "ai/state/agent-sessions.json") if path.exists() else {}
    normalized: dict[str, Any] = {}
    ids = agent_ids or default_agent_ids()
    for agent_id in ids:
        normalized[agent_id] = normalize_record(agent_id, payload.get(agent_id))
    for agent_id, record in payload.items():
        if agent_id not in normalized:
            normalized[agent_id] = normalize_record(agent_id, record if isinstance(record, dict) else {})
    write_json(registry_path(project_root), normalized)
    return normalized


def load_registry(project_root: Path, ensure_defaults: bool = False) -> dict[str, Any]:
    if ensure_defaults:
        return ensure_registry_schema(project_root)
    payload = read_json(registry_path(project_root))
    return payload if payload else {}


def upsert_session(project_root: Path, agent_id: str, clear_fields: list[str] | None = None, **fields: Any) -> dict[str, Any]:
    payload = ensure_registry_schema(project_root)
    record = normalize_record(agent_id, payload.get(agent_id))
    record.update({key: value for key, value in fields.items() if value is not None})
    for key in clear_fields or []:
        record[key] = None
    record["agent_id"] = agent_id
    record["last_heartbeat_at"] = fields.get("last_heartbeat_at") or utc_now()
    payload[agent_id] = record
    write_json(registry_path(project_root), payload)
    return record


def reusable_session_key(project_root: Path, agent_id: str, workflow_name: str | None = None) -> str | None:
    return str(session_reuse_decision(project_root, agent_id, workflow_name).get("session_key") or "") or None


def session_rotation_limits(project_root: Path, agent_id: str) -> dict[str, int]:
    state = read_json(project_root / "ai" / "state" / "orchestrator-state.json")
    rotation = state.get("session_rotation_policy") if isinstance(state.get("session_rotation_policy"), dict) else {}
    defaults = rotation.get("default") if isinstance(rotation.get("default"), dict) else {}
    agent_overrides = rotation.get("agents") if isinstance(rotation.get("agents"), dict) else {}
    override = agent_overrides.get(agent_id) if isinstance(agent_overrides.get(agent_id), dict) else {}

    def _limit(name: str, fallback: int) -> int:
        raw = override.get(name, defaults.get(name, fallback))
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = fallback
        return value if value > 0 else fallback

    return {
        "max_completion_count": _limit("max_completion_count", session_completion_limit()),
        "max_dispatch_count": _limit("max_dispatch_count", session_dispatch_limit()),
        "max_task_round_count": _limit("max_task_round_count", 3),
    }


def session_reuse_decision(project_root: Path, agent_id: str, workflow_name: str | None = None) -> dict[str, Any]:
    payload = ensure_registry_schema(project_root)
    record = normalize_record(agent_id, payload.get(agent_id))
    session_key = record.get("session_key")
    status = str(record.get("status", "idle")).lower()
    active_workflow = str(record.get("active_workflow") or "").strip()
    decision = {
        "agent_id": agent_id,
        "record": record,
        "session_key": None,
        "status": "spawn",
        "reason": "No reusable session key is available.",
        "should_retire": False,
    }
    if workflow_name and active_workflow and active_workflow != workflow_name:
        decision["reason"] = f"Persisted session workflow `{active_workflow}` does not match `{workflow_name}`."
        return decision
    if not session_key or status not in {"active", "running", "waiting", "queued", "paused"}:
        decision["reason"] = "No active reusable session is persisted for this agent."
        return decision
    limits = session_rotation_limits(project_root, agent_id)
    reusable, reason = session_reuse_budget_decision(
        record,
        completion_limit=limits["max_completion_count"],
        dispatch_limit=limits["max_dispatch_count"],
        task_round_limit=limits["max_task_round_count"],
    )
    if not reusable:
        decision["reason"] = reason
        decision["should_retire"] = True
        return decision
    decision["status"] = "send"
    decision["session_key"] = str(session_key)
    decision["reason"] = reason
    decision["rotation_limits"] = limits
    return decision


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage ai/state/agent-sessions.json for a governed project.")
    parser.add_argument("project_root", help="Target project root")
    parser.add_argument("--agent-id", help="Agent id such as orchestrator or libu2")
    parser.add_argument("--session-key", help="Session key to persist")
    parser.add_argument("--status", help="idle/active/blocked/completed/etc")
    parser.add_argument("--last-task-id", help="Last dispatched task id")
    parser.add_argument("--last-step-id", help="Last workflow step id")
    parser.add_argument("--handoff-path", help="Current handoff path")
    parser.add_argument("--resume-prompt", help="Resume prompt for the next session")
    parser.add_argument("--active-workflow", help="Current active workflow name")
    parser.add_argument("--blocked-reason", help="Reason the agent is blocked")
    parser.add_argument("--ensure-schema", action="store_true", help="Backfill the default session registry schema")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    if args.ensure_schema or not args.agent_id:
        payload = ensure_registry_schema(project_root)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    record = upsert_session(
        project_root,
        args.agent_id,
        session_key=args.session_key,
        status=args.status,
        last_task_id=args.last_task_id,
        last_step_id=args.last_step_id,
        handoff_path=args.handoff_path,
        resume_prompt=args.resume_prompt,
        active_workflow=args.active_workflow,
        blocked_reason=args.blocked_reason,
    )
    print(json.dumps(record, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
