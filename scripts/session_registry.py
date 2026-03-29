from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import HANDOFF_DIRS, read_json, require_valid_json, utc_now, write_json


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


def upsert_session(project_root: Path, agent_id: str, **fields: Any) -> dict[str, Any]:
    payload = ensure_registry_schema(project_root)
    record = normalize_record(agent_id, payload.get(agent_id))
    record.update({key: value for key, value in fields.items() if value is not None})
    record["agent_id"] = agent_id
    record["last_heartbeat_at"] = fields.get("last_heartbeat_at") or utc_now()
    payload[agent_id] = record
    write_json(registry_path(project_root), payload)
    return record


def reusable_session_key(project_root: Path, agent_id: str, workflow_name: str | None = None) -> str | None:
    payload = ensure_registry_schema(project_root)
    record = payload.get(agent_id, {})
    session_key = record.get("session_key")
    status = str(record.get("status", "idle")).lower()
    active_workflow = str(record.get("active_workflow") or "").strip()
    if workflow_name and active_workflow and active_workflow != workflow_name:
        return None
    if session_key and status in {"active", "running", "waiting", "queued", "paused"}:
        return str(session_key)
    return None


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
