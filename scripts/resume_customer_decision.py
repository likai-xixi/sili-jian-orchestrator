from __future__ import annotations

import argparse
import json
from pathlib import Path

from automation_control import set_mode
from common import read_json, utc_now, write_json, write_text
from orchestrator_local_steps import (
    FEATURE_DELIVERY_REPLAN_RESET_STEPS,
    reset_workflow_steps,
    reports_dir,
    state_path,
    sync_review_controls,
    sync_state_views,
)


VALID_DECISIONS = {
    "scope-reduction",
    "reconfirm-requirement-and-acceptance",
    "pause-batch",
    "terminate-batch",
}


def apply_customer_decision(project_root: Path, decision: str, summary: str = "") -> dict:
    normalized = decision.strip().lower()
    if normalized not in VALID_DECISIONS:
        raise ValueError(f"Unsupported customer decision: {decision}")

    state = read_json(state_path(project_root))
    sync_review_controls(project_root, state)

    payload = {
        "decision": normalized,
        "summary": summary.strip() or "Customer decision recorded.",
        "created_at": utc_now(),
    }

    if normalized in {"scope-reduction", "reconfirm-requirement-and-acceptance"}:
        reset_workflow_steps(state, FEATURE_DELIVERY_REPLAN_RESET_STEPS)
        state["current_phase"] = "planning"
        state["current_status"] = "rework" if normalized == "scope-reduction" else "planning"
        state["execution_allowed"] = False
        state["testing_allowed"] = False
        state["release_allowed"] = False
        state["next_owner"] = "neige"
        state["next_action"] = (
            "Replan around the customer decision, update architecture plus task tree, then route the revised plan for approval."
        )
        state["blockers"] = []
        state["blocker_level"] = "none"
        state["review_phase"] = "normal-review"
        state["review_escalation_level"] = "none"
        state["review_cycle_count_before_cabinet"] = 0
        state["review_cycle_count_after_cabinet"] = 0
        state["review_last_blockers"] = []
        state["review_last_blocker_categories"] = []
        state["review_last_recommendation"] = "pending"
        state["cabinet_replan_triggered"] = False
    elif normalized == "pause-batch":
        set_mode(project_root, "paused", actor="customer-decision", reason=summary or "Customer requested to pause the batch.")
        state = read_json(state_path(project_root))
        state["current_phase"] = "customer-decision"
        state["current_status"] = "paused"
        state["next_owner"] = "orchestrator"
        state["next_action"] = "Batch paused after customer decision. Resume only when a new direction is approved."
    else:
        state["current_phase"] = "closed"
        state["current_status"] = "batch-terminated"
        state["execution_allowed"] = False
        state["testing_allowed"] = False
        state["release_allowed"] = False
        state["next_owner"] = "orchestrator"
        state["next_action"] = "Current batch terminated after customer decision. Start a new governed batch only if a new direction is approved."
        state["blockers"] = []
        state["blocker_level"] = "none"

    write_json(state_path(project_root), state)
    sync_state_views(project_root, state)

    report = {
        "created_at": payload["created_at"],
        "decision": payload["decision"],
        "summary": payload["summary"],
        "current_phase": state.get("current_phase", ""),
        "current_status": state.get("current_status", ""),
        "next_owner": state.get("next_owner", ""),
        "next_action": state.get("next_action", ""),
    }
    write_json(reports_dir(project_root) / "customer-decision-resolution.json", report)
    write_text(
        reports_dir(project_root) / "customer-decision-resolution.md",
        "\n".join(
            [
                "# Customer Decision Resolution",
                "",
                f"- created_at: {report['created_at']}",
                f"- decision: {report['decision']}",
                f"- summary: {report['summary']}",
                f"- current_phase: {report['current_phase']}",
                f"- current_status: {report['current_status']}",
                f"- next_owner: {report['next_owner']}",
                f"- next_action: {report['next_action']}",
            ]
        ),
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Resume or close a batch after customer decision is received.")
    parser.add_argument("project_root", help="Target project root")
    parser.add_argument(
        "--decision",
        required=True,
        choices=sorted(VALID_DECISIONS),
        help="Customer decision for the blocked batch",
    )
    parser.add_argument("--summary", default="", help="Short summary of the customer decision")
    args = parser.parse_args()

    payload = apply_customer_decision(Path(args.project_root).resolve(), args.decision, args.summary)
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
