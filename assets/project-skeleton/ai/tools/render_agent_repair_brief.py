from __future__ import annotations

import json
import sys
from pathlib import Path

from common import write_text
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
    return findings


def build_copy_prompt(project_root: Path, findings: list[str]) -> str:
    findings_block = "\n".join(f"- {item}" for item in findings) if findings else "- none"
    return f"""使用 $sili-jian-orchestrator 处理当前项目的治理问题，不要直接开始新功能开发。

目标项目根目录：
{project_root.as_posix()}

已检测到的问题如下：
{findings_block}

要求：
1. 先基于问题输出修复方案
2. 再执行必要修复
3. 修复后重新执行状态检查与门禁检查
4. 若修复通过，再整理变更摘要并提交
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
