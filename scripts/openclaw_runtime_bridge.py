from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

from common import write_json


def detect_openclaw_cli() -> str | None:
    return shutil.which("openclaw")


def load_payload(payload_path: Path) -> dict:
    return json.loads(payload_path.read_text(encoding="utf-8"))


def bridge_report_path(payload_path: Path) -> Path:
    return payload_path.with_suffix(".bridge.json")


def candidate_parent_attach_commands(payload_path: Path, payload: dict) -> list[list[str]]:
    cli = detect_openclaw_cli()
    if not cli:
        return []
    session_key = str(payload.get("session_key") or "")
    commands = [
        [cli, "parent-attach", "--payload-file", str(payload_path)],
        [cli, "attach-parent", "--payload-file", str(payload_path)],
        [cli, "attach", "--payload-file", str(payload_path)],
        [cli, "sessions", "attach", "--payload-file", str(payload_path)],
    ]
    if session_key:
        commands.append([cli, "attach", "--session-key", session_key, "--payload-file", str(payload_path)])
    return commands


def candidate_close_session_commands(payload_path: Path, payload: dict) -> list[list[str]]:
    cli = detect_openclaw_cli()
    if not cli:
        return []
    session_key = str(payload.get("session_key") or "")
    agent_id = str(payload.get("agent_id") or "")
    commands = [
        [cli, "session", "close", "--payload-file", str(payload_path)],
        [cli, "session", "terminate", "--payload-file", str(payload_path)],
        [cli, "close-session", "--payload-file", str(payload_path)],
        [cli, "terminate-session", "--payload-file", str(payload_path)],
    ]
    if session_key:
        commands.extend(
            [
                [cli, "session", "close", "--session-key", session_key],
                [cli, "session", "terminate", "--session-key", session_key],
            ]
        )
    if agent_id:
        commands.append([cli, "session", "close", "--agent-id", agent_id, "--payload-file", str(payload_path)])
    return commands


def run_parent_attach(payload_path: Path) -> dict:
    payload = load_payload(payload_path)
    attempts: list[dict] = []
    for argv in candidate_parent_attach_commands(payload_path, payload):
        completed = subprocess.run(argv, capture_output=True, text=True, check=False)
        attempt = {
            "command": argv,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
            "returncode": completed.returncode,
        }
        attempts.append(attempt)
        if completed.returncode == 0:
            result = {
                "status": "attached",
                "payload_path": str(payload_path.resolve()),
                "selected_command": argv,
                "attempt_count": len(attempts),
                "attempts": attempts,
            }
            write_json(bridge_report_path(payload_path), result)
            return result

    blocked_reason = "OpenClaw CLI was not found on PATH." if not detect_openclaw_cli() else "No OpenClaw parent-attach command variant completed successfully."
    result = {
        "status": "attach-failed" if attempts else "openclaw-unavailable",
        "payload_path": str(payload_path.resolve()),
        "selected_command": [],
        "attempt_count": len(attempts),
        "attempts": attempts,
        "blocked_reason": blocked_reason,
    }
    write_json(bridge_report_path(payload_path), result)
    return result


def run_close_session(payload_path: Path) -> dict:
    payload = load_payload(payload_path)
    attempts: list[dict] = []
    for argv in candidate_close_session_commands(payload_path, payload):
        completed = subprocess.run(argv, capture_output=True, text=True, check=False)
        attempt = {
            "command": argv,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
            "returncode": completed.returncode,
        }
        attempts.append(attempt)
        if completed.returncode == 0:
            result = {
                "status": "closed",
                "payload_path": str(payload_path.resolve()),
                "selected_command": argv,
                "attempt_count": len(attempts),
                "attempts": attempts,
            }
            write_json(bridge_report_path(payload_path), result)
            return result

    blocked_reason = "OpenClaw CLI was not found on PATH." if not detect_openclaw_cli() else "No OpenClaw close-session command variant completed successfully."
    result = {
        "status": "close-failed" if attempts else "openclaw-unavailable",
        "payload_path": str(payload_path.resolve()),
        "selected_command": [],
        "attempt_count": len(attempts),
        "attempts": attempts,
        "blocked_reason": blocked_reason,
    }
    write_json(bridge_report_path(payload_path), result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Bridge project-local payloads into a real OpenClaw runtime command.")
    parser.add_argument("action", choices=["parent-attach", "close-session"], help="Bridge action to execute")
    parser.add_argument("payload_file", help="Prepared payload file consumed by the bridge")
    args = parser.parse_args()

    payload_path = Path(args.payload_file).resolve()
    if args.action == "parent-attach":
        result = run_parent_attach(payload_path)
    elif args.action == "close-session":
        result = run_close_session(payload_path)
    else:
        raise SystemExit(f"Unsupported bridge action: {args.action}")

    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result["status"] != "attached":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
