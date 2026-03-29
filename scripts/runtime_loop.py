from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import automation_control
import environment_bootstrap
import evidence_collector
import escalation_manager
import inbox_watcher
import parent_session_recovery
import runtime_environment
import run_orchestrator
from common import utc_now, write_json, write_text
from openclaw_adapter import deliver_outbox


FAILURE_EXIT_STATUSES = {"failed", "escalated", "environment-blocked", "control-blocked"}


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


def run_loop(
    project_root: Path,
    max_cycles: int = 10,
    max_dispatch: int = 3,
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

    for cycle_index in range(1, max_cycles + 1):
        pre_inbox = inbox_watcher.process_inbox(project_root, max_items=max_completions)
        dispatch = run_orchestrator.run(project_root, max_dispatch=max_dispatch, transport=transport)
        delivery = deliver_outbox(project_root, max_items=max_deliveries)
        post_inbox = inbox_watcher.process_inbox(project_root, max_items=max_completions)
        evidence = evidence_collector.collect_evidence(project_root) if collect_evidence else {"status": "skipped"}
        escalation = escalation_manager.generate_escalation(project_root)

        cycle = {
            "cycle": cycle_index,
            "pre_inbox": pre_inbox,
            "dispatch": dispatch,
            "delivery": delivery,
            "post_inbox": post_inbox,
            "evidence": evidence,
            "escalation": escalation,
        }
        cycles.append(cycle)

        progress_count = (
            pre_inbox["processed_count"]
            + post_inbox["processed_count"]
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
            status = "failed"
            break
        if escalation.get("status") == "escalated":
            status = "escalated"
            break
        if progress_count == 0:
            if delivery["pending_config_count"] or dispatch.get("status") == "pending-transport":
                status = "waiting-transport"
            elif dispatch.get("status") == "idle":
                status = "idle"
            else:
                status = str(dispatch.get("status") or "idle")
            break
        status = "active"
        if sleep_seconds and cycle_index < max_cycles:
            time.sleep(sleep_seconds)
    else:
        status = "max-cycles-reached"

    summary = {
        "started_at": started_at,
        "finished_at": utc_now(),
        "status": status,
        "automation_mode": "autonomous",
        "cycle_count": len(cycles),
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
        "environment": environment_summary,
        "evidence_statuses": [cycle["evidence"]["status"] for cycle in cycles],
        "escalation_statuses": [cycle["escalation"]["status"] for cycle in cycles],
        "cycles": cycles,
    }
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
    parser.add_argument("--max-cycles", type=int, default=10, help="Maximum loop cycles to execute before returning")
    parser.add_argument("--max-dispatch", type=int, default=3, help="Maximum ready workflow steps to dispatch per cycle")
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
