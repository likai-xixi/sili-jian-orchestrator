from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from common import read_json, utc_now, write_json, write_text
from host_interface_probe import probe_host_interfaces, sync_runtime_config_from_probe


def runtime_dir(project_root: Path) -> Path:
    path = project_root / "ai" / "runtime"
    path.mkdir(parents=True, exist_ok=True)
    return path


def runtime_config_path(project_root: Path) -> Path:
    return runtime_dir(project_root) / "runtime-config.json"


def reports_dir(project_root: Path) -> Path:
    path = project_root / "ai" / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def bridge_script_path(project_root: Path) -> Path:
    return project_root / "ai" / "tools" / "openclaw_runtime_bridge.py"


def build_default_parent_attach_command(project_root: Path) -> str:
    bridge_path = bridge_script_path(project_root)
    return f'"{sys.executable}" "{bridge_path}" parent-attach "{{payload_file}}"'


def ensure_runtime_environment(project_root: Path) -> dict:
    config_path = runtime_config_path(project_root)
    config = read_json(config_path)
    bridge_path = bridge_script_path(project_root)
    probe = probe_host_interfaces(project_root)
    config = sync_runtime_config_from_probe(project_root, probe)
    cli_path = str(probe.get("openclaw_cli_path") or "")
    created_fields: list[str] = []

    if not config.get("created_at"):
        config["created_at"] = utc_now()
    config["updated_at"] = utc_now()
    config["openclaw_cli_path"] = cli_path or ""
    config["openclaw_cli_available"] = bool(cli_path)
    config["bridge_path"] = str(bridge_path.resolve()) if bridge_path.exists() else ""
    config["bridge_available"] = bridge_path.exists()
    config.setdefault("spawn_command", str(config.get("spawn_command") or ""))
    config.setdefault("send_command", str(config.get("send_command") or ""))
    config.setdefault("close_session_command", str(config.get("close_session_command") or ""))
    config.setdefault("host_interface_sources", {})
    config.setdefault(
        "tool_install_commands",
        {
            "git": "",
            "node": "",
            "npm": "",
            "pnpm": "",
            "yarn": "",
            "gh": "",
        },
    )

    if not config.get("parent_attach_command") and bridge_path.exists():
        config["parent_attach_command"] = build_default_parent_attach_command(project_root)
        config["parent_attach_command_auto_generated"] = True
        created_fields.append("parent_attach_command")

    write_json(config_path, config)

    env_template = os.environ.get("OPENCLAW_PARENT_ATTACH_COMMAND", "")
    effective_command = env_template or str(config.get("parent_attach_command") or "")
    host_source = str(config.get("host_interface_sources", {}).get("parent_attach_command") or "").strip()
    if env_template:
        command_source = "environment"
    elif host_source and host_source != "missing":
        command_source = host_source
    elif effective_command:
        command_source = "project-config"
    else:
        command_source = "missing"
    auto_generated_bridge = bool(config.get("parent_attach_command_auto_generated")) and not env_template
    status = "ready" if effective_command else "blocked"
    blocked_reason = ""
    if auto_generated_bridge and not cli_path:
        status = "blocked"
        blocked_reason = "The project-local attach bridge was configured automatically, but the openclaw CLI is not on PATH."
    if not effective_command:
        blocked_reason = "No parent attach command is available. Ensure ai/tools/openclaw_runtime_bridge.py exists or set OPENCLAW_PARENT_ATTACH_COMMAND."

    payload = {
        "created_at": utc_now(),
        "project_root": str(project_root.resolve()),
        "status": status,
        "openclaw_cli_available": bool(cli_path),
        "openclaw_cli_path": cli_path or "",
        "bridge_available": bridge_path.exists(),
        "bridge_path": str(bridge_path.resolve()) if bridge_path.exists() else "",
        "command_source": command_source,
        "effective_parent_attach_command": effective_command,
        "blocked_reason": blocked_reason or None,
        "auto_configured_fields": created_fields,
        "runtime_config_path": str(config_path.resolve()),
        "host_interface_probe_path": str((reports_dir(project_root) / "host-interface-probe.json").resolve()),
    }
    write_json(reports_dir(project_root) / "runtime-environment.json", payload)
    write_text(reports_dir(project_root) / "runtime-environment.md", render_runtime_environment_markdown(payload))
    return payload


def resolve_parent_attach_command(project_root: Path) -> tuple[str, str]:
    env_template = os.environ.get("OPENCLAW_PARENT_ATTACH_COMMAND", "").strip()
    if env_template:
        return env_template, "environment"
    config = read_json(runtime_config_path(project_root))
    template = str(config.get("parent_attach_command") or "").strip()
    if template:
        return template, "project-config"
    return "", "missing"


def render_runtime_environment_markdown(payload: dict) -> str:
    return f"""# Runtime Environment

- status: {payload.get('status', '')}
- openclaw_cli_available: {'yes' if payload.get('openclaw_cli_available') else 'no'}
- openclaw_cli_path: {payload.get('openclaw_cli_path') or 'n/a'}
- bridge_available: {'yes' if payload.get('bridge_available') else 'no'}
- bridge_path: {payload.get('bridge_path') or 'n/a'}
- command_source: {payload.get('command_source', 'missing')}
- blocked_reason: {payload.get('blocked_reason') or 'none'}

## Effective Parent Attach Command

```text
{payload.get('effective_parent_attach_command') or 'n/a'}
```

## Auto Configured Fields

{chr(10).join(f"- {item}" for item in payload.get('auto_configured_fields', [])) or '- none'}
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Auto-configure the project-local OpenClaw runtime environment.")
    parser.add_argument("project_root", help="Target project root")
    args = parser.parse_args()

    payload = ensure_runtime_environment(Path(args.project_root).resolve())
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
