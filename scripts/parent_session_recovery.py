from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from common import read_json, utc_now, write_json, write_text
from runtime_environment import ensure_runtime_environment, resolve_parent_attach_command


def reattach_dir(project_root: Path) -> Path:
    path = project_root / "ai" / "runtime" / "reattach"
    path.mkdir(parents=True, exist_ok=True)
    return path


def recovery_report_path(project_root: Path) -> Path:
    return project_root / "ai" / "reports" / "parent-session-recovery.json"


def build_reattach_payload(project_root: Path, payload: dict) -> dict:
    session = payload.get("orchestrator_session", {})
    return {
        "project_root": str(project_root.resolve()),
        "agent_id": "orchestrator",
        "session_key": session.get("session_key", ""),
        "handoff_path": session.get("handoff_path", ""),
        "resume_prompt": payload.get("resume_prompt", ""),
        "escalation_status": payload.get("escalation_status", "clear"),
    }


def automatic_reattach_enabled() -> bool:
    value = os.environ.get("SILIJIAN_AUTO_REATTACH", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def reattach_payload_path(project_root: Path) -> Path:
    return reattach_dir(project_root) / "orchestrator-parent-reattach.json"


def persist_reattach_payload(project_root: Path, payload: dict) -> Path:
    path = reattach_payload_path(project_root)
    write_json(path, build_reattach_payload(project_root, payload))
    return path


def existing_attached_session(project_root: Path) -> str:
    previous = read_json(recovery_report_path(project_root))
    if previous.get("reattach_status") != "attached":
        return ""
    session = previous.get("orchestrator_session", {})
    if not isinstance(session, dict):
        return ""
    return str(session.get("session_key") or "")


def automatic_reattach_recommended(payload: dict) -> bool:
    session_key = str(payload.get("orchestrator_session", {}).get("session_key") or "")
    return bool(session_key) and str(payload.get("automation_mode", "normal")) in {"autonomous", "paused"}


def format_parent_attach_command(template: str, reattach_path: Path, reattach_payload: dict) -> tuple[str | None, str | None]:
    try:
        return (
            template.format(
                payload_file=str(reattach_path),
                session_key=reattach_payload.get("session_key", ""),
            ),
            None,
        )
    except KeyError as exc:
        return None, f"Parent-attach command template references an unknown placeholder: {exc}."
    except Exception as exc:
        return None, f"Parent-attach command template could not be formatted: {exc}"


def attempt_reattach(project_root: Path, payload: dict) -> dict:
    reattach_path = persist_reattach_payload(project_root, payload)
    reattach_payload = build_reattach_payload(project_root, payload)
    session_key = str(reattach_payload.get("session_key") or "")
    ensure_runtime_environment(project_root)
    template, command_source = resolve_parent_attach_command(project_root)
    result = {
        "status": "pending-command-config",
        "payload_path": str(reattach_path.resolve()),
        "command": "",
        "stdout": "",
        "stderr": "",
        "blocked_reason": "",
        "command_source": command_source,
    }
    if not session_key:
        result["status"] = "skipped-no-session"
        result["blocked_reason"] = "No orchestrator session key is available for parent reattach."
        return result
    if not template:
        result["blocked_reason"] = "No parent attach command is available after runtime environment setup."
        return result
    command, format_error = format_parent_attach_command(template, reattach_path, reattach_payload)
    if not command:
        result["status"] = "attach-failed"
        result["blocked_reason"] = format_error or "Parent-attach command template formatting failed."
        return result
    completed = subprocess.run(command, capture_output=True, text=True, shell=True, check=False)
    result["command"] = command
    result["stdout"] = completed.stdout.strip()
    result["stderr"] = completed.stderr.strip()
    result["status"] = "attached" if completed.returncode == 0 else "attach-failed"
    if completed.returncode != 0:
        result["blocked_reason"] = "OpenClaw parent attach command returned a non-zero exit code."
    return result


def resolve_reattach_status(project_root: Path, payload: dict, auto_reattach: bool, force_reattach: bool = False) -> dict:
    payload["reattach_auto_enabled"] = auto_reattach
    payload["reattach_payload_path"] = str(persist_reattach_payload(project_root, payload).resolve())

    session_key = str(payload.get("orchestrator_session", {}).get("session_key") or "")
    if not session_key:
        payload["reattach_status"] = "skipped-no-session"
        payload["reattach_blocked_reason"] = "No orchestrator session key is available for parent reattach."
        payload.pop("reattach_attempt", None)
        return payload

    if not auto_reattach and not force_reattach:
        payload["reattach_status"] = "auto-disabled"
        payload["reattach_blocked_reason"] = "Automatic parent-session reattach is disabled."
        payload.pop("reattach_attempt", None)
        return payload

    if not automatic_reattach_recommended(payload) and not force_reattach:
        payload["reattach_status"] = "not-required"
        payload["reattach_blocked_reason"] = "Automatic reattach only runs while the project is autonomous or paused."
        payload.pop("reattach_attempt", None)
        return payload

    if not force_reattach and existing_attached_session(project_root) == session_key:
        payload["reattach_status"] = "attached"
        payload["reattach_blocked_reason"] = None
        payload["reattach_attempt"] = {
            "status": "attached",
            "payload_path": payload["reattach_payload_path"],
            "command": "",
            "stdout": "",
            "stderr": "",
            "blocked_reason": "Skipped a duplicate attach attempt because this parent session is already attached to the same orchestrator session key.",
        }
        return payload

    attempt = attempt_reattach(project_root, payload)
    payload["reattach_attempt"] = attempt
    payload["reattach_status"] = attempt["status"]
    payload["reattach_blocked_reason"] = attempt.get("blocked_reason") or None
    return payload


def write_recovery_artifacts(
    project_root: Path,
    payload: dict,
    auto_reattach: bool | None = None,
    force_reattach: bool = False,
) -> dict:
    reports_dir = project_root / "ai" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    resolved = resolve_reattach_status(
        project_root,
        dict(payload),
        auto_reattach=automatic_reattach_enabled() if auto_reattach is None else auto_reattach,
        force_reattach=force_reattach,
    )
    write_json(recovery_report_path(project_root), resolved)
    write_text(reports_dir / "parent-session-recovery.md", render_parent_recovery_markdown(resolved))
    return resolved


def build_parent_recovery(project_root: Path) -> dict:
    state = read_json(project_root / "ai" / "state" / "orchestrator-state.json")
    sessions = read_json(project_root / "ai" / "state" / "agent-sessions.json")
    orchestrator_session = sessions.get("orchestrator", {})
    escalation = read_json(project_root / "ai" / "reports" / "escalation-report.json")
    rollover = read_json(project_root / "ai" / "reports" / "orchestrator-rollover.json")
    latest_loop = read_json(project_root / "ai" / "reports" / "runtime-loop-summary.json")

    next_prompt = f"""Resume as the parent controller for this governed project.

Current workflow: {state.get('current_workflow', 'unknown')}
Current status: {state.get('current_status', 'unknown')}
Automation mode: {state.get('automation_mode', 'normal')}
Next owner: {state.get('next_owner', 'orchestrator')}
Orchestrator session key: {orchestrator_session.get('session_key', '')}
Orchestrator last step: {orchestrator_session.get('last_step_id', '')}
Escalation status: {escalation.get('status', 'clear')}
Pause reason: {state.get('pause_reason', '')}

Before acting:
1. Read ai/state/START_HERE.md
2. Read docs/ANTI-DRIFT-RUNBOOK.md
3. Read ai/state/project-handoff.md
4. Read ai/state/orchestrator-state.json
5. Read ai/state/agent-sessions.json
6. Read ai/reports/runtime-loop-summary.json
7. Read ai/reports/escalation-report.md
8. If present, resume or re-create the orchestrator child session and continue the workflow.
"""
    payload = {
        "created_at": utc_now(),
        "project_root": str(project_root.resolve()),
        "current_workflow": state.get("current_workflow", ""),
        "current_status": state.get("current_status", ""),
        "automation_mode": state.get("automation_mode", "normal"),
        "next_owner": state.get("next_owner", "orchestrator"),
        "orchestrator_session": orchestrator_session,
        "escalation_status": escalation.get("status", "clear"),
        "escalation_items": escalation.get("items", []),
        "latest_loop_status": latest_loop.get("status", ""),
        "rollover_available": bool(rollover),
        "pause_reason": state.get("pause_reason"),
        "resume_prompt": next_prompt,
        "reattach_status": "not-attempted",
        "reattach_auto_enabled": automatic_reattach_enabled(),
        "reattach_blocked_reason": None,
    }
    return payload


def render_parent_recovery_markdown(payload: dict) -> str:
    escalation_items = "\n".join(f"- {item}" for item in payload.get("escalation_items", [])) or "- none"
    return f"""# Parent Session Recovery

- created_at: {payload.get('created_at', '')}
- current_workflow: {payload.get('current_workflow', '')}
- current_status: {payload.get('current_status', '')}
- automation_mode: {payload.get('automation_mode', 'normal')}
- next_owner: {payload.get('next_owner', '')}
- latest_loop_status: {payload.get('latest_loop_status', '')}
- rollover_available: {'yes' if payload.get('rollover_available') else 'no'}
- reattach_status: {payload.get('reattach_status', 'not-attempted')}
- reattach_auto_enabled: {'yes' if payload.get('reattach_auto_enabled') else 'no'}
- reattach_blocked_reason: {payload.get('reattach_blocked_reason') or 'none'}
- pause_reason: {payload.get('pause_reason') or 'none'}

## Orchestrator Session

- session_key: {payload.get('orchestrator_session', {}).get('session_key', '')}
- last_step_id: {payload.get('orchestrator_session', {}).get('last_step_id', '')}
- handoff_path: {payload.get('orchestrator_session', {}).get('handoff_path', '')}

## Escalation Items

{escalation_items}

## Resume Prompt

```text
{payload.get('resume_prompt', '').strip()}
```
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a parent-thread recovery prompt from project-local orchestrator state.")
    parser.add_argument("project_root", help="Target project root")
    parser.add_argument("--reattach", action="store_true", help="Attempt to reattach to the orchestrator child session using OPENCLAW_PARENT_ATTACH_COMMAND")
    parser.add_argument("--no-auto-reattach", action="store_true", help="Only write recovery artifacts and skip the default automatic reattach attempt")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    payload = build_parent_recovery(project_root)
    payload = write_recovery_artifacts(
        project_root,
        payload,
        auto_reattach=not args.no_auto_reattach,
        force_reattach=args.reattach,
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
