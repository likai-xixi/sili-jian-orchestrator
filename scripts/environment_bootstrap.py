from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import runtime_environment
from common import read_json, utc_now, write_json, write_text
from repo_command_detector import package_manager


TOOL_EXECUTABLES = {
    "git": ["git"],
    "node": ["node"],
    "npm": ["npm"],
    "pnpm": ["pnpm"],
    "yarn": ["yarn"],
    "gh": ["gh"],
    "openclaw": ["openclaw"],
}


def reports_dir(project_root: Path) -> Path:
    path = project_root / "ai" / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def executable_available(name: str) -> bool:
    candidates = TOOL_EXECUTABLES.get(name, [name])
    return any(shutil.which(candidate) for candidate in candidates)


def runtime_config(project_root: Path) -> dict:
    return runtime_environment.ensure_runtime_environment(project_root)


def project_dependency_actions(project_root: Path) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []

    if (project_root / "package.json").exists():
        manager = package_manager(project_root)
        install_command = {
            "pnpm": "pnpm install --frozen-lockfile",
            "yarn": "yarn install --frozen-lockfile",
            "npm": "npm install",
        }.get(manager, "npm install")
        actions.append(
            {
                "id": f"{manager}-install",
                "kind": "project-dependency",
                "tool": manager,
                "command": install_command,
                "reason": "Install JavaScript project dependencies from package manifests.",
            }
        )

    if (project_root / "requirements.txt").exists():
        actions.append(
            {
                "id": "pip-requirements",
                "kind": "project-dependency",
                "tool": "python",
                "command": f'"{sys.executable}" -m pip install -r "{project_root / "requirements.txt"}"',
                "reason": "Install Python project dependencies from requirements.txt.",
            }
        )
    elif (project_root / "pyproject.toml").exists() or (project_root / "setup.py").exists():
        actions.append(
            {
                "id": "pip-editable",
                "kind": "project-dependency",
                "tool": "python",
                "command": f'"{sys.executable}" -m pip install -e "{project_root}"',
                "reason": "Install the Python project in editable mode.",
            }
        )

    return actions


def required_system_tools(project_root: Path) -> list[str]:
    required: list[str] = ["git", "python"]
    if (project_root / "package.json").exists():
        required.append("node")
        required.append(package_manager(project_root))
    if (project_root / ".github" / "workflows").exists():
        required.append("gh")
    seen: set[str] = set()
    ordered: list[str] = []
    for item in required:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def missing_system_tools(project_root: Path) -> list[str]:
    missing: list[str] = []
    for tool in required_system_tools(project_root):
        if tool == "python":
            if not shutil.which(Path(sys.executable).name):
                missing.append(tool)
            continue
        if not executable_available(tool):
            missing.append(tool)
    return missing


def installer_commands(project_root: Path) -> dict[str, str]:
    config = json.loads((project_root / "ai" / "runtime" / "runtime-config.json").read_text(encoding="utf-8"))
    commands = config.get("tool_install_commands", {})
    return commands if isinstance(commands, dict) else {}


def dependency_input_files(project_root: Path) -> list[Path]:
    names = [
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "requirements.txt",
        "pyproject.toml",
        "setup.py",
    ]
    return [project_root / name for name in names if (project_root / name).exists()]


def dependency_cache_key(project_root: Path, dependency_actions: list[dict[str, str]]) -> dict:
    return {
        "commands": [action.get("command", "") for action in dependency_actions],
        "inputs": {
            str(path.relative_to(project_root)).replace("\\", "/"): path.stat().st_mtime_ns for path in dependency_input_files(project_root)
        },
    }


def run_action(command: str, cwd: Path) -> dict:
    completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, shell=True, check=False)
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "status": "completed" if completed.returncode == 0 else "failed",
    }


