from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import read_text


MULTILINE_FIELDS = {
    "goal",
    "dependencies",
    "acceptance",
    "expected_output",
    "upstream_dependencies",
    "downstream_reviewers",
    "testing_requirement",
}


def parse_task_card(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    current_key: str | None = None
    for raw_line in read_text(path).splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- ") and ":" in stripped:
            key, value = stripped[2:].split(":", 1)
            current_key = key.strip()
            data[current_key] = value.strip()
            continue
        if current_key and (line.startswith("  ") or line.startswith("\t")):
            extra = stripped
            if not extra:
                continue
            separator = "\n" if current_key in MULTILINE_FIELDS else " "
            existing = data.get(current_key, "")
            data[current_key] = f"{existing}{separator if existing else ''}{extra}"
            continue
        current_key = None
    return data


def render_field(label: str, value: str) -> str:
    if not value:
        return f"- {label}:"
    if "\n" not in value:
        return f"- {label}: {value}"
    indented = "\n".join(f"  {line}" for line in value.splitlines())
    return f"- {label}:\n{indented}"


def build_prompt(card: dict[str, str]) -> str:
    agent_label = card.get("target_agent", "department")
    lines = [
        f"[{agent_label} task]",
        render_field("task_id", card.get("task_id", "")),
        render_field("title", card.get("title", "")),
        render_field("goal", card.get("goal", "")),
        render_field("allowed_paths", card.get("allowed_paths", "")),
        render_field("forbidden_paths", card.get("forbidden_paths", "")),
        render_field("dependencies", card.get("dependencies", "")),
        render_field("acceptance", card.get("acceptance", "")),
        render_field("handoff_path", card.get("handoff_path", "")),
        render_field("expected_output", card.get("expected_output", "")),
        render_field("review_required", card.get("review_required", "")),
        render_field("upstream_dependencies", card.get("upstream_dependencies", "")),
        render_field("downstream_reviewers", card.get("downstream_reviewers", "")),
        render_field("testing_requirement", card.get("testing_requirement", "")),
        render_field("workflow_step_id", card.get("workflow_step_id", "")),
        render_field("priority", card.get("priority", "")),
        "",
        "Completion requirements:",
        "1. Update the department handoff.",
        "2. Record blockers explicitly.",
        "3. State whether the work may move to the next stage.",
        "4. Provide a concise summary back to the orchestrator.",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build sessions_spawn or sessions_send payload from a task card.")
    parser.add_argument("task_card", help="Path to task-card markdown")
    parser.add_argument("--mode", choices=["spawn", "send"], required=True)
    parser.add_argument("--session-key", help="Required for send mode")
    args = parser.parse_args()

    card = parse_task_card(Path(args.task_card))
    agent_id = card.get("target_agent_id") or card.get("target_agent")
    prompt = build_prompt(card)

    if args.mode == "spawn":
        payload = {
            "task": prompt,
            "runtime": "subagent",
            "agentId": agent_id,
            "mode": "run",
            "cleanup": "keep" if card.get("cleanup_policy", "").lower() == "keep" else "delete",
        }
    else:
        session_key = args.session_key or card.get("session_key")
        if not session_key:
            raise SystemExit("--session-key is required for send mode")
        payload = {
            "sessionKey": session_key,
            "agentId": agent_id,
            "message": prompt,
        }

    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
