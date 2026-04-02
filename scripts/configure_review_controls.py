from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import read_json, require_valid_json, utc_now, write_json
from orchestrator_local_steps import review_controls_path, sync_review_controls, sync_state_views, state_path


def configure(
    project_root: Path,
    before_cabinet: int | None = None,
    after_cabinet: int | None = None,
    pass1_agent: str | None = None,
    pass2_agent: str | None = None,
) -> dict:
    orchestrator_state_path = state_path(project_root)
    state = require_valid_json(orchestrator_state_path, "ai/state/orchestrator-state.json") if orchestrator_state_path.exists() else {}
    sync_review_controls(project_root, state)

    payload = read_json(review_controls_path(project_root))
    payload["review_cycle_limit_before_cabinet"] = (
        int(before_cabinet) if before_cabinet is not None else int(payload.get("review_cycle_limit_before_cabinet", 4))
    )
    payload["review_cycle_limit_after_cabinet"] = (
        int(after_cabinet) if after_cabinet is not None else int(payload.get("review_cycle_limit_after_cabinet", 2))
    )
    payload["review_pass_1_agent_id"] = str(pass1_agent or payload.get("review_pass_1_agent_id") or "duchayuan-pass1").strip() or "duchayuan-pass1"
    payload["review_pass_2_agent_id"] = str(pass2_agent or payload.get("review_pass_2_agent_id") or "duchayuan-pass2").strip() or "duchayuan-pass2"
    payload["updated_at"] = utc_now()
    write_json(review_controls_path(project_root), payload)

    sync_review_controls(project_root, state)
    write_json(orchestrator_state_path, state)
    sync_state_views(project_root, state)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure review cycle limits for governed cross-review loops.")
    parser.add_argument("project_root", help="Target project root")
    parser.add_argument("--before-cabinet", type=int, help="Review limit before cabinet replan")
    parser.add_argument("--after-cabinet", type=int, help="Review limit after cabinet replan")
    parser.add_argument("--pass1-agent", help="Agent id used for duchayuan pass1 review")
    parser.add_argument("--pass2-agent", help="Agent id used for duchayuan pass2 review")
    args = parser.parse_args()

    payload = configure(
        Path(args.project_root).resolve(),
        args.before_cabinet,
        args.after_cabinet,
        pass1_agent=args.pass1_agent,
        pass2_agent=args.pass2_agent,
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
