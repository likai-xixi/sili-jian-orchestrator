from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

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

AGENT_SPECS: dict[str, dict[str, str]] = {
    "neige": {"label": "内阁", "model": "minimax/MiniMax-M2.7"},
    "bingbu": {"label": "兵部", "model": "openai-codex/gpt-5.3-codex"},
    "libu2": {"label": "吏部", "model": "minimax/MiniMax-M2.7"},
    "hubu": {"label": "户部", "model": "minimax/MiniMax-M2.7"},
    "gongbu": {"label": "工部", "model": "minimax/MiniMax-M2.7"},
    "xingbu": {"label": "刑部", "model": "minimax/MiniMax-M2.7"},
    "libu": {"label": "礼部", "model": "minimax/MiniMax-M2.7"},
    "duchayuan": {"label": "都察院", "model": "minimax/MiniMax-M2.7"},
}


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


def parse_agent_details_payload(payload: object) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        agent_id = item.get("agentId") or item.get("id") or item.get("name")
        if not agent_id:
            continue
        result[str(agent_id)] = {
            "id": str(agent_id),
            "name": item.get("name"),
            "workspace": item.get("workspace"),
            "model": item.get("model"),
            "identityName": item.get("identityName"),
            "identityEmoji": item.get("identityEmoji"),
            "identitySource": item.get("identitySource"),
            "isDefault": item.get("isDefault"),
        }
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


def parse_agent_details(output: str) -> dict[str, dict[str, Any]]:
    output = output.strip()
    if not output:
        return {}
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return {}
    return parse_agent_details_payload(payload)


def strip_json_comments_and_trailing_commas(text: str) -> str:
    text = re.sub(r"//.*?$", "", text, flags=re.MULTILINE)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    return text


def load_json_loose(path: Path) -> dict[str, Any] | list[Any] | None:
    raw = path.read_text(encoding="utf-8-sig")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        try:
            return json.loads(strip_json_comments_and_trailing_commas(raw))
        except json.JSONDecodeError:
            return None


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


def read_agents_from_config() -> tuple[set[str], dict[str, dict[str, Any]], str | None]:
    for path in candidate_config_paths():
        if not path.exists():
            continue
        payload = load_json_loose(path)
        if not isinstance(payload, dict):
            continue
        agents = payload.get("agents", {}).get("list", [])
        parsed = parse_agent_list_payload(agents)
        details = parse_agent_details_payload(agents)
        if parsed:
            return parsed, details, str(path)
    return set(), {}, None


def infer_workspace_root_from_details(details: dict[str, dict[str, Any]]) -> Path | None:
    silijian = details.get("silijian", {})
    workspace = silijian.get("workspace")
    if isinstance(workspace, str) and workspace:
        return Path(workspace).expanduser().resolve().parent

    workspaces = []
    for detail in details.values():
        workspace = detail.get("workspace")
        if isinstance(workspace, str) and workspace:
            workspaces.append(Path(workspace).expanduser())
    if not workspaces:
        return None
    parents = {str(path.parent) for path in workspaces}
    if len(parents) == 1:
        return workspaces[0].parent.resolve()
    return None


def infer_workspace_path(agent_id: str, details: dict[str, dict[str, Any]], workspace_root: Path) -> Path:
    existing = details.get(agent_id, {})
    workspace = existing.get("workspace")
    if isinstance(workspace, str) and workspace:
        return Path(workspace).expanduser().resolve()

    silijian = details.get("silijian", {})
    silijian_workspace = silijian.get("workspace")
    if isinstance(silijian_workspace, str) and silijian_workspace:
        silijian_path = Path(silijian_workspace).expanduser().resolve()
        if agent_id == "silijian":
            return silijian_path
        return silijian_path.parent / f"{silijian_path.name}-{agent_id}"

    return workspace_root / f"workspace-{agent_id}"


def add_agent(cli: str, agent_id: str, workspace_dir: Path, model: str) -> subprocess.CompletedProcess[str]:
    return run_command(
        [
            cli,
            "agents",
            "add",
            agent_id,
            "--workspace",
            str(workspace_dir),
            "--model",
            model,
            "--non-interactive",
            "--json",
        ]
    )


def ensure_agents(workspace_root: Path | None, create_missing: bool) -> dict:
    cli = detect_openclaw_cli()
    existing: set[str] = set()
    details: dict[str, dict[str, Any]] = {}
    source = "none"
    cli_management_ready = False
    notes: list[str] = []

    if cli:
        listing = run_command([cli, "agents", "list", "--json"])
        if listing.returncode == 0:
            existing = parse_agent_list(listing.stdout)
            details = parse_agent_details(listing.stdout)
            source = "cli"
            cli_management_ready = True
        else:
            notes.append("openclaw agents list failed; falling back to config parsing")

    if not existing:
        config_existing, config_details, config_path = read_agents_from_config()
        if config_existing:
            existing = config_existing
            details = config_details
            source = "config"
            notes.append(f"loaded peer agents from {config_path}")

    inferred_workspace_root = infer_workspace_root_from_details(details)
    effective_workspace_root = workspace_root or inferred_workspace_root or (Path.home() / ".openclaw-peer-workspaces")

    missing = [agent for agent in REQUIRED_AGENTS if agent not in existing]
    created: list[str] = []
    failed: list[str] = []
    created_workspaces: dict[str, str] = {}

    if create_missing and missing:
        if cli and cli_management_ready:
            effective_workspace_root.mkdir(parents=True, exist_ok=True)
            for agent in missing:
                spec = AGENT_SPECS.get(agent, {})
                workspace_dir = infer_workspace_path(agent, details, effective_workspace_root)
                model = spec.get("model", "minimax/MiniMax-M2.7")
                result = add_agent(cli, agent, workspace_dir, model)
                if result.returncode == 0:
                    created.append(agent)
                    created_workspaces[agent] = str(workspace_dir)
                    details[agent] = {
                        "id": agent,
                        "name": spec.get("label", agent),
                        "workspace": str(workspace_dir),
                        "model": model,
                    }
                else:
                    failed.append(agent)
                    notes.append(f"failed to create {agent}: {result.stderr.strip() or result.stdout.strip()}")
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
        "existing_peer_agent_details": {agent: details.get(agent, {}) for agent in sorted(final_existing)},
        "missing_peer_agents": remaining_missing,
        "created_peer_agents": created,
        "created_workspaces": created_workspaces,
        "failed_peer_agents": failed,
        "dispatch_ready": not remaining_missing,
        "workspace_root": str(effective_workspace_root),
        "workspace_root_source": "explicit" if workspace_root else ("inferred" if inferred_workspace_root else "fallback"),
        "notes": "; ".join(notes) if notes else ("ok" if not remaining_missing else "some peer agents are still missing"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect and optionally create required OpenClaw peer agents.")
    parser.add_argument("--workspace-root", help="Workspace root for newly created peer agents")
    parser.add_argument("--create-missing", action="store_true", help="Create missing peer agents automatically")
    parser.add_argument("--output", help="Optional JSON output path")
    args = parser.parse_args()

    explicit_root = Path(args.workspace_root).resolve() if args.workspace_root else None
    result = ensure_agents(explicit_root, create_missing=args.create_missing)
    payload = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)


if __name__ == "__main__":
    main()
