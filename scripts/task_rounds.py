from __future__ import annotations

from pathlib import Path
from typing import Any

from common import read_json, utc_now, write_json, write_text
from session_registry import ensure_registry_schema, upsert_session


ROUND_DEFINITIONS = {
    "feature-delivery": [
        {
            "id": "planning-round",
            "title": "Planning Round",
            "steps": ["intake-feature", "confirm-or-replan", "plan-approval"],
            "participants": ["orchestrator", "neige", "duchayuan"],
            "close_step": "plan-approval",
            "commit_eligible": True,
        },
        {
            "id": "implementation-round",
            "title": "Implementation Round",
            "steps": [
                "libu2-implementation",
                "hubu-implementation",
                "gongbu-implementation",
                "libu2-cross-review",
                "hubu-cross-review",
                "gongbu-cross-review",
                "bingbu-cross-review",
                "libu-cross-review",
                "xingbu-cross-review",
                "duchayuan-cross-review",
                "department-review",
            ],
            "participants": ["libu2", "hubu", "gongbu", "bingbu", "libu", "xingbu", "duchayuan", "orchestrator"],
            "close_step": "department-review",
            "commit_eligible": True,
        },
        {
            "id": "release-round",
            "title": "Release Round",
            "steps": [
                "bingbu-testing",
                "libu-documentation",
                "xingbu-release-check",
                "final-audit",
                "release-prep",
                "update-state-and-run-summary",
            ],
            "participants": ["bingbu", "libu", "xingbu", "duchayuan", "orchestrator"],
            "close_step": "update-state-and-run-summary",
            "commit_eligible": True,
        },
    ]
}


def _round_definitions(workflow_name: str) -> list[dict[str, Any]]:
    return list(ROUND_DEFINITIONS.get(workflow_name, []))


def _state_path(project_root: Path) -> Path:
    return project_root / "ai" / "state" / "orchestrator-state.json"


def _reports_dir(project_root: Path) -> Path:
    path = project_root / "ai" / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_round_state(state: dict[str, Any]) -> dict[str, Any]:
    payload = state.get("task_rounds")
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("current_round_id", None)
    payload.setdefault("last_completed_round_id", None)
    payload.setdefault("history", [])
    payload.setdefault("completed_rounds", [])
    state["task_rounds"] = payload
    return payload


def derive_current_round(workflow_name: str, completed_steps: set[str]) -> dict[str, Any] | None:
    for definition in _round_definitions(workflow_name):
        steps = [str(item) for item in definition.get("steps", [])]
        if any(step not in completed_steps for step in steps):
            return definition
    return None


