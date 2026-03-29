from __future__ import annotations

import argparse
import json
from pathlib import Path

from session_registry import ensure_registry_schema, upsert_session


def main() -> None:
    parser = argparse.ArgumentParser(description="Update ai/state/agent-sessions.json for a target project.")
    parser.add_argument("project_root", help="Target project root")
    parser.add_argument("agent_id", help="Peer agent id such as neige or bingbu")
    parser.add_argument("--session-key", help="Session key to store")
    parser.add_argument("--status", default="active", help="idle/active/blocked/etc")
    parser.add_argument("--last-task-id", help="Last dispatched task id")
    parser.add_argument("--last-step-id", help="Last workflow step id")
    parser.add_argument("--handoff-path", help="Current handoff path")
    parser.add_argument("--resume-prompt", help="Resume prompt for the next session")
    parser.add_argument("--active-workflow", help="Current workflow bound to this session")
    parser.add_argument("--blocked-reason", help="Blocked reason to persist")
    parser.add_argument("--ensure-schema", action="store_true", help="Ensure the registry contains the full default schema")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    if args.ensure_schema:
        print(json.dumps(ensure_registry_schema(project_root), indent=2, ensure_ascii=False))
        return
    record = upsert_session(
        project_root,
        args.agent_id,
        session_key=args.session_key,
        status=args.status,
        last_task_id=args.last_task_id,
        last_step_id=args.last_step_id,
        handoff_path=args.handoff_path,
        resume_prompt=args.resume_prompt,
        active_workflow=args.active_workflow,
        blocked_reason=args.blocked_reason,
    )
    print(json.dumps(record, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
