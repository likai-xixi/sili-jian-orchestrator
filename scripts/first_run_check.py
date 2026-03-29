from __future__ import annotations

import argparse
from pathlib import Path

from common import detect_directory_mode, write_text
from ensure_openclaw_agents import ensure_agents


def build_next_prompt(mode: str) -> str:
    if mode == "skill_bundle_mode":
        return (
            "Use $sili-jian-orchestrator on the target project directory. "
            "First identify the project, inspect governance readiness, and output the first-round takeover result."
        )
    if mode == "project_mode":
        return (
            "Use $sili-jian-orchestrator to take over this project. "
            "Do not implement immediately. First inspect governance readiness and output the first-round takeover result."
        )
    return (
        "Use $sili-jian-orchestrator after switching into the target project directory, "
        "or explicitly tell it whether the current directory is the skill bundle or the project root."
    )


def build_safe_next_action(mode: str, dispatch_ready: bool) -> str:
    if mode == "skill_bundle_mode":
        return "Install or invoke the skill from a real project directory; do not create governance files here."
    if mode == "project_mode" and dispatch_ready:
        return "Run project inspection and first-round takeover before any implementation."
    if mode == "project_mode":
        return "Resolve peer-agent readiness if needed, then run project inspection before implementation."
    return "Clarify the intended target directory before taking further action."


def build_environment_meaning(mode: str) -> str:
    mapping = {
        "skill_bundle_mode": "You are inside the skill package itself, not inside a governed software project.",
        "project_mode": "You are inside a target software project and may proceed with governance-first takeover.",
        "unknown_mode": "The current directory cannot be confidently classified yet.",
    }
    return mapping.get(mode, "Unknown environment mode.")


def build_report(current_dir: Path, workspace_root: Path, create_missing: bool) -> str:
    mode = detect_directory_mode(current_dir)
    bootstrap = ensure_agents(workspace_root, create_missing=create_missing)
    missing = ", ".join(bootstrap["missing_peer_agents"]) or "None"
    return "\n".join(
        [
            "# First-Run Guide",
            "",
            f"- Skill path: {Path(__file__).resolve().parent.parent}",
            f"- Current directory: {current_dir.resolve()}",
            f"- Directory mode: {mode}",
            f"- Peer-agent bootstrap source: {bootstrap.get('detection_source', 'none')}",
            f"- Peer-agent dispatch ready: {bootstrap.get('dispatch_ready', False)}",
            f"- Missing peer agents: {missing}",
            f"- Current environment meaning: {build_environment_meaning(mode)}",
            f"- Safe next action: {build_safe_next_action(mode, bool(bootstrap.get('dispatch_ready')))}",
            f"- Suggested next prompt: {build_next_prompt(mode)}",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate first-run guidance for the orchestrator skill.")
    parser.add_argument("--current-dir", default=".", help="Directory to classify for first-run guidance")
    parser.add_argument("--workspace-root", default=str(Path.home() / ".openclaw-peer-workspaces"), help="Workspace root for any missing peer agents")
    parser.add_argument("--create-missing", action="store_true", help="Attempt to create missing peer agents when possible")
    parser.add_argument("--output", help="Optional markdown output path")
    args = parser.parse_args()

    report = build_report(Path(args.current_dir).resolve(), Path(args.workspace_root).resolve(), args.create_missing)
    if args.output:
        write_text(Path(args.output), report)
    else:
        print(report)


if __name__ == "__main__":
    main()
