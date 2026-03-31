from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import automation_control
from common import read_json, read_text, require_valid_json, utc_now, write_json, write_text
from replan_change_request import build_replan_packet


SIGNIFICANT_KEYWORDS = {
    "schema",
    "database",
    "migration",
    "auth",
    "permission",
    "payment",
    "api",
    "architecture",
    "rollout",
    "deploy",
    "发布",
    "数据库",
    "表结构",
    "迁移",
    "权限",
    "登录",
    "支付",
    "接口",
    "架构",
}
MODIFICATION_KEYWORDS = {"modify", "change", "update", "refactor", "修改", "改", "调整", "重做", "变更"}
REMOVAL_KEYWORDS = {"remove", "delete", "drop", "取消", "删除", "去掉", "移除"}
URGENT_KEYWORDS = {"现在", "马上", "尽快", "本次", "当前", "today", "now", "urgent", "asap"}


def normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


def contains_any(text: str, words: set[str]) -> bool:
    return any(word in text for word in words)


def classify_action(request: str) -> str:
    text = normalize(request)
    if contains_any(text, REMOVAL_KEYWORDS):
        return "remove"
    if contains_any(text, MODIFICATION_KEYWORDS):
        return "modify"
    return "add"


def classify_significance(request: str) -> str:
    text = normalize(request)
    if contains_any(text, SIGNIFICANT_KEYWORDS):
        return "significant"
    if len(request.strip()) >= 120:
        return "significant"
    return "incremental"


def classify_batch(request: str, significance: str) -> str:
    text = normalize(request)
    if significance == "significant":
        return "raw"
    if contains_any(text, URGENT_KEYWORDS):
        return "current_batch"
    return "raw"


def slugify(text: str) -> str:
    chars = []
    for ch in text.lower():
        if ch.isalnum():
            chars.append(ch)
        elif chars and chars[-1] != "-":
            chars.append("-")
    return "".join(chars).strip("-") or "change-request"


def next_change_request_id(project_root: Path) -> str:
    task_tree = read_json(project_root / "ai" / "state" / "task-tree.json")
    existing = task_tree.get("change_requests", [])
    return f"CR-{len(existing) + 1:03d}"


def append_section_item(markdown: str, heading: str, item: str) -> str:
    lines = markdown.splitlines()
    target = heading.strip().lower()
    output: list[str] = []
    inserted = False
    in_target = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("## "):
            if in_target and not inserted:
                output.append(f"- {item}")
                inserted = True
            in_target = stripped[3:].strip().lower() == target
            output.append(line)
            continue
        output.append(line)
        if in_target and stripped.startswith("- ") and stripped.lower() == "- none":
            output[-1] = f"- {item}"
            inserted = True
            in_target = False
    if not inserted:
        if output and output[-1] != "":
            output.append("")
        output.extend([f"## {heading}", "", f"- {item}"])
    return "\n".join(output).rstrip() + "\n"


def update_requirements_pool(project_root: Path, request_id: str, action: str, significance: str, batch: str, request: str) -> None:
    path = project_root / "ai" / "state" / "requirements-pool.md"
    markdown = read_text(path)
    entry = f"[{request_id}] action={action} impact={significance} request={request}"
    markdown = append_section_item(markdown, "Raw", entry)
    if batch == "current_batch":
        markdown = append_section_item(markdown, "Current Batch", entry)
    elif significance == "significant":
        markdown = append_section_item(markdown, "Future Batch", entry)
    write_text(path, markdown)


def update_task_tree(project_root: Path, request_id: str, action: str, significance: str, batch: str, request: str) -> dict[str, Any]:
    path = project_root / "ai" / "state" / "task-tree.json"
    payload = read_json(path)
    payload.setdefault("version", "0.1.0")
    payload.setdefault("mainline", [])
    payload.setdefault("current_batch", [])
    payload.setdefault("future_batch", [])
    payload.setdefault("tasks", [])
    payload.setdefault("change_requests", [])
    entry = {
        "request_id": request_id,
        "action": action,
        "significance": significance,
        "batch": batch,
        "status": "pending-triage",
        "request": request,
        "created_at": utc_now(),
    }
    payload["change_requests"].append(entry)
    if batch == "current_batch":
        payload["current_batch"].append({"request_id": request_id, "summary": request})
    elif significance == "significant":
        payload["future_batch"].append({"request_id": request_id, "summary": request})
    elif action == "add":
        payload["current_batch"].append({"request_id": request_id, "summary": request})
    write_json(path, payload)
    return entry


