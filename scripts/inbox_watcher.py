from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from completion_consumer import consume_completion
from common import write_json, write_text


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


def process_completion_file(project_root: Path, completion_file: Path, archive: bool = True) -> dict:
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
        write_text(
            error_path,
            f"# Inbox Processing Error\n\n- file: {archived_path.name}\n- error: {exc}\n",
        )
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
