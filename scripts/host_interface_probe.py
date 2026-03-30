from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Any

from common import read_json, utc_now, write_json, write_text


COMMAND_ENV_VARS = {
    "parent_attach_command": "OPENCLAW_PARENT_ATTACH_COMMAND",
    "spawn_command": "OPENCLAW_SPAWN_COMMAND",
    "send_command": "OPENCLAW_SEND_COMMAND",
    "close_session_command": "OPENCLAW_CLOSE_SESSION_COMMAND",
}


def reports_dir(project_root: Path) -> Path:
    path = project_root / "ai" / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def runtime_dir(project_root: Path) -> Path:
    path = project_root / "ai" / "runtime"
    path.mkdir(parents=True, exist_ok=True)
    return path


def runtime_config_path(project_root: Path) -> Path:
    return runtime_dir(project_root) / "runtime-config.json"


def cli_path() -> str:
    return shutil.which("openclaw") or ""


def candidate_config_paths() -> list[Path]:
    candidates: list[Path] = []
    explicit = os.environ.get("OPENCLAW_CONFIG_PATH", "").strip()
    if explicit:
        candidates.append(Path(explicit).expanduser())
    codey_home = os.environ.get("CODEX_HOME", "").strip()
    if codey_home:
        candidates.append(Path(codey_home) / "openclaw" / "config.json")
    appdata = os.environ.get("APPDATA", "").strip()
    if appdata:
        candidates.append(Path(appdata) / "OpenClaw" / "config.json")
    candidates.append(Path.home() / ".openclaw" / "config.json")

    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        resolved = str(path)
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return unique


def load_candidate_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {}


def extract_command(config: dict[str, Any], key: str) -> str:
    direct = config.get(key)
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    commands = config.get("commands")
    if isinstance(commands, dict):
        nested = commands.get(key)
        if isinstance(nested, str) and nested.strip():
            return nested.strip()
    runtime = config.get("runtime")
    if isinstance(runtime, dict):
        nested = runtime.get(key)
        if isinstance(nested, str) and nested.strip():
            return nested.strip()
    return ""


def probe_host_interfaces(project_root: Path) -> dict[str, Any]:
    env_commands = {
        key: os.environ.get(env_name, "").strip()
        for key, env_name in COMMAND_ENV_VARS.items()
    }
    env_commands = {key: value for key, value in env_commands.items() if value}

    config_files: list[dict[str, Any]] = []
    config_commands: dict[str, str] = {}
    for path in candidate_config_paths():
        payload = load_candidate_config(path)
        if not payload:
            continue
        found = {
            key: extract_command(payload, key)
            for key in COMMAND_ENV_VARS
        }
        found = {key: value for key, value in found.items() if value}
        config_files.append(
            {
                "path": str(path.resolve()),
                "commands": found,
            }
        )
        for key, value in found.items():
            config_commands.setdefault(key, value)

    probe = {
        "created_at": utc_now(),
        "project_root": str(project_root.resolve()),
        "openclaw_cli_path": cli_path(),
        "openclaw_cli_available": bool(cli_path()),
        "environment_commands": env_commands,
        "config_file_commands": config_commands,
        "config_files": config_files,
        "selected_commands": {
            key: env_commands.get(key) or config_commands.get(key) or ""
            for key in COMMAND_ENV_VARS
        },
        "selected_sources": {
            key: (
                "environment"
                if env_commands.get(key)
                else "config-file"
                if config_commands.get(key)
                else "missing"
            )
            for key in COMMAND_ENV_VARS
        },
    }
    write_json(reports_dir(project_root) / "host-interface-probe.json", probe)
    write_text(reports_dir(project_root) / "host-interface-probe.md", render_probe_markdown(probe))
    return probe


def sync_runtime_config_from_probe(project_root: Path, probe: dict[str, Any]) -> dict[str, Any]:
    config = read_json(runtime_config_path(project_root))
    config.setdefault("tool_install_commands", {})
    config["openclaw_cli_path"] = probe.get("openclaw_cli_path", "")
    config["openclaw_cli_available"] = bool(probe.get("openclaw_cli_available"))
    config["host_interface_sources"] = probe.get("selected_sources", {})

    for key in COMMAND_ENV_VARS:
        selected = str(probe.get("selected_commands", {}).get(key) or "").strip()
        current = str(config.get(key) or "").strip()
        auto_generated = key == "parent_attach_command" and bool(config.get("parent_attach_command_auto_generated"))
        if selected and (not current or auto_generated):
            config[key] = selected
            if key == "parent_attach_command":
                config["parent_attach_command_auto_generated"] = False

    write_json(runtime_config_path(project_root), config)
    return config


def render_probe_markdown(probe: dict[str, Any]) -> str:
    env_lines = "\n".join(
        f"- {key}: {value}" for key, value in probe.get("environment_commands", {}).items()
    ) or "- none"
    file_lines = "\n".join(
        f"- {item['path']}: {', '.join(sorted(item.get('commands', {}).keys())) or 'no known commands'}"
        for item in probe.get("config_files", [])
    ) or "- none"
    selected_lines = "\n".join(
        f"- {key}: {probe.get('selected_sources', {}).get(key, 'missing')} -> {value or 'n/a'}"
        for key, value in probe.get("selected_commands", {}).items()
    ) or "- none"
    return f"""# Host Interface Probe

- openclaw_cli_available: {'yes' if probe.get('openclaw_cli_available') else 'no'}
- openclaw_cli_path: {probe.get('openclaw_cli_path') or 'n/a'}

## Environment Commands

{env_lines}

## Config Files

{file_lines}

## Selected Commands

{selected_lines}
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe machine-visible host interfaces and sync the runtime config.")
    parser.add_argument("project_root", help="Target project root")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    probe = probe_host_interfaces(project_root)
    config = sync_runtime_config_from_probe(project_root, probe)
    print(json.dumps({"probe": probe, "runtime_config": config}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