def round_snapshot(project_root: Path, state: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = state or read_json(_state_path(project_root))
    round_state = ensure_round_state(payload)
    workflow_name = str(payload.get("current_workflow") or "")
    progress = payload.get("workflow_progress") if isinstance(payload.get("workflow_progress"), dict) else {}
    completed_steps = {str(item) for item in progress.get("completed_steps", [])}
    current_round = derive_current_round(workflow_name, completed_steps)
    active_tasks = payload.get("active_tasks", []) if isinstance(payload.get("active_tasks"), list) else []
    active_step_ids = [str(task.get("workflow_step_id") or "") for task in active_tasks if task.get("workflow_step_id")]
    if current_round is None:
        status = "complete"
        pending_steps: list[str] = []
        round_id = None
        round_title = ""
        participants: list[str] = []
        close_step = ""
    else:
        steps = [str(item) for item in current_round.get("steps", [])]
        pending_steps = [step for step in steps if step not in completed_steps]
        started = bool(set(steps) & completed_steps) or bool(set(steps) & set(active_step_ids))
        status = "active" if started else "pending"
        round_id = str(current_round.get("id") or "")
        round_title = str(current_round.get("title") or round_id)
        explicit_participants = current_round.get("participants") if isinstance(current_round.get("participants"), list) else []
        participants = sorted(str(item) for item in explicit_participants) if explicit_participants else sorted({step.split("-", 1)[0] for step in steps if "-" in step and not step.startswith("update-state")})
        close_step = str(current_round.get("close_step") or "")
    return {
        "workflow_name": workflow_name,
        "current_round_id": round_id,
        "current_round_title": round_title,
        "status": status,
        "pending_steps": pending_steps,
        "active_step_ids": active_step_ids,
        "completed_steps": sorted(completed_steps),
        "participants": participants,
        "close_step": close_step,
        "last_completed_round_id": round_state.get("last_completed_round_id"),
    }


def record_round_progress(project_root: Path, state: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = state or read_json(_state_path(project_root))
    round_state = ensure_round_state(payload)
    snapshot = round_snapshot(project_root, payload)
    round_state["current_round_id"] = snapshot.get("current_round_id")
    write_json(_state_path(project_root), payload)
    reports_dir = _reports_dir(project_root)
    write_json(reports_dir / "task-round-status.json", snapshot)
    write_text(
        reports_dir / "task-round-status.md",
        "\n".join(
            [
                "# Task Round Status",
                "",
                f"- workflow_name: {snapshot.get('workflow_name', '')}",
                f"- current_round_id: {snapshot.get('current_round_id') or 'none'}",
                f"- current_round_title: {snapshot.get('current_round_title') or 'n/a'}",
                f"- status: {snapshot.get('status', '')}",
                f"- close_step: {snapshot.get('close_step') or 'n/a'}",
                f"- participants: {', '.join(snapshot.get('participants', [])) or 'none'}",
                "",
                "## Pending Steps",
                "",
                *([f"- {item}" for item in snapshot.get("pending_steps", [])] or ["- none"]),
            ]
        )
        + "\n",
    )
    return snapshot


def complete_round_if_ready(project_root: Path, state: dict[str, Any] | None = None) -> dict[str, Any] | None:
    payload = state or read_json(_state_path(project_root))
    round_state = ensure_round_state(payload)
    workflow_name = str(payload.get("current_workflow") or "")
    definitions = _round_definitions(workflow_name)
    if not definitions:
        return None
    progress = payload.get("workflow_progress") if isinstance(payload.get("workflow_progress"), dict) else {}
    completed_steps = {str(item) for item in progress.get("completed_steps", [])}
    history = round_state.get("history", [])
    if not isinstance(history, list):
        history = []
        round_state["history"] = history
    completed_rounds = round_state.get("completed_rounds", [])
    if not isinstance(completed_rounds, list):
        completed_rounds = []
        round_state["completed_rounds"] = completed_rounds

    for definition in definitions:
        round_id = str(definition.get("id") or "")
        close_step = str(definition.get("close_step") or "")
        if not round_id or round_id in completed_rounds:
            continue
        if close_step and close_step in completed_steps:
            steps = [str(item) for item in definition.get("steps", [])]
            explicit_participants = definition.get("participants") if isinstance(definition.get("participants"), list) else []
            participants = sorted(str(item) for item in explicit_participants) if explicit_participants else sorted({step.split("-", 1)[0] for step in steps if "-" in step and not step.startswith("update-state")})
            payload_record = {
                "round_id": round_id,
                "title": str(definition.get("title") or round_id),
                "completed_at": utc_now(),
                "workflow_name": workflow_name,
                "steps": steps,
                "participants": participants,
                "commit_eligible": bool(definition.get("commit_eligible", True)),
                "close_step": close_step,
            }
            history.append(payload_record)
            completed_rounds.append(round_id)
            round_state["last_completed_round_id"] = round_id
            round_state["current_round_id"] = None
            registry = ensure_registry_schema(project_root)
            for agent_id in participants:
                existing = dict(registry.get(agent_id, {}))
                upsert_session(
                    project_root,
                    agent_id,
                    task_round_count=int(existing.get("task_round_count") or 0) + 1,
                )
            write_json(_state_path(project_root), payload)
            reports_dir = _reports_dir(project_root)
            write_json(reports_dir / "task-round-history.json", {"entries": history})
            write_text(
                reports_dir / "task-round-history.md",
                "\n".join(
                    ["# Task Round History", ""]
                    + [
                        line
                        for item in history
                        for line in (
                            f"## {item['round_id']}",
                            "",
                            f"- title: {item['title']}",
                            f"- completed_at: {item['completed_at']}",
                            f"- close_step: {item['close_step']}",
                            f"- participants: {', '.join(item['participants']) if item['participants'] else 'none'}",
                            "",
                        )
                    ]
                )
                + "\n",
            )
            record_round_progress(project_root, payload)
            return payload_record
    record_round_progress(project_root, payload)
    return None
