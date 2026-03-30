from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import read_json, read_text, utc_now, write_json, write_text
from recovery_summary import build_summary
from runtime_guardrails import context_budget_snapshot, write_context_budget_report
from session_registry import ensure_registry_schema, upsert_session


def build_rollover_payload(project_root: Path, agent_id: str = "orchestrator", reason: str | None = None) -> dict:
    state = read_json(project_root / "ai" / "state" / "orchestrator-state.json")
    registry = ensure_registry_schema(project_root)
    report_summary = build_summary(project_root)
    budget = write_context_budget_report(project_root, context_budget_snapshot(project_root, agent_id=agent_id))
    active_tasks = state.get("active_tasks", [])
    active_lines = "\n".join(
        f"- {task.get('workflow_step_id') or task.get('task_id')}: {task.get('role')} ({task.get('status')})"
        for task in active_tasks
    ) or "- none"
    blockers = state.get("blockers", [])
    blocker_lines = "\n".join(f"- {item}" for item in blockers) if blockers else "- none"
    rollover_reason = reason or (budget.get("reasons") or ["No ready workflow steps remain for this session."])[0]
    resume_prompt = f"""Continue as the {agent_id} runtime for this governed project.

Current workflow: {state.get('current_workflow', 'unknown')}
Current status: {state.get('current_status', 'unknown')}
Current phase: {state.get('current_phase', 'unknown')}
Next action: {state.get('next_action', 'review project state')}
Next owner: {state.get('next_owner', 'orchestrator')}
Rollover reason: {rollover_reason}

Active tasks:
{active_lines}

Blockers:
{blocker_lines}

Before doing anything else:
1. Read ai/state/START_HERE.md
2. Read docs/ANTI-DRIFT-RUNBOOK.md
3. Read ai/state/project-handoff.md
4. Read ai/state/orchestrator-state.json
5. Read ai/state/agent-sessions.json
6. Read the latest ai/reports/orchestrator-rollover.md
7. Dispatch the next ready workflow step or resolve blockers
"""
    return {
        "agent_id": agent_id,
        "created_at": utc_now(),
        "rollover_reason": rollover_reason,
        "current_workflow": state.get("current_workflow", ""),
        "current_status": state.get("current_status", ""),
        "current_phase": state.get("current_phase", ""),
        "next_action": state.get("next_action", ""),
        "next_owner": state.get("next_owner", ""),
        "active_tasks": active_tasks,
        "blockers": blockers,
        "session_record": registry.get(agent_id, {}),
        "project_handoff_excerpt": read_text(project_root / "ai" / "state" / "project-handoff.md"),
        "start_here_excerpt": read_text(project_root / "ai" / "state" / "START_HERE.md"),
        "recovery_summary": report_summary,
        "context_budget": budget,
        "resume_prompt": resume_prompt,
    }


def render_rollover_markdown(payload: dict) -> str:
    active_tasks = payload.get("active_tasks", [])
    blockers = payload.get("blockers", [])
    active_lines = "\n".join(
        f"- {task.get('workflow_step_id') or task.get('task_id')}: {task.get('role')} ({task.get('status')})"
        for task in active_tasks
    ) or "- none"
    blocker_lines = "\n".join(f"- {item}" for item in blockers) if blockers else "- none"
    return f"""# Orchestrator Rollover

- Agent id: {payload.get('agent_id', 'orchestrator')}
- Created at: {payload.get('created_at', '')}
- Rollover reason: {payload.get('rollover_reason', '')}
- Current workflow: {payload.get('current_workflow', '')}
- Current phase: {payload.get('current_phase', '')}
- Current status: {payload.get('current_status', '')}
- Next owner: {payload.get('next_owner', '')}
- Next action: {payload.get('next_action', '')}
- Context budget: ~{payload.get('context_budget', {}).get('total_estimated_tokens', 0)} / {payload.get('context_budget', {}).get('hard_limit_tokens', 0)} tokens

## Active Tasks

{active_lines}

## Blockers

{blocker_lines}

## Recovery Summary

{payload.get('recovery_summary', '').strip()}

## Resume Prompt

```text
{payload.get('resume_prompt', '').strip()}
```
"""


def context_rollover_required(project_root: Path, agent_id: str = "orchestrator") -> dict:
    return write_context_budget_report(project_root, context_budget_snapshot(project_root, agent_id=agent_id))


def create_rollover(project_root: Path, agent_id: str = "orchestrator", reason: str | None = None) -> dict:
    payload = build_rollover_payload(project_root, agent_id=agent_id, reason=reason)
    reports_dir = project_root / "ai" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    write_json(reports_dir / "orchestrator-rollover.json", payload)
    write_text(reports_dir / "orchestrator-rollover.md", render_rollover_markdown(payload))
    upsert_session(
        project_root,
        agent_id,
        status="waiting",
        resume_prompt=payload["resume_prompt"],
        active_workflow=payload.get("current_workflow"),
        last_rollover_at=payload.get("created_at"),
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a rollover package for the orchestrator or a peer agent.")
    parser.add_argument("project_root", help="Target project root")
    parser.add_argument("--agent-id", default="orchestrator", help="Agent id that needs a rollover package")
    args = parser.parse_args()

    payload = create_rollover(Path(args.project_root).resolve(), agent_id=args.agent_id)
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
