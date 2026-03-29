from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from common import read_json


@dataclass
class WorkflowStep:
    id: str
    role: str
    agent_id: str
    depends_on: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)


@dataclass
class WorkflowDefinition:
    name: str
    steps: list[WorkflowStep]
    review_points: list[str] = field(default_factory=list)
    recovery_points: list[str] = field(default_factory=list)


def parse_scalar(value: str) -> Any:
    text = value.strip()
    if not text:
        return ""
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [item.strip().strip("'\"") for item in inner.split(",") if item.strip()]
    if text.lower() == "true":
        return True
    if text.lower() == "false":
        return False
    return text.strip("'\"")


def parse_workflow_text(text: str) -> WorkflowDefinition:
    name = ""
    review_points: list[str] = []
    recovery_points: list[str] = []
    steps: list[dict[str, Any]] = []
    section = ""
    current_step: dict[str, Any] | None = None

    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()

        if indent == 0:
            if current_step is not None:
                steps.append(current_step)
                current_step = None
            if stripped.startswith("name:"):
                name = str(parse_scalar(stripped.split(":", 1)[1]))
                section = ""
            elif stripped == "steps:":
                section = "steps"
            elif stripped == "review_points:":
                section = "review_points"
            elif stripped == "recovery_points:":
                section = "recovery_points"
            continue

        if section == "steps":
            if indent == 2 and stripped.startswith("- "):
                if current_step is not None:
                    steps.append(current_step)
                current_step = {}
                remainder = stripped[2:].strip()
                if ":" in remainder:
                    key, value = remainder.split(":", 1)
                    current_step[key.strip()] = parse_scalar(value)
                continue
            if current_step is not None and indent >= 4 and ":" in stripped:
                key, value = stripped.split(":", 1)
                current_step[key.strip()] = parse_scalar(value)
                continue

        if section in {"review_points", "recovery_points"} and indent == 2 and stripped.startswith("- "):
            value = str(parse_scalar(stripped[2:]))
            if section == "review_points":
                review_points.append(value)
            else:
                recovery_points.append(value)

    if current_step is not None:
        steps.append(current_step)

    return WorkflowDefinition(
        name=name,
        steps=[
            WorkflowStep(
                id=str(step.get("id", "")),
                role=str(step.get("role", "")),
                agent_id=str(step.get("agent_id", step.get("role", ""))),
                depends_on=list(step.get("depends_on", [])) if isinstance(step.get("depends_on", []), list) else [],
                outputs=list(step.get("outputs", [])) if isinstance(step.get("outputs", []), list) else [],
            )
            for step in steps
        ],
        review_points=review_points,
        recovery_points=recovery_points,
    )


def workflow_path(project_root: Path, workflow_name: str) -> Path:
    return project_root / "workflows" / f"{workflow_name}.yaml"


def load_workflow(project_root: Path, workflow_name: str | None = None) -> WorkflowDefinition:
    state = read_json(project_root / "ai" / "state" / "orchestrator-state.json")
    name = workflow_name or str(state.get("current_workflow", "")).strip()
    if not name:
        raise FileNotFoundError("No workflow_name provided and orchestrator-state.json does not declare current_workflow.")
    path = workflow_path(project_root, name)
    if not path.exists():
        raise FileNotFoundError(f"Workflow file not found: {path}")
    return parse_workflow_text(path.read_text(encoding="utf-8-sig"))


def ensure_workflow_progress(state: dict[str, Any]) -> dict[str, Any]:
    progress = state.get("workflow_progress", {})
    if not isinstance(progress, dict):
        progress = {}
    progress.setdefault("completed_steps", [])
    progress.setdefault("blocked_steps", [])
    progress.setdefault("dispatched_steps", [])
    state["workflow_progress"] = progress
    return progress


def step_status_index(state: dict[str, Any]) -> dict[str, str]:
    progress = ensure_workflow_progress(state)
    statuses: dict[str, str] = {}
    for step_id in progress.get("completed_steps", []):
        statuses[str(step_id)] = "completed"
    for step_id in progress.get("blocked_steps", []):
        statuses[str(step_id)] = "blocked"
    for step_id in progress.get("dispatched_steps", []):
        statuses.setdefault(str(step_id), "queued")
    for task in state.get("active_tasks", []):
        step_id = str(task.get("workflow_step_id", "")).strip()
        if step_id:
            statuses[step_id] = str(task.get("status", "in-progress")).strip() or "in-progress"
    return statuses


def ready_steps(workflow: WorkflowDefinition, state: dict[str, Any]) -> list[WorkflowStep]:
    statuses = step_status_index(state)
    completed = {step_id for step_id, status in statuses.items() if status == "completed"}
    ready: list[WorkflowStep] = []
    for step in workflow.steps:
        status = statuses.get(step.id)
        if status in {"completed", "queued", "in-progress", "blocked"}:
            continue
        if all(dependency in completed for dependency in step.depends_on):
            ready.append(step)
    return ready


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect a governed workflow and list ready steps.")
    parser.add_argument("project_root", help="Target project root")
    parser.add_argument("--workflow", help="Optional workflow override")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    state = read_json(project_root / "ai" / "state" / "orchestrator-state.json")
    workflow = load_workflow(project_root, args.workflow)
    payload = {
        "name": workflow.name,
        "steps": [asdict(step) for step in workflow.steps],
        "ready_steps": [step.id for step in ready_steps(workflow, state)],
        "step_statuses": step_status_index(state),
        "review_points": workflow.review_points,
        "recovery_points": workflow.recovery_points,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
