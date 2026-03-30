from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import automation_control
import context_rollover
import environment_bootstrap
import evidence_collector
import escalation_manager
import git_autocommit
import inbox_watcher
import parent_session_recovery
import resource_requirements
import runtime_environment
import run_orchestrator
import task_rounds
from common import utc_now, write_json, write_text
from openclaw_adapter import deliver_outbox


FAILURE_EXIT_STATUSES = {
    "failed",
    "escalated",
    "environment-blocked",
    "control-blocked",
    "paused-for-decision",
}
DECISION_REQUIRED_CODES = {"customer_decision_required", "approval_conflict", "approval_deadlock", "resource_input_required"}


def render_runtime_loop_markdown(summary: dict) -> str:
    cycle_lines = []
    for cycle in summary.get("cycles", []):
        cycle_lines.append(
            f"- cycle {cycle['cycle']}: dispatch={cycle['dispatch']['status']}, "
            f"sent={cycle['delivery']['sent_count']}, "
            f"processed={cycle['post_inbox']['processed_count'] + cycle['pre_inbox']['processed_count']}, "
            f"evidence={cycle['evidence']['status']}, "
            f"escalation={cycle['escalation']['status']}, "
            f"failures={cycle['delivery']['failed_count'] + cycle['post_inbox']['failed_count'] + cycle['pre_inbox']['failed_count']}"
        )
    body = "\n".join(cycle_lines) if cycle_lines else "- none"
    return f"""# Runtime Loop Summary

- started_at: {summary.get('started_at', '')}
- finished_at: {summary.get('finished_at', '')}
- status: {summary.get('status', '')}
- automation_mode: {summary.get('automation_mode', '')}
- cycle_count: {summary.get('cycle_count', 0)}
- total_dispatch_count: {summary.get('total_dispatch_count', 0)}
- total_sent_count: {summary.get('total_sent_count', 0)}
- total_processed_count: {summary.get('total_processed_count', 0)}
- total_failed_count: {summary.get('total_failed_count', 0)}

## Cycles

{body}
"""


def active_work_exists(project_root: Path) -> bool:
    state = automation_control.ensure_control_state(project_root)
    active_tasks = [task for task in state.get("active_tasks", []) if str(task.get("status", "")).lower() not in {"completed", "closed"}]
    pending_outbox = list((project_root / "ai" / "runtime" / "outbox").glob("*.json"))
    return bool(active_tasks or pending_outbox)


def decision_pause_details(escalation: dict) -> tuple[bool, str, str | None]:
    findings = escalation.get("findings", []) if isinstance(escalation, dict) else []
    matched = [item for item in findings if str(item.get("code") or "") in DECISION_REQUIRED_CODES]
    if not matched:
        return False, "", None
    reason = "; ".join(str(item.get("message") or "") for item in matched if item.get("message")) or "Customer decision required."
    return True, reason, str((matched[0] or {}).get("source") or "") or None


