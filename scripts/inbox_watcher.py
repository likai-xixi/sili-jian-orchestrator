from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import close_session
from completion_consumer import consume_completion
from common import utc_now, write_json, write_text
from runtime_guardrails import invalid_completion_fuse_threshold
from session_registry import ensure_registry_schema, upsert_session


def inbox_dir(project_root: Path) -> Path:
    path = project_root / "ai" / "runtime" / "inbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def inbox_archive_dir(project_root: Path, bucket: str) -> Path:
    path = inbox_dir(project_root) / bucket
    path.mkdir(parents=True, exist_ok=True)
    return path


def pending_completion_files(project_root: Path) -> list[Path]:
    return sorted(path for path in inbox_dir(project_root).glob("*.json") if path.is_file())


def archive_completion_file(project_root: Path, completion_file: Path, bucket: str) -> Path:
    target = inbox_archive_dir(project_root, bucket) / completion_file.name
    completion_file.replace(target)
    return target


def error_log_path(project_root: Path, completion_file: Path) -> Path:
    return inbox_archive_dir(project_root, "failed") / f"{completion_file.stem}.error.txt"


def write_drift_guard_report(project_root: Path, payload: dict) -> None:
    reports_dir = project_root / "ai" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    agent_id = str(payload.get("agent_id") or "unknown")
    stem = f"agent-drift-guard-{agent_id}"
    write_json(reports_dir / f"{stem}.json", payload)
    write_text(
        reports_dir / f"{stem}.md",
        f"""# Agent Drift Guard

- created_at: {payload.get('created_at', '')}
- agent_id: {payload.get('agent_id', '')}
- invalid_completion_count: {payload.get('invalid_completion_count', 0)}
- fuse_threshold: {payload.get('fuse_threshold', 0)}
- fused: {'yes' if payload.get('fused') else 'no'}
- session_rebuild_required: {'yes' if payload.get('session_rebuild_required') else 'no'}
- reason: {payload.get('reason', '')}
- close_status: {payload.get('close_status') or 'not-attempted'}
""",
    )


def guard_invalid_completion(project_root: Path, payload: dict, error: str) -> dict | None:
    agent_id = str(payload.get("agent_id") or payload.get("role") or "").strip()
    if not agent_id:
        return None

    registry = ensure_registry_schema(project_root)
    record = dict(registry.get(agent_id, {}))
    invalid_count = int(record.get("consecutive_invalid_completions") or 0) + 1
    threshold = invalid_completion_fuse_threshold()
    fused = invalid_count >= threshold
    reason = f"Invalid completion from {agent_id}: {error}"

    upsert_session(
        project_root,
        agent_id,
        session_key=str(payload.get("session_key") or "") or None,
        consecutive_invalid_completions=invalid_count,
        last_invalid_completion_at=utc_now(),
        last_invalid_completion_reason=error,
        drift_status="fused" if fused else "monitor",
        rebuild_required=fused,
        rebuild_reason=reason if fused else None,
    )

    close_payload = None
    if fused:
        close_payload = close_session.apply_close(project_root, agent_id, reason, force_native=True)

    guard_payload = {
        "created_at": utc_now(),
        "agent_id": agent_id,
        "invalid_completion_count": invalid_count,
        "fuse_threshold": threshold,
        "fused": fused,
        "session_rebuild_required": fused,
        "reason": reason,
        "close_status": close_payload.get("native_close_status") if close_payload else None,
        "close_payload": close_payload,
    }
    write_drift_guard_report(project_root, guard_payload)
    return guard_payload


def process_completion_file(project_root: Path, completion_file: Path, archive: bool = True) -> dict:
    payload: dict | None = None
    try:
        payload = json.loads(completion_file.read_text(encoding="utf-8"))
        result = consume_completion(project_root, payload)
        archived_path = archive_completion_file(project_root, completion_file, "processed") if archive else None
        return {
            "file": completion_file.name,
            "status": "processed",
            "result": result,
            "archived_path": str(archived_path.resolve()) if archived_path else None,
        }
    except Exception as exc:
        archived_path = archive_completion_file(project_root, completion_file, "failed") if archive else completion_file
        error_path = error_log_path(project_root, archived_path)
        guard = guard_invalid_completion(project_root, payload, str(exc)) if isinstance(payload, dict) else None
        write_text(
            error_path,
            f"# Inbox Processing Error\n\n- file: {archived_path.name}\n- error: {exc}\n",
        )
        if guard is not None:
            return {
                "file": completion_file.name,
                "status": "guarded",
                "error": str(exc),
                "guard": guard,
                "archived_path": str(archived_path.resolve()),
                "error_log": str(error_path.resolve()),
            }
        return {
            "file": completion_file.name,
            "status": "failed",
            "error": str(exc),
            "archived_path": str(archived_path.resolve()),
            "error_log": str(error_path.resolve()),
        }


def process_inbox(project_root: Path, max_items: int | None = None, archive: bool = True) -> dict:
    files = pending_completion_files(project_root)
    if max_items is not None:
        files = files[:max_items]
    results = [process_completion_file(project_root, path, archive=archive) for path in files]
    summary = {
        "attempted_count": len(results),
        "processed_count": sum(1 for item in results if item["status"] == "processed"),
        "guarded_count": sum(1 for item in results if item["status"] == "guarded"),
        "failed_count": sum(1 for item in results if item["status"] == "failed"),
        "items": results,
    }
    reports_dir = project_root / "ai" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    write_json(reports_dir / "inbox-watch-summary.json", summary)
    write_text(
        reports_dir / "inbox-watch-summary.md",
        "# Inbox Watch Summary\n\n"
        + "\n".join(f"- {item['file']}: {item['status']}" for item in results)
        + ("\n" if results else "- no inbox payloads\n"),
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Consume queued completion payloads from ai/runtime/inbox.")
    parser.add_argument("project_root", help="Target project root")
    parser.add_argument("--max-items", type=int, help="Maximum number of inbox payloads to consume")
    parser.add_argument("--no-archive", action="store_true", help="Do not move processed payloads into archive folders")
    args = parser.parse_args()

    result = process_inbox(Path(args.project_root).resolve(), max_items=args.max_items, archive=not args.no_archive)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result["failed_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
