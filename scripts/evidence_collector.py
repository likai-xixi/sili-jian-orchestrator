from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

from common import read_json, read_text, utc_now, write_json, write_text
from provider_evidence import collect_provider_evidence
from repo_command_detector import command_summary


LATE_PHASES = {"testing", "department-review", "final-audit", "accepted", "committed", "archived"}


def run_command(project_root: Path, command: str) -> dict:
    if command == "github-actions-workflow-present":
        return {
            "command": command,
            "returncode": 0,
            "stdout": "github workflow present; external CI execution expected",
            "stderr": "",
            "status": "PASS_WITH_WARNING",
        }
    completed = subprocess.run(command, cwd=project_root, capture_output=True, text=True, shell=True, check=False)
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "status": "PASS" if completed.returncode == 0 else "FAIL",
    }


def parse_test_counts(output: str, status: str) -> tuple[int, int, int]:
    unittest_match = re.search(r"Ran\s+(\d+)\s+tests?", output)
    failed_match = re.search(r"failures=(\d+)", output)
    error_match = re.search(r"errors=(\d+)", output)
    skipped_match = re.search(r"skipped=(\d+)", output)
    pytest_match = re.search(r"(\d+)\s+passed", output)
    pytest_failed = re.search(r"(\d+)\s+failed", output)
    pytest_skipped = re.search(r"(\d+)\s+skipped", output)

    if unittest_match:
        total = int(unittest_match.group(1))
        failed = int(failed_match.group(1)) if failed_match else 0
        failed += int(error_match.group(1)) if error_match else 0
        skipped = int(skipped_match.group(1)) if skipped_match else 0
        passed = max(total - failed - skipped, 0)
        return passed, failed, skipped
    if pytest_match:
        passed = int(pytest_match.group(1))
        failed = int(pytest_failed.group(1)) if pytest_failed else 0
        skipped = int(pytest_skipped.group(1)) if pytest_skipped else 0
        return passed, failed, skipped
    if status == "FAIL":
        return (0, 1, 0)
    return (0, 0, 0)


def docs_handoff_status(project_root: Path) -> str:
    required = [
        project_root / "ai" / "state" / "START_HERE.md",
        project_root / "ai" / "state" / "project-handoff.md",
        project_root / "ai" / "state" / "orchestrator-state.json",
    ]
    return "PASS" if all(path.exists() for path in required) else "FAIL"


def gate_recommendation(
    test_status: str,
    build_status: str,
    lint_status: str,
    docs_status: str,
    ci_status: str,
    release_status: str,
    rollback_status: str,
) -> str:
    statuses = [test_status, build_status, lint_status, docs_status, ci_status, release_status, rollback_status]
    if any(status == "FAIL" for status in statuses):
        return "BLOCKER"
    if any(status == "SKIPPED" for status in statuses):
        return "PASS_WITH_WARNING"
    if any(status == "PASS_WITH_WARNING" for status in statuses):
        return "PASS_WITH_WARNING"
    return "PASS"


def command_status(result: dict | None) -> str:
    if not result:
        return "SKIPPED"
    return str(result.get("status") or "SKIPPED")


def prefer_provider_result(provider_result: dict | None, local_result: dict | None) -> dict | None:
    if provider_result and provider_result.get("status") not in {"", "SKIPPED"}:
        return provider_result
    return local_result


