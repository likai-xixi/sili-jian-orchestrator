from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from common import extract_field_value, read_text, utc_now, write_json, write_text


def reports_dir(project_root: Path) -> Path:
    path = project_root / "ai" / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_git(project_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(project_root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def current_changes(project_root: Path) -> list[str]:
    result = run_git(project_root, "status", "--porcelain", "--untracked-files=all", "--", ".")
    if result.returncode != 0:
        return []
    return [line.rstrip() for line in result.stdout.splitlines() if line.strip()]


def _normalize_change_path(raw: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    if " -> " in text:
        text = text.split(" -> ", 1)[1].strip()
    if text.startswith('"') and text.endswith('"') and len(text) >= 2:
        text = text[1:-1]
    return text.replace("\\", "/")


def change_paths(changes: list[str]) -> list[str]:
    paths: list[str] = []
    for item in changes:
        if len(item) < 4:
            continue
        normalized = _normalize_change_path(item[3:])
        if normalized:
            paths.append(normalized)
    return paths


def staged_changes(project_root: Path, paths: list[str] | None = None) -> list[str]:
    scope = paths if paths else ["."]
    result = run_git(project_root, "diff", "--cached", "--name-only", "--", *scope)
    if result.returncode != 0:
        return []
    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]


def committed_changes(project_root: Path, revision: str = "HEAD") -> list[str]:
    result = run_git(project_root, "show", "--name-only", "--pretty=format:", revision)
    if result.returncode != 0:
        return []
    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]


def _normalize_selector(project_root: Path, raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    candidate = Path(value)
    if candidate.is_absolute():
        try:
            value = str(candidate.resolve().relative_to(project_root.resolve()))
        except ValueError:
            return ""
    return value.replace("\\", "/").strip("/")


def _split_files_touched(project_root: Path, raw: str) -> list[str]:
    items: list[str] = []
    for chunk in raw.replace("\n", ",").split(","):
        normalized = _normalize_selector(project_root, chunk)
        if normalized and normalized.lower() not in {"none", "n/a", "na"}:
            items.append(normalized)
    return items


def round_related_selectors(project_root: Path, round_id: str | None) -> set[str]:
    selectors: set[str] = set()
    if not round_id:
        return selectors
    handoff_root = project_root / "ai" / "handoff"
    for handoff_path in handoff_root.glob("*/active/*.md"):
        text = read_text(handoff_path)
        if extract_field_value(text, "task_round_id") != round_id:
            continue
        selectors.add(str(handoff_path.resolve().relative_to(project_root.resolve())).replace("\\", "/"))
        selectors.update(_split_files_touched(project_root, extract_field_value(text, "files_touched")))
    return selectors


def path_selected(path: str, selectors: set[str]) -> bool:
    normalized = path.replace("\\", "/").strip("/")
    if normalized.startswith("ai/"):
        return True
    for selector in selectors:
        base = selector.strip("/")
        if not base:
            continue
        if normalized == base or normalized.startswith(base + "/"):
            return True
    return False


def eligible_change_paths(project_root: Path, changes: list[str], round_id: str | None) -> tuple[list[str], list[str]]:
    selectors = round_related_selectors(project_root, round_id)
    eligible: list[str] = []
    ignored: list[str] = []
    seen: set[str] = set()
    for path in change_paths(changes):
        if path in seen:
            continue
        seen.add(path)
        if path_selected(path, selectors):
            eligible.append(path)
        else:
            ignored.append(path)
    return eligible, ignored


def render_report(payload: dict) -> str:
    changes = "\n".join(f"- {item}" for item in payload.get("changes", [])) or "- none"
    ignored = "\n".join(f"- {item}" for item in payload.get("ignored_changes", [])) or "- none"
    return f"""# Auto Commit

- created_at: {payload.get('created_at', '')}
- status: {payload.get('status', '')}
- repo_root: {payload.get('repo_root', '')}
- commit_message: {payload.get('commit_message') or 'n/a'}
- commit_sha: {payload.get('commit_sha') or 'n/a'}
- push_status: {payload.get('push_status') or 'n/a'}
- reason: {payload.get('reason') or 'n/a'}

## Changes

{changes}

## Ignored Changes

{ignored}
"""


def autocommit(project_root: Path, *, cycle_index: int, push: bool = False, scope_label: str | None = None) -> dict:
    project_root = project_root.resolve()
    created_at = utc_now()
    rev_parse = run_git(project_root, "rev-parse", "--show-toplevel")
    if rev_parse.returncode != 0:
        payload = {
            "created_at": created_at,
            "status": "skipped-no-git",
            "repo_root": "",
            "changes": [],
            "reason": "No git repository is available for automatic commits.",
        }
        write_json(reports_dir(project_root) / "auto-commit.json", payload)
        write_text(reports_dir(project_root) / "auto-commit.md", render_report(payload))
        return payload

    changes = current_changes(project_root)
    repo_root = rev_parse.stdout.strip()
    if not changes:
        payload = {
            "created_at": created_at,
            "status": "skipped-no-changes",
            "repo_root": repo_root,
            "changes": [],
            "ignored_changes": [],
            "reason": "No project-root changes were present to commit.",
        }
        write_json(reports_dir(project_root) / "auto-commit.json", payload)
        write_text(reports_dir(project_root) / "auto-commit.md", render_report(payload))
        return payload

    label = (scope_label or f"runtime cycle {cycle_index}").strip()
    eligible_paths, ignored_paths = eligible_change_paths(project_root, changes, scope_label)
    if not eligible_paths:
        payload = {
            "created_at": created_at,
            "status": "skipped-no-eligible-changes",
            "repo_root": repo_root,
            "changes": [],
            "ignored_changes": ignored_paths,
            "reason": "Only unrelated local changes were present, so the automatic checkpoint was skipped.",
        }
        write_json(reports_dir(project_root) / "auto-commit.json", payload)
        write_text(reports_dir(project_root) / "auto-commit.md", render_report(payload))
        return payload

    commit_message = f"chore(orchestrator): checkpoint after {label}"
    add_result = run_git(project_root, "add", "-A", "--", *eligible_paths)
    staged_paths = staged_changes(project_root, eligible_paths)
    if not staged_paths:
        payload = {
            "created_at": created_at,
            "status": "skipped-no-staged-changes",
            "repo_root": repo_root,
            "changes": [],
            "ignored_changes": ignored_paths,
            "reason": "No eligible changes were staged for the automatic checkpoint.",
            "add_stdout": add_result.stdout.strip(),
            "add_stderr": add_result.stderr.strip(),
        }
        write_json(reports_dir(project_root) / "auto-commit.json", payload)
        write_text(reports_dir(project_root) / "auto-commit.md", render_report(payload))
        return payload
    commit_result = run_git(project_root, "commit", "--only", "-m", commit_message, "--", *eligible_paths)
    payload = {
        "created_at": created_at,
        "status": "committed" if commit_result.returncode == 0 else "commit-failed",
        "repo_root": repo_root,
        "changes": staged_paths,
        "ignored_changes": ignored_paths,
        "eligible_paths": eligible_paths,
        "commit_message": commit_message,
        "add_stdout": add_result.stdout.strip(),
        "add_stderr": add_result.stderr.strip(),
        "commit_stdout": commit_result.stdout.strip(),
        "commit_stderr": commit_result.stderr.strip(),
        "commit_sha": None,
        "push_status": "not-requested",
        "reason": "",
    }
    if commit_result.returncode == 0:
        payload["changes"] = committed_changes(project_root)
        sha_result = run_git(project_root, "rev-parse", "HEAD")
        if sha_result.returncode == 0:
            payload["commit_sha"] = sha_result.stdout.strip()
        if push:
            push_result = run_git(project_root, "push")
            payload["push_status"] = "pushed" if push_result.returncode == 0 else "push-failed"
            payload["push_stdout"] = push_result.stdout.strip()
            payload["push_stderr"] = push_result.stderr.strip()
    else:
        payload["reason"] = "git commit returned a non-zero exit code."

    write_json(reports_dir(project_root) / "auto-commit.json", payload)
    write_text(reports_dir(project_root) / "auto-commit.md", render_report(payload))
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Commit current project-root changes as an orchestrator checkpoint.")
    parser.add_argument("project_root", help="Target project root")
    parser.add_argument("--cycle-index", type=int, default=1, help="Runtime loop cycle index for the commit message")
    parser.add_argument("--push", action="store_true", help="Push after a successful commit")
    args = parser.parse_args()

    payload = autocommit(Path(args.project_root).resolve(), cycle_index=args.cycle_index, push=args.push)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if payload["status"] == "commit-failed" or payload.get("push_status") == "push-failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
