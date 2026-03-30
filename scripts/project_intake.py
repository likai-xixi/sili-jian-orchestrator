from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import runtime_loop
from common import detect_directory_mode, read_json, utc_now, write_json, write_text


INTAKE_FILENAME = ".sili-jian-intake.json"


def intake_path(workspace_root: Path) -> Path:
    return workspace_root / INTAKE_FILENAME


def intake_markdown_path(workspace_root: Path) -> Path:
    return workspace_root / ".sili-jian-intake.md"


def slugify(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "-", text.strip().lower()).strip("-")
    return cleaned or "new-project"


def summarize_requirement(request: str) -> str:
    cleaned = " ".join(request.strip().split())
    return cleaned[:240]


def proposed_plan(requirement: str) -> list[str]:
    summary = summarize_requirement(requirement)
    return [
        f"Clarify the core user flow and constraints for: {summary}",
        "Freeze the first implementation scope and acceptance criteria.",
        "Bootstrap governance, runtime config, and project dependencies in the new project directory.",
        "Enter autonomous delivery after the project name and initial scope are confirmed.",
    ]


def proposed_options(requirement: str) -> list[dict[str, str]]:
    summary = summarize_requirement(requirement)
    return [
        {
            "id": "option-a",
            "title": "Lean MVP",
            "summary": f"Freeze the smallest usable flow for: {summary}",
            "tradeoff": "Fastest to ship, but more follow-up work lands later.",
        },
        {
            "id": "option-b",
            "title": "Balanced baseline",
            "summary": "Clarify constraints, freeze acceptance, then enter autonomous delivery with a stable first batch.",
            "tradeoff": "Slightly slower at the start, but better suited for unattended execution.",
        },
        {
            "id": "option-c",
            "title": "Documentation-first",
            "summary": "Spend the first round on architecture, task tree, and governance completeness before implementation.",
            "tradeoff": "Highest planning confidence, but the slowest route into coding.",
        },
    ]


def parse_project_name(request: str) -> str:
    patterns = [
        r"(?:\u9879\u76ee\u540d\u79f0|\u9879\u76ee\u540d)\s*(?:\u53eb|\u662f|\u4e3a|[:\uff1a])\s*([A-Za-z0-9\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff _-]*)",
        r"(?:\u9879\u76ee\u53eb|\u53eb\u505a|\u547d\u540d\u4e3a)\s*([A-Za-z0-9\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff _-]*)",
        r"project name\s*(?:is|[:\uff1a])?\s*([A-Za-z0-9][A-Za-z0-9 _-]*)",
    ]
    for pattern in patterns:
        match = re.search(pattern, request, flags=re.IGNORECASE)
        if match:
            candidate = re.split(r"[\u3002\uff0c,.;:!?()\[\]\n]", match.group(1), maxsplit=1)[0]
            return candidate.strip(" .,:;\u3002\uff0c\uff1b\uff1a")
    return ""


def render_intake_markdown(payload: dict) -> str:
    plan_lines = "\n".join(f"- {item}" for item in payload.get("proposed_plan", [])) or "- none"
    option_lines = "\n\n".join(
        "\n".join(
            [
                f"### {item.get('id', '').upper()} {item.get('title', '')}",
                f"- summary: {item.get('summary', '')}",
                f"- tradeoff: {item.get('tradeoff', '')}",
            ]
        )
        for item in payload.get("proposed_options", [])
        if isinstance(item, dict)
    ) or "- none"
    return f"""# New Project Intake

- created_at: {payload.get('created_at', '')}
- workspace_root: {payload.get('workspace_root', '')}
- requirement_summary: {payload.get('requirement_summary', '')}
- intake_status: {payload.get('intake_status', '')}
- needs_project_name: {'yes' if payload.get('needs_project_name') else 'no'}
- project_name: {payload.get('project_name') or 'n/a'}
- proposed_project_slug: {payload.get('proposed_project_slug') or 'n/a'}

## Proposed Plan

{plan_lines}

## Guided Options

{option_lines}

## Next Prompt

{payload.get('next_prompt', '')}
"""


