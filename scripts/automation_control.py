from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import read_json, read_text, require_valid_json, utc_now, write_json, write_text
from session_registry import ensure_registry_schema


VALID_AUTOMATION_MODES = {"normal", "armed", "autonomous", "paused"}
ACTIVE_SESSION_STATUSES = {"active", "running", "waiting", "queued", "paused"}
PAUSABLE_TASK_STATUSES = {"in-progress", "queued", "active", "waiting", "paused"}


CONTROL_DEFAULTS = {
    "automation_mode": "normal",
    "conversation_mode": "interactive",
    "background_runtime_enabled": False,
    "automation_last_changed_at": None,
    "automation_last_changed_by": None,
    "automation_last_reason": None,
    "pause_reason": None,
    "paused_at": None,
    "paused_by": None,
    "resume_action": None,
}


def state_path(project_root: Path) -> Path:
    return project_root / "ai" / "state" / "orchestrator-state.json"


def handoff_path(project_root: Path) -> Path:
    return project_root / "ai" / "state" / "project-handoff.md"


def start_here_path(project_root: Path) -> Path:
    return project_root / "ai" / "state" / "START_HERE.md"


def ensure_control_state(project_root: Path) -> dict[str, Any]:
    path = state_path(project_root)
    payload = require_valid_json(path, "ai/state/orchestrator-state.json") if path.exists() else {}
    for key, value in CONTROL_DEFAULTS.items():
        payload.setdefault(key, value)
    if payload["automation_mode"] not in VALID_AUTOMATION_MODES:
        payload["automation_mode"] = "normal"
    payload["conversation_mode"] = "interactive"
    payload["background_runtime_enabled"] = payload["automation_mode"] == "autonomous"
    write_json(state_path(project_root), payload)
    return payload


def replace_or_append_line(text: str, prefix: str, new_line: str) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            lines[index] = new_line
            return "\n".join(lines).rstrip() + "\n"
    lines.append(new_line)
    return "\n".join(lines).rstrip() + "\n"


def update_control_markdown(project_root: Path, state: dict[str, Any]) -> None:
    handoff = read_text(handoff_path(project_root))
    if handoff:
        handoff = replace_or_append_line(handoff, "- Automation mode:", f"- Automation mode: {state.get('automation_mode', 'normal')}")
        handoff = replace_or_append_line(
            handoff,
            "- Conversation mode:",
            f"- Conversation mode: {state.get('conversation_mode', 'interactive')}",
        )
        write_text(handoff_path(project_root), handoff)

    start_here = read_text(start_here_path(project_root))
    if start_here:
        start_here = replace_or_append_line(start_here, "- Automation mode:", f"- Automation mode: {state.get('automation_mode', 'normal')}")
        start_here = replace_or_append_line(
            start_here,
            "- Conversation mode:",
            f"- Conversation mode: {state.get('conversation_mode', 'interactive')}",
        )
        write_text(start_here_path(project_root), start_here)


def update_sessions_for_mode(project_root: Path, state: dict[str, Any], mode: str, reason: str | None = None) -> dict[str, Any]:
    registry = ensure_registry_schema(project_root)
    active_roles = {str(task.get("role", "")).strip() for task in state.get("active_tasks", []) if task.get("role")}
    pause_note = f"Paused by control plane: {reason or 'no reason provided'}"

    for agent_id, record in registry.items():
        if mode == "paused":
            if agent_id == "orchestrator" or agent_id in active_roles or str(record.get("status", "")).lower() in ACTIVE_SESSION_STATUSES:
                record["status"] = "paused"
                record["blocked_reason"] = pause_note
        elif mode == "autonomous":
            if agent_id == "orchestrator":
                record["status"] = "waiting"
                record["blocked_reason"] = None
            elif str(record.get("status", "")).lower() == "paused":
                record["status"] = "waiting" if record.get("session_key") or record.get("last_task_id") else "idle"
                record["blocked_reason"] = None
        elif mode in {"normal", "armed"}:
            if agent_id == "orchestrator":
                record["status"] = "idle"
                record["blocked_reason"] = None
            elif str(record.get("status", "")).lower() == "paused":
                record["status"] = "idle"
                record["blocked_reason"] = None

    write_json(project_root / "ai" / "state" / "agent-sessions.json", registry)
    return registry


def update_tasks_for_mode(state: dict[str, Any], mode: str) -> None:
    for task in state.get("active_tasks", []):
        current = str(task.get("status", "")).strip().lower()
        if mode == "paused" and current in PAUSABLE_TASK_STATUSES:
            task["status"] = "paused"
        elif mode == "autonomous" and current == "paused":
            task["status"] = "in-progress"


def control_summary(project_root: Path, state: dict[str, Any], reason: str | None = None) -> dict[str, Any]:
    return {
        "project_root": str(project_root.resolve()),
        "automation_mode": state.get("automation_mode", "normal"),
        "conversation_mode": state.get("conversation_mode", "interactive"),
        "background_runtime_enabled": bool(state.get("background_runtime_enabled")),
        "current_workflow": state.get("current_workflow", ""),
        "current_status": state.get("current_status", ""),
        "next_owner": state.get("next_owner", ""),
        "next_action": state.get("next_action", ""),
        "pause_reason": state.get("pause_reason"),
        "paused_at": state.get("paused_at"),
        "paused_by": state.get("paused_by"),
        "resume_action": state.get("resume_action"),
        "updated_at": state.get("automation_last_changed_at"),
        "updated_by": state.get("automation_last_changed_by"),
        "reason": reason or state.get("automation_last_reason"),
    }