def ensure_environment(
    project_root: Path,
    apply: bool = True,
    include_system_tools: bool = False,
) -> dict:
    runtime_payload = runtime_environment.ensure_runtime_environment(project_root)
    dependency_actions = project_dependency_actions(project_root)
    dependency_key = dependency_cache_key(project_root, dependency_actions)
    missing_tools = missing_system_tools(project_root)
    tool_installers = installer_commands(project_root)
    previous_summary = read_json(reports_dir(project_root) / "environment-bootstrap.json")

    dependency_results: list[dict] = []
    if apply:
        cached_actions = previous_summary.get("dependency_actions", []) if isinstance(previous_summary, dict) else []
        cache_reusable = (
            previous_summary.get("dependency_cache_key") == dependency_key
            and cached_actions
            and all(str(item.get("status")) == "completed" for item in cached_actions)
        )
        if cache_reusable:
            dependency_results = [{**item, "status": "cached"} for item in cached_actions]
        else:
            for action in dependency_actions:
                dependency_results.append(
                    {
                        **action,
                        **run_action(action["command"], project_root),
                    }
                )
    else:
        dependency_results = [{**action, "status": "planned"} for action in dependency_actions]

    system_tool_results: list[dict] = []
    if include_system_tools:
        for tool in missing_tools:
            command = str(tool_installers.get(tool) or "").strip()
            if command:
                system_tool_results.append(
                    {
                        "tool": tool,
                        "kind": "system-tool",
                        **run_action(command, project_root),
                    }
                )
            else:
                system_tool_results.append(
                    {
                        "tool": tool,
                        "kind": "system-tool",
                        "command": "",
                        "status": "blocked",
                        "stdout": "",
                        "stderr": "",
                        "returncode": None,
                        "blocked_reason": f"No install command configured for missing tool `{tool}`.",
                    }
                )
    else:
        system_tool_results = [
            {
                "tool": tool,
                "kind": "system-tool",
                "command": str(tool_installers.get(tool) or ""),
                "status": "pending-config" if str(tool_installers.get(tool) or "").strip() else "blocked",
                "stdout": "",
                "stderr": "",
                "returncode": None,
                "blocked_reason": None if str(tool_installers.get(tool) or "").strip() else f"No install command configured for missing tool `{tool}`.",
            }
            for tool in missing_tools
        ]

    failed_dependencies = [item for item in dependency_results if item["status"] == "failed"]
    failed_tools = [item for item in system_tool_results if item["status"] in {"failed", "blocked"}]
    status = "ready"
    if failed_dependencies:
        status = "dependency-failed"
    elif runtime_payload["status"] != "ready":
        status = "runtime-blocked"
    elif missing_tools and include_system_tools and failed_tools:
        status = "tooling-blocked"
    elif missing_tools and not include_system_tools:
        status = "tooling-pending"

    summary = {
        "created_at": utc_now(),
        "project_root": str(project_root.resolve()),
        "status": status,
        "runtime_environment": runtime_payload,
        "apply": apply,
        "include_system_tools": include_system_tools,
        "dependency_cache_key": dependency_key,
        "dependency_actions": dependency_results,
        "missing_system_tools": missing_tools,
        "system_tool_actions": system_tool_results,
    }
    report_dir = reports_dir(project_root)
    write_json(report_dir / "environment-bootstrap.json", summary)
    write_text(report_dir / "environment-bootstrap.md", render_environment_bootstrap_markdown(summary))
    return summary


def render_environment_bootstrap_markdown(summary: dict) -> str:
    dependency_lines = "\n".join(
        f"- {item.get('id', item.get('tool', 'action'))}: {item['status']} ({item.get('command', '')})"
        for item in summary.get("dependency_actions", [])
    ) or "- none"
    tool_lines = "\n".join(
        f"- {item.get('tool', 'tool')}: {item['status']} ({item.get('command') or 'no command configured'})"
        for item in summary.get("system_tool_actions", [])
    ) or "- none"
    return f"""# Environment Bootstrap

- status: {summary.get('status', '')}
- apply: {'yes' if summary.get('apply') else 'no'}
- include_system_tools: {'yes' if summary.get('include_system_tools') else 'no'}
- runtime_status: {summary.get('runtime_environment', {}).get('status', '')}

## Dependency Actions

{dependency_lines}

## System Tool Actions

{tool_lines}
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Auto-configure runtime settings and install project dependencies for governed automation.")
    parser.add_argument("project_root", help="Target project root")
    parser.add_argument("--plan-only", action="store_true", help="Only write the bootstrap plan without running dependency installers")
    parser.add_argument("--include-system-tools", action="store_true", help="Also attempt configured system-tool installers")
    args = parser.parse_args()

    payload = ensure_environment(
        Path(args.project_root).resolve(),
        apply=not args.plan_only,
        include_system_tools=args.include_system_tools,
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if payload["status"] in {"dependency-failed", "tooling-blocked"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