def ensure_workspace_root(workspace_root: Path) -> None:
    mode = detect_directory_mode(workspace_root)
    if mode != "workspace_root_mode":
        raise ValueError(
            "project_intake.py must run from an OpenClaw workspace root. "
            f"Detected mode={mode} at {workspace_root}."
        )


def record_requirement(workspace_root: Path, request: str, actor: str = "user") -> dict:
    ensure_workspace_root(workspace_root)
    project_name = parse_project_name(request)
    payload = {
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "workspace_root": str(workspace_root.resolve()),
        "actor": actor,
        "raw_requirement": request,
        "requirement_summary": summarize_requirement(request),
        "intake_status": "ready-to-create" if project_name else "needs-project-name",
        "needs_project_name": not bool(project_name),
        "project_name": project_name,
        "proposed_project_slug": slugify(project_name) if project_name else "",
        "proposed_plan": proposed_plan(request),
        "proposed_options": proposed_options(request),
        "next_prompt": (
            f"\u5df2\u8bc6\u522b\u9879\u76ee\u540d `{project_name}`\uff1b\u8bf7\u5728 Lean MVP / Balanced baseline / Documentation-first \u4e09\u79cd\u8def\u5f84\u4e2d\u9009\u4e00\u4e2a\u4f5c\u4e3a\u9996\u8f6e\u65b9\u6848\uff0c\u786e\u8ba4\u540e\u6211\u4f1a\u81ea\u52a8\u521b\u5efa\u9879\u76ee\u76ee\u5f55\u3001bootstrap \u6cbb\u7406\u9aa8\u67b6\uff0c\u5e76\u8fdb\u5165\u53f8\u793c\u76d1\u81ea\u52a8\u6a21\u5f0f\u3002"
            if project_name
            else "\u8bf7\u544a\u8bc9\u6211\u9879\u76ee\u540d\uff0c\u5e76\u4ece Lean MVP / Balanced baseline / Documentation-first \u4e2d\u9009\u4e00\u4e2a\u9996\u8f6e\u65b9\u6848\uff1b\u786e\u8ba4\u540e\u6211\u4f1a\u81ea\u52a8\u521b\u5efa\u9879\u76ee\u76ee\u5f55\u3001bootstrap \u6cbb\u7406\u9aa8\u67b6\uff0c\u5e76\u8fdb\u5165\u53f8\u793c\u76d1\u81ea\u52a8\u6a21\u5f0f\u3002"
        ),
    }
    write_json(intake_path(workspace_root), payload)
    write_text(intake_markdown_path(workspace_root), render_intake_markdown(payload))
    return payload


def load_intake(workspace_root: Path) -> dict:
    return read_json(intake_path(workspace_root))


def update_new_project_files(project_root: Path, requirement: str) -> None:
    state_dir = project_root / "ai" / "state"
    task_intake = state_dir / "task-intake.md"
    requirements = state_dir / "requirements-pool.md"
    handoff = state_dir / "project-handoff.md"
    summary = summarize_requirement(requirement)
    if task_intake.exists():
        task_intake_text = task_intake.read_text(encoding="utf-8")
        task_intake_text = task_intake_text.replace("- [fill here]", f"- {summary}", 1)
        task_intake_text = task_intake_text.replace(
            "- [fill here if there is existing code; otherwise write no existing implementation]",
            "- No existing implementation yet; this is a brand new project baseline.",
            1,
        )
        task_intake_text = task_intake_text.replace(
            "- Customer acknowledged current implementation baseline: pending / not-applicable",
            "- Customer acknowledged current implementation baseline: not-applicable",
            1,
        )
        write_text(
            task_intake,
            task_intake_text.rstrip() + f"\n\n## Captured Requirement\n\n- {summary}\n",
        )
    if requirements.exists():
        write_text(
            requirements,
            requirements.read_text(encoding="utf-8").rstrip()
            + f"\n\n## New Incoming Requirements\n\n- {summary}\n",
        )
    if handoff.exists():
        write_text(
            handoff,
            handoff.read_text(encoding="utf-8").rstrip()
            + f"\n\n## Intake Notes\n\n- Initial requirement captured: {summary}\n",
        )


