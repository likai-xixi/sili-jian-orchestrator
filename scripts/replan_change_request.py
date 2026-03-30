from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import read_json, read_text, utc_now, write_json, write_text


def replace_or_append_line(text: str, prefix: str, new_line: str) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            lines[index] = new_line
            return "\n".join(lines).rstrip() + "\n"
    lines.append(new_line)
    return "\n".join(lines).rstrip() + "\n"


def append_note(markdown: str, note: str) -> str:
    lines = markdown.splitlines()
    output: list[str] = []
    inserted = False
    in_target = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            if in_target and not inserted:
                output.append(f"- {note}")
                inserted = True
            in_target = stripped[3:].strip().lower() == "notes for next round"
            output.append(line)
            continue
        output.append(line)
        if in_target and stripped.lower() == "- none":
            output[-1] = f"- {note}"
            inserted = True
            in_target = False
    if not inserted:
        if output and output[-1] != "":
            output.append("")
        output.extend(["## Notes For Next Round", "", f"- {note}"])
    return "\n".join(output).rstrip() + "\n"


def locate_change_request(task_tree: dict[str, Any], request_id: str) -> dict[str, Any]:
    for item in task_tree.get("change_requests", []):
        if str(item.get("request_id")) == request_id:
            return item
    return {}


def replan_status(change_request: dict[str, Any]) -> str:
    significance = str(change_request.get("significance", "incremental"))
    action = str(change_request.get("action", "add"))
    if significance == "significant":
        return "redesign" if action in {"modify", "remove"} else "rework"
    return "rework"


def report_stem(request_id: str) -> str:
    return f"replan-{request_id.lower()}"


def guided_options(change_request: dict[str, Any]) -> list[dict[str, str]]:
    action = str(change_request.get("action") or "change")
    significance = str(change_request.get("significance") or "incremental")
    return [
        {
            "id": "option-a",
            "title": "Minimal patch",
            "summary": f"Keep the current batch moving and absorb only the smallest {action} needed right now.",
            "tradeoff": "Fastest path, but leaves more follow-up work and review risk for later.",
        },
        {
            "id": "option-b",
            "title": "Structured replan",
            "summary": f"Re-freeze architecture, task tree, and acceptance around this {significance} change before execution resumes.",
            "tradeoff": "Most stable option and usually the recommended path, but it pauses execution longer.",
        },
        {
            "id": "option-c",
            "title": "Split into phases",
            "summary": "Protect the approved scope in the current batch, move the new request into a follow-up batch, and continue with a narrower delivery target.",
            "tradeoff": "Balanced risk, but requires clear boundary-setting and explicit customer agreement.",
        },
    ]


def update_task_tree_for_replan(project_root: Path, request_id: str) -> dict[str, Any]:
    path = project_root / "ai" / "state" / "task-tree.json"
    payload = read_json(path)
    entry = locate_change_request(payload, request_id)
    if entry:
        entry["status"] = "replan-required"
        entry["replan_requested_at"] = utc_now()
    payload.setdefault("replan_queue", [])
    queue_entry = {
        "request_id": request_id,
        "status": "pending-replan",
        "queued_at": utc_now(),
    }
    payload["replan_queue"] = [item for item in payload["replan_queue"] if str(item.get("request_id")) != request_id]
    payload["replan_queue"].append(queue_entry)
    write_json(path, payload)
    return locate_change_request(payload, request_id) or queue_entry


def update_state_for_replan(project_root: Path, request_id: str, change_request: dict[str, Any]) -> dict[str, Any]:
    path = project_root / "ai" / "state" / "orchestrator-state.json"
    state = read_json(path)
    status = replan_status(change_request)
    state["current_phase"] = "planning"
    state["current_status"] = status
    state["execution_allowed"] = False
    state["testing_allowed"] = False
    state["release_allowed"] = False
    state["next_owner"] = "neige"
    state["next_action"] = (
        f"Replan change request {request_id}, update architecture and task-tree impacts, then return the plan for approval."
    )
    state["primary_goal"] = f"Replan around {request_id} without losing continuity."
    state["last_heartbeat_goal"] = f"Freeze broad execution and re-evaluate scope for {request_id}."
    state["last_heartbeat_reason"] = "A mid-flight requirement changed scope enough to require planning before execution resumes."
    state["replan_required"] = True
    state["replan_request_id"] = request_id
    state["plan_frozen"] = False
    state.setdefault("workflow_progress", {})
    state["workflow_progress"]["replan_requested_for"] = request_id
    write_json(path, state)
    return state