def collect_evidence(project_root: Path, force: bool = False) -> dict:
    state = read_json(project_root / "ai" / "state" / "orchestrator-state.json")
    current_status = str(state.get("current_status", "")).lower()
    current_phase = str(state.get("current_phase", "")).lower()
    should_collect = force or current_status in LATE_PHASES or current_phase in LATE_PHASES
    detection = command_summary(project_root)
    reports_dir = project_root / "ai" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    if not should_collect:
        summary = {
            "collected_at": utc_now(),
            "status": "skipped",
            "reason": "current workflow stage does not require evidence collection yet",
            "commands": detection["commands"],
        }
        write_json(reports_dir / "evidence-summary.json", summary)
        return summary

    provider_summary = collect_provider_evidence(project_root)
    provider_results = provider_summary.get("results", {})
    lint_result = run_command(project_root, detection["commands"]["lint"]) if detection["commands"]["lint"] else None
    build_result = run_command(project_root, detection["commands"]["build"]) if detection["commands"]["build"] else None
    test_result = run_command(project_root, detection["commands"]["test"]) if detection["commands"]["test"] else None
    ci_result = run_command(project_root, detection["commands"]["ci"]) if detection["commands"]["ci"] else None
    release_result = None
    rollback_result = None
    if detection["commands"]["release"] and os.environ.get("SILIJIAN_RUN_RELEASE_VERIFICATION") == "1":
        release_result = run_command(project_root, detection["commands"]["release"])
    if detection["commands"]["rollback"] and os.environ.get("SILIJIAN_RUN_ROLLBACK_VERIFICATION") == "1":
        rollback_result = run_command(project_root, detection["commands"]["rollback"])

    ci_result = prefer_provider_result(provider_results.get("ci"), ci_result)
    release_result = prefer_provider_result(provider_results.get("release"), release_result)
    rollback_result = prefer_provider_result(provider_results.get("rollback"), rollback_result)

    lint_status = command_status(lint_result)
    build_status = command_status(build_result)
    test_status = command_status(test_result)
    ci_status = command_status(ci_result)
    release_status = command_status(release_result)
    rollback_status = command_status(rollback_result)
    docs_status = docs_handoff_status(project_root)

    passed, failed, skipped = parse_test_counts(
        "\n".join(filter(None, [test_result["stdout"] if test_result else "", test_result["stderr"] if test_result else ""])),
        test_status,
    )
    blocker_lines = []
    if test_status == "FAIL":
        blocker_lines.append("test command failed")
    if build_status == "FAIL":
        blocker_lines.append("build command failed")
    if lint_status == "FAIL":
        blocker_lines.append("lint command failed")
    if ci_status == "FAIL":
        blocker_lines.append("ci command failed")
    if release_status == "FAIL":
        blocker_lines.append("release verification failed")
    if rollback_status == "FAIL":
        blocker_lines.append("rollback verification failed")
    if docs_status == "FAIL":
        blocker_lines.append("docs or handoff state missing")

    recommendation = gate_recommendation(
        test_status,
        build_status,
        lint_status,
        docs_status,
        ci_status,
        release_status,
        rollback_status,
    )
    mainline_result = "YES" if test_status == "PASS" else "NO"
    release_recommendation = "YES" if recommendation in {"PASS", "PASS_WITH_WARNING"} and mainline_result == "YES" else "NO"

    test_report = f"""# Test Report

## Round

- {state.get('current_workflow', 'unknown')}:{current_status or current_phase or 'pending'}

## Test Target

- {project_root.name}

## Scope

- workflow: {state.get('current_workflow', 'unknown')}

## Coverage

- unit: {test_status}
- integration: {'SKIPPED' if not test_result else test_status}
- e2e: SKIPPED
- regression: {test_status}
- contract: SKIPPED
- build verification: {build_status}
- ci verification: {ci_status}
- release verification: {release_status}
- rollback verification: {rollback_status}
- ci evidence source: {ci_result.get('source', 'command') if ci_result else 'none'}
- release evidence source: {release_result.get('source', 'command') if release_result else 'none'}
- rollback evidence source: {rollback_result.get('source', 'command') if rollback_result else 'none'}

## Counts

- passed: {passed}
- failed: {failed}
- skipped: {skipped}

## Mainline Result

- {mainline_result}

## Blockers

- {', '.join(blocker_lines) if blocker_lines else 'none'}

## Warnings

- {'manual follow-up recommended for skipped checks' if 'SKIPPED' in {lint_status, build_status, test_status} else 'none'}

## Recommendation

- {recommendation}

## Release Recommendation

- {release_recommendation}

## Updated At

- {utc_now()}
"""
    write_text(reports_dir / "test-report.md", test_report)

    matrix_text = read_text(reports_dir / "department-approval-matrix.md")
    acceptance_text = read_text(reports_dir / "acceptance-report.md")
    change_text = read_text(reports_dir / "change-summary.md")
    gate_report = f"""# Gate Report

## Basic Gates

- lint: {lint_status}
- build: {build_status}
- unit test: {test_status}
- integration test: {'SKIPPED' if not test_result else test_status}
- ci check: {ci_status}
- release verification: {release_status}
- rollback verification: {rollback_status}
- docs and handoff check: {docs_status}
- provider ci source: {ci_result.get('source', 'none') if ci_result else 'none'}
- provider release source: {release_result.get('source', 'none') if release_result else 'none'}
- provider rollback source: {rollback_result.get('source', 'none') if rollback_result else 'none'}

## Final Gates

- approval matrix complete: {'YES' if bool(matrix_text) else 'NO'}
- acceptance report present: {'YES' if bool(acceptance_text) else 'NO'}
- change summary present: {'YES' if bool(change_text) else 'NO'}
- blocker count zero: {'YES' if not blocker_lines else 'NO'}
- mainline regression passed: {mainline_result}
- rollback point available: {'YES' if rollback_status in {'PASS', 'PASS_WITH_WARNING'} or not state.get('release_allowed') else 'NO'}

## Recommendation

- {recommendation}
"""
    write_text(reports_dir / "gate-report.md", gate_report)

    summary = {
        "collected_at": utc_now(),
        "status": "collected",
        "commands": detection["commands"],
        "lint": lint_result or {"status": "SKIPPED"},
        "build": build_result or {"status": "SKIPPED"},
        "test": test_result or {"status": "SKIPPED", "passed": passed, "failed": failed, "skipped": skipped},
        "ci": ci_result or {"status": "SKIPPED"},
        "release": release_result or {"status": "SKIPPED"},
        "rollback": rollback_result or {"status": "SKIPPED"},
        "provider_evidence": provider_summary,
        "docs_handoff": {"status": docs_status},
        "recommendation": recommendation,
        "release_recommendation": release_recommendation,
        "mainline_result": mainline_result,
        "blockers": blocker_lines,
        "report_paths": {
            "test_report": str((reports_dir / "test-report.md").resolve()),
            "gate_report": str((reports_dir / "gate-report.md").resolve()),
        },
    }
    write_json(reports_dir / "evidence-summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect test/build/gate evidence for governed delivery.")
    parser.add_argument("project_root", help="Target project root")
    parser.add_argument("--force", action="store_true", help="Collect evidence even when the project is not yet in a late workflow phase")
    args = parser.parse_args()

    summary = collect_evidence(Path(args.project_root).resolve(), force=args.force)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if summary.get("status") == "collected" and summary.get("recommendation") == "BLOCKER":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
