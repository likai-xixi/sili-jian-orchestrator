from __future__ import annotations

import argparse
from pathlib import Path

from common import detect_directory_mode, write_text
from ensure_openclaw_agents import ensure_agents


def build_next_prompt(mode: str, lang: str) -> str:
    if lang == "en":
        if mode == "skill_bundle_mode":
            return (
                "Use $sili-jian-orchestrator on the target project directory. "
                "First identify the project, inspect governance readiness, and output the first-round takeover result."
            )
        if mode == "workspace_root_mode":
            return (
                "If you already have a real business project, switch into that project root and rerun first-use guidance. "
                "If you are still defining a brand new project from this workspace root, use scripts/project_intake.py first."
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

    if mode == "skill_bundle_mode":
        return "使用 $sili-jian-orchestrator 到真实项目目录中执行首次启用引导，并输出首轮接管结果。"
    if mode == "workspace_root_mode":
        return "如果你已经有真实业务项目，请先切换到该项目根目录再运行首次启用引导。如果你还在这个 workspace 根目录里定义全新项目，先使用 scripts/project_intake.py。"
    if mode == "project_mode":
        return "使用 $sili-jian-orchestrator 接管当前项目，先做治理检查和首轮接管结果输出，不要直接开发。"
    return "请先切换到目标项目目录，或者明确告诉技能当前目录是技能目录还是项目目录。"


def build_safe_next_action(mode: str, dispatch_ready: bool, lang: str) -> str:
    if lang == "en":
        if mode == "skill_bundle_mode":
            return "Install or invoke the skill from a real project directory; do not create governance files here."
        if mode == "workspace_root_mode":
            return "Either switch into the real business project root, or stay here and use scripts/project_intake.py to create a new governed project."
        if mode == "project_mode" and dispatch_ready:
            return "Run project inspection and first-round takeover before any implementation."
        if mode == "project_mode":
            return "Resolve peer-agent readiness if needed, then run project inspection before implementation."
        return "Clarify the intended target directory before taking further action."

    if mode == "skill_bundle_mode":
        return "这里是技能目录，请在真实项目目录中调用技能，不要在这里创建治理文件。"
    if mode == "workspace_root_mode":
        return "这里是 OpenClaw workspace 根目录。可以切换到真实业务项目根目录，或留在这里用 scripts/project_intake.py 创建全新受治理项目。"
    if mode == "project_mode" and dispatch_ready:
        return "先执行项目治理检查和首轮接管，不要直接进入实现。"
    if mode == "project_mode":
        return "先确认 peer-agent 就绪情况，再进行项目治理检查。"
    return "请先澄清当前目录用途，再继续下一步。"


def build_environment_meaning(mode: str, lang: str) -> str:
    if lang == "en":
        mapping = {
            "skill_bundle_mode": "You are inside the skill package itself, not inside a governed software project.",
            "workspace_root_mode": "You are inside an OpenClaw workspace root that may contain skills or shared tooling; do not treat it as a single business project root.",
            "project_mode": "You are inside a target software project and may proceed with governance-first takeover.",
            "unknown_mode": "The current directory cannot be confidently classified yet.",
        }
        return mapping.get(mode, "Unknown environment mode.")

    mapping = {
        "skill_bundle_mode": "当前目录是技能包目录，不是业务项目目录。",
        "workspace_root_mode": "当前目录是 OpenClaw workspace 根目录，可能包含技能与共享工具，不应当作单一业务项目根目录。",
        "project_mode": "当前目录是目标业务项目目录，可以进入治理优先的接管流程。",
        "unknown_mode": "当前目录暂时无法被可靠识别。",
    }
    return mapping.get(mode, "未知目录模式。")


def build_report(current_dir: Path, workspace_root: Path | None, create_missing: bool, lang: str) -> str:
    mode = detect_directory_mode(current_dir)
    bootstrap = ensure_agents(workspace_root, create_missing=create_missing)
    missing = ", ".join(bootstrap["missing_peer_agents"]) or "None"

    if lang == "en":
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
                f"- Workspace root used for agent bootstrap: {bootstrap.get('workspace_root')}",
                f"- Workspace root source: {bootstrap.get('workspace_root_source')}",
                f"- Current environment meaning: {build_environment_meaning(mode, lang)}",
                f"- Safe next action: {build_safe_next_action(mode, bool(bootstrap.get('dispatch_ready')), lang)}",
                f"- Suggested next prompt: {build_next_prompt(mode, lang)}",
            ]
        )

    return "\n".join(
        [
            "# 首次启用引导",
            "",
            f"- 技能路径: {Path(__file__).resolve().parent.parent}",
            f"- 当前目录: {current_dir.resolve()}",
            f"- 目录模式: {mode}",
            f"- peer-agent 检测来源: {bootstrap.get('detection_source', 'none')}",
            f"- peer-agent 调度是否就绪: {bootstrap.get('dispatch_ready', False)}",
            f"- 缺失的 peer-agent: {missing}",
            f"- agent bootstrap 使用的 workspace 根: {bootstrap.get('workspace_root')}",
            f"- workspace 根来源: {bootstrap.get('workspace_root_source')}",
            f"- 当前环境含义: {build_environment_meaning(mode, lang)}",
            f"- 最安全的下一步: {build_safe_next_action(mode, bool(bootstrap.get('dispatch_ready')), lang)}",
            f"- 建议下一条提示词: {build_next_prompt(mode, lang)}",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate first-run guidance for the orchestrator skill.")
    parser.add_argument("--current-dir", default=".", help="Directory to classify for first-run guidance")
    parser.add_argument("--workspace-root", help="Workspace root for any missing peer agents")
    parser.add_argument("--create-missing", action="store_true", help="Attempt to create missing peer agents when possible")
    parser.add_argument("--lang", default="zh-CN", choices=["zh-CN", "en"], help="Output language")
    parser.add_argument("--output", help="Optional markdown output path")
    args = parser.parse_args()

    explicit_root = Path(args.workspace_root).resolve() if args.workspace_root else None
    report = build_report(Path(args.current_dir).resolve(), explicit_root, args.create_missing, args.lang)
    if args.output:
        write_text(Path(args.output), report)
    else:
        print(report)


if __name__ == "__main__":
    main()