def run_loop(
    project_root: Path,
    max_cycles: int | None = 10,
    max_dispatch: int | None = 3,
    transport: str = "outbox",
    max_deliveries: int | None = None,
    max_completions: int | None = None,
    sleep_seconds: float = 0.0,
    collect_evidence: bool = True,
    activate: bool = False,
    actor: str = "user",
    activation_reason: str | None = None,
) -> dict:
    cycles: list[dict] = []
    status = "idle"
    started_at = utc_now()
    control = automation_control.ensure_control_state(project_root)
    autonomy = automation_control.autonomy_settings(project_root, control)
    resolved_max_cycles = max_cycles if max_cycles is not None else autonomy["max_cycles"]
    resolved_max_dispatch = max_dispatch if max_dispatch is not None else autonomy["max_dispatch"]
    failure_streak_limit = autonomy["failure_streak_limit"]
    idle_streak_limit = autonomy["idle_streak_limit"]
    auto_commit_enabled = autonomy["auto_commit_enabled"]
    auto_commit_push = autonomy["auto_commit_push"]
    stop_on_customer_decision = autonomy["stop_on_customer_decision"]
    recoverable_failure_streak = 0
    idle_streak = 0
    runtime_environment.ensure_runtime_environment(project_root)
    environment_summary = environment_bootstrap.ensure_environment(
        project_root,
        apply=True,
        include_system_tools=False,
    )
    if environment_summary.get("status") == "dependency-failed":
        summary = {
            "started_at": started_at,
            "finished_at": utc_now(),
            "status": "environment-blocked",
            "automation_mode": str(control.get("automation_mode", "normal")),
            "cycle_count": 0,
            "total_dispatch_count": 0,
            "total_attempted_dispatch_count": 0,
            "total_sent_count": 0,
            "total_processed_count": 0,
            "total_failed_count": 0,
            "environment": environment_summary,
            "evidence_statuses": [],
            "escalation_statuses": [],
            "cycles": [],
            "message": "Project dependency bootstrap failed. Fix environment-bootstrap blockers before entering the runtime loop.",
        }
        reports_dir = project_root / "ai" / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        write_json(reports_dir / "runtime-loop-summary.json", summary)
        write_text(reports_dir / "runtime-loop-summary.md", render_runtime_loop_markdown(summary))
        parent_session_recovery.write_recovery_artifacts(
            project_root, parent_session_recovery.build_parent_recovery(project_root)
        )
        return summary
    if activate and control.get("automation_mode") != "autonomous":
        control = automation_control.set_mode(
            project_root,
            "autonomous",
            actor=actor,
            reason=activation_reason or "Runtime loop activation requested.",
        )

    mode = str(control.get("automation_mode", "normal"))
    if mode != "autonomous":
        status = "paused" if mode == "paused" else "control-blocked"
        summary = {
            "started_at": started_at,
            "finished_at": utc_now(),
            "status": status,
            "automation_mode": mode,
            "cycle_count": 0,
            "total_dispatch_count": 0,
            "total_attempted_dispatch_count": 0,
            "total_sent_count": 0,
            "total_processed_count": 0,
            "total_failed_count": 0,
            "evidence_statuses": [],
            "escalation_statuses": [],
            "cycles": [],
            "environment": environment_summary,
            "message": "Autonomous runtime is not active. Switch to automation_mode=autonomous before entering the loop.",
        }
        reports_dir = project_root / "ai" / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        write_json(reports_dir / "runtime-loop-summary.json", summary)
        write_text(reports_dir / "runtime-loop-summary.md", render_runtime_loop_markdown(summary))
        parent_session_recovery.write_recovery_artifacts(
            project_root, parent_session_recovery.build_parent_recovery(project_root)
        )
        return summary

    budget = context_rollover.context_rollover_required(project_root)
    rollover_payload: dict | None = None
    if budget.get("should_rollover"):
        rollover_payload = context_rollover.create_rollover(
            project_root,
            reason=(budget.get("reasons") or ["Context budget threshold reached."])[0],
        )
        summary = {
            "started_at": started_at,
            "finished_at": utc_now(),
            "status": "context-rollover",
            "automation_mode": "autonomous",
            "cycle_count": 0,
            "total_dispatch_count": 0,
            "total_attempted_dispatch_count": 0,
            "total_sent_count": 0,
            "total_processed_count": 0,
            "total_failed_count": 0,
            "evidence_statuses": [],
            "escalation_statuses": [],
            "cycles": [],
            "environment": environment_summary,
            "context_budget": budget,
            "rollover_report": str((project_root / "ai" / "reports" / "orchestrator-rollover.md").resolve()),
            "message": rollover_payload.get("rollover_reason", "Context budget threshold reached."),
        }
        reports_dir = project_root / "ai" / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        write_json(reports_dir / "runtime-loop-summary.json", summary)
        write_text(reports_dir / "runtime-loop-summary.md", render_runtime_loop_markdown(summary))
        parent_session_recovery.write_recovery_artifacts(
            project_root, parent_session_recovery.build_parent_recovery(project_root)
        )
        return summary

    resource_gate = resource_requirements.evaluate_runtime_constraints(project_root)
    if resource_gate.get("status") != "ok":
        freeze = automation_control.freeze_for_decision(
            project_root,
            reason=resource_gate.get("message", "Resource input required before autonomous execution can continue."),
            actor="runtime_loop",
            resume_action="Provide the missing real-world dependency or close the resource retest debt, then resume autonomous execution.",
            decision_report_path=resource_gate.get("report_path"),
        )
        summary = {
            "started_at": started_at,
            "finished_at": utc_now(),
            "status": "paused-for-decision",
            "automation_mode": "paused",
            "cycle_count": 0,
            "total_dispatch_count": 0,
            "total_attempted_dispatch_count": 0,
            "total_sent_count": 0,
            "total_processed_count": 0,
            "total_failed_count": 0,
            "evidence_statuses": [],
            "escalation_statuses": [],
            "cycles": [],
            "environment": environment_summary,
            "resource_gate": resource_gate,
            "decision_freeze": freeze,
            "message": resource_gate.get("message", ""),
        }
        reports_dir = project_root / "ai" / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        write_json(reports_dir / "runtime-loop-summary.json", summary)
        write_text(reports_dir / "runtime-loop-summary.md", render_runtime_loop_markdown(summary))
        parent_session_recovery.write_recovery_artifacts(
            project_root, parent_session_recovery.build_parent_recovery(project_root)
        )
        return summary

    for cycle_index in range(1, resolved_max_cycles + 1):
        pre_inbox = inbox_watcher.process_inbox(project_root, max_items=max_completions)
        resource_gate = resource_requirements.evaluate_runtime_constraints(project_root)
        if resource_gate.get("status") != "ok":
            freeze = automation_control.freeze_for_decision(
                project_root,
                reason=resource_gate.get("message", "Resource input required before autonomous execution can continue."),
                actor="runtime_loop",
                resume_action="Provide the missing real-world dependency or close the resource retest debt, then resume autonomous execution.",
                decision_report_path=resource_gate.get("report_path"),
            )
            cycles.append(
                {
                    "cycle": cycle_index,
                    "pre_inbox": pre_inbox,
                    "dispatch": {"status": "skipped-resource-gate", "dispatch_count": 0, "local_completion_count": 0},
                    "delivery": {"sent_count": 0, "failed_count": 0, "pending_config_count": 0},
                    "post_inbox": {"processed_count": 0, "failed_count": 0, "guarded_count": 0},
                    "evidence": {"status": "skipped-resource-gate"},
                    "escalation": {"status": "resource-input-required"},
                    "auto_commit": {"status": "skipped-resource-gate"},
                    "completed_task_round": None,
                    "decision_freeze": freeze,
                    "resource_gate": resource_gate,
                }
            )
            status = "paused-for-decision"
            break
        dispatch = run_orchestrator.run(project_root, max_dispatch=resolved_max_dispatch, transport=transport)
        delivery = deliver_outbox(project_root, max_items=max_deliveries)
        post_inbox = inbox_watcher.process_inbox(project_root, max_items=max_completions)
        evidence = evidence_collector.collect_evidence(project_root) if collect_evidence else {"status": "skipped"}
        escalation = escalation_manager.generate_escalation(project_root)
        auto_commit = {"status": "skipped-no-round-completion"}

        cycle = {
            "cycle": cycle_index,
            "pre_inbox": pre_inbox,
            "dispatch": dispatch,
            "delivery": delivery,
            "post_inbox": post_inbox,
            "evidence": evidence,
            "escalation": escalation,
            "auto_commit": auto_commit,
            "completed_task_round": None,
        }
        cycles.append(cycle)

        progress_count = (
            pre_inbox["processed_count"]
            + pre_inbox.get("guarded_count", 0)
            + post_inbox["processed_count"]
            + post_inbox.get("guarded_count", 0)
            + delivery["sent_count"]
            + int(dispatch.get("dispatch_count", 0))
            + int(dispatch.get("local_completion_count", 0))
        )
        failure_count = (
            pre_inbox["failed_count"]
            + post_inbox["failed_count"]
            + delivery["failed_count"]
        )

        if failure_count:
            recoverable_failure_streak += 1
            cycle["recovery_state"] = {
                "failure_streak": recoverable_failure_streak,
                "failure_streak_limit": failure_streak_limit,
                "continued": recoverable_failure_streak < failure_streak_limit,
            }
            if recoverable_failure_streak >= failure_streak_limit:
                status = "failed"
                break
            if sleep_seconds:
                time.sleep(sleep_seconds)
            continue
        recoverable_failure_streak = 0
        should_pause, decision_reason, decision_report_path = decision_pause_details(escalation)
        resource_gate = resource_requirements.evaluate_runtime_constraints(project_root)
        if resource_gate.get("status") != "ok":
            freeze = automation_control.freeze_for_decision(
                project_root,
                reason=resource_gate.get("message", "Resource input required before autonomous execution can continue."),
                actor="runtime_loop",
                resume_action="Provide the missing real-world dependency or close the resource retest debt, then resume autonomous execution.",
                decision_report_path=resource_gate.get("report_path"),
            )
            cycle["decision_freeze"] = freeze
            cycle["resource_gate"] = resource_gate
            status = "paused-for-decision"
            break
        if escalation.get("status") == "escalated":
            if should_pause and stop_on_customer_decision:
                freeze = automation_control.freeze_for_decision(
                    project_root,
                    reason=decision_reason,
                    actor="runtime_loop",
                    resume_action="Review the available options, record the decision, then resume autonomous execution.",
                    decision_report_path=decision_report_path,
                )
                cycle["decision_freeze"] = freeze
                status = "paused-for-decision"
                break
            recoverable_failure_streak += 1
            cycle["recovery_state"] = {
                "failure_streak": recoverable_failure_streak,
                "failure_streak_limit": failure_streak_limit,
                "continued": recoverable_failure_streak < failure_streak_limit,
            }
            if recoverable_failure_streak >= failure_streak_limit:
                status = "escalated"
                break
            if sleep_seconds:
                time.sleep(sleep_seconds)
            continue
        budget = context_rollover.context_rollover_required(project_root)
        if budget.get("should_rollover"):
            rollover_payload = context_rollover.create_rollover(
                project_root,
                reason=(budget.get("reasons") or ["Context budget threshold reached."])[0],
            )
            status = "context-rollover"
            break
        completed_task_round = task_rounds.complete_round_if_ready(project_root)
        cycle["completed_task_round"] = completed_task_round
        if auto_commit_enabled and completed_task_round and completed_task_round.get("commit_eligible", True):
            auto_commit = git_autocommit.autocommit(
                project_root,
                cycle_index=cycle_index,
                push=auto_commit_push,
                scope_label=str(completed_task_round.get("round_id") or f"runtime-cycle-{cycle_index}"),
            )
            cycle["auto_commit"] = auto_commit
            if auto_commit.get("status") == "commit-failed" or auto_commit.get("push_status") == "push-failed":
                status = "failed"
                break
        if progress_count == 0:
            idle_streak += 1
            has_active_work = active_work_exists(project_root)
            cycle["idle_state"] = {
                "idle_streak": idle_streak,
                "idle_streak_limit": idle_streak_limit,
                "active_work_exists": has_active_work,
                "limit_reached": idle_streak >= idle_streak_limit,
            }
            if has_active_work:
                if idle_streak >= idle_streak_limit:
                    if delivery["pending_config_count"] or dispatch.get("status") == "pending-transport":
                        status = "waiting-transport"
                    else:
                        status = "idle-streak-limit-reached"
                    break
                if sleep_seconds:
                    time.sleep(sleep_seconds)
                continue
            if delivery["pending_config_count"] or dispatch.get("status") == "pending-transport":
                status = "waiting-transport"
            elif dispatch.get("status") == "idle":
                status = "idle"
            else:
                status = str(dispatch.get("status") or "idle")
            break
        idle_streak = 0
        status = "active"
        if sleep_seconds and cycle_index < resolved_max_cycles:
            time.sleep(sleep_seconds)
    else:
        status = "max-cycles-reached"

    summary = {
        "started_at": started_at,
        "finished_at": utc_now(),
        "status": status,
        "automation_mode": "autonomous",
        "cycle_count": len(cycles),
        "resolved_max_cycles": resolved_max_cycles,
        "resolved_max_dispatch": resolved_max_dispatch,
        "failure_streak_limit": failure_streak_limit,
        "idle_streak_limit": idle_streak_limit,
        "total_dispatch_count": sum(int(cycle["dispatch"].get("dispatch_count", 0)) for cycle in cycles),
        "total_attempted_dispatch_count": sum(int(cycle["dispatch"].get("attempted_dispatch_count", 0)) for cycle in cycles),
        "total_sent_count": sum(cycle["delivery"]["sent_count"] for cycle in cycles),
        "total_processed_count": sum(
            cycle["pre_inbox"]["processed_count"] + cycle["post_inbox"]["processed_count"] for cycle in cycles
        ),
        "total_failed_count": sum(
            cycle["pre_inbox"]["failed_count"] + cycle["post_inbox"]["failed_count"] + cycle["delivery"]["failed_count"]
            for cycle in cycles
        ),
        "completed_task_rounds": [cycle["completed_task_round"]["round_id"] for cycle in cycles if cycle.get("completed_task_round")],
        "auto_commit_statuses": [cycle["auto_commit"]["status"] for cycle in cycles if cycle.get("auto_commit")],
        "environment": environment_summary,
        "evidence_statuses": [cycle["evidence"]["status"] for cycle in cycles],
        "escalation_statuses": [cycle["escalation"]["status"] for cycle in cycles],
        "cycles": cycles,
    }
    if budget:
        summary["context_budget"] = budget
    if rollover_payload:
        summary["rollover_report"] = str((project_root / "ai" / "reports" / "orchestrator-rollover.md").resolve())
        summary["message"] = rollover_payload.get("rollover_reason", "Context budget threshold reached.")
    reports_dir = project_root / "ai" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    write_json(reports_dir / "runtime-loop-summary.json", summary)
    write_text(reports_dir / "runtime-loop-summary.md", render_runtime_loop_markdown(summary))
    recovery = parent_session_recovery.write_recovery_artifacts(
        project_root, parent_session_recovery.build_parent_recovery(project_root)
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the orchestrator runtime loop across dispatch, transport bridge, and inbox consumption.")
    parser.add_argument("project_root", help="Target project root")
    parser.add_argument("--max-cycles", type=int, help="Maximum loop cycles to execute before returning")
    parser.add_argument("--max-dispatch", type=int, help="Maximum ready workflow steps to dispatch per cycle")
    parser.add_argument("--transport", choices=["outbox", "command"], default="outbox", help="Transport mode used when dispatching new work")
    parser.add_argument("--max-deliveries", type=int, help="Maximum queued envelopes to deliver per cycle")
    parser.add_argument("--max-completions", type=int, help="Maximum inbox payloads to consume per cycle")
    parser.add_argument("--sleep-seconds", type=float, default=0.0, help="Optional sleep between cycles for long-running automation")
    parser.add_argument("--no-evidence", action="store_true", help="Skip automatic evidence collection during the loop")
    parser.add_argument("--activate", action="store_true", help="Switch automation mode to autonomous before entering the loop")
    parser.add_argument("--actor", default="user", help="Who started the loop when --activate is used")
    parser.add_argument("--activation-reason", help="Why the autonomous loop was activated")
    args = parser.parse_args()

    summary = run_loop(
        Path(args.project_root).resolve(),
        max_cycles=args.max_cycles,
        max_dispatch=args.max_dispatch,
        transport=args.transport,
        max_deliveries=args.max_deliveries,
        max_completions=args.max_completions,
        sleep_seconds=args.sleep_seconds,
        collect_evidence=not args.no_evidence,
        activate=args.activate,
        actor=args.actor,
        activation_reason=args.activation_reason,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if summary["total_failed_count"] or summary.get("status") in FAILURE_EXIT_STATUSES:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