def create_project_from_intake(
    workspace_root: Path,
    project_name: str | None = None,
    actor: str = "user",
    activate: bool = False,
    transport: str = "outbox",
    max_cycles: int = 1,
    max_dispatch: int = 3,
) -> dict:
    ensure_workspace_root(workspace_root)
    intake = load_intake(workspace_root)
    if not intake:
        raise ValueError("No pending new-project intake exists in the current workspace.")

    resolved_project_name = (project_name or str(intake.get("project_name") or "")).strip()
    if not resolved_project_name:
        raise ValueError("No project name is available yet. Record the requirement first or pass --project-name.")

    project_slug = slugify(resolved_project_name)
    project_root = workspace_root / project_slug
    if project_root.exists():
        if not project_root.is_dir():
            raise ValueError(f"Project slug `{project_slug}` already exists as a file at {project_root}.")
        if any(project_root.iterdir()):
            raise ValueError(
                f"Project slug `{project_slug}` already exists at {project_root}; "
                "choose a different project name or use a fresh directory."
            )
    skill_root = Path(__file__).resolve().parent.parent
    bootstrap = subprocess.run(
        [
            sys.executable,
            str(skill_root / "scripts" / "bootstrap_governance.py"),
            str(project_root),
            "--project-name",
            resolved_project_name,
            "--project-id",
            project_slug,
            "--skill-root",
            str(skill_root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if bootstrap.returncode != 0:
        raise RuntimeError(bootstrap.stderr or bootstrap.stdout or "bootstrap_governance.py failed")

    update_new_project_files(project_root, str(intake.get("raw_requirement") or ""))
    intake["updated_at"] = utc_now()
    intake["intake_status"] = "project-created"
    intake["needs_project_name"] = False
    intake["project_name"] = resolved_project_name
    intake["proposed_project_slug"] = project_slug
    intake["project_root"] = str(project_root.resolve())
    write_json(intake_path(workspace_root), intake)
    write_text(intake_markdown_path(workspace_root), render_intake_markdown(intake))

    result = {
        "status": "project-created",
        "project_root": str(project_root.resolve()),
        "project_name": resolved_project_name,
        "project_slug": project_slug,
        "bootstrap_stdout": bootstrap.stdout.strip(),
        "bootstrap_stderr": bootstrap.stderr.strip(),
    }
    if activate:
        result["runtime_loop"] = runtime_loop.run_loop(
            project_root,
            max_cycles=max_cycles,
            max_dispatch=max_dispatch,
            transport=transport,
            activate=True,
            actor=actor,
            activation_reason=f"Activate new project {resolved_project_name} from workspace intake.",
        )
    return result


def workspace_requires_intake(project_root: Path) -> bool:
    return detect_directory_mode(project_root) == "workspace_root_mode"


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture a workspace-level requirement, ask for a project name, and create a new governed project.")
    parser.add_argument("project_root", help="Current workspace root")
    parser.add_argument("--requirement", help="Requirement text to capture")
    parser.add_argument("--project-name", help="Project name to create from the pending intake")
    parser.add_argument("--activate", action="store_true", help="Immediately enter autonomous mode after project creation")
    parser.add_argument("--actor", default="user", help="Who initiated the intake")
    parser.add_argument("--transport", choices=["outbox", "command"], default="outbox")
    parser.add_argument("--max-cycles", type=int, default=1)
    parser.add_argument("--max-dispatch", type=int, default=3)
    args = parser.parse_args()

    workspace_root = Path(args.project_root).resolve()
    ensure_workspace_root(workspace_root)
    if args.requirement:
        payload = record_requirement(workspace_root, args.requirement, actor=args.actor)
    elif args.project_name:
        payload = create_project_from_intake(
            workspace_root,
            args.project_name,
            actor=args.actor,
            activate=args.activate,
            transport=args.transport,
            max_cycles=args.max_cycles,
            max_dispatch=args.max_dispatch,
        )
    else:
        payload = load_intake(workspace_root)
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
