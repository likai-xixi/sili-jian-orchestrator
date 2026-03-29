from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

REQUIRED_AGENTS = [
    "neige",
    "bingbu",
    "libu2",
    "hubu",
    "gongbu",
    "xingbu",
    "libu",
    "duchayuan",
]


def run_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False)


def detect_openclaw_cli() -> str | None:
    return shutil.which("openclaw")


def parse_agent_list_payload(payload: object) -> set[str]:
    if not isinstance(payload, list):
        return set()
    result = set()
    for item in payload:
        if isinstance(item, dict):
            agent_id = item.get("agentId") or item.get("id") or item.get("name")
            if agent_id:
                result.add(str(agent_id))
    return result


def parse_agent_list(output: str) -> set[str]:
    output = output.strip()
    if not output:
        return set()
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return set()
    return parse_agent_list_payload(payload)


def candidate_config_paths() -> list[Path]:
    candidates = [Path.home() / ".openclaw" / "openclaw.json"]
    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        candidates.append(Path(user_profile) / ".openclaw" / "openclaw.json")
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata).parent / ".openclaw" / "openclaw.json")
    seen: set[str] = set()
    unique: list[Path] = []
    for path in candidates:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def read_agents_from_config() -> tuple[set[str], str | None]:
    for path in candidate_config_paths():
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            continue
        agents = payload.get("agents", {}).get("list", [])
        parsed = parse_agent_list_payload(agents)
        if parsed:
            return parsed, str(path)
    return set(), None


def ensure_agents(workspace_root: Path, create_missing: bool) -> dict:
    cli = detect_openclaw_cli()
    existing: set[str] = set()
    source = "none"
    cli_management_ready = False
    notes: list[str] = []

    if cli:
        listing = run_command([cli, "agents", "list", "--json"])
        if listing.returncode == 0:
            existing = parse_agent_list(listing.stdout)
            source = "cli"
            cli_management_ready = True
        else:
            notes.append("openclaw agents list failed; falling back to config parsing")

    if not existing:
        config_existing, config_path = read_agents_from_config()
        if config_existing:
            existing = config_existing
            source = "config"
            notes.append(f"loaded peer agents from {config_path}")

    missing = [agent for agent in REQUIRED_AGENTS if agent not in existing]
    created: list[str] = []
    failed: list[str] = []

    if create_missing and missing:
        if cli and cli_management_ready:
            workspace_root.mkdir(parents=True, exist_ok=True)
            for agent in missing:
                workspace_dir = workspace_root / f"workspace-{agent}"
                result = run_command([cli, "agents", "add", agent, "--workspace", str(workspace_dir), "--non-interactive"])
                if result.returncode == 0:
                    created.append(agent)
                else:
                    failed.append(agent)
        elif cli and not cli_management_ready:
            failed.extend(missing)
            notes.append("CLI exists but agent management is not healthy enough for auto-creation")
        else:
            failed.extend(missing)
            notes.append("openclaw CLI not found in PATH")

    final_existing = set(existing) | set(created)
    remaining_missing = [agent for agent in REQUIRED_AGENTS if agent not in final_existing]
    return {
        "cli_available": bool(cli),
        "cli_management_ready": cli_management_ready,
        "detection_source": source,
        "required_peer_agents": REQUIRED_AGENTS,
        "existing_peer_agents": sorted(existing),
        "missing_peer_agents": remaining_missing,
        "created_peer_agents": created,
        "failed_peer_agents": failed,
        "dispatch_ready": not remaining_missing,
        "notes": "; ".join(notes) if notes else ("ok" if not remaining_missing else "some peer agents are still missing"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect and optionally create required OpenClaw peer agents.")
    parser.add_argument("--workspace-root", default=str(Path.home() / ".openclaw-peer-workspaces"), help="Workspace root for newly created peer agents")
    parser.add_argument("--create-missing", action="store_true", help="Create missing peer agents automatically")
    parser.add_argument("--output", help="Optional JSON output path")
    args = parser.parse_args()

    result = ensure_agents(Path(args.workspace_root).resolve(), create_missing=args.create_missing)
    payload = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)


if __name__ == "__main__":
    main()