def update_handoff_for_replan(project_root: Path, request_id: str, state: dict[str, Any], change_request: dict[str, Any]) -> None:
    path = project_root / "ai" / "state" / "project-handoff.md"
    markdown = read_text(path)
    markdown = replace_or_append_line(markdown, "- Status:", f"- Status: {state.get('current_status', 'rework')}")
    markdown = replace_or_append_line(markdown, "- Current phase:", f"- Current phase: {state.get('current_phase', 'planning')}")
    markdown = replace_or_append_line(markdown, "- Next action:", f"- Next action: {state.get('next_action', '')}")
    markdown = replace_or_append_line(markdown, "- Next owner:", f"- Next owner: {state.get('next_owner', 'neige')}")
    markdown = append_note(
        markdown,
        f"{request_id}: replan required for {change_request.get('action', 'change')} / {change_request.get('significance', 'incremental')} scope.",
    )
    write_text(path, markdown)


def build_replan_packet(project_root: Path, request_id: str) -> dict[str, Any]:
    task_tree = read_json(project_root / "ai" / "state" / "task-tree.json")
    change_request = locate_change_request(task_tree, request_id)
    state = update_state_for_replan(project_root, request_id, change_request)
    task_entry = update_task_tree_for_replan(project_root, request_id)
    update_handoff_for_replan(project_root, request_id, state, task_entry)

    packet = {
        "request_id": request_id,
        "created_at": utc_now(),
        "current_workflow": state.get("current_workflow", ""),
        "replan_status": state.get("current_status", "rework"),
        "next_owner": state.get("next_owner", "neige"),
        "next_action": state.get("next_action", ""),
        "change_request": task_entry,
        "freeze_summary": {
            "execution_allowed": state.get("execution_allowed", False),
            "testing_allowed": state.get("testing_allowed", False),
            "release_allowed": state.get("release_allowed", False),
        },
        "recommended_flow": [
            "re-read the change request and requirements pool",
            "update architecture impacts",
            "update task tree and affected batches",
            "route the revised plan through plan approval",
            "resume autonomy only after the new plan is frozen",
        ],
        "guided_options": guided_options(task_entry),
    }
    reports_dir = project_root / "ai" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    stem = report_stem(request_id)
    write_json(reports_dir / f"{stem}.json", packet)
    write_text(
        reports_dir / f"{stem}.md",
        (
            f"""# Replan Packet

- request_id: {packet['request_id']}
- created_at: {packet['created_at']}
- current_workflow: {packet['current_workflow']}
- replan_status: {packet['replan_status']}
- next_owner: {packet['next_owner']}
- next_action: {packet['next_action']}

## Change Request

- action: {task_entry.get('action', '')}
- significance: {task_entry.get('significance', '')}
- request: {task_entry.get('request', '')}

## Freeze Summary

- execution_allowed: {'yes' if packet['freeze_summary']['execution_allowed'] else 'no'}
- testing_allowed: {'yes' if packet['freeze_summary']['testing_allowed'] else 'no'}
- release_allowed: {'yes' if packet['freeze_summary']['release_allowed'] else 'no'}

## Recommended Flow

"""
            + "\n".join(f"- {item}" for item in packet["recommended_flow"])
            + "\n\n## Guided Options\n\n"
            + "\n\n".join(
                [
                    "\n".join(
                        [
                            f"### {item['id'].upper()} {item['title']}",
                            f"- summary: {item['summary']}",
                            f"- tradeoff: {item['tradeoff']}",
                        ]
                    )
                    for item in packet["guided_options"]
                ]
            )
            + "\n"
        ),
    )
    return packet


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a replan packet for a recorded mid-flight change request.")
    parser.add_argument("project_root", help="Target project root")
    parser.add_argument("request_id", help="Existing change request id such as CR-001")
    args = parser.parse_args()

    payload = build_replan_packet(Path(args.project_root).resolve(), args.request_id)
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
