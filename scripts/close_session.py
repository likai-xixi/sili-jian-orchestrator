from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from common import read_json, read_text, utc_now, write_json, write_text
from runtime_environment import ensure_runtime_environment
from session_registry import ensure_registry_schema


def reports_dir(project_root: Path) -> Path:
    path = project_root / "ai" / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def reattach_dir(project_root: Path) -> Path:
    path = project_root / "ai" / "runtime" / "reattach"
    path.mkdir(parents=True, exist_ok=True)
    return path


def runtime_config(project_root: Path) -> dict:
    return read_json(project_root / "ai" / "runtime" / "runtime-config.json")


def resolve_close_command(project_root: Path) -> tuple[str, str]:
    env_value = os.environ.get("OPENCLAW_CLOSE_SESSION_COMMAND", "").strip()
    if env_value:
        return env_value, "environment"
    config = runtime_config(project_root)
    value = str(config.get("close_session_command") or "").strip()
    if value:
        source = str(config.get("host_interface_sources", {}).get("close_session_command") or "project-config")
        return value, source
    return "", "missing"


def find_active_task(state: dict, agent_id: str) -> dict | None:
    for task in state.get("active_tasks", []):
        if str(task.get("role") or "") == agent_id and str(task.get("status") or "").lower() not in {"closed", "completed"}:
            return task
    return None


def update_project_handoff(project_root: Path, agent_id: str, reason: str, native_status: str) -> None:
    handoff_path = project_root / "ai" / "state" / "project-handoff.md"
    text = read_text(handoff_path)
    if not text:
        return
    addition = f"\n## Session Closure\n\n- agent: {agent_id}\n- reason: {reason}\n- native_close_status: {native_status}\n- closed_at: {utc_now()}\n"
    write_text(handoff_path, text.rstrip() + addition)


def build_close_payload(project_root: Path, agent_id: str, reason: str) -> dict:
    registry = ensure_registry_schema(project_root)
    state = read_json(project_root / "ai" / "state" / "orchestrator-state.json")
    record = registry.get(agent_id, {})
    task = find_active_task(state, agent_id)
    return {
        "created_at": utc_now(),
        "project_root": str(project_root.resolve()),
        "agent_id": agent_id,
        "session_key": str(record.get("session_key") or ""),
        "last_task_id": record.get("last_task_id"),
        "last_step_id": record.get("last_step_id"),
        "handoff_path": record.get("handoff_path"),
        "reason": reason,
        "active_task": task,
        "native_close_status": "not-attempted",
    }


def close_payload_path(project_root: Path, agent_id: str) -> Path:
    return reattach_dir(project_root) / f"{agent_id}-close-session.json"


def write_close_artifacts(project_root: Path, payload: dict) -> dict:
    path = close_payload_path(project_root, str(payload.get("agent_id") or "agent"))
    write_json(path, payload)
    report_base = reports_dir(project_root)
    write_json(report_base / f"session-close-{payload['agent_id']}.json", payload)
    write_text(report_base / f"session-close-{payload['agent_id']}.md", render_close_markdown(payload))
    payload["payload_path"] = str(path.resolve())
    return payload


def render_close_markdown(payload: dict) -> str:
    return f"""# Session Close

- agent_id: {payload.get('agent_id', '')}
- session_key: {payload.get('session_key', '')}
- reason: {payload.get('reason', '')}
- native_close_status: {payload.get('native_close_status', '')}
- native_close_command_source: {payload.get('native_close_command_source', 'missing')}
- native_close_blocked_reason: {payload.get('native_close_blocked_reason') or 'none'}
"""


def attempt_native_close(project_root: Path, payload: dict) -> dict:
    ensure_runtime_environment(project_root)
    template, source = resolve_close_command(project_root)
    path = close_payload_path(project_root, str(payload.get("agent_id") or "agent"))
    result = {
        "status": "pending-command-config",
        "command_source": source,
        "command": "",
        "stdout": "",
        "stderr": "",
        "blocked_reason": "",
    }
    if not str(payload.get("session_key") or ""):
        result["status"] = "skipped-no-session"
        result["blocked_reason"] = "No persisted session key is available to close."
        return result
    if not template:
        result["blocked_reason"] = "No close-session command is configured."
        return result
    command = template.format(
        payload_file=str(path),
        session_key=str(payload.get("session_key") or ""),
        agent_id=str(payload.get("agent_id") or ""),
    )
    completed = subprocess.run(command, capture_output=True, text=True, shell=True, check=False)
    result["command"] = command
    result["stdout"] = completed.stdout.strip()
    result["stderr"] = completed.stderr.strip()
    result["status"] = "closed" if completed.returncode == 0 else "close-failed"
    if completed.returncode != 0:
        result["blocked_reason"] = "The configured close-session command returned a non-zero exit code."
    return result


def apply_close(project_root: Path, agent_id: str, reason: str, force_native: bool = False) -> dict:
    payload = build_close_payload(project_root, agent_id, reason)
    payload = write_close_artifacts(project_root, payload)
    native = attempt_native_close(project_root, payload) if force_native or payload.get("session_key") else {
        "status": "logical-only",
        "command_source": "missing",
        "command": "",
        "stdout": "",
        "stderr": "",
        "blocked_reason": "No session key was available, so only the local registry was retired.",
    }
    payload["native_close_attempt"] = native
    payload["native_close_status"] = native["status"]
    payload["native_close_command_source"] = native.get("command_source", "missing")
    payload["native_close_blocked_reason"] = native.get("blocked_reason") or None

    registry = ensure_registry_schema(project_root)
    record = dict(registry.get(agent_id, {}))
    record["status"] = "closed"
    record["blocked_reason"] = reason
    if native["status"] == "closed":
        record["session_key"] = None
    registry[agent_id] = record
    write_json(project_root / "ai" / "state" / "agent-sessions.json", registry)

    state_path = project_root / "ai" / "state" / "orchestrator-state.json"
    state = read_json(state_path)
    active_tasks = state.get("active_tasks", [])
    for task in active_tasks:
        if str(task.get("role") or "") == agent_id and str(task.get("status") or "").lower() not in {"completed", "closed"}:
            task["status"] = "closed"
    state["active_tasks"] = active_tasks
    state["next_owner"] = "orchestrator"
    state["next_action"] = f"Session for {agent_id} was closed. Reassign work or continue with another agent."
    write_json(state_path, state)

    update_project_handoff(project_root, agent_id, reason, payload["native_close_status"])
    payload = write_close_artifacts(project_root, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Write handoff, close a child session natively when possible, and retire it from the local registry.")
    parser.add_argument("project_root", help="Target project root")
    parser.add_argument("--agent-id", required=True, help="Target child agent id")
    parser.add_argument("--reason", default="Session closed by orchestrator request.", help="Why the session is being closed")
    parser.add_argument("--force-native", action="store_true", help="Attempt the native close command whenever a session key is present")
    args = parser.parse_args()

    payload = apply_close(Path(args.project_root).resolve(), args.agent_id, args.reason, force_native=args.force_native)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if payload["native_close_status"] == "close-failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
