from __future__ import annotations

import json
import sys
from pathlib import Path

from common import write_text
from render_agent_repair_brief import build_findings, render_markdown as render_repair_markdown
from validate_gates import render_markdown as render_gates_markdown
from validate_gates import validate as validate_gates
from validate_state import render_markdown as render_state_markdown
from validate_state import validate as validate_state


def main() -> None:
    project_root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd().resolve()
    reports_dir = project_root / "ai" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    state_report = validate_state(project_root)
    gate_report = validate_gates(project_root)

    write_text(reports_dir / "state-validation.md", render_state_markdown(state_report))
    write_text(reports_dir / "gate-validation.md", render_gates_markdown(gate_report))
    write_text(
        reports_dir / "agent-repair-brief.md",
        render_repair_markdown(project_root, state_report, gate_report, build_findings(state_report, gate_report)),
    )
    write_text(
        reports_dir / "project-guard-summary.json",
        json.dumps({"state": state_report, "gates": gate_report}, indent=2, ensure_ascii=False),
    )

    print("[Project Guard] state_consistent =", state_report.get("state_consistent"))
    print("[Project Guard] phase_gate_passed =", gate_report.get("phase_gate_passed"))
    print("[Project Guard] final_gate_passed =", gate_report.get("final_gate_passed"))
    print("[Project Guard] agent_repair_brief = ai/reports/agent-repair-brief.md")

    if not state_report.get("state_consistent"):
        raise SystemExit(1)
    if not gate_report.get("phase_gate_passed"):
        raise SystemExit(1)
    if gate_report.get("release_stage") and not gate_report.get("final_gate_passed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
