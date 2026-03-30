from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

from common import utc_now, write_json, write_text


def package_manager(project_root: Path) -> str:
    if (project_root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (project_root / "yarn.lock").exists():
        return "yarn"
    return "npm"


def package_script_commands(project_root: Path) -> dict[str, str]:
    package_json = project_root / "package.json"
    if not package_json.exists():
        return {}
    try:
        payload = json.loads(package_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    scripts = payload.get("scripts", {})
    if not isinstance(scripts, dict):
        return {}
    runner = package_manager(project_root)
    commands: dict[str, str] = {}
    if scripts.get("lint"):
        commands["lint"] = f"{runner} run lint"
    if scripts.get("build"):
        commands["build"] = f"{runner} run build"
    if scripts.get("test"):
        commands["test"] = f"{runner} run test"
    if scripts.get("ci"):
        commands["ci"] = f"{runner} run ci"
    if scripts.get("release"):
        commands["release"] = f"{runner} run release"
    elif scripts.get("deploy"):
        commands["release"] = f"{runner} run deploy"
    if scripts.get("rollback"):
        commands["rollback"] = f"{runner} run rollback"
    return commands


def python_commands(project_root: Path) -> dict[str, str]:
    commands: dict[str, str] = {}
    has_python = any(project_root.rglob("*.py")) or (project_root / "pyproject.toml").exists()
    if not has_python:
        return commands

    test_roots = [project_root / "tests", project_root / "test"]
    test_root = next((path for path in test_roots if path.exists()), None)
    if test_root is not None:
        commands["test"] = f'"{sys.executable}" -m unittest discover -s {test_root.name} -v'

    py_files = sorted(
        path
        for path in project_root.rglob("*.py")
        if all(part not in {".git", "node_modules", "__pycache__", ".venv", "venv"} for part in path.parts)
    )
    if py_files:
        quoted = " ".join(f'"{str(path)}"' for path in py_files)
        commands["build"] = f'"{sys.executable}" -m py_compile {quoted}'
    if (project_root / "scripts" / "run_repo_ci.py").exists():
        commands["ci"] = f'"{sys.executable}" scripts/run_repo_ci.py'
    elif (project_root / "scripts" / "run_project_guard.py").exists():
        commands["ci"] = f'"{sys.executable}" scripts/run_project_guard.py "{project_root}"'
    return commands


def pyproject_commands(project_root: Path) -> dict[str, str]:
    pyproject = project_root / "pyproject.toml"
    if not pyproject.exists():
        return {}
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return {}
    commands: dict[str, str] = {}
    scripts = data.get("tool", {}).get("poetry", {}).get("scripts", {})
    if scripts and "test" not in commands and (project_root / "tests").exists():
        commands["test"] = f'"{sys.executable}" -m unittest discover -s tests -v'
    return commands


def script_file_commands(project_root: Path) -> dict[str, str]:
    commands: dict[str, str] = {}
    scripts_dir = project_root / "scripts"
    if not scripts_dir.exists():
        return commands

    release_candidates = sorted(path for path in scripts_dir.glob("*") if path.is_file() and any(token in path.stem.lower() for token in ["release", "deploy"]))
    rollback_candidates = sorted(path for path in scripts_dir.glob("*") if path.is_file() and "rollback" in path.stem.lower())

    def command_for(path: Path) -> str:
        if path.suffix.lower() == ".py":
            return f'"{sys.executable}" "{path}"'
        return f'"{path}"'

    if release_candidates:
        commands["release"] = command_for(release_candidates[0])
    if rollback_candidates:
        commands["rollback"] = command_for(rollback_candidates[0])
    return commands


def github_workflow_commands(project_root: Path) -> dict[str, str]:
    workflows_dir = project_root / ".github" / "workflows"
    if not workflows_dir.exists():
        return {}
    if (project_root / "scripts" / "run_repo_ci.py").exists():
        return {"ci": f'"{sys.executable}" scripts/run_repo_ci.py'}
    return {"ci": "github-actions-workflow-present"}


def detect_commands(project_root: Path) -> dict[str, str]:
    detected: dict[str, str] = {}
    for source in [
        package_script_commands(project_root),
        pyproject_commands(project_root),
        script_file_commands(project_root),
        github_workflow_commands(project_root),
        python_commands(project_root),
    ]:
        for key, value in source.items():
            detected.setdefault(key, value)
    return detected


def command_summary(project_root: Path) -> dict:
    commands = detect_commands(project_root)
    summary = {
        "project_root": str(project_root.resolve()),
        "detected_at": utc_now(),
        "commands": {
            "lint": commands.get("lint", ""),
            "build": commands.get("build", ""),
            "test": commands.get("test", ""),
            "ci": commands.get("ci", ""),
            "release": commands.get("release", ""),
            "rollback": commands.get("rollback", ""),
        },
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect project lint/build/test commands for governed evidence collection.")
    parser.add_argument("project_root", help="Target project root")
    parser.add_argument("--output", help="Optional JSON output path")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    summary = command_summary(project_root)
    if args.output:
        output = Path(args.output)
        write_json(output, summary)
        write_text(output.with_suffix(".md"), "# Command Detection\n\n" + "\n".join(f"- {k}: {v or 'not detected'}" for k, v in summary["commands"].items()))
    else:
        print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
