from __future__ import annotations

import json
import sys
from pathlib import Path

from common import PASS_CONCLUSIONS, write_text
from validate_gates import validate as validate_gates
from validate_state import validate as validate_state


def build_findings(state_report: dict, gate_report: dict) -> list[str]:
    findings: list[str] = []
    for item in state_report.get("findings", []):
        findings.append(f"[state/{item.get('severity', 'note')}] {item.get('code')}: {item.get('message')}")
    for key in ["blocker_sources", "placeholder_sources"]:
        for value in gate_report.get(key, []):
            findings.append(f"[gates/warning] {key}: {value}")
    if not gate_report.get("phase_gate_passed", False):
        findings.append("[gates/error] phase_gate_passed: current project is not ready to continue to the next stage.")
    if gate_report.get("release_stage") and not gate_report.get("final_gate_passed", False):
        for key, label in [
            ("handoff_present", "project handoff"),
            ("test_report_present", "test report"),
            ("approval_matrix_present", "department approval matrix"),
            ("acceptance_report_present", "acceptance report"),
            ("change_summary_present", "change summary"),
            ("gate_report_present", "gate report"),
        ]:
            if not gate_report.get(key, False):
                findings.append(f"[gates/error] final_gate_missing: missing required artifact `{label}`.")
        if not gate_report.get("matrix_complete", False):
            findings.append("[gates/error] final_gate_matrix_complete: department approval matrix is incomplete.")
        if gate_report.get("test_conclusion") not in PASS_CONCLUSIONS:
            findings.append(
                f"[gates/error] final_gate_test_conclusion: unexpected test conclusion `{gate_report.get('test_conclusion', '') or 'missing'}`."
            )
        if gate_report.get("matrix_recommendation") not in PASS_CONCLUSIONS:
            findings.append(
                "[gates/error] final_gate_matrix_recommendation: "
                f"unexpected matrix recommendation `{gate_report.get('matrix_recommendation', '') or 'missing'}`."
            )
        if gate_report.get("acceptance_conclusion") not in {"PASS", "PASS_WITH_WARNING"}:
            findings.append(
                "[gates/error] final_gate_acceptance_conclusion: "
                f"unexpected acceptance conclusion `{gate_report.get('acceptance_conclusion', '') or 'missing'}`."
            )
        if gate_report.get("gate_recommendation") not in {"PASS", "PASS_WITH_WARNING"}:
            findings.append(
                "[gates/error] final_gate_gate_recommendation: "
                f"unexpected gate recommendation `{gate_report.get('gate_recommendation', '') or 'missing'}`."
            )
        if gate_report.get("mainline_regression") != "YES":
            findings.append(
                "[gates/error] final_gate_mainline_regression: "
                f"mainline regression passed is `{gate_report.get('mainline_regression', '') or 'missing'}`."
            )
        if gate_report.get("release_allowed") and gate_report.get("rollback_point_available") != "YES":
            findings.append(
                "[gates/error] final_gate_rollback_point: "
                f"rollback point available is `{gate_report.get('rollback_point_available', '') or 'missing'}`."
            )
    return findings


def build_copy_prompt(project_root: Path, findings: list[str]) -> str:
    findings_block = "\n".join(f"- {item}" for item in findings) if findings else "- none"
    return f"""使用 $sili-jian-orchestrator 处理当前项目的治理问题，不要直接开始新功能开发。

目标项目根目录：
{project_root.as_posix()}

已检测到的问题如下：
{findings_block}

要求：
1. 先基于问题输出修复方案。
2. 再执行必要修复。
3. 修复后重新执行状态检查与门禁检查。
4. 如果修复通过，再整理变更摘要并提交。
5. 输出：
   - 修复方案
   - 实际修复清单
   - 修复后的检查结果
   - 是否建议提交"""


def render_markdown(project_root: Path, state_report: dict, gate_report: dict, findings: list[str]) -> str:
    lines = [
        "# Agent Repair Brief",
        "",
        "## Summary",
        "",
        f"- project_root: {project_root.as_posix()}",
        f"- state_consistent: {'yes' if state_report.get('state_consistent') else 'no'}",
        f"- phase_gate_passed: {'yes' if gate_report.get('phase_gate_passed') else 'no'}",
        f"- final_gate_passed: {'yes' if gate_report.get('final_gate_passed') else 'no'}",
        "",
        "## Findings",
        "",
    ]
    if findings:
        lines.extend(f"- {item}" for item in findings)
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Suggested Next Action",
            "",
            "- Run governance repair first, then re-run state and gate validation before any new implementation.",
            "",
            "## Copy Prompt",
            "",
            "```text",
            build_copy_prompt(project_root, findings),
            "```",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    project_root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd().resolve()
    reports_dir = project_root / "ai" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    state_report = validate_state(project_root)
    gate_report = validate_gates(project_root)
    findings = build_findings(state_report, gate_report)
    markdown = render_markdown(project_root, state_report, gate_report, findings)

    write_text(reports_dir / "agent-repair-brief.md", markdown)
    write_text(
        reports_dir / "agent-repair-brief.json",
        json.dumps(
            {
                "project_root": project_root.as_posix(),
                "state": state_report,
                "gates": gate_report,
                "findings": findings,
                "copy_prompt": build_copy_prompt(project_root, findings),
            },
            indent=2,
            ensure_ascii=False,
        ),
    )

    print(markdown)


if __name__ == "__main__":
    main()