def render_control_markdown(payload: dict[str, Any]) -> str:
    return f"""# Automation Control

- automation_mode: {payload.get('automation_mode', 'normal')}
- conversation_mode: {payload.get('conversation_mode', 'interactive')}
- background_runtime_enabled: {'yes' if payload.get('background_runtime_enabled') else 'no'}
- current_workflow: {payload.get('current_workflow', '')}
- current_status: {payload.get('current_status', '')}
- next_owner: {payload.get('next_owner', '')}
- next_action: {payload.get('next_action', '')}
- pause_reason: {payload.get('pause_reason') or 'none'}
- paused_at: {payload.get('paused_at') or 'n/a'}
- paused_by: {payload.get('paused_by') or 'n/a'}
- resume_action: {payload.get('resume_action') or 'n/a'}
- updated_at: {payload.get('updated_at') or 'n/a'}
- updated_by: {payload.get('updated_by') or 'n/a'}
- reason: {payload.get('reason') or 'n/a'}
"""


def render_pause_markdown(payload: dict[str, Any], sessions: dict[str, Any]) -> str:
    active_tasks = payload.get("active_tasks", [])
    task_lines = "\n".join(
        f"- {task.get('task_id', '')}: {task.get('role', '')} ({task.get('status', '')})"
        for task in active_tasks
    ) or "- none"
    paused_sessions = "\n".join(
        f"- {agent_id}: {record.get('status', '')}"
        for agent_id, record in sessions.items()
        if str(record.get("status", "")).lower() == "paused"
    ) or "- none"
    return f"""# Pause Report

- paused_at: {payload.get('paused_at') or 'n/a'}
- paused_by: {payload.get('paused_by') or 'n/a'}
- pause_reason: {payload.get('pause_reason') or 'n/a'}
- resume_action: {payload.get('resume_action') or 'n/a'}
- next_owner: {payload.get('next_owner', '')}
- background_runtime_enabled: {'yes' if payload.get('background_runtime_enabled') else 'no'}

## Active Tasks

{task_lines}

## Paused Sessions

{paused_sessions}
"""


def write_control_reports(project_root: Path, state: dict[str, Any], sessions: dict[str, Any], reason: str | None = None) -> dict[str, Any]:
    reports_dir = project_root / "ai" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    payload = control_summary(project_root, state, reason=reason)
    payload["active_tasks"] = state.get("active_tasks", [])
    payload["session_statuses"] = {agent_id: record.get("status") for agent_id, record in sessions.items()}
    write_json(reports_dir / "automation-control.json", payload)
    write_text(reports_dir / "automation-control.md", render_control_markdown(payload))
    if state.get("automation_mode") == "paused":
        write_json(reports_dir / "pause-report.json", payload)
        write_text(reports_dir / "pause-report.md", render_pause_markdown(payload, sessions))
    return payload


def set_mode(
    project_root: Path,
    mode: str,
    actor: str = "user",
    reason: str | None = None,
    resume_action: str | None = None,
) -> dict[str, Any]:
    normalized_mode = mode.strip().lower()
    if normalized_mode not in VALID_AUTOMATION_MODES:
        raise ValueError(f"Unsupported automation mode: {mode}")

    state = ensure_control_state(project_root)
    now = utc_now()
    current_resume_action = resume_action or state.get("resume_action") or state.get("next_action")

    if normalized_mode == "paused":
        state["pause_reason"] = reason or "Paused by user request."
        state["paused_at"] = now
        state["paused_by"] = actor
        state["resume_action"] = current_resume_action
        state["next_owner"] = "orchestrator"
        state["next_action"] = (
            f"Automation paused. Resume autonomy, then continue: {current_resume_action}"
            if current_resume_action
            else "Automation paused. Resume autonomy before continuing."
        )
    else:
        if normalized_mode == "autonomous" and state.get("automation_mode") == "paused" and current_resume_action:
            state["next_action"] = current_resume_action
        state["pause_reason"] = None
        state["paused_at"] = None
        state["paused_by"] = None
        state["resume_action"] = current_resume_action if normalized_mode == "armed" else None

    state["automation_mode"] = normalized_mode
    state["conversation_mode"] = "interactive"
    state["background_runtime_enabled"] = normalized_mode == "autonomous"
    state["automation_last_changed_at"] = now
    state["automation_last_changed_by"] = actor
    state["automation_last_reason"] = reason or (
        "Autonomous runtime activated." if normalized_mode == "autonomous" else f"Automation mode set to {normalized_mode}."
    )

    update_tasks_for_mode(state, normalized_mode)
    write_json(state_path(project_root), state)
    update_control_markdown(project_root, state)
    sessions = update_sessions_for_mode(project_root, state, normalized_mode, reason=reason)
    return write_control_reports(project_root, state, sessions, reason=reason)


def current_status(project_root: Path) -> dict[str, Any]:
    state = ensure_control_state(project_root)
    sessions = ensure_registry_schema(project_root)
    return write_control_reports(project_root, state, sessions)


def main() -> None:
    parser = argparse.ArgumentParser(description="Control normal, autonomous, armed, and paused runtime modes for the chief orchestrator.")
    parser.add_argument("project_root", help="Target project root")
    parser.add_argument("--mode", choices=sorted(VALID_AUTOMATION_MODES), help="Target automation mode")
    parser.add_argument("--actor", default="user", help="Who initiated the mode change")
    parser.add_argument("--reason", help="Why the mode changed")
    parser.add_argument("--resume-action", help="Action to resume when automation restarts after a pause")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    payload = (
        set_mode(project_root, args.mode, actor=args.actor, reason=args.reason, resume_action=args.resume_action)
        if args.mode
        else current_status(project_root)
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
