from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from common import utc_now, write_json


KIND_ENV_PREFIX = {
    "ci": "SILIJIAN_CI",
    "release": "SILIJIAN_RELEASE",
    "rollback": "SILIJIAN_ROLLBACK",
}

PASS_STATES = {"success", "passed", "pass", "completed", "succeeded", "yes", "green"}
WARN_STATES = {"neutral", "warning", "pass_with_warning", "in_progress", "queued", "pending", "running"}
FAIL_STATES = {"failure", "failed", "fail", "error", "timed_out", "cancelled", "canceled", "no", "red"}
SKIP_STATES = {"skipped", "not_run", "not-run", "none", ""}


def status_from_value(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_")
    if normalized in PASS_STATES:
        return "PASS"
    if normalized in WARN_STATES:
        return "PASS_WITH_WARNING"
    if normalized in FAIL_STATES:
        return "FAIL"
    if normalized in SKIP_STATES:
        return "SKIPPED"
    return "PASS_WITH_WARNING"


def provider_json_path(kind: str) -> str:
    return f"{KIND_ENV_PREFIX[kind]}_PROVIDER_JSON"


def provider_name(kind: str) -> str:
    return f"{KIND_ENV_PREFIX[kind]}_PROVIDER"


def provider_source(kind: str) -> str:
    return f"{KIND_ENV_PREFIX[kind]}_PROVIDER_SOURCE"


def github_repo_env(kind: str) -> str:
    return f"{KIND_ENV_PREFIX[kind]}_GITHUB_REPO"


def github_branch_env(kind: str) -> str:
    return f"{KIND_ENV_PREFIX[kind]}_GITHUB_BRANCH"


def github_workflow_env(kind: str) -> str:
    return f"{KIND_ENV_PREFIX[kind]}_GITHUB_WORKFLOW"


def preferred_status_value(payload: dict[str, Any]) -> str:
    # GitHub Actions commonly reports status=completed plus conclusion=failure/success.
    for key in ("conclusion", "result", "status", "state"):
        value = payload.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def normalize_payload(kind: str, provider: str, payload: dict[str, Any], source: str) -> dict[str, Any]:
    raw_status = preferred_status_value(payload)
    return {
        "kind": kind,
        "provider": provider,
        "source": source,
        "collected_at": utc_now(),
        "status": status_from_value(raw_status),
        "raw_status": raw_status,
        "summary": str(payload.get("summary") or payload.get("title") or payload.get("name") or ""),
        "url": str(payload.get("url") or payload.get("html_url") or ""),
        "run_id": str(payload.get("run_id") or payload.get("databaseId") or payload.get("id") or ""),
        "workflow": str(payload.get("workflow") or payload.get("workflowName") or payload.get("name") or ""),
        "raw": payload,
    }


def load_json_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_provider_json(kind: str) -> dict[str, Any] | None:
    configured = os.environ.get(provider_json_path(kind), "").strip()
    if not configured:
        return None
    path = Path(configured).resolve()
    if not path.exists():
        return {
            "kind": kind,
            "provider": os.environ.get(provider_name(kind), "json"),
            "source": "json-file",
            "collected_at": utc_now(),
            "status": "FAIL",
            "raw_status": "missing-json",
            "summary": f"Configured provider JSON file is missing: {path}",
            "url": "",
            "run_id": "",
            "workflow": "",
            "raw": {"path": str(path)},
        }
    try:
        payload = load_json_payload(path)
    except json.JSONDecodeError as exc:
        return {
            "kind": kind,
            "provider": os.environ.get(provider_name(kind), "json"),
            "source": "json-file",
            "collected_at": utc_now(),
            "status": "FAIL",
            "raw_status": "invalid-json",
            "summary": f"Configured provider JSON file is invalid: {path}",
            "url": "",
            "run_id": "",
            "workflow": "",
            "raw": {
                "path": str(path),
                "error": str(exc),
            },
        }
    except (OSError, UnicodeDecodeError) as exc:
        return {
            "kind": kind,
            "provider": os.environ.get(provider_name(kind), "json"),
            "source": "json-file",
            "collected_at": utc_now(),
            "status": "FAIL",
            "raw_status": "read-error",
            "summary": f"Configured provider JSON file could not be read: {path}",
            "url": "",
            "run_id": "",
            "workflow": "",
            "raw": {
                "path": str(path),
                "error": str(exc),
            },
        }
    provider = str(payload.get("provider") or os.environ.get(provider_name(kind), "json"))
    return normalize_payload(kind, provider, payload, "json-file")


def github_cli_available() -> bool:
    return shutil.which("gh") is not None


def github_run_list(kind: str) -> dict[str, Any] | None:
    repo = os.environ.get(github_repo_env(kind), "").strip()
    workflow = os.environ.get(github_workflow_env(kind), "").strip()
    branch = os.environ.get(github_branch_env(kind), "").strip()
    if not github_cli_available() or not repo:
        return None

    command = [
        "gh",
        "run",
        "list",
        "--repo",
        repo,
        "--limit",
        "1",
        "--json",
        "databaseId,status,conclusion,workflowName,displayTitle,url,headBranch",
    ]
    if workflow:
        command.extend(["--workflow", workflow])
    if branch:
        command.extend(["--branch", branch])

    completed = subprocess.run(command, capture_output=True, text=True, shell=False, check=False)
    if completed.returncode != 0:
        return {
            "kind": kind,
            "provider": "github-actions",
            "source": "gh-cli",
            "collected_at": utc_now(),
            "status": "FAIL",
            "raw_status": "gh-cli-error",
            "summary": completed.stderr.strip() or "gh run list failed",
            "url": "",
            "run_id": "",
            "workflow": workflow,
            "raw": {"command": command},
        }
    try:
        items = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError:
        items = []
    if not items:
        return {
            "kind": kind,
            "provider": "github-actions",
            "source": "gh-cli",
            "collected_at": utc_now(),
            "status": "PASS_WITH_WARNING",
            "raw_status": "no-run-found",
            "summary": "No matching GitHub Actions run was found.",
            "url": "",
            "run_id": "",
            "workflow": workflow,
            "raw": {"command": command},
        }
    payload = items[0]
    payload["summary"] = payload.get("displayTitle") or payload.get("workflowName") or "GitHub Actions run"
    payload["workflow"] = payload.get("workflowName") or workflow
    return normalize_payload(kind, "github-actions", payload, "gh-cli")


def collect_kind(kind: str, project_root: Path) -> dict[str, Any]:
    json_result = read_provider_json(kind)
    if json_result:
        return json_result

    provider = os.environ.get(provider_name(kind), "").strip().lower()
    if provider == "github-actions":
        github_result = github_run_list(kind)
        if github_result:
            return github_result

    source = os.environ.get(provider_source(kind), "").strip().lower()
    if source == "github-actions":
        github_result = github_run_list(kind)
        if github_result:
            return github_result

    return {
        "kind": kind,
        "provider": provider or "none",
        "source": "not-configured",
        "collected_at": utc_now(),
        "status": "SKIPPED",
        "raw_status": "",
        "summary": "No provider-backed evidence configured.",
        "url": "",
        "run_id": "",
        "workflow": "",
        "raw": {"project_root": str(project_root.resolve())},
    }


def collect_provider_evidence(project_root: Path) -> dict[str, Any]:
    results = {kind: collect_kind(kind, project_root) for kind in ("ci", "release", "rollback")}
    summary = {
        "collected_at": utc_now(),
        "project_root": str(project_root.resolve()),
        "results": results,
    }
    reports_dir = project_root / "ai" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    write_json(reports_dir / "provider-evidence-summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect provider-backed CI, release, and rollback evidence.")
    parser.add_argument("project_root", help="Target project root")
    args = parser.parse_args()

    payload = collect_provider_evidence(Path(args.project_root).resolve())
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
