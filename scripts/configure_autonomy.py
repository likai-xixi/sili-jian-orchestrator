from __future__ import annotations

import argparse
import json
from pathlib import Path

import automation_control
from common import utc_now, write_json


def configure(
    project_root: Path,
    *,
    max_cycles: int | None = None,
    max_dispatch: int | None = None,
    failure_streak_limit: int | None = None,
    idle_streak_limit: int | None = None,
    auto_commit: bool | None = None,
    auto_commit_push: bool | None = None,
    stop_on_customer_decision: bool | None = None,
    agent_id: str | None = None,
    completion_limit: int | None = None,
    dispatch_limit: int | None = None,
    task_round_limit: int | None = None,
) -> dict:
    state = automation_control.ensure_control_state(project_root)
    if max_cycles is not None:
        state["autonomous_runtime_max_cycles"] = max(1, int(max_cycles))
    if max_dispatch is not None:
        state["autonomous_max_dispatch"] = max(1, int(max_dispatch))
    if failure_streak_limit is not None:
        state["autonomous_failure_streak_limit"] = max(1, int(failure_streak_limit))
    if idle_streak_limit is not None:
        state["autonomous_idle_streak_limit"] = max(1, int(idle_streak_limit))
    if auto_commit is not None:
        state["autonomous_auto_commit_enabled"] = bool(auto_commit)
    if auto_commit_push is not None:
        state["autonomous_auto_commit_push"] = bool(auto_commit_push)
    if stop_on_customer_decision is not None:
        state["autonomous_stop_on_customer_decision"] = bool(stop_on_customer_decision)

    rotation = state.get("session_rotation_policy")
    if not isinstance(rotation, dict):
        rotation = {}
    default_rotation = rotation.get("default")
    if not isinstance(default_rotation, dict):
        default_rotation = {}
    agent_rotation = rotation.get("agents")
    if not isinstance(agent_rotation, dict):
        agent_rotation = {}

    target = default_rotation
    if agent_id:
        target = agent_rotation.setdefault(str(agent_id), dict(default_rotation))
    if completion_limit is not None:
        target["max_completion_count"] = max(1, int(completion_limit))
    if dispatch_limit is not None:
        target["max_dispatch_count"] = max(1, int(dispatch_limit))
    if task_round_limit is not None:
        target["max_task_round_count"] = max(1, int(task_round_limit))

    rotation["default"] = default_rotation
    rotation["agents"] = agent_rotation
    state["session_rotation_policy"] = rotation
    state["automation_last_changed_at"] = utc_now()
    state["automation_last_changed_by"] = "configure_autonomy.py"
    state["automation_last_reason"] = "Autonomy settings updated."
    write_json(automation_control.state_path(project_root), state)
    automation_control.update_control_markdown(project_root, state)
    return automation_control.autonomy_settings(project_root, state)


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure unattended autonomy defaults and per-agent session rotation.")
    parser.add_argument("project_root", help="Target project root")
    parser.add_argument("--max-cycles", type=int, help="Default runtime loop cycles when entering autonomous mode")
    parser.add_argument("--max-dispatch", type=int, help="Default maximum ready steps to dispatch per cycle")
    parser.add_argument("--failure-streak-limit", type=int, help="Recoverable failure cycles before the loop stops")
    parser.add_argument("--idle-streak-limit", type=int, help="Idle cycles to tolerate while waiting for progress")
    parser.add_argument("--auto-commit", dest="auto_commit", action="store_true", help="Commit after successful cycles")
    parser.add_argument("--no-auto-commit", dest="auto_commit", action="store_false", help="Disable automatic commits")
    parser.add_argument("--auto-commit-push", dest="auto_commit_push", action="store_true", help="Push after each automatic commit")
    parser.add_argument("--no-auto-commit-push", dest="auto_commit_push", action="store_false", help="Do not push automatic commits")
    parser.add_argument("--stop-on-customer-decision", dest="stop_on_customer_decision", action="store_true", help="Freeze automation when a customer decision is required")
    parser.add_argument("--no-stop-on-customer-decision", dest="stop_on_customer_decision", action="store_false", help="Do not auto-freeze on customer decisions")
    parser.add_argument("--agent-id", help="Optional agent id for a session rotation override")
    parser.add_argument("--completion-limit", type=int, help="Session completion count limit for the default or chosen agent")
    parser.add_argument("--dispatch-limit", type=int, help="Session dispatch count limit for the default or chosen agent")
    parser.add_argument("--task-round-limit", type=int, help="Completed task-round limit for the default or chosen agent")
    parser.set_defaults(auto_commit=None, auto_commit_push=None, stop_on_customer_decision=None)
    args = parser.parse_args()

    payload = configure(
        Path(args.project_root).resolve(),
        max_cycles=args.max_cycles,
        max_dispatch=args.max_dispatch,
        failure_streak_limit=args.failure_streak_limit,
        idle_streak_limit=args.idle_streak_limit,
        auto_commit=args.auto_commit,
        auto_commit_push=args.auto_commit_push,
        stop_on_customer_decision=args.stop_on_customer_decision,
        agent_id=args.agent_id,
        completion_limit=args.completion_limit,
        dispatch_limit=args.dispatch_limit,
        task_round_limit=args.task_round_limit,
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