def update_project_handoff(project_root: Path, request_id: str, significance: str, request: str) -> None:
    path = project_root / "ai" / "state" / "project-handoff.md"
    markdown = read_text(path)
    note = f"{request_id}: pending change request ({significance}) -> {request}"
    markdown = append_section_item(markdown, "Notes For Next Round", note)
    write_text(path, markdown)


def write_change_request_report(project_root: Path, payload: dict[str, Any]) -> None:
    reports_dir = project_root / "ai" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    stem = slugify(payload["request_id"].lower())
    options = payload.get("guided_options", []) if isinstance(payload.get("guided_options"), list) else []
    option_lines = (
        "\n\n".join(
            "\n".join(
                [
                    f"### {item.get('id', '').upper()} {item.get('title', '')}",
                    f"- summary: {item.get('summary', '')}",
                    f"- tradeoff: {item.get('tradeoff', '')}",
                ]
            )
            for item in options
            if isinstance(item, dict)
        )
        or "### OPTION-B Structured replan\n- summary: Freeze the change into architecture, task tree, and acceptance before resuming execution.\n- tradeoff: Slower now, safer later."
    )
    write_json(reports_dir / f"{stem}.json", payload)
    write_text(
        reports_dir / f"{stem}.md",
        f"""# Change Request

- request_id: {payload['request_id']}
- action: {payload['action']}
- significance: {payload['significance']}
- batch: {payload['batch']}
- requires_replan: {'yes' if payload['requires_replan'] else 'no'}
- automation_paused: {'yes' if payload['automation_paused'] else 'no'}
- created_at: {payload['created_at']}

## Request

- {payload['request']}

## Recommended Next Action

- {payload['recommended_next_action']}

## Guided Options

{option_lines}
""",
    )


def apply_change_request(project_root: Path, request: str, actor: str = "user") -> dict[str, Any]:
    state_path = project_root / "ai" / "state" / "orchestrator-state.json"
    state = require_valid_json(state_path, "ai/state/orchestrator-state.json") if state_path.exists() else {}
    request_id = next_change_request_id(project_root)
    action = classify_action(request)
    significance = classify_significance(request)
    batch = classify_batch(request, significance)
    requires_replan = significance == "significant" or action in {"modify", "remove"}
    recommended_next_action = (
        f"Review change request {request_id}, update architecture/task-tree impacts, and replan affected workflow steps."
        if requires_replan
        else f"Review change request {request_id} and fold it into the next executable batch."
    )

    state.setdefault("pending_change_requests", [])
    state["pending_change_requests"].append(
        {
            "request_id": request_id,
            "request": request,
            "action": action,
            "significance": significance,
            "batch": batch,
            "created_at": utc_now(),
        }
    )
    state["last_change_request_id"] = request_id
    state["next_owner"] = "orchestrator"
    state["next_action"] = recommended_next_action
    state["automation_last_reason"] = f"Change request received: {request_id}"
    write_json(state_path, state)

    update_requirements_pool(project_root, request_id, action, significance, batch, request)
    task_tree_entry = update_task_tree(project_root, request_id, action, significance, batch, request)
    update_project_handoff(project_root, request_id, significance, request)

    automation_paused = False
    replan_packet = None
    control = automation_control.ensure_control_state(project_root)
    if control.get("automation_mode") == "autonomous" and requires_replan:
        automation_control.set_mode(
            project_root,
            "paused",
            actor=actor,
            reason=f"Change request {request_id}: {request}",
            resume_action=recommended_next_action,
        )
        automation_paused = True
    if requires_replan:
        replan_packet = build_replan_packet(project_root, request_id)

    payload = {
        "request_id": request_id,
        "request": request,
        "action": action,
        "significance": significance,
        "batch": batch,
        "requires_replan": requires_replan,
        "automation_paused": automation_paused,
        "created_at": utc_now(),
        "recommended_next_action": recommended_next_action,
        "task_tree_entry": task_tree_entry,
        "replan_packet": replan_packet,
        "guided_options": (replan_packet or {}).get("guided_options", []),
    }
    write_change_request_report(project_root, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Record a mid-flight feature change request from one natural-language sentence.")
    parser.add_argument("project_root", help="Target project root")
    parser.add_argument("request", help="Natural-language change request")
    parser.add_argument("--actor", default="user", help="Who submitted the change request")
    args = parser.parse_args()

    payload = apply_change_request(Path(args.project_root).resolve(), args.request, actor=args.actor)
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
