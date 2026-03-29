from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

from common import read_json, utc_now, write_json


def detect_openclaw_cli() -> str | None:
    return shutil.which("openclaw")


def runtime_dir(project_root: Path) -> Path:
    return project_root / "ai" / "runtime"


def outbox_dir(project_root: Path) -> Path:
    path = runtime_dir(project_root) / "outbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def outbox_archive_dir(project_root: Path, bucket: str) -> Path:
    path = outbox_dir(project_root) / bucket
    path.mkdir(parents=True, exist_ok=True)
    return path


def persist_dispatch_envelope(project_root: Path, envelope: dict[str, Any]) -> Path:
    dispatch_id = str(envelope["dispatch_id"])
    path = outbox_dir(project_root) / f"{dispatch_id}.json"
    write_json(path, envelope)
    return path


def runtime_config_path(project_root: Path) -> Path:
    return project_root / "ai" / "runtime" / "runtime-config.json"


def command_template(project_root: Path, mode: str) -> str | None:
    if mode == "spawn":
        env_name = "OPENCLAW_SPAWN_COMMAND"
        config_key = "spawn_command"
    else:
        env_name = "OPENCLAW_SEND_COMMAND"
        config_key = "send_command"
    env_value = os.environ.get(env_name, "").strip()
    if env_value:
        return env_value
    config = read_json(runtime_config_path(project_root))
    value = str(config.get(config_key) or "").strip()
    return value or None


def execute_dispatch_command(project_root: Path, envelope_path: Path, envelope: dict[str, Any]) -> dict[str, Any]:
    template = command_template(project_root, str(envelope.get("mode") or "spawn"))
    envelope["last_attempted_at"] = utc_now()
    if not template:
        envelope["status"] = "queued-awaiting-command-config"
        envelope.pop("sent_at", None)
        return envelope

    command = template.format(
        payload_file=str(envelope_path),
        dispatch_file=str(envelope_path),
        agent_id=str(envelope.get("agent_id") or ""),
    )
    completed = subprocess.run(command, capture_output=True, text=True, shell=True, check=False)
    envelope["command"] = command
    envelope["stdout"] = completed.stdout.strip()
    envelope["stderr"] = completed.stderr.strip()
    if completed.returncode == 0:
        envelope["status"] = "sent"
        envelope["sent_at"] = utc_now()
    else:
        envelope["status"] = "failed"
        envelope.pop("sent_at", None)
    return envelope


def load_dispatch_envelope(envelope_path: Path) -> dict[str, Any]:
    return json.loads(envelope_path.read_text(encoding="utf-8"))


def archive_dispatch_envelope(project_root: Path, envelope_path: Path, bucket: str) -> Path:
    target = outbox_archive_dir(project_root, bucket) / envelope_path.name
    envelope_path.replace(target)
    return target


def deliver_envelope(project_root: Path, envelope_path: Path) -> dict[str, Any]:
    envelope = load_dispatch_envelope(envelope_path)
    if envelope.get("status") == "sent":
        archived_path: Path | None = None
        if envelope_path.parent == outbox_dir(project_root):
            archived_path = archive_dispatch_envelope(project_root, envelope_path, "sent")
        return {
            "dispatch_id": envelope.get("dispatch_id"),
            "status": "sent",
            "agent_id": envelope.get("agent_id"),
            "envelope_path": str((archived_path or envelope_path).resolve()),
            "archived_path": str(archived_path.resolve()) if archived_path else None,
        }

    updated = execute_dispatch_command(project_root, envelope_path, envelope)
    write_json(envelope_path, updated)
    archived_path: Path | None = None
    if updated.get("status") == "sent":
        archived_path = archive_dispatch_envelope(project_root, envelope_path, "sent")

    return {
        "dispatch_id": updated.get("dispatch_id"),
        "status": updated.get("status"),
        "agent_id": updated.get("agent_id"),
        "envelope_path": str((archived_path or envelope_path).resolve()),
        "archived_path": str(archived_path.resolve()) if archived_path else None,
    }


def deliver_outbox(project_root: Path, max_items: int | None = None) -> dict[str, Any]:
    items = sorted(path for path in outbox_dir(project_root).glob("*.json") if path.is_file())
    if max_items is not None:
        items = items[:max_items]
    results = [deliver_envelope(project_root, path) for path in items]
    return {
        "attempted_count": len(results),
        "sent_count": sum(1 for item in results if item["status"] == "sent"),
        "failed_count": sum(1 for item in results if item["status"] == "failed"),
        "pending_config_count": sum(1 for item in results if item["status"] == "queued-awaiting-command-config"),
        "items": results,
    }


def dispatch_payload(
    project_root: Path,
    payload: dict[str, Any],
    mode: str,
    agent_id: str,
    task_card: Path | None = None,
    transport: str | None = None,
) -> dict[str, Any]:
    dispatch_id = f"{utc_now().replace(':', '').replace('+00:00', 'Z')}-{agent_id}-{mode}-{uuid4().hex[:8]}"
    selected_transport = transport or os.environ.get("SILIJIAN_DISPATCH_TRANSPORT", "outbox")
    envelope = {
        "dispatch_id": dispatch_id,
        "created_at": utc_now(),
        "transport": selected_transport,
        "mode": mode,
        "agent_id": agent_id,
        "task_card": str(task_card) if task_card else None,
        "payload": payload,
        "status": "queued",
        "openclaw_cli_available": bool(detect_openclaw_cli()),
    }
    envelope_path = persist_dispatch_envelope(project_root, envelope)

    if selected_transport == "command":
        envelope = execute_dispatch_command(project_root, envelope_path, envelope)
        write_json(envelope_path, envelope)

    return envelope


def main() -> None:
    parser = argparse.ArgumentParser(description="Queue or execute an OpenClaw dispatch envelope.")
    parser.add_argument("project_root", help="Target project root")
    parser.add_argument("payload_file", nargs="?", help="JSON file containing the prepared payload")
    parser.add_argument("--mode", choices=["spawn", "send"])
    parser.add_argument("--agent-id", help="Target agent id")
    parser.add_argument("--task-card", help="Optional task card source path")
    parser.add_argument("--transport", choices=["outbox", "command"], help="Dispatch transport override")
    parser.add_argument("--drain-outbox", action="store_true", help="Deliver queued envelopes already present in ai/runtime/outbox")
    parser.add_argument("--max-items", type=int, help="Maximum queued envelopes to deliver when using --drain-outbox")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    if args.drain_outbox:
        result = deliver_outbox(project_root, max_items=args.max_items)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    if not args.payload_file or not args.mode or not args.agent_id:
        raise SystemExit("payload_file, --mode, and --agent-id are required unless --drain-outbox is used")

    payload = json.loads(Path(args.payload_file).read_text(encoding="utf-8"))
    envelope = dispatch_payload(
        project_root,
        payload,
        args.mode,
        args.agent_id,
        task_card=Path(args.task_card).resolve() if args.task_card else None,
        transport=args.transport,
    )
    print(json.dumps(envelope, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
