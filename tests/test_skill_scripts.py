import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import repair_state  # noqa: E402
import automation_control  # noqa: E402
import bootstrap_governance  # noqa: E402
import change_request_control  # noqa: E402
import close_session  # noqa: E402
import completion_consumer  # noqa: E402
import common  # noqa: E402
import configure_review_controls  # noqa: E402
import configure_autonomy  # noqa: E402
import context_rollover  # noqa: E402
import environment_bootstrap  # noqa: E402
import escalation_manager  # noqa: E402
import evidence_collector  # noqa: E402
import first_run_check  # noqa: E402
import git_autocommit  # noqa: E402
import host_interface_probe  # noqa: E402
import inbox_watcher  # noqa: E402
import natural_language_control  # noqa: E402
import openclaw_adapter  # noqa: E402
import openclaw_runtime_bridge  # noqa: E402
import orchestrator_local_steps  # noqa: E402
import parent_session_recovery  # noqa: E402
import project_intake  # noqa: E402
import provider_evidence  # noqa: E402
import resource_requirements  # noqa: E402
import replan_change_request  # noqa: E402
import render_agent_repair_brief  # noqa: E402
import repo_command_detector  # noqa: E402
import resume_customer_decision  # noqa: E402
import run_orchestrator  # noqa: E402
import runtime_environment  # noqa: E402
import runtime_guardrails  # noqa: E402
import runtime_loop  # noqa: E402
import session_registry  # noqa: E402
import sync_project_tools  # noqa: E402
import task_rounds  # noqa: E402
import validate_gates  # noqa: E402
import validate_state  # noqa: E402
import workflow_engine  # noqa: E402
from common import ensure_handoff_stub, inspect_project, scenario_from_intent  # noqa: E402


def write_transport_helper(script_path: Path) -> None:
    script_path.write_text(
        """import json
import sys
from pathlib import Path


def extract_field(task_text: str, field_name: str) -> str:
    prefix = f"- {field_name}:"
    for raw_line in task_text.splitlines():
        line = raw_line.strip()
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return ""


def parse_required_skills(value: str) -> list[str]:
    text = value.strip()
    if not text or text.lower() == "none":
        return []
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return [item.strip().strip("'\\\"") for item in text.split(",") if item.strip()]


dispatch_path = Path(sys.argv[1]).resolve()
envelope = json.loads(dispatch_path.read_text(encoding="utf-8"))
project_root = dispatch_path.parents[3]
payload = envelope.get("payload", {})
task_text = payload.get("task") or payload.get("message") or ""
skill_policy = (extract_field(task_text, "skill_policy") or "optional").strip().lower()
required_skills = parse_required_skills(extract_field(task_text, "required_skills"))
if skill_policy == "required":
    execution_mode = "skill"
    skills_used = required_skills or ["simulated-required-skill"]
elif skill_policy == "forbidden":
    execution_mode = "direct"
    skills_used = []
else:
    execution_mode = "direct"
    skills_used = []
completion = {
    "agent_id": envelope.get("agent_id"),
    "task_id": extract_field(task_text, "task_id") or envelope.get("dispatch_id"),
    "workflow_step_id": extract_field(task_text, "workflow_step_id"),
    "status": "completed",
    "summary": "Auto-completed by the transport helper.",
    "completion_schema_version": extract_field(task_text, "completion_schema_version") or "v1",
    "execution_trace": {
        "execution_mode": execution_mode,
        "skills_used": skills_used,
        "evidence_refs": [f"dispatch:{envelope.get('dispatch_id')}"],
    },
}
inbox_dir = project_root / "ai" / "runtime" / "inbox"
inbox_dir.mkdir(parents=True, exist_ok=True)
(inbox_dir / f"{envelope['dispatch_id']}.json").write_text(json.dumps(completion, indent=2), encoding="utf-8")
""",
        encoding="utf-8",
    )


def write_reattach_helper(script_path: Path) -> None:
    script_path.write_text(
        """import json
import sys
from pathlib import Path

payload_path = Path(sys.argv[1]).resolve()
payload = json.loads(payload_path.read_text(encoding="utf-8"))
marker = payload_path.with_suffix('.attached.txt')
marker.write_text(payload.get('session_key', ''), encoding='utf-8')
""",
        encoding="utf-8",
    )


def write_fake_openclaw_cli(cli_dir: Path) -> Path:
    cli_dir.mkdir(parents=True, exist_ok=True)
    handler = cli_dir / "openclaw_handler.py"
    handler.write_text(
        """import json
import sys
from pathlib import Path


argv = sys.argv[1:]
if len(argv) >= 3 and argv[0] == "parent-attach" and argv[1] == "--payload-file":
    payload = Path(argv[2]).resolve()
    data = json.loads(payload.read_text(encoding="utf-8"))
    payload.with_suffix(".cli-attached.txt").write_text(data.get("session_key", ""), encoding="utf-8")
    raise SystemExit(0)
if len(argv) >= 3 and argv[0] == "session" and argv[1] == "close":
    if argv[2] == "--payload-file" and len(argv) >= 4:
        payload = Path(argv[3]).resolve()
        data = json.loads(payload.read_text(encoding="utf-8"))
        payload.with_suffix(".cli-closed.txt").write_text(data.get("session_key", ""), encoding="utf-8")
        raise SystemExit(0)
    if argv[2] == "--session-key" and len(argv) >= 4:
        marker = Path.cwd() / "session-close-cli-marker.txt"
        marker.write_text(argv[3], encoding="utf-8")
        raise SystemExit(0)
raise SystemExit(1)
""",
        encoding="utf-8",
    )
    shell_command = cli_dir / "openclaw"
    shell_command.write_text(f'#!/bin/sh\n"{sys.executable}" "{handler}" "$@"\n', encoding="utf-8")
    os.chmod(shell_command, 0o755)

    cmd_command = cli_dir / "openclaw.cmd"
    cmd_command.write_text(f'@"{sys.executable}" "{handler}" %*\n', encoding="utf-8")
    return shell_command if os.name != "nt" else cmd_command


class GovernanceScriptRegressionTests(unittest.TestCase):
    def test_bootstrap_takeover_creates_test_layers_and_takeover_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            (project_root / ".git").mkdir(parents=True)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "bootstrap_governance.py"),
                    str(project_root),
                    "--scenario",
                    "mid-stream-takeover",
                    "--project-name",
                    "xianyu",
                    "--project-id",
                    "xianyu",
                    "--skill-root",
                    str(REPO_ROOT),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)

            state = json.loads((project_root / "ai" / "state" / "orchestrator-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["current_workflow"], "takeover-project")

            for layer in ["unit", "integration", "e2e", "regression", "contract", "fixtures"]:
                self.assertTrue((project_root / "tests" / layer).is_dir(), layer)

            self.assertTrue((project_root / "ai" / "handoff" / "orchestrator" / "active" / "TAKEOVER-ASSESSMENT.md").exists())
            self.assertTrue((project_root / "ai" / "tools" / "run_project_guard.py").exists())
            self.assertTrue((project_root / "ai" / "tools" / "render_agent_repair_brief.py").exists())
            self.assertTrue((project_root / "ai" / "tools" / "build_dispatch_payload.py").exists())
            self.assertTrue((project_root / "ai" / "tools" / "recovery_summary.py").exists())
            self.assertTrue((project_root / "ai" / "tools" / "automation_control.py").exists())
            self.assertTrue((project_root / "ai" / "tools" / "configure_autonomy.py").exists())
            self.assertTrue((project_root / "ai" / "tools" / "change_request_control.py").exists())
            self.assertTrue((project_root / "ai" / "tools" / "close_session.py").exists())
            self.assertTrue((project_root / "ai" / "tools" / "git_autocommit.py").exists())
            self.assertTrue((project_root / "ai" / "tools" / "natural_language_control.py").exists())
            self.assertTrue((project_root / "ai" / "tools" / "replan_change_request.py").exists())
            self.assertTrue((project_root / "ai" / "tools" / "provider_evidence.py").exists())
            self.assertTrue((project_root / "ai" / "tools" / "host_interface_probe.py").exists())
            self.assertTrue((project_root / "ai" / "tools" / "runtime_environment.py").exists())
            self.assertTrue((project_root / "ai" / "tools" / "runtime_guardrails.py").exists())
            self.assertTrue((project_root / "ai" / "tools" / "environment_bootstrap.py").exists())
            self.assertTrue((project_root / "ai" / "tools" / "openclaw_runtime_bridge.py").exists())
            self.assertTrue((project_root / "ai" / "tools" / "repo_command_detector.py").exists())
            self.assertTrue((project_root / "ai" / "tools" / "evidence_collector.py").exists())
            self.assertTrue((project_root / "ai" / "tools" / "escalation_manager.py").exists())
            self.assertTrue((project_root / "ai" / "tools" / "parent_session_recovery.py").exists())
            self.assertTrue((project_root / "ai" / "tools" / "inbox_watcher.py").exists())
            self.assertTrue((project_root / "ai" / "tools" / "orchestrator_local_steps.py").exists())
            self.assertTrue((project_root / "ai" / "tools" / "run_orchestrator.py").exists())
            self.assertTrue((project_root / "ai" / "tools" / "runtime_loop.py").exists())
            self.assertTrue((project_root / "ai" / "tools" / "task_rounds.py").exists())
            self.assertTrue((project_root / "ai" / "tools" / "resource_requirements.py").exists())
            self.assertTrue((project_root / "ai" / "tools" / "project_intake.py").exists())
            self.assertTrue((project_root / "ai" / "tools" / "configure_review_controls.py").exists())
            self.assertTrue((project_root / "ai" / "tools" / "resume_customer_decision.py").exists())
            self.assertTrue((project_root / "ai" / "tools" / "session_registry.py").exists())
            self.assertTrue((project_root / ".github" / "workflows" / "project-guard.yml").exists())
            self.assertTrue((project_root / ".github" / "workflows" / "project-repair-brief.yml").exists())
            self.assertTrue((project_root / "docs" / "requirement-communication-template.md").exists())
            self.assertTrue((project_root / "docs" / "ANTI-DRIFT-RUNBOOK.md").exists())
            self.assertTrue((project_root / "docs" / "RESOURCE-DEPENDENCY-POLICIES.md").exists())
            self.assertTrue((project_root / "ai" / "state" / "review-controls.json").exists())
            doc_index = (project_root / "ai" / "state" / "doc-index.md").read_text(encoding="utf-8")
            self.assertIn("docs/requirement-communication-template.md", doc_index)
            self.assertIn("ai/state/review-controls.json", doc_index)
            runtime_result = subprocess.run(
                [
                    sys.executable,
                    str(project_root / "ai" / "tools" / "run_orchestrator.py"),
                    str(project_root),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(runtime_result.returncode, 0, runtime_result.stderr)
            rollover_result = subprocess.run(
                [
                    sys.executable,
                    str(project_root / "ai" / "tools" / "context_rollover.py"),
                    str(project_root),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(rollover_result.returncode, 0, rollover_result.stderr)
            loop_result = subprocess.run(
                [
                    sys.executable,
                    str(project_root / "ai" / "tools" / "runtime_loop.py"),
                    str(project_root),
                    "--max-cycles",
                    "1",
                    "--max-dispatch",
                    "1",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(loop_result.returncode, 0)
            self.assertEqual(json.loads(loop_result.stdout)["status"], "control-blocked")
            self.assertEqual(
                (project_root / "ai" / "tools" / "validate_state.py").read_text(encoding="utf-8"),
                (SCRIPTS_DIR / "validate_state.py").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                (project_root / "ai" / "tools" / "run_project_guard.py").read_text(encoding="utf-8"),
                (SCRIPTS_DIR / "run_project_guard.py").read_text(encoding="utf-8"),
            )

    def test_build_dispatch_payload_creates_handoff_stub_and_delete_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            project_root.mkdir(parents=True)

            task_card = project_root / "task-card.md"
            task_card.write_text(
                """# Task Card

- task_id: FEAT-001
- target_agent: libu2
- target_agent_id: libu2
- dispatch_mode: spawn
- cleanup_policy: delete
- title: Build API slice
- goal:
  Create the first API slice.
- allowed_paths: src/api,src/services
- forbidden_paths: docs
- dependencies:
  none
- acceptance:
  API compiles
  Basic validation exists
- handoff_path: ai/handoff/libu2/active/FEAT-001.md
- expected_output:
  backend implementation
- review_required: yes
- upstream_dependencies:
  none
- downstream_reviewers:
  orchestrator
- testing_requirement:
  unit
- workflow_step_id: libu2-implementation
- priority: P1
""",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "build_dispatch_payload.py"),
                    str(task_card),
                    "--mode",
                    "spawn",
                    "--project-root",
                    str(project_root),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["agentId"], "libu2")
            self.assertEqual(payload["cleanup"], "delete")
            self.assertTrue((project_root / "ai" / "handoff" / "libu2" / "active" / "FEAT-001.md").exists())

    def test_session_registry_backfills_orchestrator_runtime_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            state_dir.mkdir(parents=True)
            (state_dir / "agent-sessions.json").write_text(
                json.dumps({"libu2": {"agent_id": "libu2", "status": "active", "last_step_id": "libu2-implementation"}}, indent=2)
                + "\n",
                encoding="utf-8",
            )

            payload = session_registry.ensure_registry_schema(project_root)
            self.assertIn("orchestrator", payload)
            self.assertEqual(payload["libu2"]["last_step_id"], "libu2-implementation")
            self.assertIn("resume_prompt", payload["orchestrator"])

    def test_workflow_engine_returns_parallel_ready_steps_after_plan_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            workflows_dir = project_root / "workflows"
            state_dir.mkdir(parents=True)
            workflows_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "workflow_progress": {"completed_steps": ["intake-feature", "confirm-or-replan", "plan-approval"]},
                        "active_tasks": [],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (workflows_dir / "feature-delivery.yaml").write_text(
                (REPO_ROOT / "assets" / "project-skeleton" / "workflows" / "feature-delivery.yaml").read_text(encoding="utf-8"),
                encoding="utf-8",
            )

            workflow = workflow_engine.load_workflow(project_root)
            state = json.loads((state_dir / "orchestrator-state.json").read_text(encoding="utf-8"))
            ready = [step.id for step in workflow_engine.ready_steps(workflow, state)]
            self.assertEqual(ready[:3], ["libu2-implementation", "hubu-implementation", "gongbu-implementation"])

    def test_workflow_engine_returns_cross_review_steps_after_implementation_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            workflows_dir = project_root / "workflows"
            state_dir.mkdir(parents=True)
            workflows_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "workflow_progress": {
                            "completed_steps": [
                                "intake-feature",
                                "confirm-or-replan",
                                "plan-approval",
                                "libu2-implementation",
                                "hubu-implementation",
                                "gongbu-implementation",
                            ]
                        },
                        "active_tasks": [],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (workflows_dir / "feature-delivery.yaml").write_text(
                (REPO_ROOT / "assets" / "project-skeleton" / "workflows" / "feature-delivery.yaml").read_text(encoding="utf-8"),
                encoding="utf-8",
            )

            workflow = workflow_engine.load_workflow(project_root)
            state = json.loads((state_dir / "orchestrator-state.json").read_text(encoding="utf-8"))
            ready = [step.id for step in workflow_engine.ready_steps(workflow, state)]
            self.assertEqual(
                ready[:7],
                [
                    "libu2-cross-review",
                    "hubu-cross-review",
                    "gongbu-cross-review",
                    "bingbu-cross-review",
                    "libu-cross-review",
                    "xingbu-cross-review",
                    "duchayuan-cross-review",
                ],
            )

    def test_run_orchestrator_default_dispatch_limit_covers_all_cross_reviews(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            workflows_dir = project_root / "workflows"
            state_dir.mkdir(parents=True)
            workflows_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "current_phase": "department-review",
                        "current_status": "department-review",
                        "automation_mode": "normal",
                        "workflow_progress": {
                            "completed_steps": [
                                "intake-feature",
                                "confirm-or-replan",
                                "plan-approval",
                                "libu2-implementation",
                                "hubu-implementation",
                                "gongbu-implementation",
                            ]
                        },
                        "active_tasks": [],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text("{}\n", encoding="utf-8")
            (workflows_dir / "feature-delivery.yaml").write_text(
                (REPO_ROOT / "assets" / "project-skeleton" / "workflows" / "feature-delivery.yaml").read_text(encoding="utf-8"),
                encoding="utf-8",
            )

            payload = run_orchestrator.run(project_root, transport="outbox")

            self.assertEqual(payload["status"], "dispatched")
            self.assertEqual(payload["dispatch_count"], 7)
            self.assertEqual(payload["attempted_dispatch_count"], 7)

    def test_run_orchestrator_writes_dispatch_plan_and_outbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            workflows_dir = project_root / "workflows"
            state_dir.mkdir(parents=True)
            workflows_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "current_phase": "executing",
                        "current_status": "executing",
                        "workflow_progress": {"completed_steps": ["intake-feature", "confirm-or-replan", "plan-approval"]},
                        "active_tasks": [],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text("{}\n", encoding="utf-8")
            (workflows_dir / "feature-delivery.yaml").write_text(
                (REPO_ROOT / "assets" / "project-skeleton" / "workflows" / "feature-delivery.yaml").read_text(encoding="utf-8"),
                encoding="utf-8",
            )

            result = run_orchestrator.run(project_root, max_dispatch=2, transport="outbox")
            self.assertEqual(result["status"], "dispatched")
            self.assertEqual(result["dispatch_count"], 2)
            self.assertTrue((project_root / "ai" / "reports" / "orchestrator-dispatch-plan.md").exists())
            outbox_items = list((project_root / "ai" / "runtime" / "outbox").glob("*.json"))
            self.assertEqual(len(outbox_items), 2)
            state = json.loads((state_dir / "orchestrator-state.json").read_text(encoding="utf-8"))
            self.assertEqual(len(state["active_tasks"]), 2)

    def test_run_orchestrator_executes_local_orchestrator_steps_without_outbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            bootstrap = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "bootstrap_governance.py"),
                    str(project_root),
                    "--project-name",
                    "demo",
                    "--project-id",
                    "demo",
                    "--skill-root",
                    str(REPO_ROOT),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)

            result = run_orchestrator.run(project_root, max_dispatch=1, transport="outbox")
            self.assertEqual(result["status"], "local-progress")
            self.assertEqual(result["dispatch_count"], 0)
            self.assertEqual(result["local_completion_count"], 1)
            self.assertEqual(result["dispatches"][0]["status"], "local-completed")
            self.assertEqual(len(list((project_root / "ai" / "runtime" / "outbox").glob("*.json"))), 0)

            state = json.loads((project_root / "ai" / "state" / "orchestrator-state.json").read_text(encoding="utf-8"))
            self.assertIn("identify-project", state["workflow_progress"]["completed_steps"])
            self.assertTrue((project_root / "ai" / "reports" / "project-inspection.json").exists())

    def test_run_orchestrator_waits_for_active_work_instead_of_generating_rollover(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            workflows_dir = project_root / "workflows"
            state_dir.mkdir(parents=True)
            workflows_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "automation_mode": "autonomous",
                        "current_workflow": "feature-delivery",
                        "current_phase": "executing",
                        "current_status": "executing",
                        "workflow_progress": {
                            "completed_steps": ["intake-feature", "confirm-or-replan", "plan-approval"],
                            "blocked_steps": [],
                            "dispatched_steps": [
                                "libu2-implementation",
                                "hubu-implementation",
                                "gongbu-implementation",
                            ],
                        },
                        "active_tasks": [
                            {
                                "task_id": "LIBU2-1",
                                "role": "libu2",
                                "status": "in-progress",
                                "handoff_path": "ai/handoff/libu2/active/LIBU2-1.md",
                                "workflow_step_id": "libu2-implementation",
                            },
                            {
                                "task_id": "HUBU-1",
                                "role": "hubu",
                                "status": "in-progress",
                                "handoff_path": "ai/handoff/hubu/active/HUBU-1.md",
                                "workflow_step_id": "hubu-implementation",
                            },
                            {
                                "task_id": "GONGBU-1",
                                "role": "gongbu",
                                "status": "in-progress",
                                "handoff_path": "ai/handoff/gongbu/active/GONGBU-1.md",
                                "workflow_step_id": "gongbu-implementation",
                            },
                        ],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text("{}\n", encoding="utf-8")
            (workflows_dir / "feature-delivery.yaml").write_text(
                (REPO_ROOT / "assets" / "project-skeleton" / "workflows" / "feature-delivery.yaml").read_text(encoding="utf-8"),
                encoding="utf-8",
            )

            result = run_orchestrator.run(project_root, max_dispatch=7, transport="outbox")

            self.assertEqual(result["status"], "waiting-on-active-work")
            self.assertEqual(result["active_task_count"], 3)
            self.assertFalse((project_root / "ai" / "reports" / "orchestrator-rollover.md").exists())
            state = json.loads((state_dir / "orchestrator-state.json").read_text(encoding="utf-8"))
            self.assertIn("Await completion from active tasks", state["next_action"])

    def test_run_orchestrator_blocks_when_formal_department_review_sources_are_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "current_phase": "department-review",
                        "current_status": "department-review",
                        "next_owner": "bingbu",
                        "next_action": "Dispatch formal testing after review.",
                        "workflow_progress": {
                            "completed_steps": [
                                "intake-feature",
                                "confirm-or-replan",
                                "plan-approval",
                                "libu2-implementation",
                                "hubu-implementation",
                                "gongbu-implementation",
                                "libu2-cross-review",
                                "hubu-cross-review",
                                "gongbu-cross-review",
                                "bingbu-cross-review",
                                "libu-cross-review",
                                "xingbu-cross-review",
                                "duchayuan-cross-review",
                                "department-review",
                            ],
                            "blocked_steps": [],
                            "dispatched_steps": [],
                        },
                        "active_tasks": [],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "START_HERE.md").write_text(
                "# Start Here\n\n- Stage: department-review\n- Workflow: feature-delivery\n- Next owner: bingbu\n",
                encoding="utf-8",
            )
            (state_dir / "project-handoff.md").write_text(
                "# Project Handoff\n\n- Status: department-review\n- Current phase: department-review\n- Current workflow: feature-delivery\n- Next owner: bingbu\n",
                encoding="utf-8",
            )
            (reports_dir / "department-approval-matrix.md").write_text(
                "# Department Approval Matrix\n\n## Reviewer duchayuan\n- libu2: PASS\n\n## Recommendation\n\n- PASS\n",
                encoding="utf-8",
            )

            result = run_orchestrator.run(project_root, max_dispatch=1, transport="outbox")

            self.assertEqual(result["status"], "state-validation-blocked")
            self.assertTrue((reports_dir / "department-review-source-guard.md").exists())

    def test_run_orchestrator_blocks_with_skill_policy_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "current_phase": "executing",
                        "current_status": "executing",
                        "next_owner": "orchestrator",
                        "next_action": "Review latest completion.",
                        "workflow_progress": {
                            "completed_steps": ["intake-feature", "confirm-or-replan", "plan-approval"],
                            "blocked_steps": [],
                            "dispatched_steps": [],
                        },
                        "active_tasks": [],
                        "last_completion": {
                            "task_id": "SKILL-FAIL-1",
                            "workflow_step_id": "libu2-implementation",
                            "completion_schema_version": "v1",
                            "skill_audit_recorded": True,
                        },
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "START_HERE.md").write_text(
                "# Start Here\n\n- Stage: executing\n- Workflow: feature-delivery\n- Next owner: orchestrator\n",
                encoding="utf-8",
            )
            (state_dir / "project-handoff.md").write_text(
                "# Project Handoff\n\n- Status: executing\n- Current phase: executing\n- Current workflow: feature-delivery\n- Next owner: orchestrator\n",
                encoding="utf-8",
            )
            (reports_dir / "agent-skill-usage.json").write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "task_id": "SKILL-FAIL-1",
                                "agent_id": "libu2",
                                "compliant": False,
                                "violation_code": "skill_policy_violation",
                                "violation_reason": "required skill was missing",
                            }
                        ]
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = run_orchestrator.run(project_root, max_dispatch=1, transport="outbox")

            self.assertEqual(result["status"], "state-validation-blocked")
            self.assertIn("Skill usage policy violations", result["message"])
            self.assertTrue((reports_dir / "department-review-source-guard.md").exists())

    def test_run_orchestrator_preserves_invalid_state_after_local_step_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            workflows_dir = project_root / "workflows"
            state_dir.mkdir(parents=True)
            workflows_dir.mkdir(parents=True)

            state_path = state_dir / "orchestrator-state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "automation_mode": "autonomous",
                        "current_workflow": "feature-delivery",
                        "current_phase": "draft",
                        "current_status": "draft",
                        "next_owner": "orchestrator",
                        "workflow_progress": {"completed_steps": [], "blocked_steps": [], "dispatched_steps": []},
                        "active_tasks": [],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text("{}\n", encoding="utf-8")
            (workflows_dir / "feature-delivery.yaml").write_text(
                (REPO_ROOT / "assets" / "project-skeleton" / "workflows" / "feature-delivery.yaml").read_text(encoding="utf-8"),
                encoding="utf-8",
            )

            def corrupt_local_step(project_root: Path, step: object, task_id: str) -> dict[str, str]:
                state_path.write_text("{ broken", encoding="utf-8")
                return {
                    "task_id": task_id,
                    "step_id": getattr(step, "id", ""),
                    "role": getattr(step, "role", ""),
                    "status": "completed-local",
                }

            with mock.patch.object(run_orchestrator, "is_local_orchestrator_step", return_value=True), mock.patch.object(
                run_orchestrator,
                "execute_local_step",
                side_effect=corrupt_local_step,
            ):
                with self.assertRaisesRegex(ValueError, "orchestrator-state.json"):
                    run_orchestrator.run(project_root, max_dispatch=1, transport="outbox")

            self.assertEqual(state_path.read_text(encoding="utf-8"), "{ broken")
            backups = list(state_dir.glob("orchestrator-state.json.corrupt-*.bak"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "{ broken")

    def test_run_orchestrator_executes_resume_recovery_steps_locally(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            workflows_dir = project_root / "workflows"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            workflows_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "resume-orchestrator",
                        "current_phase": "recovery",
                        "current_status": "paused",
                        "next_owner": "orchestrator",
                        "workflow_progress": {"completed_steps": [], "blocked_steps": [], "dispatched_steps": []},
                        "active_tasks": [],
                        "execution_allowed": True,
                        "testing_allowed": False,
                        "release_allowed": False,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text("{}\n", encoding="utf-8")
            (state_dir / "project-meta.json").write_text(
                json.dumps({"project_name": "demo", "project_id": "demo"}, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (state_dir / "project-handoff.md").write_text(
                "# Project Handoff\n\n## Completed\n\n- none\n\n## In Progress\n\n- none\n\n## Blocked\n\n- none\n",
                encoding="utf-8",
            )
            (workflows_dir / "resume-orchestrator.yaml").write_text(
                (REPO_ROOT / "assets" / "project-skeleton" / "workflows" / "resume-orchestrator.yaml").read_text(encoding="utf-8"),
                encoding="utf-8",
            )

            for _ in range(5):
                result = run_orchestrator.run(project_root, max_dispatch=1, transport="outbox")
                self.assertEqual(result["status"], "local-progress")
                self.assertEqual(result["dispatch_count"], 0)
                self.assertEqual(result["local_completion_count"], 1)

            state = json.loads((state_dir / "orchestrator-state.json").read_text(encoding="utf-8"))
            self.assertEqual(
                state["workflow_progress"]["completed_steps"],
                [
                    "read-recovery-entry",
                    "read-latest-reports",
                    "read-active-handoffs",
                    "produce-recovery-summary",
                    "update-state-and-handoff",
                ],
            )
            self.assertEqual(state["current_workflow"], "resume-orchestrator")
            self.assertEqual(state["current_status"], "paused")
            self.assertIn("recovery summary", state["next_action"].lower())
            self.assertEqual(len(list((project_root / "ai" / "runtime" / "outbox").glob("*.json"))), 0)
            self.assertTrue((reports_dir / "recovery-summary.md").exists())

    def test_automation_control_pause_records_state_sessions_and_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            bootstrap = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "bootstrap_governance.py"),
                    str(project_root),
                    "--project-name",
                    "demo",
                    "--project-id",
                    "demo",
                    "--skill-root",
                    str(REPO_ROOT),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)

            state_path = project_root / "ai" / "state" / "orchestrator-state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["active_tasks"] = [
                {
                    "task_id": "LIBU2-1",
                    "role": "libu2",
                    "status": "in-progress",
                    "handoff_path": "ai/handoff/libu2/active/LIBU2-1.md",
                    "workflow_step_id": "libu2-implementation",
                }
            ]
            state["next_action"] = "Continue libu2 implementation."
            state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            (project_root / "ai" / "state" / "agent-sessions.json").write_text(
                json.dumps(
                    {
                        "orchestrator": {"agent_id": "orchestrator", "status": "active", "session_key": "sess-orch"},
                        "libu2": {"agent_id": "libu2", "status": "active", "session_key": "sess-libu2"},
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            payload = automation_control.set_mode(
                project_root,
                "paused",
                actor="user",
                reason="Need clarification from the parent thread.",
            )

            self.assertEqual(payload["automation_mode"], "paused")
            updated_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(updated_state["automation_mode"], "paused")
            self.assertEqual(updated_state["pause_reason"], "Need clarification from the parent thread.")
            self.assertEqual(updated_state["active_tasks"][0]["status"], "paused")
            registry = json.loads((project_root / "ai" / "state" / "agent-sessions.json").read_text(encoding="utf-8"))
            self.assertEqual(registry["orchestrator"]["status"], "paused")
            self.assertEqual(registry["libu2"]["status"], "paused")
            self.assertTrue((project_root / "ai" / "reports" / "automation-control.md").exists())
            self.assertTrue((project_root / "ai" / "reports" / "pause-report.md").exists())
            handoff = (project_root / "ai" / "state" / "project-handoff.md").read_text(encoding="utf-8")
            self.assertIn("- Automation mode: paused", handoff)

    def test_automation_control_preserves_invalid_state_file_instead_of_overwriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            state_dir.mkdir(parents=True)
            state_path = state_dir / "orchestrator-state.json"
            state_path.write_text("{invalid json", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "invalid JSON"):
                automation_control.ensure_control_state(project_root)

            backups = list(state_dir.glob("orchestrator-state.json.corrupt-*.bak"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(state_path.read_text(encoding="utf-8"), "{invalid json")

    def test_runtime_loop_requires_autonomous_mode_but_can_activate(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            bootstrap = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "bootstrap_governance.py"),
                    str(project_root),
                    "--project-name",
                    "demo",
                    "--project-id",
                    "demo",
                    "--skill-root",
                    str(REPO_ROOT),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)

            blocked = runtime_loop.run_loop(project_root, max_cycles=1, max_dispatch=1, transport="outbox")
            self.assertEqual(blocked["status"], "control-blocked")
            self.assertEqual(blocked["automation_mode"], "normal")

            activated = runtime_loop.run_loop(
                project_root,
                max_cycles=1,
                max_dispatch=1,
                transport="outbox",
                activate=True,
                actor="user",
                activation_reason="Enter autonomous mode.",
            )
            self.assertNotEqual(activated["status"], "control-blocked")
            state = json.loads((project_root / "ai" / "state" / "orchestrator-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["automation_mode"], "autonomous")

    def test_runtime_loop_skips_environment_bootstrap_when_not_autonomous(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            state_dir.mkdir(parents=True)
            (state_dir / "orchestrator-state.json").write_text(
                json.dumps({"automation_mode": "normal"}, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            with mock.patch("runtime_loop.runtime_environment.ensure_runtime_environment") as ensure_runtime, mock.patch(
                "runtime_loop.environment_bootstrap.ensure_environment"
            ) as ensure_environment, mock.patch(
                "runtime_loop.parent_session_recovery.build_parent_recovery", return_value={}
            ), mock.patch(
                "runtime_loop.parent_session_recovery.write_recovery_artifacts", return_value={}
            ):
                blocked = runtime_loop.run_loop(project_root, max_cycles=1, max_dispatch=1, transport="outbox")

            self.assertEqual(blocked["status"], "control-blocked")
            self.assertEqual(blocked["environment"]["status"], "skipped-control-check")
            ensure_runtime.assert_not_called()
            ensure_environment.assert_not_called()

    def test_runtime_loop_forces_rollover_when_context_budget_threshold_is_reached(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            docs_dir = project_root / "docs"
            state_dir.mkdir(parents=True)
            docs_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps({"current_workflow": "feature-delivery", "current_status": "executing", "active_tasks": []}, indent=2)
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text("{}\n", encoding="utf-8")
            (state_dir / "START_HERE.md").write_text("# Start\n", encoding="utf-8")
            (state_dir / "project-handoff.md").write_text("X" * 400, encoding="utf-8")
            (docs_dir / "ANTI-DRIFT-RUNBOOK.md").write_text("# Runbook\n", encoding="utf-8")

            with mock.patch.dict(
                os.environ,
                {
                    "SILIJIAN_CONTEXT_SOFT_LIMIT_TOKENS": "20",
                    "SILIJIAN_CONTEXT_HARD_LIMIT_TOKENS": "40",
                },
                clear=False,
            ):
                summary = runtime_loop.run_loop(project_root, max_cycles=2, max_dispatch=1, transport="outbox", activate=True)

            self.assertEqual(summary["status"], "context-rollover")
            self.assertTrue((project_root / "ai" / "reports" / "orchestrator-rollover.md").exists())
            self.assertGreater(summary["context_budget"]["total_estimated_tokens"], 20)

    def test_task_rounds_complete_planning_round_and_increment_participants(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)
            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "workflow_progress": {
                            "completed_steps": ["intake-feature", "confirm-or-replan", "plan-approval"],
                            "dispatched_steps": [],
                            "blocked_steps": [],
                        },
                        "active_tasks": [],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text("{}\n", encoding="utf-8")

            record = task_rounds.complete_round_if_ready(project_root)
            self.assertEqual(record["round_id"], "planning-round")
            state = json.loads((state_dir / "orchestrator-state.json").read_text(encoding="utf-8"))
            self.assertIn("planning-round", state["task_rounds"]["completed_rounds"])
            registry = json.loads((state_dir / "agent-sessions.json").read_text(encoding="utf-8"))
            self.assertEqual(registry["neige"]["task_round_count"], 1)
            self.assertEqual(registry["duchayuan"]["task_round_count"], 1)
            self.assertTrue((reports_dir / "task-round-history.json").exists())

    def test_runtime_loop_cli_exits_non_zero_for_control_blocked_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            bootstrap = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "bootstrap_governance.py"),
                    str(project_root),
                    "--project-name",
                    "demo",
                    "--project-id",
                    "demo",
                    "--skill-root",
                    str(REPO_ROOT),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "runtime_loop.py"),
                    str(project_root),
                    "--max-cycles",
                    "1",
                    "--max-dispatch",
                    "1",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "control-blocked")

    def test_natural_language_control_enters_and_pauses_automation(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            bootstrap = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "bootstrap_governance.py"),
                    str(project_root),
                    "--project-name",
                    "demo",
                    "--project-id",
                    "demo",
                    "--skill-root",
                    str(REPO_ROOT),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)

            entered = natural_language_control.execute_request(
                project_root,
                "司礼监：进入自动模式",
                actor="user",
                max_cycles=1,
                max_dispatch=1,
            )
            self.assertEqual(entered["intent"], "autonomous")
            self.assertEqual(entered["control"]["automation_mode"], "autonomous")
            self.assertIn("runtime_loop", entered)

            paused = natural_language_control.execute_request(project_root, "司礼监：暂停自动推进", actor="user")
            self.assertEqual(paused["intent"], "pause")
            self.assertEqual(paused["control"]["automation_mode"], "paused")

            status = natural_language_control.execute_request(project_root, "司礼监：查看当前模式", actor="user")
            self.assertEqual(status["intent"], "status")
            self.assertEqual(status["control"]["automation_mode"], "paused")

    def test_natural_language_control_status_tolerates_invalid_window_notice_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            bootstrap = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "bootstrap_governance.py"),
                    str(project_root),
                    "--project-name",
                    "demo",
                    "--project-id",
                    "demo",
                    "--skill-root",
                    str(REPO_ROOT),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)
            (project_root / "ai" / "reports" / "openclaw-window-notifications.json").write_text("{bad\n", encoding="utf-8")

            status = natural_language_control.execute_request(project_root, "status", actor="user")

            self.assertEqual(status["intent"], "status")
            self.assertIn("control", status)
            self.assertIsNone(status.get("window_notification"))

    def test_natural_language_control_routes_change_request_with_fixed_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            bootstrap = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "bootstrap_governance.py"),
                    str(project_root),
                    "--project-name",
                    "demo",
                    "--project-id",
                    "demo",
                    "--skill-root",
                    str(REPO_ROOT),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)
            automation_control.set_mode(project_root, "autonomous", actor="user", reason="Start autonomous loop")

            payload = natural_language_control.execute_request(
                project_root,
                "司礼监：把数据库表结构和登录权限流程一起改掉，并补一轮迁移脚本",
                actor="user",
            )
            self.assertEqual(payload["intent"], "change_request")
            self.assertIn("change_request", payload)
            self.assertTrue(payload["change_request"]["requires_replan"])
            self.assertEqual(payload["control"]["automation_mode"], "paused")

    def test_natural_language_control_detects_close_session_variants(self):
        self.assertEqual(natural_language_control.classify_request("司礼监：关闭 libu2 当前会话"), "close_session")
        self.assertEqual(natural_language_control.classify_request("orchestrator: close libu2 current session"), "close_session")

    def test_change_request_control_records_request_and_pauses_for_significant_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            bootstrap = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "bootstrap_governance.py"),
                    str(project_root),
                    "--project-name",
                    "demo",
                    "--project-id",
                    "demo",
                    "--skill-root",
                    str(REPO_ROOT),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)
            automation_control.set_mode(project_root, "autonomous", actor="user", reason="Start autonomous loop")

            payload = change_request_control.apply_change_request(
                project_root,
                "把数据库表结构和登录权限流程一起改掉，并补一轮迁移脚本",
                actor="user",
            )

            self.assertEqual(payload["significance"], "significant")
            self.assertTrue(payload["requires_replan"])
            self.assertTrue(payload["automation_paused"])
            state = json.loads((project_root / "ai" / "state" / "orchestrator-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["last_change_request_id"], payload["request_id"])
            self.assertTrue(state["pending_change_requests"])
            self.assertEqual(state["current_phase"], "planning")
            self.assertIn(state["current_status"], {"rework", "redesign"})
            self.assertFalse(state["execution_allowed"])
            requirements = (project_root / "ai" / "state" / "requirements-pool.md").read_text(encoding="utf-8")
            self.assertIn(payload["request_id"], requirements)
            task_tree = json.loads((project_root / "ai" / "state" / "task-tree.json").read_text(encoding="utf-8"))
            self.assertEqual(task_tree["change_requests"][0]["request_id"], payload["request_id"])
            self.assertEqual(task_tree["change_requests"][0]["status"], "replan-required")
            self.assertTrue(payload["replan_packet"])
            self.assertEqual(payload["replan_packet"]["request_id"], payload["request_id"])
            self.assertGreaterEqual(len(payload["guided_options"]), 3)
            self.assertTrue((project_root / "ai" / "reports" / f"replan-{payload['request_id'].lower()}.md").exists())
            control = automation_control.current_status(project_root)
            self.assertEqual(control["automation_mode"], "paused")

    def test_change_request_control_preserves_invalid_state_before_applying_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            state_dir.mkdir(parents=True)
            invalid_state = "{invalid json\n"
            (state_dir / "orchestrator-state.json").write_text(invalid_state, encoding="utf-8")
            (state_dir / "requirements-pool.md").write_text("# Requirements Pool\n\n## Raw\n\n- none\n", encoding="utf-8")
            (state_dir / "task-tree.json").write_text(json.dumps({}, indent=2) + "\n", encoding="utf-8")
            (state_dir / "project-handoff.md").write_text("# Project Handoff\n\n## Notes For Next Round\n\n- none\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                change_request_control.apply_change_request(project_root, "add login button", actor="user")

            backups = list(state_dir.glob("orchestrator-state.json.corrupt-*.bak"))
            self.assertTrue(backups)
            self.assertEqual((state_dir / "orchestrator-state.json").read_text(encoding="utf-8"), invalid_state)

    def test_configure_autonomy_updates_defaults_and_agent_rotation(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            bootstrap = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "bootstrap_governance.py"),
                    str(project_root),
                    "--project-name",
                    "demo",
                    "--project-id",
                    "demo",
                    "--skill-root",
                    str(REPO_ROOT),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)

            payload = configure_autonomy.configure(
                project_root,
                max_cycles=24,
                max_dispatch=2,
                failure_streak_limit=4,
                idle_streak_limit=5,
                auto_commit=False,
                agent_id="libu2",
                completion_limit=2,
                dispatch_limit=3,
                task_round_limit=2,
            )
            self.assertEqual(payload["max_cycles"], 24)
            self.assertEqual(payload["max_dispatch"], 2)
            self.assertFalse(payload["auto_commit_enabled"])
            self.assertEqual(payload["session_rotation_policy"]["agents"]["libu2"]["max_completion_count"], 2)
            self.assertEqual(payload["session_rotation_policy"]["agents"]["libu2"]["max_task_round_count"], 2)
            state = json.loads((project_root / "ai" / "state" / "orchestrator-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["autonomous_runtime_max_cycles"], 24)
            self.assertEqual(state["session_rotation_policy"]["agents"]["libu2"]["max_dispatch_count"], 3)

    def test_autonomy_settings_default_max_dispatch_is_seven(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            (project_root / "ai" / "state").mkdir(parents=True)

            state = automation_control.ensure_control_state(project_root)
            payload = automation_control.autonomy_settings(project_root, state)

            self.assertEqual(state["autonomous_runtime_max_cycles"], 999)
            self.assertEqual(payload["max_cycles"], 999)
            self.assertEqual(state["autonomous_max_dispatch"], 7)
            self.assertEqual(payload["max_dispatch"], 7)

    def test_autonomy_settings_parses_string_booleans(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            state_dir.mkdir(parents=True)
            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "automation_mode": "autonomous",
                        "autonomous_auto_commit_enabled": "false",
                        "autonomous_auto_commit_push": "false",
                        "autonomous_stop_on_customer_decision": "false",
                        "window_notification_on_escalation": "false",
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            state = automation_control.ensure_control_state(project_root)
            payload = automation_control.autonomy_settings(project_root, state)

            self.assertFalse(payload["auto_commit_enabled"])
            self.assertFalse(payload["auto_commit_push"])
            self.assertFalse(payload["stop_on_customer_decision"])
            self.assertFalse(state["window_notification_on_escalation"])

    def test_session_registry_honors_per_agent_rotation_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            state_dir.mkdir(parents=True)
            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "session_rotation_policy": {
                            "default": {"max_completion_count": 4, "max_dispatch_count": 6},
                            "agents": {"libu2": {"max_completion_count": 1, "max_dispatch_count": 2}},
                        }
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text(
                json.dumps(
                    {
                        "libu2": {
                            "agent_id": "libu2",
                            "session_key": "session-libu2",
                            "status": "active",
                            "active_workflow": "feature-delivery",
                            "completion_count": 1,
                            "dispatch_count": 1,
                        }
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            decision = session_registry.session_reuse_decision(project_root, "libu2", workflow_name="feature-delivery")
            self.assertTrue(decision["should_retire"])
            self.assertIn("completion_count 1 reached the reuse limit of 1", decision["reason"])

    def test_session_registry_refuses_reuse_when_task_round_budget_is_exhausted(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            state_dir.mkdir(parents=True)
            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "session_rotation_policy": {
                            "default": {"max_completion_count": 4, "max_dispatch_count": 6, "max_task_round_count": 1},
                            "agents": {},
                        }
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text(
                json.dumps(
                    {
                        "libu2": {
                            "agent_id": "libu2",
                            "session_key": "session-libu2",
                            "status": "active",
                            "active_workflow": "feature-delivery",
                            "task_round_count": 1,
                        }
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            decision = session_registry.session_reuse_decision(project_root, "libu2", workflow_name="feature-delivery")
            self.assertTrue(decision["should_retire"])
            self.assertIn("task_round_count 1 reached the reuse limit of 1", decision["reason"])

    def test_runtime_loop_pauses_and_freezes_on_customer_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            bootstrap = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "bootstrap_governance.py"),
                    str(project_root),
                    "--project-name",
                    "demo",
                    "--project-id",
                    "demo",
                    "--skill-root",
                    str(REPO_ROOT),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)
            state_path = project_root / "ai" / "state" / "orchestrator-state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["current_workflow"] = "feature-delivery"
            state["current_phase"] = "customer-decision"
            state["current_status"] = "await-customer-decision"
            state["execution_allowed"] = True
            state["testing_allowed"] = True
            state["release_allowed"] = True
            state["active_tasks"] = [
                {
                    "task_id": "LIBU2-1",
                    "role": "libu2",
                    "status": "in-progress",
                    "handoff_path": "ai/handoff/libu2/active/LIBU2-1.md",
                    "workflow_step_id": "libu2-implementation",
                }
            ]
            state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            (project_root / "ai" / "reports" / "customer-decision-required.md").write_text("# Decision\n", encoding="utf-8")
            (project_root / "ai" / "state" / "agent-sessions.json").write_text(
                json.dumps({"libu2": {"agent_id": "libu2", "session_key": "abc", "status": "active"}}, indent=2) + "\n",
                encoding="utf-8",
            )

            summary = runtime_loop.run_loop(project_root, max_cycles=1, max_dispatch=1, transport="outbox", activate=True)
            self.assertEqual(summary["status"], "paused-for-decision")
            frozen = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(frozen["automation_mode"], "paused")
            self.assertFalse(frozen["execution_allowed"])
            self.assertFalse(frozen["testing_allowed"])
            self.assertFalse(frozen["release_allowed"])
            self.assertEqual(frozen["active_tasks"][0]["status"], "paused")
            sessions = json.loads((project_root / "ai" / "state" / "agent-sessions.json").read_text(encoding="utf-8"))
            self.assertEqual(sessions["libu2"]["status"], "paused")

    def test_runtime_loop_pauses_when_blocking_resource_gap_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            bootstrap = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "bootstrap_governance.py"),
                    str(project_root),
                    "--project-name",
                    "demo",
                    "--project-id",
                    "demo",
                    "--skill-root",
                    str(REPO_ROOT),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)
            resource_requirements.record_gap(
                project_root,
                resource_name="Stripe live key",
                category="credential",
                policy="block",
                due_stage="immediate",
                scope_level="module",
                scope_label="payments",
                notes="Cannot continue real payment development without the live key.",
            )

            summary = runtime_loop.run_loop(project_root, max_cycles=1, max_dispatch=1, transport="outbox", activate=True)
            self.assertEqual(summary["status"], "paused-for-decision")
            frozen = json.loads((project_root / "ai" / "state" / "orchestrator-state.json").read_text(encoding="utf-8"))
            self.assertEqual(frozen["automation_mode"], "paused")
            self.assertFalse(frozen["execution_allowed"])
            report = (project_root / "ai" / "reports" / "resource-gap-report.md").read_text(encoding="utf-8")
            self.assertIn("Stripe live key", report)

    def test_runtime_loop_freezes_when_formal_department_review_sources_are_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)
            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "current_phase": "department-review",
                        "current_status": "department-review",
                        "automation_mode": "autonomous",
                        "next_owner": "bingbu",
                        "next_action": "Dispatch formal testing after review.",
                        "workflow_progress": {
                            "completed_steps": [
                                "intake-feature",
                                "confirm-or-replan",
                                "plan-approval",
                                "libu2-implementation",
                                "hubu-implementation",
                                "gongbu-implementation",
                                "libu2-cross-review",
                                "hubu-cross-review",
                                "gongbu-cross-review",
                                "bingbu-cross-review",
                                "libu-cross-review",
                                "xingbu-cross-review",
                                "duchayuan-cross-review",
                                "department-review",
                            ],
                            "blocked_steps": [],
                            "dispatched_steps": [],
                        },
                        "active_tasks": [],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "START_HERE.md").write_text(
                "# Start Here\n\n- Stage: department-review\n- Workflow: feature-delivery\n- Next owner: bingbu\n",
                encoding="utf-8",
            )
            (state_dir / "project-handoff.md").write_text(
                "# Project Handoff\n\n- Status: department-review\n- Current phase: department-review\n- Current workflow: feature-delivery\n- Next owner: bingbu\n",
                encoding="utf-8",
            )
            (reports_dir / "department-approval-matrix.md").write_text(
                "# Department Approval Matrix\n\n## Reviewer duchayuan\n- libu2: PASS\n\n## Recommendation\n\n- PASS\n",
                encoding="utf-8",
            )

            with mock.patch("runtime_loop.runtime_environment.ensure_runtime_environment"), mock.patch(
                "runtime_loop.environment_bootstrap.ensure_environment", return_value={"status": "ok"}
            ), mock.patch(
                "runtime_loop.context_rollover.context_rollover_required", return_value={"should_rollover": False}
            ), mock.patch(
                "runtime_loop.parent_session_recovery.build_parent_recovery", return_value={}
            ), mock.patch(
                "runtime_loop.parent_session_recovery.write_recovery_artifacts", return_value={}
            ):
                summary = runtime_loop.run_loop(project_root, max_cycles=1, max_dispatch=1, transport="outbox")

            self.assertEqual(summary["status"], "paused-for-decision")
            self.assertEqual(summary["cycles"][0]["dispatch"]["status"], "state-validation-blocked")
            self.assertEqual(summary["cycles"][0]["decision_freeze"]["automation_mode"], "paused")
            self.assertTrue((reports_dir / "department-review-source-guard.md").exists())

    def test_resource_gap_round_trip_requires_retest_before_closing(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            bootstrap = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "bootstrap_governance.py"),
                    str(project_root),
                    "--project-name",
                    "demo",
                    "--project-id",
                    "demo",
                    "--skill-root",
                    str(REPO_ROOT),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)

            recorded = resource_requirements.record_gap(
                project_root,
                resource_name="Realtime analytics API",
                category="real-api",
                policy="mock",
                due_stage="release",
                scope_level="module",
                scope_label="analytics",
                notes="Use stubbed ingestion until the provider contract is approved.",
            )
            gap_id = recorded["gap"]["gap_id"]
            state = json.loads((project_root / "ai" / "state" / "orchestrator-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["resource_gaps"][0]["status"], "deferred")

            resolved = resource_requirements.resolve_gap(
                project_root,
                gap_id=gap_id,
                resolution_summary="Customer supplied the production sandbox token.",
                supplied_by="customer",
            )
            self.assertEqual(resolved["gap"]["status"], "retest-pending")

            closed = resource_requirements.complete_retest(
                project_root,
                gap_id=gap_id,
                outcome="pass",
                summary_text="Realtime ingestion passed against the live provider.",
            )
            self.assertEqual(closed["gap"]["status"], "closed")
            self.assertEqual(closed["gap"]["retest_status"], "passed")

    def test_resource_gap_summary_parses_string_boolean_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            state_dir.mkdir(parents=True)
            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_phase": "release",
                        "current_status": "planning",
                        "release_allowed": "false",
                        "resource_policy": {
                            "default_policy": "mock",
                            "categories": {"other": "mock"},
                            "release_requires_real_validation": "false",
                        },
                        "resource_gaps": [
                            {
                                "gap_id": "gap-1",
                                "resource_name": "partner-api",
                                "category": "other",
                                "policy": "mock",
                                "status": "deferred",
                                "due_stage": "release",
                                "scope_level": "project",
                                "scope_label": "",
                                "real_validation_required": True,
                            }
                        ],
                        "resource_gap_history": [],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            report = resource_requirements.summary(project_root)

            self.assertFalse(report["requires_user_input"])
            self.assertEqual(report["release_validation_pending"], [])

    def test_runtime_loop_auto_commits_after_completed_task_round(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            helper = Path(tmp) / "transport_helper.py"
            write_transport_helper(helper)
            bootstrap = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "bootstrap_governance.py"),
                    str(project_root),
                    "--project-name",
                    "demo",
                    "--project-id",
                    "demo",
                    "--skill-root",
                    str(REPO_ROOT),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)
            state_path = project_root / "ai" / "state" / "orchestrator-state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["current_workflow"] = "feature-delivery"
            state["current_phase"] = "planning"
            state["current_status"] = "planning"
            state["workflow_progress"] = {
                "completed_steps": ["intake-feature"],
                "blocked_steps": [],
                "dispatched_steps": [],
            }
            state["active_tasks"] = []
            state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(project_root), "init"], capture_output=True, text=True, check=False)
            subprocess.run(["git", "-C", str(project_root), "config", "user.email", "codex@example.com"], capture_output=True, text=True, check=False)
            subprocess.run(["git", "-C", str(project_root), "config", "user.name", "Codex"], capture_output=True, text=True, check=False)
            subprocess.run(["git", "-C", str(project_root), "add", "-A"], capture_output=True, text=True, check=False)
            subprocess.run(["git", "-C", str(project_root), "commit", "-m", "initial"], capture_output=True, text=True, check=False)

            with mock.patch.dict(os.environ, {"OPENCLAW_SPAWN_COMMAND": f'"{sys.executable}" "{helper}" "{{dispatch_file}}"'}):
                summary = runtime_loop.run_loop(project_root, max_cycles=3, max_dispatch=1, transport="outbox", activate=True)

            self.assertGreaterEqual(summary["total_dispatch_count"], 1)
            self.assertIn("planning-round", summary["completed_task_rounds"])
            report = json.loads((project_root / "ai" / "reports" / "auto-commit.json").read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "committed")
            head = subprocess.run(
                ["git", "-C", str(project_root), "log", "-1", "--pretty=%s"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertIn("checkpoint after planning-round", head.stdout.strip())

    def test_runtime_loop_keeps_polling_while_active_work_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            state_dir.mkdir(parents=True)
            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "automation_mode": "autonomous",
                        "autonomous_idle_streak_limit": 5,
                        "current_workflow": "feature-delivery",
                        "current_phase": "executing",
                        "current_status": "executing",
                        "active_tasks": [
                            {
                                "task_id": "LIBU2-1",
                                "role": "libu2",
                                "status": "in-progress",
                                "workflow_step_id": "libu2-implementation",
                            }
                        ],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text("{}\n", encoding="utf-8")

            with mock.patch("runtime_loop.runtime_environment.ensure_runtime_environment"), mock.patch(
                "runtime_loop.environment_bootstrap.ensure_environment", return_value={"status": "ok"}
            ), mock.patch(
                "runtime_loop.inbox_watcher.process_inbox",
                return_value={"processed_count": 0, "guarded_count": 0, "failed_count": 0, "items": []},
            ), mock.patch(
                "runtime_loop.run_orchestrator.run",
                return_value={
                    "status": "idle",
                    "dispatch_count": 0,
                    "attempted_dispatch_count": 0,
                    "local_completion_count": 0,
                },
            ), mock.patch(
                "runtime_loop.deliver_outbox",
                return_value={"sent_count": 0, "failed_count": 0, "pending_config_count": 0, "items": []},
            ), mock.patch(
                "runtime_loop.evidence_collector.collect_evidence", return_value={"status": "ok"}
            ), mock.patch(
                "runtime_loop.escalation_manager.generate_escalation", return_value={"status": "clear", "findings": []}
            ), mock.patch(
                "runtime_loop.task_rounds.complete_round_if_ready", return_value=None
            ), mock.patch(
                "runtime_loop.context_rollover.context_rollover_required", return_value={"should_rollover": False}
            ), mock.patch(
                "runtime_loop.parent_session_recovery.build_parent_recovery", return_value={}
            ), mock.patch(
                "runtime_loop.parent_session_recovery.write_recovery_artifacts", return_value={}
            ):
                summary = runtime_loop.run_loop(project_root, max_cycles=3, max_dispatch=1, transport="outbox")

            self.assertEqual(summary["status"], "max-cycles-reached")
            self.assertEqual(summary["cycle_count"], 3)

    def test_runtime_loop_stops_when_idle_streak_limit_is_reached(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            state_dir.mkdir(parents=True)
            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "automation_mode": "autonomous",
                        "autonomous_idle_streak_limit": 2,
                        "current_workflow": "feature-delivery",
                        "current_phase": "executing",
                        "current_status": "executing",
                        "active_tasks": [
                            {
                                "task_id": "LIBU2-1",
                                "role": "libu2",
                                "status": "in-progress",
                                "workflow_step_id": "libu2-implementation",
                            }
                        ],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text("{}\n", encoding="utf-8")

            with mock.patch("runtime_loop.runtime_environment.ensure_runtime_environment"), mock.patch(
                "runtime_loop.environment_bootstrap.ensure_environment", return_value={"status": "ok"}
            ), mock.patch(
                "runtime_loop.inbox_watcher.process_inbox",
                return_value={"processed_count": 0, "guarded_count": 0, "failed_count": 0, "items": []},
            ), mock.patch(
                "runtime_loop.run_orchestrator.run",
                return_value={
                    "status": "idle",
                    "dispatch_count": 0,
                    "attempted_dispatch_count": 0,
                    "local_completion_count": 0,
                },
            ), mock.patch(
                "runtime_loop.deliver_outbox",
                return_value={"sent_count": 0, "failed_count": 0, "pending_config_count": 0, "items": []},
            ), mock.patch(
                "runtime_loop.evidence_collector.collect_evidence", return_value={"status": "ok"}
            ), mock.patch(
                "runtime_loop.escalation_manager.generate_escalation", return_value={"status": "clear", "findings": []}
            ), mock.patch(
                "runtime_loop.task_rounds.complete_round_if_ready", return_value=None
            ), mock.patch(
                "runtime_loop.context_rollover.context_rollover_required", return_value={"should_rollover": False}
            ), mock.patch(
                "runtime_loop.parent_session_recovery.build_parent_recovery", return_value={}
            ), mock.patch(
                "runtime_loop.parent_session_recovery.write_recovery_artifacts", return_value={}
            ):
                summary = runtime_loop.run_loop(project_root, max_cycles=5, max_dispatch=1, transport="outbox")

            self.assertEqual(summary["status"], "idle-streak-limit-reached")
            self.assertEqual(summary["cycle_count"], 2)
            self.assertTrue(summary["cycles"][-1]["idle_state"]["limit_reached"])

    def test_runtime_loop_emits_window_notification_when_escalated(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            state_dir.mkdir(parents=True)
            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "automation_mode": "autonomous",
                        "current_workflow": "feature-delivery",
                        "current_phase": "executing",
                        "current_status": "executing",
                        "active_tasks": [],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text("{}\n", encoding="utf-8")

            with mock.patch("runtime_loop.runtime_environment.ensure_runtime_environment"), mock.patch(
                "runtime_loop.environment_bootstrap.ensure_environment", return_value={"status": "ok"}
            ), mock.patch(
                "runtime_loop.inbox_watcher.process_inbox",
                return_value={"processed_count": 0, "guarded_count": 0, "failed_count": 0, "items": []},
            ), mock.patch(
                "runtime_loop.run_orchestrator.run",
                return_value={
                    "status": "idle",
                    "dispatch_count": 0,
                    "attempted_dispatch_count": 0,
                    "local_completion_count": 0,
                },
            ), mock.patch(
                "runtime_loop.deliver_outbox",
                return_value={"sent_count": 0, "failed_count": 0, "pending_config_count": 0, "items": []},
            ), mock.patch(
                "runtime_loop.evidence_collector.collect_evidence", return_value={"status": "ok"}
            ), mock.patch(
                "runtime_loop.escalation_manager.generate_escalation",
                return_value={
                    "status": "escalated",
                    "items": ["Skill policy violation detected."],
                    "findings": [{"code": "skill_policy_violation", "severity": "error", "message": "Skill policy violation detected."}],
                    "window_notification": {
                        "level": "error",
                        "title": "司礼监告警：流程已触发门禁",
                        "reason": "Skill policy violation detected.",
                        "impact": "Autonomous dispatch is blocked until violations are addressed.",
                        "decision_needed": "yes",
                        "options": ["Fix and retry."],
                    },
                },
            ), mock.patch(
                "runtime_loop.task_rounds.complete_round_if_ready", return_value=None
            ), mock.patch(
                "runtime_loop.context_rollover.context_rollover_required", return_value={"should_rollover": False}
            ), mock.patch(
                "runtime_loop.parent_session_recovery.build_parent_recovery", return_value={}
            ), mock.patch(
                "runtime_loop.parent_session_recovery.write_recovery_artifacts", return_value={}
            ):
                summary = runtime_loop.run_loop(project_root, max_cycles=1, max_dispatch=1, transport="outbox")

            self.assertTrue(summary["window_notification_required"])
            self.assertTrue(summary["window_notifications"])
            self.assertIn("司礼监告警", summary["latest_window_notification"]["title"])
            self.assertTrue((project_root / "ai" / "reports" / "openclaw-window-notifications.json").exists())

    def test_runtime_loop_can_disable_window_notifications(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            state_dir.mkdir(parents=True)
            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "automation_mode": "normal",
                        "window_notification_on_escalation": False,
                        "current_workflow": "feature-delivery",
                        "current_phase": "draft",
                        "current_status": "draft",
                        "active_tasks": [],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text("{}\n", encoding="utf-8")

            summary = runtime_loop.run_loop(project_root, max_cycles=1, max_dispatch=1, transport="outbox")

            self.assertEqual(summary["status"], "control-blocked")
            self.assertFalse(summary["window_notification_required"])
            self.assertEqual(summary["window_notifications"], [])
            notice = json.loads((project_root / "ai" / "reports" / "openclaw-window-notifications.json").read_text(encoding="utf-8"))
            self.assertEqual(notice["notifications"], [])

    def test_runtime_loop_can_disable_window_notifications_from_string_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            state_dir.mkdir(parents=True)
            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "automation_mode": "normal",
                        "window_notification_on_escalation": "false",
                        "current_workflow": "feature-delivery",
                        "current_phase": "draft",
                        "current_status": "draft",
                        "active_tasks": [],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text("{}\n", encoding="utf-8")

            summary = runtime_loop.run_loop(project_root, max_cycles=1, max_dispatch=1, transport="outbox")

            self.assertEqual(summary["status"], "control-blocked")
            self.assertFalse(summary["window_notification_required"])
            self.assertEqual(summary["window_notifications"], [])
            notice = json.loads((project_root / "ai" / "reports" / "openclaw-window-notifications.json").read_text(encoding="utf-8"))
            self.assertEqual(notice["notifications"], [])

    def test_git_autocommit_only_commits_current_round_related_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            src_dir = project_root / "src"
            handoff_dir = project_root / "ai" / "handoff" / "libu2" / "active"
            state_dir = project_root / "ai" / "state"
            src_dir.mkdir(parents=True)
            handoff_dir.mkdir(parents=True)
            state_dir.mkdir(parents=True)

            tracked_file = src_dir / "kept.py"
            unrelated_file = project_root / "notes.txt"
            staged_unrelated_file = src_dir / "unrelated_staged.py"
            state_file = state_dir / "orchestrator-state.json"
            tracked_file.write_text("print('old')\n", encoding="utf-8")
            unrelated_file.write_text("draft v1\n", encoding="utf-8")
            staged_unrelated_file.write_text("print('before')\n", encoding="utf-8")
            state_file.write_text("{}\n", encoding="utf-8")

            subprocess.run(["git", "-C", str(project_root), "init"], capture_output=True, text=True, check=False)
            subprocess.run(["git", "-C", str(project_root), "config", "user.email", "codex@example.com"], capture_output=True, text=True, check=False)
            subprocess.run(["git", "-C", str(project_root), "config", "user.name", "Codex"], capture_output=True, text=True, check=False)
            subprocess.run(["git", "-C", str(project_root), "add", "-A"], capture_output=True, text=True, check=False)
            subprocess.run(["git", "-C", str(project_root), "commit", "-m", "initial"], capture_output=True, text=True, check=False)

            tracked_file.write_text("print('new')\n", encoding="utf-8")
            unrelated_file.write_text("draft v2\n", encoding="utf-8")
            staged_unrelated_file.write_text("print('after')\n", encoding="utf-8")
            state_file.write_text(json.dumps({"updated": True}, indent=2) + "\n", encoding="utf-8")
            (handoff_dir / "LIBU2-ROUND.md").write_text(
                "# Role Handoff\n\n"
                "- task_round_id: implementation-round\n"
                "- files_touched: src/kept.py\n",
                encoding="utf-8",
            )
            subprocess.run(
                ["git", "-C", str(project_root), "add", "--", "src/unrelated_staged.py"],
                capture_output=True,
                text=True,
                check=False,
            )

            payload = git_autocommit.autocommit(project_root, cycle_index=1, scope_label="implementation-round")

            self.assertEqual(payload["status"], "committed")
            self.assertIn("notes.txt", payload["ignored_changes"])
            self.assertNotIn("src/unrelated_staged.py", payload["changes"])
            show = subprocess.run(
                ["git", "-C", str(project_root), "show", "--name-only", "--pretty=format:", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
            )
            committed_paths = {line.strip() for line in show.stdout.splitlines() if line.strip()}
            self.assertIn("src/kept.py", committed_paths)
            self.assertIn("ai/state/orchestrator-state.json", committed_paths)
            self.assertNotIn("notes.txt", committed_paths)
            self.assertNotIn("src/unrelated_staged.py", committed_paths)
            status = subprocess.run(
                ["git", "-C", str(project_root), "status", "--porcelain", "--", "notes.txt", "src/unrelated_staged.py"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertIn("notes.txt", status.stdout)
            self.assertIn("src/unrelated_staged.py", status.stdout)

    def test_openclaw_adapter_drains_outbox_and_archives_sent_envelopes(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            helper = Path(tmp) / "transport_helper.py"
            project_root.mkdir(parents=True)
            write_transport_helper(helper)

            openclaw_adapter.dispatch_payload(
                project_root,
                {"task": "[libu2 task]\\n- task_id: LIBU2-1\\n- workflow_step_id: libu2-implementation\\n"},
                "spawn",
                "libu2",
                transport="outbox",
            )

            with mock.patch.dict(os.environ, {"OPENCLAW_SPAWN_COMMAND": f'"{sys.executable}" "{helper}" "{{dispatch_file}}"'}):
                result = openclaw_adapter.deliver_outbox(project_root)

            self.assertEqual(result["attempted_count"], 1)
            self.assertEqual(result["sent_count"], 1)
            self.assertEqual(result["failed_count"], 0)
            self.assertEqual(len(list((project_root / "ai" / "runtime" / "outbox").glob("*.json"))), 0)
            sent_items = list((project_root / "ai" / "runtime" / "outbox" / "sent").glob("*.json"))
            self.assertEqual(len(sent_items), 1)
            inbox_items = list((project_root / "ai" / "runtime" / "inbox").glob("*.json"))
            self.assertEqual(len(inbox_items), 1)

    def test_openclaw_adapter_skips_corrupt_outbox_envelope_and_continues(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            helper = Path(tmp) / "transport_helper.py"
            project_root.mkdir(parents=True)
            write_transport_helper(helper)

            openclaw_adapter.dispatch_payload(
                project_root,
                {"task": "[libu2 task]\\n- task_id: LIBU2-2\\n- workflow_step_id: libu2-implementation\\n"},
                "spawn",
                "libu2",
                transport="outbox",
            )
            (project_root / "ai" / "runtime" / "outbox" / "bad-envelope.json").write_text("{bad\n", encoding="utf-8")

            with mock.patch.dict(os.environ, {"OPENCLAW_SPAWN_COMMAND": f'"{sys.executable}" "{helper}" "{{dispatch_file}}"'}):
                result = openclaw_adapter.deliver_outbox(project_root)

            self.assertEqual(result["attempted_count"], 2)
            self.assertEqual(result["sent_count"], 1)
            self.assertEqual(result["failed_count"], 1)
            self.assertTrue((project_root / "ai" / "runtime" / "outbox" / "failed" / "bad-envelope.json").exists())
            self.assertEqual(len(list((project_root / "ai" / "runtime" / "outbox" / "sent").glob("*.json"))), 1)

    def test_repo_command_detector_prefers_package_scripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            project_root.mkdir(parents=True)
            (project_root / "package.json").write_text(
                json.dumps({"scripts": {"lint": "eslint .", "build": "tsc -b", "test": "vitest run"}}, indent=2) + "\n",
                encoding="utf-8",
            )
            (project_root / "pnpm-lock.yaml").write_text("lockfileVersion: 9\n", encoding="utf-8")

            summary = repo_command_detector.command_summary(project_root)
            self.assertEqual(summary["commands"]["lint"], "pnpm run lint")
            self.assertEqual(summary["commands"]["build"], "pnpm run build")
            self.assertEqual(summary["commands"]["test"], "pnpm run test")

    def test_repo_command_detector_detects_ci_release_and_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            scripts_dir = project_root / "scripts"
            workflows_dir = project_root / ".github" / "workflows"
            scripts_dir.mkdir(parents=True)
            workflows_dir.mkdir(parents=True)
            (scripts_dir / "run_repo_ci.py").write_text("print('ci')\n", encoding="utf-8")
            (scripts_dir / "release.py").write_text("print('release')\n", encoding="utf-8")
            (scripts_dir / "rollback.py").write_text("print('rollback')\n", encoding="utf-8")
            (workflows_dir / "ci.yml").write_text("name: ci\n", encoding="utf-8")

            summary = repo_command_detector.command_summary(project_root)
            self.assertIn("run_repo_ci.py", summary["commands"]["ci"])
            self.assertIn("release.py", summary["commands"]["release"])
            self.assertIn("rollback.py", summary["commands"]["rollback"])

    def test_repo_command_detector_uses_existing_test_directory_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            test_dir = project_root / "test"
            test_dir.mkdir(parents=True)
            (project_root / "service.py").write_text("print('ok')\n", encoding="utf-8")

            summary = repo_command_detector.command_summary(project_root)

            self.assertIn("-s test -v", summary["commands"]["test"])

    def test_evidence_collector_writes_reports_for_python_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            tests_dir = project_root / "tests"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)
            tests_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "current_phase": "testing",
                        "current_status": "testing",
                        "release_allowed": False,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "START_HERE.md").write_text("# START_HERE\n", encoding="utf-8")
            (state_dir / "project-handoff.md").write_text("# Project Handoff\n", encoding="utf-8")
            (tests_dir / "test_sample.py").write_text(
                "import unittest\n\nclass Smoke(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n",
                encoding="utf-8",
            )

            summary = evidence_collector.collect_evidence(project_root, force=True)
            self.assertEqual(summary["status"], "collected")
            self.assertEqual(summary["test"]["status"], "PASS")
            self.assertEqual(summary["build"]["status"], "PASS")
            self.assertTrue((reports_dir / "test-report.md").exists())
            self.assertTrue((reports_dir / "gate-report.md").exists())
            self.assertIn("- YES", (reports_dir / "test-report.md").read_text(encoding="utf-8"))
            self.assertIn("mainline regression passed: YES", (reports_dir / "gate-report.md").read_text(encoding="utf-8"))

    def test_evidence_collector_detects_ci_release_and_rollback_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            scripts_dir = project_root / "scripts"
            state_dir.mkdir(parents=True)
            scripts_dir.mkdir(parents=True)
            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "review-and-release",
                        "current_phase": "final-audit",
                        "current_status": "accepted",
                        "release_allowed": True,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "START_HERE.md").write_text("# START_HERE\n", encoding="utf-8")
            (state_dir / "project-handoff.md").write_text("# Project Handoff\n", encoding="utf-8")
            (scripts_dir / "run_repo_ci.py").write_text("print('ci ok')\n", encoding="utf-8")
            (scripts_dir / "release.py").write_text("print('release ok')\n", encoding="utf-8")
            (scripts_dir / "rollback.py").write_text("print('rollback ok')\n", encoding="utf-8")

            with mock.patch.dict(
                os.environ,
                {"SILIJIAN_RUN_RELEASE_VERIFICATION": "1", "SILIJIAN_RUN_ROLLBACK_VERIFICATION": "1"},
            ):
                summary = evidence_collector.collect_evidence(project_root, force=True)

            self.assertEqual(summary["ci"]["status"], "PASS")
            self.assertEqual(summary["release"]["status"], "PASS")
            self.assertEqual(summary["rollback"]["status"], "PASS")

    def test_provider_evidence_reads_json_backed_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            reports_dir = project_root / "ai" / "reports"
            reports_dir.mkdir(parents=True)
            ci_json = Path(tmp) / "ci-provider.json"
            release_json = Path(tmp) / "release-provider.json"
            rollback_json = Path(tmp) / "rollback-provider.json"
            ci_json.write_text(
                json.dumps({"provider": "github-actions", "status": "success", "summary": "CI green", "url": "https://ci"}, indent=2) + "\n",
                encoding="utf-8",
            )
            release_json.write_text(
                json.dumps({"provider": "deploy-provider", "status": "failed", "summary": "Release blocked"}, indent=2) + "\n",
                encoding="utf-8",
            )
            rollback_json.write_text(
                json.dumps({"provider": "deploy-provider", "status": "pending", "summary": "Rollback staged"}, indent=2) + "\n",
                encoding="utf-8",
            )

            with mock.patch.dict(
                os.environ,
                {
                    "SILIJIAN_CI_PROVIDER_JSON": str(ci_json),
                    "SILIJIAN_RELEASE_PROVIDER_JSON": str(release_json),
                    "SILIJIAN_ROLLBACK_PROVIDER_JSON": str(rollback_json),
                },
                clear=False,
            ):
                summary = provider_evidence.collect_provider_evidence(project_root)

            self.assertEqual(summary["results"]["ci"]["status"], "PASS")
            self.assertEqual(summary["results"]["release"]["status"], "FAIL")
            self.assertEqual(summary["results"]["rollback"]["status"], "PASS_WITH_WARNING")
            self.assertTrue((reports_dir / "provider-evidence-summary.json").exists())

    def test_provider_evidence_treats_invalid_json_as_fail_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            reports_dir = project_root / "ai" / "reports"
            reports_dir.mkdir(parents=True)
            invalid_json = Path(tmp) / "ci-provider.json"
            invalid_json.write_text("{ broken", encoding="utf-8")

            with mock.patch.dict(
                os.environ,
                {
                    "SILIJIAN_CI_PROVIDER_JSON": str(invalid_json),
                },
                clear=False,
            ):
                summary = provider_evidence.collect_provider_evidence(project_root)

            ci_result = summary["results"]["ci"]
            self.assertEqual(ci_result["status"], "FAIL")
            self.assertEqual(ci_result["raw_status"], "invalid-json")
            self.assertEqual(ci_result["source"], "json-file")
            self.assertIn("invalid", ci_result["summary"].lower())
            self.assertTrue((reports_dir / "provider-evidence-summary.json").exists())

    def test_provider_evidence_treats_unreadable_json_path_as_fail_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            reports_dir = project_root / "ai" / "reports"
            reports_dir.mkdir(parents=True)
            unreadable_path = Path(tmp) / "ci-provider-dir"
            unreadable_path.mkdir()

            with mock.patch.dict(
                os.environ,
                {
                    "SILIJIAN_CI_PROVIDER_JSON": str(unreadable_path),
                },
                clear=False,
            ):
                summary = provider_evidence.collect_provider_evidence(project_root)

            ci_result = summary["results"]["ci"]
            self.assertEqual(ci_result["status"], "FAIL")
            self.assertEqual(ci_result["raw_status"], "read-error")
            self.assertEqual(ci_result["source"], "json-file")
            self.assertIn("could not be read", ci_result["summary"].lower())
            self.assertTrue((reports_dir / "provider-evidence-summary.json").exists())

    def test_provider_evidence_prefers_conclusion_over_completed_status(self):
        payload = provider_evidence.normalize_payload(
            "ci",
            "github-actions",
            {
                "status": "completed",
                "conclusion": "failure",
                "workflowName": "Skill CI",
                "displayTitle": "Regression run",
            },
            "gh-cli",
        )

        self.assertEqual(payload["raw_status"], "failure")
        self.assertEqual(payload["status"], "FAIL")

    def test_evidence_collector_prefers_provider_results_over_local_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            tests_dir = project_root / "tests"
            scripts_dir = project_root / "scripts"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)
            tests_dir.mkdir(parents=True)
            scripts_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "current_phase": "final-audit",
                        "current_status": "final-audit",
                        "release_allowed": True,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "START_HERE.md").write_text("# START_HERE\n", encoding="utf-8")
            (state_dir / "project-handoff.md").write_text("# Project Handoff\n", encoding="utf-8")
            (tests_dir / "test_sample.py").write_text(
                "import unittest\n\nclass Sample(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            (scripts_dir / "run_repo_ci.py").write_text("raise SystemExit(1)\n", encoding="utf-8")
            (scripts_dir / "release.py").write_text("raise SystemExit(1)\n", encoding="utf-8")
            (scripts_dir / "rollback.py").write_text("raise SystemExit(1)\n", encoding="utf-8")

            ci_json = Path(tmp) / "ci-provider.json"
            release_json = Path(tmp) / "release-provider.json"
            rollback_json = Path(tmp) / "rollback-provider.json"
            ci_json.write_text(json.dumps({"provider": "github-actions", "status": "success", "summary": "Provider CI ok"}) + "\n", encoding="utf-8")
            release_json.write_text(json.dumps({"provider": "deploy-provider", "status": "success", "summary": "Provider release ok"}) + "\n", encoding="utf-8")
            rollback_json.write_text(json.dumps({"provider": "deploy-provider", "status": "success", "summary": "Provider rollback ok"}) + "\n", encoding="utf-8")

            with mock.patch.dict(
                os.environ,
                {
                    "SILIJIAN_CI_PROVIDER_JSON": str(ci_json),
                    "SILIJIAN_RELEASE_PROVIDER_JSON": str(release_json),
                    "SILIJIAN_ROLLBACK_PROVIDER_JSON": str(rollback_json),
                    "SILIJIAN_RUN_RELEASE_VERIFICATION": "1",
                    "SILIJIAN_RUN_ROLLBACK_VERIFICATION": "1",
                },
                clear=False,
            ):
                summary = evidence_collector.collect_evidence(project_root, force=True)

            self.assertEqual(summary["ci"]["status"], "PASS")
            self.assertEqual(summary["ci"]["source"], "json-file")
            self.assertEqual(summary["release"]["status"], "PASS")
            self.assertEqual(summary["rollback"]["status"], "PASS")
            self.assertEqual(summary["recommendation"], "PASS_WITH_WARNING")
            gate_report = (reports_dir / "gate-report.md").read_text(encoding="utf-8")
            self.assertIn("provider ci source: json-file", gate_report)
            gate_text = (project_root / "ai" / "reports" / "gate-report.md").read_text(encoding="utf-8")
            self.assertIn("- ci check: PASS", gate_text)
            self.assertIn("- rollback point available: YES", gate_text)

    def test_evidence_collector_skipped_tests_do_not_fake_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "current_phase": "testing",
                        "current_status": "testing",
                        "release_allowed": False,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "START_HERE.md").write_text("# START_HERE\n", encoding="utf-8")
            (state_dir / "project-handoff.md").write_text("# Project Handoff\n", encoding="utf-8")

            summary = evidence_collector.collect_evidence(project_root, force=True)

            self.assertEqual(summary["test"]["status"], "SKIPPED")
            self.assertEqual(summary["mainline_result"], "NO")
            self.assertEqual(summary["release_recommendation"], "NO")
            report = (reports_dir / "test-report.md").read_text(encoding="utf-8")
            self.assertIn("- passed: 0", report)
            self.assertIn("- failed: 0", report)
            self.assertIn("- skipped: 0", report)
            self.assertIn("- PASS_WITH_WARNING", report)

    def test_evidence_collector_blocks_failed_provider_release_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            tests_dir = project_root / "tests"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)
            tests_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "review-and-release",
                        "current_phase": "final-audit",
                        "current_status": "accepted",
                        "release_allowed": True,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "START_HERE.md").write_text("# START_HERE\n", encoding="utf-8")
            (state_dir / "project-handoff.md").write_text("# Project Handoff\n", encoding="utf-8")
            (tests_dir / "test_sample.py").write_text(
                "import unittest\n\nclass ReleaseSmoke(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n",
                encoding="utf-8",
            )

            release_json = Path(tmp) / "release-provider.json"
            release_json.write_text(
                json.dumps({"provider": "deploy-provider", "status": "failed", "summary": "Release blocked"}, indent=2) + "\n",
                encoding="utf-8",
            )

            with mock.patch.dict(
                os.environ,
                {"SILIJIAN_RELEASE_PROVIDER_JSON": str(release_json)},
                clear=False,
            ):
                summary = evidence_collector.collect_evidence(project_root, force=True)

            self.assertEqual(summary["release"]["status"], "FAIL")
            self.assertEqual(summary["recommendation"], "BLOCKER")
            report = (reports_dir / "test-report.md").read_text(encoding="utf-8")
            self.assertIn("- BLOCKER", report)
            self.assertIn("- NO", report)
            gate_report = (reports_dir / "gate-report.md").read_text(encoding="utf-8")
            self.assertIn("- release verification: FAIL", gate_report)

    def test_run_orchestrator_does_not_mark_steps_active_when_command_transport_is_unconfigured(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            workflows_dir = project_root / "workflows"
            state_dir.mkdir(parents=True)
            workflows_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "current_phase": "executing",
                        "current_status": "executing",
                        "workflow_progress": {"completed_steps": ["intake-feature", "confirm-or-replan", "plan-approval"]},
                        "active_tasks": [],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text("{}\n", encoding="utf-8")
            (workflows_dir / "feature-delivery.yaml").write_text(
                (REPO_ROOT / "assets" / "project-skeleton" / "workflows" / "feature-delivery.yaml").read_text(encoding="utf-8"),
                encoding="utf-8",
            )

            result = run_orchestrator.run(project_root, max_dispatch=1, transport="command")
            self.assertEqual(result["status"], "pending-transport")
            self.assertEqual(result["dispatch_count"], 0)
            self.assertEqual(result["attempted_dispatch_count"], 1)
            self.assertEqual(result["dispatches"][0]["status"], "queued-awaiting-command-config")

            state = json.loads((state_dir / "orchestrator-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["active_tasks"], [])
            self.assertEqual(state["workflow_progress"]["dispatched_steps"], [])
            self.assertIn("Fix the transport", state["next_action"])

    def test_inbox_watcher_processes_payloads_and_archives_processed_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            inbox_dir = project_root / "ai" / "runtime" / "inbox"
            state_dir.mkdir(parents=True)
            inbox_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "active_tasks": [
                            {
                                "task_id": "LIBU2_IMPLEMENTATION-1",
                                "role": "libu2",
                                "status": "in-progress",
                                "handoff_path": "ai/handoff/libu2/active/LIBU2_IMPLEMENTATION-1.md",
                                "workflow_step_id": "libu2-implementation",
                            }
                        ],
                        "workflow_progress": {"completed_steps": ["plan-approval"], "blocked_steps": [], "dispatched_steps": ["libu2-implementation"]},
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text("{}\n", encoding="utf-8")
            (inbox_dir / "completion.json").write_text(
                json.dumps(
                    {
                        "agent_id": "libu2",
                        "task_id": "LIBU2_IMPLEMENTATION-1",
                        "workflow_step_id": "libu2-implementation",
                        "status": "completed",
                        "summary": "Processed from inbox.",
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = inbox_watcher.process_inbox(project_root)
            self.assertEqual(result["processed_count"], 1)
            self.assertEqual(result["failed_count"], 0)
            self.assertEqual(len(list(inbox_dir.glob("*.json"))), 0)
            self.assertTrue((inbox_dir / "processed" / "completion.json").exists())
            state = json.loads((state_dir / "orchestrator-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["active_tasks"], [])
            self.assertIn("libu2-implementation", state["workflow_progress"]["completed_steps"])

    def test_inbox_watcher_fuses_session_after_consecutive_invalid_completions(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            runtime_dir = project_root / "ai" / "runtime"
            inbox_dir = project_root / "ai" / "runtime" / "inbox"
            helper = Path(tmp) / "close_helper.py"
            state_dir.mkdir(parents=True)
            runtime_dir.mkdir(parents=True)
            inbox_dir.mkdir(parents=True)
            helper.write_text(
                """import json
import sys
from pathlib import Path

payload = Path(sys.argv[1]).resolve()
data = json.loads(payload.read_text(encoding='utf-8'))
payload.with_suffix('.closed.txt').write_text(data.get('session_key', ''), encoding='utf-8')
""",
                encoding="utf-8",
            )

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "active_tasks": [
                            {
                                "task_id": "LIBU2-REAL",
                                "role": "libu2",
                                "status": "in-progress",
                                "handoff_path": "ai/handoff/libu2/active/LIBU2-REAL.md",
                                "workflow_step_id": "libu2-implementation",
                            }
                        ],
                        "workflow_progress": {"completed_steps": ["plan-approval"], "blocked_steps": [], "dispatched_steps": ["libu2-implementation"]},
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text(
                json.dumps(
                    {
                        "libu2": {
                            "agent_id": "libu2",
                            "session_key": "sess-drift",
                            "status": "active",
                            "active_workflow": "feature-delivery",
                        }
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (runtime_dir / "runtime-config.json").write_text(
                json.dumps(
                    {
                        "close_session_command": f'"{sys.executable}" "{helper}" "{{payload_file}}"',
                        "host_interface_sources": {"close_session_command": "project-config"},
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            invalid_payload = {
                "agent_id": "libu2",
                "task_id": "FAKE-1",
                "workflow_step_id": "final-audit",
                "status": "completed",
            }

            with mock.patch.dict(os.environ, {"SILIJIAN_INVALID_COMPLETION_FUSE_THRESHOLD": "2"}, clear=False):
                (inbox_dir / "invalid-1.json").write_text(json.dumps(invalid_payload, indent=2) + "\n", encoding="utf-8")
                first = inbox_watcher.process_inbox(project_root)
                self.assertEqual(first["guarded_count"], 1)
                self.assertEqual(first["failed_count"], 0)

                (inbox_dir / "invalid-2.json").write_text(json.dumps(invalid_payload, indent=2) + "\n", encoding="utf-8")
                second = inbox_watcher.process_inbox(project_root)

            self.assertEqual(second["guarded_count"], 1)
            registry = json.loads((state_dir / "agent-sessions.json").read_text(encoding="utf-8"))
            self.assertEqual(registry["libu2"]["status"], "closed")
            self.assertTrue(registry["libu2"]["rebuild_required"])
            state = json.loads((state_dir / "orchestrator-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["active_tasks"][0]["status"], "closed")
            self.assertTrue((project_root / "ai" / "reports" / "agent-drift-guard-libu2.json").exists())

    def test_inbox_watcher_records_single_violation_for_guarded_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            inbox_dir = project_root / "ai" / "runtime" / "inbox"
            state_dir.mkdir(parents=True)
            inbox_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "active_tasks": [
                            {
                                "task_id": "STRICT-1",
                                "role": "libu2",
                                "status": "in-progress",
                                "handoff_path": "ai/handoff/libu2/active/STRICT-1.md",
                                "workflow_step_id": "libu2-implementation",
                                "skill_policy": "required",
                                "required_skills": ["libu2-implementation"],
                                "completion_schema_version": "v1",
                            }
                        ],
                        "workflow_progress": {"completed_steps": ["plan-approval"], "blocked_steps": [], "dispatched_steps": ["libu2-implementation"]},
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text("{}\n", encoding="utf-8")
            (inbox_dir / "bad.json").write_text(
                json.dumps(
                    {
                        "agent_id": "libu2",
                        "task_id": "STRICT-1",
                        "workflow_step_id": "libu2-implementation",
                        "status": "completed",
                        "summary": "invalid",
                        "completion_schema_version": "v1",
                        "execution_trace": {"execution_mode": "direct", "skills_used": [], "evidence_refs": ["e-1"]},
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            summary = inbox_watcher.process_inbox(project_root)
            self.assertEqual(summary["guarded_count"], 1)
            audit = json.loads((project_root / "ai" / "reports" / "agent-skill-usage.json").read_text(encoding="utf-8"))
            self.assertEqual(audit["totals"]["violations"], 1)
            self.assertEqual(len(audit["items"]), 1)
            self.assertEqual(audit["items"][-1]["violation_code"], "skill_policy_violation")

    def test_inbox_watcher_honors_state_skill_violation_fuse_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            state_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "automation_mode": "autonomous",
                        "skill_violation_fuse_threshold": 1,
                        "current_workflow": "feature-delivery",
                        "current_status": "executing",
                        "active_tasks": [],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text("{}\n", encoding="utf-8")

            payload = inbox_watcher.guard_invalid_completion(project_root, {"agent_id": "libu2"}, "protocol violation")

            self.assertIsNotNone(payload)
            self.assertEqual(payload["fuse_threshold"], 1)
            self.assertTrue(payload["fused"])
            registry = json.loads((state_dir / "agent-sessions.json").read_text(encoding="utf-8"))
            self.assertEqual(registry["libu2"]["status"], "closed")
            self.assertTrue(registry["libu2"]["rebuild_required"])

    def test_completion_consumer_marks_step_complete_and_updates_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            state_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "active_tasks": [
                            {
                                "task_id": "LIBU2_IMPLEMENTATION-1",
                                "role": "libu2",
                                "status": "in-progress",
                                "handoff_path": "ai/handoff/libu2/active/LIBU2_IMPLEMENTATION-1.md",
                                "workflow_step_id": "libu2-implementation",
                            }
                        ],
                        "workflow_progress": {"completed_steps": ["plan-approval"], "blocked_steps": [], "dispatched_steps": ["libu2-implementation"]},
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text("{}\n", encoding="utf-8")

            result = completion_consumer.consume_completion(
                project_root,
                {
                    "agent_id": "libu2",
                    "task_id": "LIBU2_IMPLEMENTATION-1",
                    "workflow_step_id": "libu2-implementation",
                    "status": "completed",
                    "summary": "Backend implementation finished.",
                    "files_touched": ["src/api/user.ts"],
                    "session_key": "session-libu2",
                },
            )
            self.assertEqual(result["status"], "completed")
            state = json.loads((state_dir / "orchestrator-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["active_tasks"], [])
            self.assertIn("libu2-implementation", state["workflow_progress"]["completed_steps"])
            registry = json.loads((state_dir / "agent-sessions.json").read_text(encoding="utf-8"))
            self.assertEqual(registry["libu2"]["status"], "waiting")
            decision = session_registry.session_reuse_decision(project_root, "libu2", workflow_name="feature-delivery")
            self.assertEqual(decision["session_key"], "session-libu2")
            self.assertEqual(decision["status"], "send")
            self.assertTrue((project_root / "ai" / "handoff" / "libu2" / "active" / "LIBU2_IMPLEMENTATION-1.md").exists())
            self.assertEqual(result["next_owner"], "orchestrator")
            self.assertFalse(result["requires_confirmation"])
            self.assertEqual(result["continuation_mode"], "manual-trigger-required")
            self.assertIn("Review completion from libu2", result["next_action"])
            self.assertIn("next_owner=orchestrator", result["next_step_summary"])
            self.assertIn("Manual trigger needed", result["next_step_hint"])

    def test_completion_consumer_rejects_required_skill_policy_without_skill_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            state_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "active_tasks": [
                            {
                                "task_id": "LIBU2_IMPLEMENTATION-STRICT",
                                "role": "libu2",
                                "status": "in-progress",
                                "handoff_path": "ai/handoff/libu2/active/LIBU2_IMPLEMENTATION-STRICT.md",
                                "workflow_step_id": "libu2-implementation",
                                "skill_policy": "required",
                                "required_skills": ["libu2-implementation"],
                                "completion_schema_version": "v1",
                            }
                        ],
                        "workflow_progress": {"completed_steps": ["plan-approval"], "blocked_steps": [], "dispatched_steps": ["libu2-implementation"]},
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text("{}\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "skill_policy=required"):
                completion_consumer.consume_completion(
                    project_root,
                    {
                        "agent_id": "libu2",
                        "task_id": "LIBU2_IMPLEMENTATION-STRICT",
                        "workflow_step_id": "libu2-implementation",
                        "status": "completed",
                        "summary": "Finished without skill trace.",
                        "completion_schema_version": "v1",
                        "execution_trace": {
                            "execution_mode": "direct",
                            "skills_used": [],
                            "evidence_refs": ["proof-1"],
                        },
                    },
                )

            audit = json.loads((project_root / "ai" / "reports" / "agent-skill-usage.json").read_text(encoding="utf-8"))
            self.assertGreaterEqual(audit["totals"]["violations"], 1)
            self.assertEqual(audit["items"][-1]["violation_code"], "skill_policy_violation")
            state = json.loads((state_dir / "orchestrator-state.json").read_text(encoding="utf-8"))
            self.assertEqual(len(state["active_tasks"]), 1)

    def test_completion_consumer_records_skill_usage_for_compliant_required_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            state_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "active_tasks": [
                            {
                                "task_id": "LIBU2_IMPLEMENTATION-STRICT",
                                "role": "libu2",
                                "status": "in-progress",
                                "handoff_path": "ai/handoff/libu2/active/LIBU2_IMPLEMENTATION-STRICT.md",
                                "workflow_step_id": "libu2-implementation",
                                "skill_policy": "required",
                                "required_skills": ["libu2-implementation"],
                                "completion_schema_version": "v1",
                            }
                        ],
                        "workflow_progress": {"completed_steps": ["plan-approval"], "blocked_steps": [], "dispatched_steps": ["libu2-implementation"]},
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text("{}\n", encoding="utf-8")

            result = completion_consumer.consume_completion(
                project_root,
                {
                    "agent_id": "libu2",
                    "task_id": "LIBU2_IMPLEMENTATION-STRICT",
                    "workflow_step_id": "libu2-implementation",
                    "status": "completed",
                    "summary": "Finished with required skill trace.",
                    "completion_schema_version": "v1",
                    "execution_trace": {
                        "execution_mode": "skill",
                        "skills_used": ["libu2-implementation"],
                        "evidence_refs": ["proof-1"],
                    },
                },
            )

            self.assertEqual(result["status"], "completed")
            audit = json.loads((project_root / "ai" / "reports" / "agent-skill-usage.json").read_text(encoding="utf-8"))
            self.assertEqual(audit["totals"]["violations"], 0)
            self.assertEqual(audit["totals"]["compliant"], 1)
            self.assertEqual(audit["items"][-1]["skills_used"], ["libu2-implementation"])

    def test_completion_consumer_rejects_untracked_peer_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            state_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "active_tasks": [],
                        "workflow_progress": {"completed_steps": [], "blocked_steps": [], "dispatched_steps": []},
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text("{}\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "does not match any active task"):
                completion_consumer.consume_completion(
                    project_root,
                    {
                        "agent_id": "libu2",
                        "task_id": "FAKE-1",
                        "workflow_step_id": "final-audit",
                        "status": "completed",
                    },
                )

    def test_completion_consumer_keeps_other_active_blockers_after_successful_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            state_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "current_status": "blocked",
                        "active_tasks": [
                            {
                                "task_id": "HUBU-1",
                                "role": "hubu",
                                "status": "blocked",
                                "handoff_path": "ai/handoff/hubu/active/HUBU-1.md",
                                "workflow_step_id": "hubu-implementation",
                                "blockers": ["schema drift"],
                            },
                            {
                                "task_id": "LIBU2-1",
                                "role": "libu2",
                                "status": "in-progress",
                                "handoff_path": "ai/handoff/libu2/active/LIBU2-1.md",
                                "workflow_step_id": "libu2-implementation",
                            },
                        ],
                        "workflow_progress": {
                            "completed_steps": ["intake-feature", "confirm-or-replan", "plan-approval"],
                            "blocked_steps": ["hubu-implementation"],
                            "dispatched_steps": ["libu2-implementation"],
                        },
                        "blockers": ["schema drift"],
                        "blocker_level": "high",
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text("{}\n", encoding="utf-8")

            result = completion_consumer.consume_completion(
                project_root,
                {
                    "agent_id": "libu2",
                    "task_id": "LIBU2-1",
                    "workflow_step_id": "libu2-implementation",
                    "status": "completed",
                    "summary": "libu2 done",
                },
            )

            self.assertEqual(result["status"], "completed")
            state = json.loads((state_dir / "orchestrator-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["current_status"], "blocked")
            self.assertEqual(state["blockers"], ["schema drift"])
            self.assertEqual(state["blocker_level"], "high")
            self.assertEqual(len(state["active_tasks"]), 1)
            self.assertEqual(state["active_tasks"][0]["task_id"], "HUBU-1")

    def test_completion_consumer_restores_previous_status_after_last_blocker_clears(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            state_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "current_phase": "executing",
                        "current_status": "blocked",
                        "status_before_blocked": "executing",
                        "active_tasks": [
                            {
                                "task_id": "LIBU2-1",
                                "role": "libu2",
                                "status": "blocked",
                                "handoff_path": "ai/handoff/libu2/active/LIBU2-1.md",
                                "workflow_step_id": "libu2-implementation",
                                "blockers": ["schema drift"],
                            }
                        ],
                        "workflow_progress": {
                            "completed_steps": ["plan-approval"],
                            "blocked_steps": ["libu2-implementation"],
                            "dispatched_steps": [],
                        },
                        "blockers": ["schema drift"],
                        "blocker_level": "high",
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text("{}\n", encoding="utf-8")

            result = completion_consumer.consume_completion(
                project_root,
                {
                    "agent_id": "libu2",
                    "task_id": "LIBU2-1",
                    "workflow_step_id": "libu2-implementation",
                    "status": "completed",
                    "summary": "fixed",
                },
            )

            self.assertEqual(result["status"], "completed")
            state = json.loads((state_dir / "orchestrator-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["current_status"], "executing")
            self.assertEqual(state["blockers"], [])
            self.assertNotIn("status_before_blocked", state)

    def test_completion_consumer_recovers_workflow_step_id_from_active_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            state_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "active_tasks": [
                            {
                                "task_id": "LIBU2_IMPLEMENTATION-1",
                                "role": "libu2",
                                "status": "in-progress",
                                "handoff_path": "ai/handoff/libu2/active/LIBU2_IMPLEMENTATION-1.md",
                                "workflow_step_id": "libu2-implementation",
                            }
                        ],
                        "workflow_progress": {
                            "completed_steps": ["plan-approval"],
                            "blocked_steps": [],
                            "dispatched_steps": ["libu2-implementation"],
                        },
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text("{}\n", encoding="utf-8")

            result = completion_consumer.consume_completion(
                project_root,
                {
                    "agent_id": "libu2",
                    "task_id": "LIBU2_IMPLEMENTATION-1",
                    "status": "completed",
                    "summary": "Backend implementation finished.",
                },
            )

            self.assertEqual(result["workflow_step_id"], "libu2-implementation")
            state = json.loads((state_dir / "orchestrator-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["active_tasks"], [])
            self.assertIn("libu2-implementation", state["workflow_progress"]["completed_steps"])
            self.assertNotIn("libu2-implementation", state["workflow_progress"]["dispatched_steps"])

    def test_completion_consumer_rejects_handoff_path_outside_project_handoff_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            state_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "active_tasks": [],
                        "workflow_progress": {"completed_steps": [], "blocked_steps": [], "dispatched_steps": []},
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text("{}\n", encoding="utf-8")
            escaped_path = project_root.parent / "outside-handoff.md"
            if escaped_path.exists():
                escaped_path.unlink()

            with self.assertRaisesRegex(ValueError, "handoff_path escapes ai/handoff root"):
                completion_consumer.consume_completion(
                    project_root,
                    {
                        "agent_id": "libu2",
                        "task_id": "TASK-1",
                        "workflow_step_id": "libu2-implementation",
                        "status": "completed",
                        "handoff_path": "../outside-handoff.md",
                    },
                )

            self.assertFalse(escaped_path.exists())
            state = json.loads((state_dir / "orchestrator-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["active_tasks"], [])
            self.assertEqual(state["workflow_progress"]["completed_steps"], [])

    def test_escalation_manager_writes_report_for_blocked_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)
            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "current_status": "blocked",
                        "next_owner": "orchestrator",
                        "blockers": ["ci failing"],
                        "last_dispatch_batch": {"items": [{"step_id": "bingbu-testing", "status": "failed"}]},
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (reports_dir / "evidence-summary.json").write_text(
                json.dumps({"recommendation": "BLOCKER", "blockers": ["test command failed"]}, indent=2) + "\n",
                encoding="utf-8",
            )
            (reports_dir / "inbox-watch-summary.json").write_text(
                json.dumps({"failed_count": 1}, indent=2) + "\n",
                encoding="utf-8",
            )

            payload = escalation_manager.generate_escalation(project_root)
            self.assertEqual(payload["status"], "escalated")
            self.assertTrue(payload["items"])
            self.assertTrue((reports_dir / "escalation-report.md").exists())

    def test_escalation_manager_detects_provider_failure_and_approval_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)
            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "current_status": "department-review",
                        "next_owner": "duchayuan",
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (reports_dir / "provider-evidence-summary.json").write_text(
                json.dumps(
                    {
                        "results": {
                            "ci": {"status": "PASS", "provider": "github-actions", "summary": "green"},
                            "release": {"status": "FAIL", "provider": "deploy-provider", "summary": "release failed"},
                            "rollback": {"status": "PASS_WITH_WARNING", "provider": "deploy-provider", "summary": "rollback pending"},
                        }
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            (reports_dir / "department-approval-matrix.md").write_text(
                """# Department Approval Matrix

## Aggregated Issues
- blockers: none
- warnings: none
- suggestions: none
- conflicts needing arbitration: schema mismatch unresolved

## Reviewer xingbu
- closure: waiting for sign-off
""",
                encoding="utf-8",
            )
            (state_dir / "risk-report.md").write_text(
                "# Risk Report\n\n- HIGH schema migration without confirmed rollback rehearsal\n",
                encoding="utf-8",
            )

            payload = escalation_manager.generate_escalation(project_root)
            joined = "\n".join(payload["items"])
            self.assertEqual(payload["status"], "escalated")
            self.assertIn("release provider failure", joined)
            self.assertIn("approval conflict needs arbitration", joined)
            self.assertIn("high-risk change noted in risk report", joined)
            self.assertGreaterEqual(payload["severity_counts"]["error"], 2)

    def test_escalation_manager_can_disable_window_notifications_from_string_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)
            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "current_status": "blocked",
                        "window_notification_on_escalation": "false",
                        "next_owner": "orchestrator",
                        "blockers": ["ci failing"],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            payload = escalation_manager.generate_escalation(project_root)
            self.assertEqual(payload["status"], "escalated")
            self.assertFalse(payload["window_notification_required"])
            self.assertIsNone(payload["window_notification"])

    def test_parent_session_recovery_builds_resume_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)
            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "current_status": "department-review",
                        "next_owner": "duchayuan",
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text(
                json.dumps({"orchestrator": {"session_key": "sess-1", "last_step_id": "department-review", "handoff_path": "ai/handoff/orchestrator/active/TASK.md"}}, indent=2)
                + "\n",
                encoding="utf-8",
            )
            (reports_dir / "runtime-loop-summary.json").write_text(json.dumps({"status": "escalated"}, indent=2) + "\n", encoding="utf-8")
            (reports_dir / "escalation-report.json").write_text(json.dumps({"status": "escalated", "items": ["review conflict"]}, indent=2) + "\n", encoding="utf-8")

            payload = parent_session_recovery.build_parent_recovery(project_root)
            self.assertIn("sess-1", payload["resume_prompt"])
            self.assertEqual(payload["escalation_status"], "escalated")

    def test_runtime_environment_auto_configures_parent_attach_bridge(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            bootstrap = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "bootstrap_governance.py"),
                    str(project_root),
                    "--project-name",
                    "demo",
                    "--project-id",
                    "demo",
                    "--skill-root",
                    str(REPO_ROOT),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)

            payload = runtime_environment.ensure_runtime_environment(project_root)
            config = json.loads((project_root / "ai" / "runtime" / "runtime-config.json").read_text(encoding="utf-8"))

            self.assertEqual(payload["command_source"], "project-config")
            self.assertIn("openclaw_runtime_bridge.py", config["parent_attach_command"])
            self.assertIn("parent_attach_command", payload["auto_configured_fields"])
            self.assertTrue((project_root / "ai" / "reports" / "runtime-environment.json").exists())

    def test_runtime_environment_prefers_host_config_over_auto_generated_parent_attach(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            (project_root / "ai" / "tools").mkdir(parents=True)
            (project_root / "ai" / "tools" / "openclaw_runtime_bridge.py").write_text("print('bridge')\n", encoding="utf-8")
            config_file = Path(tmp) / "openclaw-config.json"

            with mock.patch.dict(os.environ, {"OPENCLAW_CONFIG_PATH": str(config_file)}, clear=False):
                first = runtime_environment.ensure_runtime_environment(project_root)
                config_file.write_text(
                    json.dumps({"parent_attach_command": "custom-parent --payload {payload_file}"}, indent=2) + "\n",
                    encoding="utf-8",
                )
                second = runtime_environment.ensure_runtime_environment(project_root)

            config = json.loads((project_root / "ai" / "runtime" / "runtime-config.json").read_text(encoding="utf-8"))
            self.assertIn("openclaw_runtime_bridge.py", first["effective_parent_attach_command"])
            self.assertEqual(second["effective_parent_attach_command"], "custom-parent --payload {payload_file}")
            self.assertEqual(second["command_source"], "config-file")
            self.assertEqual(config["parent_attach_command"], "custom-parent --payload {payload_file}")
            self.assertFalse(config["parent_attach_command_auto_generated"])

    def test_runtime_environment_preserves_invalid_runtime_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            runtime_dir = project_root / "ai" / "runtime"
            tools_dir = project_root / "ai" / "tools"
            runtime_dir.mkdir(parents=True)
            tools_dir.mkdir(parents=True)
            (tools_dir / "openclaw_runtime_bridge.py").write_text("print('bridge')\n", encoding="utf-8")
            config_path = runtime_dir / "runtime-config.json"
            config_path.write_text("{ invalid", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "runtime-config.json"):
                runtime_environment.ensure_runtime_environment(project_root)

            self.assertEqual(config_path.read_text(encoding="utf-8"), "{ invalid")
            backups = list(runtime_dir.glob("runtime-config.json.corrupt-*.bak"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "{ invalid")

    def test_host_interface_probe_reads_machine_visible_commands_into_runtime_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            runtime_dir = project_root / "ai" / "runtime"
            runtime_dir.mkdir(parents=True)
            config_file = Path(tmp) / "openclaw-config.json"
            config_file.write_text(
                json.dumps(
                    {
                        "commands": {
                            "spawn_command": "spawn-from-config",
                            "send_command": "send-from-config",
                        }
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            with mock.patch.dict(
                os.environ,
                {
                    "OPENCLAW_CONFIG_PATH": str(config_file),
                    "OPENCLAW_PARENT_ATTACH_COMMAND": "attach-from-env",
                },
                clear=False,
            ):
                probe = host_interface_probe.probe_host_interfaces(project_root)
                config = host_interface_probe.sync_runtime_config_from_probe(project_root, probe)

            self.assertEqual(probe["selected_commands"]["parent_attach_command"], "attach-from-env")
            self.assertEqual(probe["selected_commands"]["spawn_command"], "spawn-from-config")
            self.assertEqual(config["parent_attach_command"], "attach-from-env")
            self.assertEqual(config["spawn_command"], "spawn-from-config")
            self.assertEqual(config["send_command"], "send-from-config")
            self.assertTrue((project_root / "ai" / "reports" / "host-interface-probe.json").exists())

    def test_render_project_handoff_uses_report_conclusions(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            reports_dir = project_root / "ai" / "reports"
            state_dir = project_root / "ai" / "state"
            reports_dir.mkdir(parents=True)
            state_dir.mkdir(parents=True)
            (reports_dir / "architecture-review.md").write_text("# Architecture Review\n\n## Conclusion\n\n- PASS\n", encoding="utf-8")
            (reports_dir / "acceptance-report.md").write_text(
                "# Acceptance Report\n\n## Final Conclusion\n\n- PASS_WITH_WARNING\n",
                encoding="utf-8",
            )
            (reports_dir / "test-report.md").write_text("# Test Report\n\n## Recommendation\n\n- PASS\n", encoding="utf-8")

            rendered = orchestrator_local_steps.render_project_handoff(
                project_root,
                {
                    "current_status": "accepted",
                    "current_phase": "final-audit",
                    "current_workflow": "feature-delivery",
                    "workflow_progress": {},
                    "active_tasks": [],
                },
            )

            self.assertIn("- Latest plan review conclusion: PASS", rendered)
            self.assertIn("- Latest result audit conclusion: PASS_WITH_WARNING", rendered)
            self.assertIn("- Latest test conclusion: PASS", rendered)

    def test_environment_bootstrap_installs_python_requirements(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            bootstrap = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "bootstrap_governance.py"),
                    str(project_root),
                    "--project-name",
                    "demo",
                    "--project-id",
                    "demo",
                    "--skill-root",
                    str(REPO_ROOT),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)
            (project_root / "requirements.txt").write_text("requests==2.0.0\n", encoding="utf-8")

            calls: list[str] = []

            def fake_run(command, cwd=None, capture_output=None, text=None, shell=None, check=None):
                calls.append(str(command))
                return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

            with mock.patch("environment_bootstrap.subprocess.run", side_effect=fake_run):
                payload = environment_bootstrap.ensure_environment(project_root, apply=True, include_system_tools=False)

            self.assertIn(payload["status"], {"tooling-pending", "runtime-blocked", "ready"})
            self.assertTrue(any("pip install -r" in call for call in calls))
            self.assertEqual(payload["dependency_actions"][0]["status"], "completed")
            self.assertTrue((project_root / "ai" / "reports" / "environment-bootstrap.json").exists())

    def test_openclaw_adapter_uses_runtime_config_command_when_env_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            helper = Path(tmp) / "transport_helper.py"
            write_transport_helper(helper)
            runtime_dir = project_root / "ai" / "runtime"
            runtime_dir.mkdir(parents=True)
            (runtime_dir / "runtime-config.json").write_text(
                json.dumps(
                    {
                        "spawn_command": f'"{sys.executable}" "{helper}" "{{dispatch_file}}"',
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            with mock.patch.dict(os.environ, {"OPENCLAW_SPAWN_COMMAND": ""}, clear=False):
                envelope = openclaw_adapter.dispatch_payload(
                    project_root,
                    {"task": "demo"},
                    "spawn",
                    "libu2",
                    transport="command",
                )

            self.assertEqual(envelope["status"], "sent")
            inbox_items = list((project_root / "ai" / "runtime" / "inbox").glob("*.json"))
            self.assertEqual(len(inbox_items), 1)

    def test_openclaw_adapter_marks_failed_for_invalid_command_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            runtime_dir = project_root / "ai" / "runtime"
            runtime_dir.mkdir(parents=True)
            (runtime_dir / "runtime-config.json").write_text(
                json.dumps({"spawn_command": "echo {missing_placeholder}"}, indent=2) + "\n",
                encoding="utf-8",
            )

            with mock.patch.dict(os.environ, {"OPENCLAW_SPAWN_COMMAND": ""}, clear=False):
                envelope = openclaw_adapter.dispatch_payload(
                    project_root,
                    {"task": "demo"},
                    "spawn",
                    "libu2",
                    transport="command",
                )

            self.assertEqual(envelope["status"], "failed")
            self.assertIn("unknown placeholder", str(envelope.get("stderr") or "").lower())

    def test_openclaw_adapter_generates_unique_dispatch_ids_for_same_agent_same_second(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"

            first = openclaw_adapter.dispatch_payload(project_root, {"task": "demo-1"}, "spawn", "libu2", transport="outbox")
            second = openclaw_adapter.dispatch_payload(project_root, {"task": "demo-2"}, "spawn", "libu2", transport="outbox")

            self.assertNotEqual(first["dispatch_id"], second["dispatch_id"])
            outbox_items = list((project_root / "ai" / "runtime" / "outbox").glob("*.json"))
            self.assertEqual(len(outbox_items), 2)

    def test_openclaw_adapter_sanitizes_dispatch_path_for_agent_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            project_root.mkdir(parents=True)

            envelope = openclaw_adapter.dispatch_payload(
                project_root,
                {"task": "demo"},
                "spawn",
                "..\\..\\..\\evil",
                transport="outbox",
            )

            self.assertNotIn("..", envelope["dispatch_id"])
            outbox = (project_root / "ai" / "runtime" / "outbox").resolve()
            outbox_items = list(outbox.glob("*.json"))
            self.assertEqual(len(outbox_items), 1)
            self.assertEqual(outbox_items[0].stem, envelope["dispatch_id"])
            outbox_items[0].resolve().relative_to(outbox)

    def test_session_registry_reuses_only_same_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            (project_root / "ai" / "state").mkdir(parents=True)

            session_registry.upsert_session(
                project_root,
                "libu2",
                session_key="sess-libu2",
                status="active",
                active_workflow="takeover-project",
            )

            self.assertIsNone(session_registry.reusable_session_key(project_root, "libu2", workflow_name="feature-delivery"))
            self.assertEqual(
                session_registry.reusable_session_key(project_root, "libu2", workflow_name="takeover-project"),
                "sess-libu2",
            )

    def test_session_registry_refuses_reuse_when_session_budget_is_exhausted(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            (project_root / "ai" / "state").mkdir(parents=True)

            session_registry.upsert_session(
                project_root,
                "libu2",
                session_key="sess-libu2",
                status="active",
                active_workflow="feature-delivery",
                completion_count=3,
                dispatch_count=3,
            )

            with mock.patch.dict(os.environ, {"SILIJIAN_SESSION_COMPLETION_LIMIT": "3"}, clear=False):
                decision = session_registry.session_reuse_decision(project_root, "libu2", workflow_name="feature-delivery")

            self.assertIsNone(decision["session_key"])
            self.assertTrue(decision["should_retire"])
            self.assertIn("completion_count", decision["reason"])

    def test_run_orchestrator_blocks_when_session_rollover_close_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            runtime_dir = project_root / "ai" / "runtime"
            workflows_dir = project_root / "workflows"
            state_dir.mkdir(parents=True)
            runtime_dir.mkdir(parents=True)
            workflows_dir.mkdir(parents=True)
            helper = Path(tmp) / "close_fail.py"
            helper.write_text("raise SystemExit(1)\n", encoding="utf-8")

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "current_phase": "executing",
                        "current_status": "executing",
                        "workflow_progress": {
                            "completed_steps": ["intake-feature", "confirm-or-replan", "plan-approval"],
                            "blocked_steps": [],
                            "dispatched_steps": [],
                        },
                        "active_tasks": [],
                        "session_rotation_policy": {
                            "default": {
                                "max_completion_count": 4,
                                "max_dispatch_count": 1,
                                "max_task_round_count": 3,
                            },
                            "agents": {},
                        },
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text(
                json.dumps(
                    {
                        "libu2": {
                            "agent_id": "libu2",
                            "session_key": "sess-existing",
                            "status": "active",
                            "active_workflow": "feature-delivery",
                            "dispatch_count": 1,
                        }
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (runtime_dir / "runtime-config.json").write_text(
                json.dumps(
                    {
                        "close_session_command": f'"{sys.executable}" "{helper}" "{{payload_file}}"',
                        "host_interface_sources": {"close_session_command": "project-config"},
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (workflows_dir / "feature-delivery.yaml").write_text(
                (REPO_ROOT / "assets" / "project-skeleton" / "workflows" / "feature-delivery.yaml").read_text(
                    encoding="utf-8"
                ),
                encoding="utf-8",
            )

            result = run_orchestrator.run(project_root, max_dispatch=1, transport="outbox")

            self.assertEqual(result["status"], "session-rollover-blocked")
            self.assertEqual(result["dispatch_count"], 0)
            self.assertEqual(result["dispatches"][0]["status"], "session-rollover-blocked")
            self.assertEqual(len(list((project_root / "ai" / "runtime" / "outbox").glob("*.json"))), 0)
            registry = json.loads((state_dir / "agent-sessions.json").read_text(encoding="utf-8"))
            self.assertEqual(registry["libu2"]["status"], "active")
            self.assertEqual(registry["libu2"]["session_key"], "sess-existing")
            state = json.loads((state_dir / "orchestrator-state.json").read_text(encoding="utf-8"))
            self.assertIn("Session rollover is blocked", state["next_action"])

    def test_environment_bootstrap_reports_missing_system_tool_installers(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            bootstrap = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "bootstrap_governance.py"),
                    str(project_root),
                    "--project-name",
                    "demo",
                    "--project-id",
                    "demo",
                    "--skill-root",
                    str(REPO_ROOT),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)
            workflows_dir = project_root / ".github" / "workflows"
            workflows_dir.mkdir(parents=True, exist_ok=True)
            (workflows_dir / "ci.yml").write_text("name: ci\n", encoding="utf-8")

            with mock.patch("environment_bootstrap.executable_available", side_effect=lambda name: False if name == "gh" else True):
                payload = environment_bootstrap.ensure_environment(project_root, apply=False, include_system_tools=True)

            self.assertIn("gh", payload["missing_system_tools"])
            gh_entry = next(item for item in payload["system_tool_actions"] if item["tool"] == "gh")
            self.assertEqual(gh_entry["status"], "blocked")
            self.assertIn("No install command configured", gh_entry["blocked_reason"])

    def test_environment_bootstrap_does_not_flag_python_when_sys_executable_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            project_root.mkdir(parents=True, exist_ok=True)

            with mock.patch("environment_bootstrap.required_system_tools", return_value=["python"]):
                with mock.patch("environment_bootstrap.shutil.which", return_value=None):
                    missing = environment_bootstrap.missing_system_tools(project_root)

            self.assertEqual(missing, [])

    def test_environment_bootstrap_reuses_cached_dependency_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            bootstrap = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "bootstrap_governance.py"),
                    str(project_root),
                    "--project-name",
                    "demo",
                    "--project-id",
                    "demo",
                    "--skill-root",
                    str(REPO_ROOT),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)
            (project_root / "requirements.txt").write_text("requests==2.0.0\n", encoding="utf-8")

            with mock.patch(
                "environment_bootstrap.run_action",
                return_value={"command": "pip", "returncode": 0, "stdout": "ok", "stderr": "", "status": "completed"},
            ) as first_run:
                first = environment_bootstrap.ensure_environment(project_root, apply=True, include_system_tools=False)

            self.assertEqual(first["dependency_actions"][0]["status"], "completed")
            self.assertEqual(first_run.call_count, 1)

            with mock.patch("environment_bootstrap.run_action") as second_run:
                second = environment_bootstrap.ensure_environment(project_root, apply=True, include_system_tools=False)

            self.assertEqual(second["dependency_actions"][0]["status"], "cached")
            second_run.assert_not_called()

    def test_parent_session_recovery_attempts_reattach_when_command_is_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            helper = Path(tmp) / "reattach_helper.py"
            write_reattach_helper(helper)
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)
            (state_dir / "orchestrator-state.json").write_text(
                json.dumps({"current_workflow": "feature-delivery", "current_status": "department-review", "next_owner": "orchestrator"}, indent=2)
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text(
                json.dumps({"orchestrator": {"session_key": "sess-reattach", "last_step_id": "department-review"}}, indent=2)
                + "\n",
                encoding="utf-8",
            )
            (reports_dir / "runtime-loop-summary.json").write_text(json.dumps({"status": "active"}, indent=2) + "\n", encoding="utf-8")
            (reports_dir / "escalation-report.json").write_text(json.dumps({"status": "clear", "items": []}, indent=2) + "\n", encoding="utf-8")

            payload = parent_session_recovery.build_parent_recovery(project_root)
            with mock.patch.dict(os.environ, {"OPENCLAW_PARENT_ATTACH_COMMAND": f'"{sys.executable}" "{helper}" "{{payload_file}}"'}):
                result = parent_session_recovery.attempt_reattach(project_root, payload)

            self.assertEqual(result["status"], "attached")
            marker = project_root / "ai" / "runtime" / "reattach" / "orchestrator-parent-reattach.attached.txt"
            self.assertTrue(marker.exists())
            self.assertEqual(marker.read_text(encoding="utf-8"), "sess-reattach")

    def test_parent_session_recovery_uses_project_runtime_config_when_env_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            helper = Path(tmp) / "reattach_helper.py"
            write_reattach_helper(helper)
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            runtime_dir = project_root / "ai" / "runtime"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)
            runtime_dir.mkdir(parents=True)
            (state_dir / "orchestrator-state.json").write_text(
                json.dumps({"current_workflow": "feature-delivery", "current_status": "department-review", "automation_mode": "autonomous"}, indent=2)
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text(
                json.dumps({"orchestrator": {"session_key": "sess-config", "last_step_id": "department-review"}}, indent=2)
                + "\n",
                encoding="utf-8",
            )
            (reports_dir / "runtime-loop-summary.json").write_text(json.dumps({"status": "active"}, indent=2) + "\n", encoding="utf-8")
            (reports_dir / "escalation-report.json").write_text(json.dumps({"status": "clear", "items": []}, indent=2) + "\n", encoding="utf-8")
            (runtime_dir / "runtime-config.json").write_text(
                json.dumps(
                    {
                        "parent_attach_command": f'"{sys.executable}" "{helper}" "{{payload_file}}"',
                        "bridge_available": False,
                        "openclaw_cli_available": False,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            payload = parent_session_recovery.build_parent_recovery(project_root)
            with mock.patch.dict(os.environ, {"OPENCLAW_PARENT_ATTACH_COMMAND": ""}, clear=False):
                result = parent_session_recovery.write_recovery_artifacts(project_root, payload)

            self.assertEqual(result["reattach_status"], "attached")
            self.assertEqual(result["reattach_attempt"]["command_source"], "project-config")

    def test_parent_session_recovery_auto_attempts_reattach_when_writing_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            helper = Path(tmp) / "reattach_helper.py"
            write_reattach_helper(helper)
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)
            (state_dir / "orchestrator-state.json").write_text(
                json.dumps({"current_workflow": "feature-delivery", "current_status": "department-review", "automation_mode": "autonomous"}, indent=2)
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text(
                json.dumps({"orchestrator": {"session_key": "sess-auto", "last_step_id": "department-review"}}, indent=2)
                + "\n",
                encoding="utf-8",
            )
            (reports_dir / "runtime-loop-summary.json").write_text(json.dumps({"status": "active"}, indent=2) + "\n", encoding="utf-8")
            (reports_dir / "escalation-report.json").write_text(json.dumps({"status": "clear", "items": []}, indent=2) + "\n", encoding="utf-8")

            payload = parent_session_recovery.build_parent_recovery(project_root)
            with mock.patch.dict(os.environ, {"OPENCLAW_PARENT_ATTACH_COMMAND": f'"{sys.executable}" "{helper}" "{{payload_file}}"'}):
                result = parent_session_recovery.write_recovery_artifacts(project_root, payload)

            self.assertEqual(result["reattach_status"], "attached")
            self.assertEqual(result["reattach_attempt"]["status"], "attached")
            report = json.loads((reports_dir / "parent-session-recovery.json").read_text(encoding="utf-8"))
            self.assertEqual(report["reattach_status"], "attached")

    def test_parent_session_recovery_skips_duplicate_auto_reattach_for_same_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            helper = Path(tmp) / "reattach_helper.py"
            write_reattach_helper(helper)
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)
            (state_dir / "orchestrator-state.json").write_text(
                json.dumps({"current_workflow": "feature-delivery", "current_status": "department-review", "automation_mode": "autonomous"}, indent=2)
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text(
                json.dumps({"orchestrator": {"session_key": "sess-auto", "last_step_id": "department-review"}}, indent=2)
                + "\n",
                encoding="utf-8",
            )
            (reports_dir / "runtime-loop-summary.json").write_text(json.dumps({"status": "active"}, indent=2) + "\n", encoding="utf-8")
            (reports_dir / "escalation-report.json").write_text(json.dumps({"status": "clear", "items": []}, indent=2) + "\n", encoding="utf-8")

            payload = parent_session_recovery.build_parent_recovery(project_root)
            with mock.patch.dict(os.environ, {"OPENCLAW_PARENT_ATTACH_COMMAND": f'"{sys.executable}" "{helper}" "{{payload_file}}"'}):
                first = parent_session_recovery.write_recovery_artifacts(project_root, payload)
                second = parent_session_recovery.write_recovery_artifacts(project_root, parent_session_recovery.build_parent_recovery(project_root))

            self.assertEqual(first["reattach_status"], "attached")
            self.assertEqual(second["reattach_status"], "attached")
            self.assertIn("duplicate attach attempt", second["reattach_attempt"]["blocked_reason"])

    def test_parent_session_recovery_marks_attach_failed_for_invalid_command_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)
            (state_dir / "orchestrator-state.json").write_text(
                json.dumps({"current_workflow": "feature-delivery", "current_status": "department-review", "automation_mode": "autonomous"}, indent=2)
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text(
                json.dumps({"orchestrator": {"session_key": "sess-bad-template", "last_step_id": "department-review"}}, indent=2)
                + "\n",
                encoding="utf-8",
            )
            (reports_dir / "runtime-loop-summary.json").write_text(json.dumps({"status": "active"}, indent=2) + "\n", encoding="utf-8")
            (reports_dir / "escalation-report.json").write_text(json.dumps({"status": "clear", "items": []}, indent=2) + "\n", encoding="utf-8")

            payload = parent_session_recovery.build_parent_recovery(project_root)
            with mock.patch.dict(os.environ, {"OPENCLAW_PARENT_ATTACH_COMMAND": "echo {missing_placeholder}"}):
                result = parent_session_recovery.write_recovery_artifacts(project_root, payload, auto_reattach=True, force_reattach=True)

            self.assertEqual(result["reattach_status"], "attach-failed")
            self.assertIn("unknown placeholder", str(result["reattach_blocked_reason"]).lower())

    def test_openclaw_runtime_bridge_tries_parent_attach_cli_variants(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp_root = Path(tmp)
            payload_path = temp_root / "orchestrator-parent-reattach.json"
            payload_path.write_text(
                json.dumps({"session_key": "sess-cli", "resume_prompt": "resume"}, indent=2) + "\n",
                encoding="utf-8",
            )
            cli_dir = temp_root / "cli"
            write_fake_openclaw_cli(cli_dir)
            env = dict(os.environ)
            env["PATH"] = str(cli_dir) + os.pathsep + env.get("PATH", "")

            completed = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "openclaw_runtime_bridge.py"), "parent-attach", str(payload_path)],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(completed.stdout)
            self.assertEqual(report["status"], "attached")
            self.assertTrue((payload_path.with_suffix(".cli-attached.txt")).exists())

    def test_openclaw_runtime_bridge_tries_close_session_cli_variants(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp_root = Path(tmp)
            payload_path = temp_root / "orchestrator-close-session.json"
            payload_path.write_text(
                json.dumps({"session_key": "sess-cli-close", "agent_id": "orchestrator"}, indent=2) + "\n",
                encoding="utf-8",
            )
            cli_dir = temp_root / "cli"
            write_fake_openclaw_cli(cli_dir)
            env = dict(os.environ)
            env["PATH"] = str(cli_dir) + os.pathsep + env.get("PATH", "")

            completed = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "openclaw_runtime_bridge.py"), "close-session", str(payload_path)],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(completed.stdout)
            self.assertEqual(report["status"], "closed")
            self.assertTrue((payload_path.with_suffix(".cli-closed.txt")).exists())

    def test_close_session_closes_native_session_and_retires_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            runtime_dir = project_root / "ai" / "runtime"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            runtime_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)
            helper = Path(tmp) / "close_helper.py"
            helper.write_text(
                """import json
import sys
from pathlib import Path

payload = Path(sys.argv[1]).resolve()
data = json.loads(payload.read_text(encoding='utf-8'))
payload.with_suffix('.closed.txt').write_text(data.get('session_key', ''), encoding='utf-8')
""",
                encoding="utf-8",
            )
            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "current_status": "executing",
                        "active_tasks": [
                            {
                                "task_id": "LIBU2-1",
                                "role": "libu2",
                                "status": "in-progress",
                                "workflow_step_id": "libu2-implementation",
                            }
                        ],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text(
                json.dumps({"libu2": {"agent_id": "libu2", "session_key": "sess-close", "status": "active"}}, indent=2)
                + "\n",
                encoding="utf-8",
            )
            (runtime_dir / "runtime-config.json").write_text(
                json.dumps(
                    {
                        "close_session_command": f'"{sys.executable}" "{helper}" "{{payload_file}}"',
                        "host_interface_sources": {"close_session_command": "project-config"},
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            payload = close_session.apply_close(project_root, "libu2", "Close for handoff consolidation.", force_native=True)

            self.assertEqual(payload["native_close_status"], "closed")
            registry = json.loads((state_dir / "agent-sessions.json").read_text(encoding="utf-8"))
            self.assertEqual(registry["libu2"]["status"], "closed")
            self.assertIsNone(registry["libu2"]["session_key"])
            state = json.loads((state_dir / "orchestrator-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["active_tasks"][0]["status"], "closed")
            self.assertTrue((reports_dir / "session-close-libu2.json").exists())

    def test_close_session_does_not_retire_registry_when_native_close_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            runtime_dir = project_root / "ai" / "runtime"
            state_dir.mkdir(parents=True)
            runtime_dir.mkdir(parents=True)
            helper = Path(tmp) / "close_fail.py"
            helper.write_text("raise SystemExit(1)\n", encoding="utf-8")

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "current_status": "executing",
                        "active_tasks": [
                            {
                                "task_id": "LIBU2-1",
                                "role": "libu2",
                                "status": "in-progress",
                                "workflow_step_id": "libu2-implementation",
                            }
                        ],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text(
                json.dumps({"libu2": {"agent_id": "libu2", "session_key": "sess-close", "status": "active"}}, indent=2)
                + "\n",
                encoding="utf-8",
            )
            (runtime_dir / "runtime-config.json").write_text(
                json.dumps(
                    {
                        "close_session_command": f'"{sys.executable}" "{helper}" "{{payload_file}}"',
                        "host_interface_sources": {"close_session_command": "project-config"},
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            payload = close_session.apply_close(project_root, "libu2", "Close for handoff consolidation.", force_native=True)

            self.assertFalse(payload["retired"])
            self.assertEqual(payload["native_close_status"], "close-failed")
            registry = json.loads((state_dir / "agent-sessions.json").read_text(encoding="utf-8"))
            self.assertEqual(registry["libu2"]["status"], "active")
            self.assertEqual(registry["libu2"]["session_key"], "sess-close")
            state = json.loads((state_dir / "orchestrator-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["active_tasks"][0]["status"], "in-progress")

    def test_close_session_marks_failed_for_invalid_command_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            runtime_dir = project_root / "ai" / "runtime"
            state_dir.mkdir(parents=True)
            runtime_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "current_status": "executing",
                        "active_tasks": [{"task_id": "LIBU2-1", "role": "libu2", "status": "in-progress"}],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text(
                json.dumps({"libu2": {"agent_id": "libu2", "session_key": "sess-close", "status": "active"}}, indent=2)
                + "\n",
                encoding="utf-8",
            )
            (runtime_dir / "runtime-config.json").write_text(
                json.dumps({"close_session_command": "echo {missing_placeholder}"}, indent=2) + "\n",
                encoding="utf-8",
            )

            payload = close_session.apply_close(project_root, "libu2", "Close for handoff consolidation.", force_native=True)

            self.assertFalse(payload["retired"])
            self.assertEqual(payload["native_close_status"], "close-failed")
            self.assertIn("unknown placeholder", str(payload.get("native_close_blocked_reason") or "").lower())
            registry = json.loads((state_dir / "agent-sessions.json").read_text(encoding="utf-8"))
            self.assertEqual(registry["libu2"]["status"], "active")

    def test_close_session_sanitizes_artifact_paths_for_agent_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            state_dir.mkdir(parents=True)

            agent_id = "..\\..\\escape/agent"
            (state_dir / "orchestrator-state.json").write_text(
                json.dumps({"active_tasks": []}, indent=2) + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text(
                json.dumps({agent_id: {"agent_id": agent_id, "session_key": None, "status": "idle"}}, indent=2) + "\n",
                encoding="utf-8",
            )

            payload = close_session.apply_close(project_root, agent_id, "Close for path traversal protection.")

            payload_path = Path(payload["payload_path"]).resolve()
            reattach_base = (project_root / "ai" / "runtime" / "reattach").resolve()
            self.assertEqual(payload["native_close_status"], "logical-only")
            self.assertNotIn("..", payload_path.name)
            self.assertTrue(payload_path.exists())
            payload_path.relative_to(reattach_base)

            token = close_session.safe_filename_token(agent_id)
            report_json = (project_root / "ai" / "reports" / f"session-close-{token}.json").resolve()
            self.assertTrue(report_json.exists())
            report_json.relative_to((project_root / "ai" / "reports").resolve())

    def test_natural_language_control_routes_close_session_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            runtime_dir = project_root / "ai" / "runtime"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            runtime_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)
            helper = Path(tmp) / "close_helper.py"
            helper.write_text(
                """import json
import sys
from pathlib import Path

payload = Path(sys.argv[1]).resolve()
data = json.loads(payload.read_text(encoding='utf-8'))
payload.with_suffix('.closed.txt').write_text(data.get('session_key', ''), encoding='utf-8')
""",
                encoding="utf-8",
            )
            (state_dir / "orchestrator-state.json").write_text(
                json.dumps({"automation_mode": "normal", "current_workflow": "feature-delivery", "current_status": "executing", "active_tasks": []}, indent=2)
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text(
                json.dumps({"libu2": {"agent_id": "libu2", "session_key": "sess-close", "status": "active"}}, indent=2)
                + "\n",
                encoding="utf-8",
            )
            (runtime_dir / "runtime-config.json").write_text(
                json.dumps(
                    {
                        "close_session_command": f'"{sys.executable}" "{helper}" "{{payload_file}}"',
                        "host_interface_sources": {"close_session_command": "project-config"},
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            payload = natural_language_control.execute_request(project_root, "司礼监：关闭 libu2 当前会话")

            self.assertEqual(payload["intent"], "close_session")
            self.assertEqual(payload["session_close"]["native_close_status"], "closed")
            self.assertEqual(payload["control"]["automation_mode"], "normal")

    def test_project_intake_records_requirement_and_creates_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "workspace"
            workspace_root.mkdir(parents=True)
            (workspace_root / "OpenClaw" / "skills").mkdir(parents=True)

            intake = project_intake.record_requirement(
                workspace_root,
                "\u505a\u4e00\u4e2a\u5185\u90e8\u5ba1\u6279\u7cfb\u7edf\uff0c\u652f\u6301\u591a\u7ea7\u5ba1\u6279\u548c\u901a\u77e5\uff0c\u9879\u76ee\u540d\u4e3a approval-center\u3002",
                actor="user",
            )
            self.assertFalse(intake["needs_project_name"])
            self.assertEqual(intake["project_name"], "approval-center")
            self.assertTrue((workspace_root / ".sili-jian-intake.json").exists())

            created = project_intake.create_project_from_intake(workspace_root, actor="user")

            self.assertEqual(created["status"], "project-created")
            project_root = Path(created["project_root"])
            self.assertTrue((project_root / "ai" / "tools" / "project_intake.py").exists())
            task_intake = (project_root / "ai" / "state" / "task-intake.md").read_text(encoding="utf-8")
            self.assertIn("\u5185\u90e8\u5ba1\u6279\u7cfb\u7edf", task_intake)

    def test_project_intake_extracts_real_chinese_project_name_patterns(self):
        cases = [
            ("\u505a\u4e00\u4e2a\u5185\u90e8\u5ba1\u6279\u7cfb\u7edf\uff0c\u652f\u6301\u591a\u7ea7\u5ba1\u6279\u548c\u901a\u77e5\uff0c\u9879\u76ee\u540d\u4e3a approval-center\u3002", "approval-center"),
            ("\u9879\u76ee\u540d: \u5ba1\u6279\u4e2d\u5fc3", "\u5ba1\u6279\u4e2d\u5fc3"),
            ("\u9879\u76ee\u540d\u79f0\u662f approval center", "approval center"),
            ("\u547d\u540d\u4e3a \u5ba1\u6279\u4e2d\u5fc3\u4e8c\u671f", "\u5ba1\u6279\u4e2d\u5fc3\u4e8c\u671f"),
            ("project name: demo-app", "demo-app"),
        ]

        for request, expected in cases:
            with self.subTest(request=request):
                self.assertEqual(project_intake.parse_project_name(request), expected)

    def test_project_intake_rejects_existing_non_empty_project_slug_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "workspace"
            existing_root = workspace_root / "approval-center"
            workspace_root.mkdir(parents=True)
            (workspace_root / "OpenClaw" / "skills").mkdir(parents=True)
            existing_root.mkdir(parents=True)
            (existing_root / ".git").mkdir()
            (existing_root / "package.json").write_text("{}\n", encoding="utf-8")

            project_intake.record_requirement(
                workspace_root,
                "\u505a\u4e00\u4e2a\u5185\u90e8\u5ba1\u6279\u7cfb\u7edf\uff0c\u652f\u6301\u591a\u7ea7\u5ba1\u6279\u548c\u901a\u77e5\uff0c\u9879\u76ee\u540d\u4e3a approval-center\u3002",
                actor="user",
            )

            with self.assertRaisesRegex(ValueError, "already exists"):
                project_intake.create_project_from_intake(workspace_root, actor="user")

    def test_project_intake_rejects_non_workspace_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            project_root.mkdir(parents=True)
            (project_root / ".git").mkdir()

            with self.assertRaises(ValueError):
                project_intake.record_requirement(project_root, "\u505a\u4e00\u4e2a\u65b0\u9879\u76ee")

    def test_first_run_check_workspace_root_mentions_project_intake(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "workspace"
            (workspace_root / "OpenClaw" / "skills").mkdir(parents=True)

            with mock.patch.object(
                first_run_check,
                "ensure_agents",
                return_value={
                    "missing_peer_agents": [],
                    "detection_source": "test",
                    "dispatch_ready": False,
                    "workspace_root": str(workspace_root),
                    "workspace_root_source": "test",
                },
            ):
                report = first_run_check.build_report(workspace_root, workspace_root, create_missing=False, lang="en")

            self.assertIn("scripts/project_intake.py", report)

    def test_bootstrap_auto_scenario_treats_empty_git_repo_as_new_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            project_root.mkdir(parents=True)
            (project_root / ".git").mkdir()

            self.assertEqual(bootstrap_governance.detect_bootstrap_scenario(project_root, "auto"), "new-project")

            (project_root / "src").mkdir()
            self.assertEqual(bootstrap_governance.detect_bootstrap_scenario(project_root, "auto"), "mid-stream-takeover")

    def test_takeover_inspection_generates_current_implementation_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            (project_root / ".git").mkdir(parents=True)
            (project_root / "src").mkdir()
            (project_root / "src" / "main.py").write_text("print('demo')\n", encoding="utf-8")

            bootstrap = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "bootstrap_governance.py"),
                    str(project_root),
                    "--scenario",
                    "mid-stream-takeover",
                    "--project-name",
                    "demo",
                    "--project-id",
                    "demo",
                    "--skill-root",
                    str(REPO_ROOT),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)

            first_cycle = run_orchestrator.run(project_root, max_dispatch=1, transport="outbox")
            second_cycle = run_orchestrator.run(project_root, max_dispatch=1, transport="outbox")

            self.assertEqual(first_cycle["status"], "local-progress")
            self.assertEqual(second_cycle["status"], "local-progress")
            summary_path = project_root / "ai" / "reports" / "current-implementation-summary.md"
            self.assertTrue(summary_path.exists())
            summary_text = summary_path.read_text(encoding="utf-8")
            self.assertIn("Existing implementation detected", summary_text)
            self.assertIn("src/main.py", summary_text)

    def test_takeover_planning_requires_customer_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            (project_root / ".git").mkdir(parents=True)
            (project_root / "src").mkdir()
            (project_root / "src" / "main.py").write_text("print('demo')\n", encoding="utf-8")

            bootstrap = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "bootstrap_governance.py"),
                    str(project_root),
                    "--scenario",
                    "mid-stream-takeover",
                    "--project-name",
                    "demo",
                    "--project-id",
                    "demo",
                    "--skill-root",
                    str(REPO_ROOT),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)

            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            (state_dir / "architecture.md").write_text("# Architecture\n\n- API and admin UI\n", encoding="utf-8")
            (state_dir / "task-tree.json").write_text(
                json.dumps({"mainline": ["baseline"], "tasks": [{"id": "doc-freeze"}]}, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (reports_dir / "architecture-review.md").write_text(
                "# Architecture Review\n\n## Conclusion\n\n- PASS\n",
                encoding="utf-8",
            )
            (reports_dir / "current-implementation-summary.md").write_text(
                "# Current Implementation Summary\n\n## Status\n\n- Existing implementation detected and summarized for customer confirmation.\n",
                encoding="utf-8",
            )
            (state_dir / "task-intake.md").write_text(
                """# Task Intake

## Raw Requirement

- stabilize the existing approval flow

## Current Implemented Scope

- legacy approval APIs and one admin entry page

## Confirmed Requirement

- customer wants to keep current approval flow and add audit trail

## Frozen Requirement

- freeze current approval flow and add audit trail in phase one

## Review Gates

- Internal document review status: PASS
- Customer acknowledged current implementation baseline: pending
- Customer confirmed requirement and scope: yes
- Approved to start development: pending
""",
                encoding="utf-8",
            )

            pending_report = inspect_project(project_root, intent="mid-stream-takeover")
            self.assertFalse(pending_report["planning_ready"])
            self.assertFalse(pending_report["customer_acknowledged_implementation"])
            self.assertFalse(pending_report["development_approved"])

            (state_dir / "task-intake.md").write_text(
                """# Task Intake

## Raw Requirement

- stabilize the existing approval flow

## Current Implemented Scope

- legacy approval APIs and one admin entry page

## Confirmed Requirement

- customer wants to keep current approval flow and add audit trail

## Frozen Requirement

- freeze current approval flow and add audit trail in phase one

## Review Gates

- Internal document review status: PASS
- Customer acknowledged current implementation baseline: yes
- Customer confirmed requirement and scope: yes
- Approved to start development: yes
""",
                encoding="utf-8",
            )

            approved_report = inspect_project(project_root, intent="mid-stream-takeover")
            self.assertTrue(approved_report["planning_ready"])
            self.assertTrue(approved_report["customer_acknowledged_implementation"])
            self.assertTrue(approved_report["customer_confirmed_requirement"])
            self.assertTrue(approved_report["development_approved"])

            state_path = state_dir / "orchestrator-state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["current_status"] = "executing"
            state["execution_allowed"] = "false"
            state["testing_allowed"] = "false"
            state["release_allowed"] = "false"
            state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

            string_flag_report = inspect_project(project_root, intent="mid-stream-takeover")
            self.assertFalse(string_flag_report["execution_ready"])
            self.assertFalse(string_flag_report["testing_ready"])
            self.assertFalse(string_flag_report["release_allowed"])

    def test_update_state_and_handoff_waits_for_customer_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            bootstrap = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "bootstrap_governance.py"),
                    str(project_root),
                    "--project-name",
                    "demo",
                    "--project-id",
                    "demo",
                    "--skill-root",
                    str(REPO_ROOT),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)

            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            (state_dir / "architecture.md").write_text("# Architecture\n\n- brand new service\n", encoding="utf-8")
            (state_dir / "task-tree.json").write_text(
                json.dumps({"mainline": ["mvp"], "tasks": [{"id": "scope-freeze"}]}, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (reports_dir / "architecture-review.md").write_text(
                "# Architecture Review\n\n## Conclusion\n\n- PASS\n",
                encoding="utf-8",
            )
            (state_dir / "task-intake.md").write_text(
                """# Task Intake

## Raw Requirement

- build a lightweight approval center

## Current Implemented Scope

- No existing implementation yet; this is a brand new project baseline.

## Confirmed Requirement

- customer wants approval submit, review, and notification in MVP

## Frozen Requirement

- MVP includes submit, review, and notification

## Review Gates

- Internal document review status: PASS
- Customer acknowledged current implementation baseline: not-applicable
- Customer confirmed requirement and scope: pending
- Approved to start development: pending
""",
                encoding="utf-8",
            )

            step = workflow_engine.WorkflowStep(id="update-state-and-handoff", role="orchestrator", agent_id="orchestrator")
            orchestrator_local_steps.apply_post_completion_state(project_root, step)
            blocked_state = json.loads((state_dir / "orchestrator-state.json").read_text(encoding="utf-8"))
            self.assertEqual(blocked_state["current_workflow"], "new-project")
            self.assertEqual(blocked_state["current_status"], "draft")
            self.assertFalse(blocked_state["execution_allowed"])
            self.assertIn("customer", blocked_state["next_action"].lower())

            (state_dir / "task-intake.md").write_text(
                """# Task Intake

## Raw Requirement

- build a lightweight approval center

## Current Implemented Scope

- No existing implementation yet; this is a brand new project baseline.

## Confirmed Requirement

- customer wants approval submit, review, and notification in MVP

## Frozen Requirement

- MVP includes submit, review, and notification

## Review Gates

- Internal document review status: PASS
- Customer acknowledged current implementation baseline: not-applicable
- Customer confirmed requirement and scope: yes
- Approved to start development: yes
""",
                encoding="utf-8",
            )

            orchestrator_local_steps.apply_post_completion_state(project_root, step)
            approved_state = json.loads((state_dir / "orchestrator-state.json").read_text(encoding="utf-8"))
            self.assertEqual(approved_state["current_workflow"], "feature-delivery")
            self.assertEqual(approved_state["current_status"], "plan-approved")
            self.assertTrue(approved_state["execution_allowed"])

    def test_update_state_and_handoff_calls_out_missing_architecture_before_generic_continue(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            bootstrap = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "bootstrap_governance.py"),
                    str(project_root),
                    "--project-name",
                    "demo",
                    "--project-id",
                    "demo",
                    "--skill-root",
                    str(REPO_ROOT),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)

            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            (state_dir / "task-tree.json").write_text(
                json.dumps({"mainline": ["mvp"], "tasks": [{"id": "scope-freeze"}]}, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (reports_dir / "architecture-review.md").write_text(
                "# Architecture Review\n\n## Conclusion\n\n- PASS\n",
                encoding="utf-8",
            )
            (state_dir / "task-intake.md").write_text(
                """# Task Intake

## Raw Requirement

- build a lightweight approval center

## Current Implemented Scope

- No existing implementation yet; this is a brand new project baseline.

## Confirmed Requirement

- customer wants approval submit, review, and notification in MVP

## Frozen Requirement

- MVP includes submit, review, and notification

## Review Gates

- Internal document review status: PASS
- Customer acknowledged current implementation baseline: not-applicable
- Customer confirmed requirement and scope: yes
- Approved to start development: yes
""",
                encoding="utf-8",
            )

            step = workflow_engine.WorkflowStep(id="update-state-and-handoff", role="orchestrator", agent_id="orchestrator")
            orchestrator_local_steps.apply_post_completion_state(project_root, step)
            state = json.loads((state_dir / "orchestrator-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["current_status"], "draft")
            self.assertFalse(state["execution_allowed"])
            self.assertEqual(state["next_action"], "write architecture.md with the approved system design")

    def test_runtime_loop_dispatches_delivers_and_consumes_in_one_cycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            helper = Path(tmp) / "transport_helper.py"
            write_transport_helper(helper)

            bootstrap = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "bootstrap_governance.py"),
                    str(project_root),
                    "--project-name",
                    "demo",
                    "--project-id",
                    "demo",
                    "--skill-root",
                    str(REPO_ROOT),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)

            with mock.patch.dict(os.environ, {"OPENCLAW_SPAWN_COMMAND": f'"{sys.executable}" "{helper}" "{{dispatch_file}}"'}):
                summary = runtime_loop.run_loop(project_root, max_cycles=4, max_dispatch=1, transport="outbox", activate=True)

            self.assertGreaterEqual(summary["total_dispatch_count"], 1)
            self.assertEqual(summary["total_sent_count"], 1)
            self.assertEqual(summary["total_processed_count"], 1)
            state = json.loads((project_root / "ai" / "state" / "orchestrator-state.json").read_text(encoding="utf-8"))
            self.assertIn("identify-project", state["workflow_progress"]["completed_steps"])
            self.assertIn("bootstrap-governance", state["workflow_progress"]["completed_steps"])
            self.assertIn("create-run-snapshot", state["workflow_progress"]["completed_steps"])
            self.assertIn("freeze-initial-plan", state["workflow_progress"]["completed_steps"])
            self.assertTrue((project_root / "ai" / "reports" / "runtime-loop-summary.json").exists())
            self.assertTrue((project_root / "ai" / "reports" / "parent-session-recovery.json").exists())

    def test_context_rollover_writes_resume_prompt_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "current_phase": "testing",
                        "current_status": "testing",
                        "next_action": "Collect test evidence.",
                        "next_owner": "bingbu",
                        "active_tasks": [{"task_id": "BINGBU-1", "role": "bingbu", "status": "in-progress", "workflow_step_id": "bingbu-testing"}],
                        "blockers": [],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "agent-sessions.json").write_text("{}\n", encoding="utf-8")
            (state_dir / "project-meta.json").write_text(json.dumps({"project_name": "demo", "project_id": "demo"}) + "\n", encoding="utf-8")
            (state_dir / "project-handoff.md").write_text("# Project Handoff\n", encoding="utf-8")
            (state_dir / "START_HERE.md").write_text("# Start Here\n", encoding="utf-8")

            payload = context_rollover.create_rollover(project_root)
            self.assertIn("Collect test evidence.", payload["resume_prompt"])
            self.assertTrue((reports_dir / "orchestrator-rollover.md").exists())
            registry = json.loads((state_dir / "agent-sessions.json").read_text(encoding="utf-8"))
            self.assertEqual(registry["orchestrator"]["status"], "waiting")

    def test_validate_state_accepts_libu_documentation_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            handoff_dir = project_root / "ai" / "handoff" / "libu" / "active"
            handoff_dir.mkdir(parents=True)
            state_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_phase": "department-review",
                        "current_status": "department-review",
                        "current_workflow": "feature-delivery",
                        "next_owner": "libu",
                        "execution_allowed": True,
                        "testing_allowed": True,
                        "release_allowed": False,
                        "active_tasks": [
                            {
                                "task_id": "DOC-001",
                                "role": "libu",
                                "status": "in-progress",
                                "handoff_path": "ai/handoff/libu/active/DOC-001.md",
                                "workflow_step_id": "libu-documentation",
                            }
                        ],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            (state_dir / "START_HERE.md").write_text(
                """# Start Here

- Stage: department-review
- Workflow: feature-delivery
- Next owner: libu
""",
                encoding="utf-8",
            )

            (state_dir / "project-handoff.md").write_text(
                """# Project Handoff

- Status: department-review
- Current phase: department-review
- Current workflow: feature-delivery
- Next owner: libu
""",
                encoding="utf-8",
            )

            (handoff_dir / "DOC-001.md").write_text(
                """# Role Handoff

- task_id: DOC-001
- role: libu
- status: in-progress
- workflow_step_id: libu-documentation
""",
                encoding="utf-8",
            )

            report = validate_state.validate(project_root)
            codes = {item["code"] for item in report["findings"]}
            self.assertNotIn("workflow_step_not_in_current_workflow", codes)

    def test_validate_state_blocks_on_skill_usage_violation_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_phase": "executing",
                        "current_status": "executing",
                        "current_workflow": "feature-delivery",
                        "next_owner": "orchestrator",
                        "next_action": "review completion",
                        "execution_allowed": True,
                        "testing_allowed": False,
                        "release_allowed": False,
                        "active_tasks": [],
                        "last_completion": {
                            "task_id": "LIBU2-1",
                            "workflow_step_id": "libu2-implementation",
                            "completion_schema_version": "v1",
                            "skill_audit_recorded": True,
                        },
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "START_HERE.md").write_text(
                "# Start Here\n\n- Stage: executing\n- Workflow: feature-delivery\n- Next owner: orchestrator\n",
                encoding="utf-8",
            )
            (state_dir / "project-handoff.md").write_text(
                "# Project Handoff\n\n- Status: executing\n- Current phase: executing\n- Current workflow: feature-delivery\n- Next owner: orchestrator\n",
                encoding="utf-8",
            )
            (reports_dir / "agent-skill-usage.json").write_text(
                json.dumps(
                    {
                        "updated_at": "2026-01-01T00:00:00+00:00",
                        "schema_version": "v1",
                        "items": [
                            {
                                "task_id": "LIBU2-1",
                                "agent_id": "libu2",
                                "compliant": False,
                                "violation_code": "skill_policy_violation",
                                "violation_reason": "skill_policy=required but execution_trace.skills_used is empty.",
                            }
                        ],
                        "totals": {"total": 1, "compliant": 0, "violations": 1},
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            report = validate_state.validate(project_root)
            codes = {item["code"] for item in report["findings"]}
            self.assertIn("skill_policy_violation", codes)
            self.assertFalse(report["state_consistent"])

    def test_validate_state_parses_string_booleans_for_runtime_and_skill_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_phase": "draft",
                        "current_status": "draft",
                        "current_workflow": "feature-delivery",
                        "next_owner": "orchestrator",
                        "next_action": "review completion",
                        "execution_allowed": "false",
                        "testing_allowed": "false",
                        "release_allowed": "false",
                        "active_tasks": [],
                        "last_completion": {
                            "task_id": "LIBU2-1",
                            "workflow_step_id": "libu2-implementation",
                            "completion_schema_version": "v1",
                            "skill_audit_recorded": "false",
                        },
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "START_HERE.md").write_text(
                "# Start Here\n\n- Stage: draft\n- Workflow: feature-delivery\n- Next owner: orchestrator\n",
                encoding="utf-8",
            )
            (state_dir / "project-handoff.md").write_text(
                "# Project Handoff\n\n- Status: draft\n- Current phase: draft\n- Current workflow: feature-delivery\n- Next owner: orchestrator\n",
                encoding="utf-8",
            )
            (reports_dir / "agent-skill-usage.json").write_text(
                json.dumps(
                    {
                        "updated_at": "2026-01-01T00:00:00+00:00",
                        "schema_version": "v1",
                        "items": [
                            {
                                "task_id": "LIBU2-1",
                                "agent_id": "libu2",
                                "compliant": "false",
                                "violation_code": "skill_policy_violation",
                                "violation_reason": "skill_policy=required but execution_trace.skills_used is empty.",
                            }
                        ],
                        "totals": {"total": 1, "compliant": 0, "violations": 1},
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            report = validate_state.validate(project_root)
            codes = {item["code"] for item in report["findings"]}
            self.assertNotIn("execution_allowed_too_early", codes)
            self.assertIn("skill_policy_violation", codes)
            self.assertIn("missing_skill_usage_trace", codes)
            self.assertFalse(report["state_consistent"])

    def test_validate_state_ignores_historical_skill_violations_outside_active_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_phase": "executing",
                        "current_status": "executing",
                        "current_workflow": "feature-delivery",
                        "next_owner": "orchestrator",
                        "next_action": "continue",
                        "execution_allowed": True,
                        "testing_allowed": False,
                        "release_allowed": False,
                        "active_tasks": [],
                        "last_completion": {
                            "task_id": "NEW-OK-1",
                            "workflow_step_id": "libu2-implementation",
                            "completion_schema_version": "v1",
                            "skill_audit_recorded": True,
                        },
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "START_HERE.md").write_text(
                "# Start Here\n\n- Stage: executing\n- Workflow: feature-delivery\n- Next owner: orchestrator\n",
                encoding="utf-8",
            )
            (state_dir / "project-handoff.md").write_text(
                "# Project Handoff\n\n- Status: executing\n- Current phase: executing\n- Current workflow: feature-delivery\n- Next owner: orchestrator\n",
                encoding="utf-8",
            )
            (reports_dir / "agent-skill-usage.json").write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "task_id": "OLD-FAIL-1",
                                "agent_id": "libu2",
                                "compliant": False,
                                "violation_code": "skill_policy_violation",
                                "violation_reason": "old violation",
                            },
                            {
                                "task_id": "NEW-OK-1",
                                "agent_id": "libu2",
                                "compliant": True,
                                "violation_code": "",
                                "violation_reason": "",
                            },
                        ]
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            report = validate_state.validate(project_root)
            codes = {item["code"] for item in report["findings"]}
            self.assertNotIn("skill_policy_violation", codes)
            self.assertTrue(report["state_consistent"])

    def test_build_department_matrix_ignores_stale_handoff_files_outside_registry_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            reports_dir = project_root / "ai" / "reports"
            state_dir = project_root / "ai" / "state"
            reports_dir.mkdir(parents=True)
            state_dir.mkdir(parents=True)

            registry: dict[str, dict[str, str]] = {}
            for role in orchestrator_local_steps.DEPARTMENT_ROLES:
                active_dir = project_root / "ai" / "handoff" / role / "active"
                active_dir.mkdir(parents=True, exist_ok=True)
                current_path = active_dir / f"{role.upper()}-CURRENT.md"
                stale_path = active_dir / f"{role.upper()}-OLD.md"
                current_path.write_text(
                    f"# Role Handoff\n\n- task_id: {role.upper()}-CURRENT\n- role: {role}\n- status: completed\n- blockers: none\n",
                    encoding="utf-8",
                )
                stale_path.write_text(
                    f"# Role Handoff\n\n- task_id: {role.upper()}-OLD\n- role: {role}\n- status: blocked\n- blockers: schema drift\n",
                    encoding="utf-8",
                )
                registry[role] = {
                    "agent_id": role,
                    "handoff_path": str(current_path.relative_to(project_root)).replace("\\", "/"),
                    "status": "idle",
                }

            (state_dir / "agent-sessions.json").write_text(
                json.dumps(registry, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            orchestrator_local_steps.build_department_matrix(
                project_root,
                {"current_workflow": "review-and-release"},
                "collect-department-approvals",
            )

            matrix = (reports_dir / "department-approval-matrix.md").read_text(encoding="utf-8")
            self.assertIn("- blockers: none", matrix)
            self.assertIn("\n- PASS\n", matrix)

    def test_build_department_matrix_includes_duchayuan_cross_review_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            reports_dir = project_root / "ai" / "reports"
            state_dir = project_root / "ai" / "state"
            reports_dir.mkdir(parents=True)
            state_dir.mkdir(parents=True)

            registry: dict[str, dict[str, str]] = {}
            for role in [*orchestrator_local_steps.DEPARTMENT_ROLES, "duchayuan"]:
                active_dir = project_root / "ai" / "handoff" / role / "active"
                active_dir.mkdir(parents=True, exist_ok=True)
                current_path = active_dir / f"{role.upper()}-CURRENT.md"
                current_path.write_text(
                    f"# Role Handoff\n\n- task_id: {role.upper()}-CURRENT\n- role: {role}\n- status: completed\n- blockers: none\n",
                    encoding="utf-8",
                )
                registry[role] = {
                    "agent_id": role,
                    "handoff_path": str(current_path.relative_to(project_root)).replace("\\", "/"),
                    "status": "idle",
                }

            (state_dir / "agent-sessions.json").write_text(
                json.dumps(registry, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            orchestrator_local_steps.build_department_matrix(
                project_root,
                {"current_workflow": "feature-delivery"},
                "department-review",
            )

            matrix = (reports_dir / "department-approval-matrix.md").read_text(encoding="utf-8")
            self.assertIn("## Reviewer duchayuan", matrix)
            self.assertIn("- libu2: PASS", matrix)

    def test_feature_delivery_review_limits_default_to_four_before_cabinet(self):
        state = json.loads(
            (REPO_ROOT / "assets" / "project-skeleton" / "ai" / "state" / "orchestrator-state.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(state["review_cycle_limit_before_cabinet"], 4)
        self.assertEqual(state["review_cycle_count_before_cabinet"], 0)
        self.assertEqual(state["review_cycle_limit_after_cabinet"], 2)
        self.assertEqual(state["review_cycle_count_after_cabinet"], 0)

    def test_department_review_failure_requeues_implementation_batch_within_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            reports_dir = project_root / "ai" / "reports"
            state_dir = project_root / "ai" / "state"
            workflows_dir = project_root / "workflows"
            reports_dir.mkdir(parents=True)
            state_dir.mkdir(parents=True)
            workflows_dir.mkdir(parents=True)

            (workflows_dir / "feature-delivery.yaml").write_text(
                (REPO_ROOT / "assets" / "project-skeleton" / "workflows" / "feature-delivery.yaml").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "current_phase": "department-review",
                        "current_status": "department-review",
                        "execution_allowed": True,
                        "testing_allowed": False,
                        "release_allowed": False,
                        "review_cycle_limit_before_cabinet": 4,
                        "review_cycle_count_before_cabinet": 0,
                        "review_cycle_limit_after_cabinet": 2,
                        "review_cycle_count_after_cabinet": 0,
                        "review_phase": "normal-review",
                        "cabinet_replan_triggered": False,
                        "active_tasks": [],
                        "workflow_progress": {
                            "completed_steps": [
                                "intake-feature",
                                "confirm-or-replan",
                                "plan-approval",
                                "libu2-implementation",
                                "hubu-implementation",
                                "gongbu-implementation",
                                "libu2-cross-review",
                                "hubu-cross-review",
                                "gongbu-cross-review",
                                "bingbu-cross-review",
                                "libu-cross-review",
                                "xingbu-cross-review",
                                "duchayuan-cross-review",
                            ],
                            "blocked_steps": [],
                            "dispatched_steps": [],
                        },
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            registry: dict[str, dict[str, str]] = {}
            for role in [*orchestrator_local_steps.DEPARTMENT_ROLES, "duchayuan"]:
                active_dir = project_root / "ai" / "handoff" / role / "active"
                active_dir.mkdir(parents=True, exist_ok=True)
                current_path = active_dir / f"{role.upper()}-CURRENT.md"
                status = "blocked" if role == "hubu" else "completed"
                blockers = "schema drift" if role == "hubu" else "none"
                current_path.write_text(
                    f"# Role Handoff\n\n- task_id: {role.upper()}-CURRENT\n- role: {role}\n- status: {status}\n- blockers: {blockers}\n",
                    encoding="utf-8",
                )
                registry[role] = {
                    "agent_id": role,
                    "handoff_path": str(current_path.relative_to(project_root)).replace("\\", "/"),
                    "status": "idle",
                }
            (state_dir / "agent-sessions.json").write_text(
                json.dumps(registry, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            orchestrator_local_steps.execute_local_step(
                project_root,
                workflow_engine.WorkflowStep(id="department-review", role="orchestrator", agent_id="orchestrator"),
                "DEPT-REVIEW-001",
            )

            state = json.loads((state_dir / "orchestrator-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["current_status"], "review-rework")
            self.assertEqual(state["review_cycle_count_before_cabinet"], 1)
            self.assertEqual(state["next_owner"], "orchestrator")
            self.assertNotIn("libu2-implementation", state["workflow_progress"]["completed_steps"])
            self.assertNotIn("department-review", state["workflow_progress"]["completed_steps"])

            workflow = workflow_engine.load_workflow(project_root)
            ready = [step.id for step in workflow_engine.ready_steps(workflow, state)]
            self.assertEqual(ready[:3], ["libu2-implementation", "hubu-implementation", "gongbu-implementation"])

    def test_department_review_failure_exceeding_first_limit_escalates_to_cabinet(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            reports_dir = project_root / "ai" / "reports"
            state_dir = project_root / "ai" / "state"
            workflows_dir = project_root / "workflows"
            reports_dir.mkdir(parents=True)
            state_dir.mkdir(parents=True)
            workflows_dir.mkdir(parents=True)

            (workflows_dir / "feature-delivery.yaml").write_text(
                (REPO_ROOT / "assets" / "project-skeleton" / "workflows" / "feature-delivery.yaml").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "current_phase": "department-review",
                        "current_status": "department-review",
                        "execution_allowed": True,
                        "testing_allowed": False,
                        "release_allowed": False,
                        "review_cycle_limit_before_cabinet": 1,
                        "review_cycle_count_before_cabinet": 1,
                        "review_cycle_limit_after_cabinet": 2,
                        "review_cycle_count_after_cabinet": 0,
                        "review_phase": "normal-review",
                        "cabinet_replan_triggered": False,
                        "active_tasks": [],
                        "workflow_progress": {
                            "completed_steps": [
                                "intake-feature",
                                "confirm-or-replan",
                                "plan-approval",
                                "libu2-implementation",
                                "hubu-implementation",
                                "gongbu-implementation",
                                "libu2-cross-review",
                                "hubu-cross-review",
                                "gongbu-cross-review",
                                "bingbu-cross-review",
                                "libu-cross-review",
                                "xingbu-cross-review",
                                "duchayuan-cross-review",
                            ],
                            "blocked_steps": [],
                            "dispatched_steps": [],
                        },
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            registry: dict[str, dict[str, str]] = {}
            for role in [*orchestrator_local_steps.DEPARTMENT_ROLES, "duchayuan"]:
                active_dir = project_root / "ai" / "handoff" / role / "active"
                active_dir.mkdir(parents=True, exist_ok=True)
                current_path = active_dir / f"{role.upper()}-CURRENT.md"
                status = "blocked" if role == "gongbu" else "completed"
                blockers = "flow mismatch" if role == "gongbu" else "none"
                current_path.write_text(
                    f"# Role Handoff\n\n- task_id: {role.upper()}-CURRENT\n- role: {role}\n- status: {status}\n- blockers: {blockers}\n",
                    encoding="utf-8",
                )
                registry[role] = {
                    "agent_id": role,
                    "handoff_path": str(current_path.relative_to(project_root)).replace("\\", "/"),
                    "status": "idle",
                }
            (state_dir / "agent-sessions.json").write_text(
                json.dumps(registry, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            orchestrator_local_steps.execute_local_step(
                project_root,
                workflow_engine.WorkflowStep(id="department-review", role="orchestrator", agent_id="orchestrator"),
                "DEPT-REVIEW-002",
            )

            state = json.loads((state_dir / "orchestrator-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["current_status"], "cabinet-review")
            self.assertTrue(state["cabinet_replan_triggered"])
            self.assertEqual(state["review_phase"], "cabinet-replan-review")
            self.assertEqual(state["next_owner"], "neige")
            cabinet_report = (reports_dir / "cabinet-replan-report.md").read_text(encoding="utf-8")
            self.assertIn("flow mismatch", cabinet_report)
            review_history = json.loads((reports_dir / "review-history.json").read_text(encoding="utf-8"))
            self.assertEqual(review_history["entries"][-1]["outcome"], "escalated-to-cabinet")

            workflow = workflow_engine.load_workflow(project_root)
            ready = [step.id for step in workflow_engine.ready_steps(workflow, state)]
            self.assertEqual(ready[0], "confirm-or-replan")

    def test_department_review_failure_after_cabinet_limit_generates_customer_decision_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            reports_dir = project_root / "ai" / "reports"
            state_dir = project_root / "ai" / "state"
            workflows_dir = project_root / "workflows"
            reports_dir.mkdir(parents=True)
            state_dir.mkdir(parents=True)
            workflows_dir.mkdir(parents=True)

            (workflows_dir / "feature-delivery.yaml").write_text(
                (REPO_ROOT / "assets" / "project-skeleton" / "workflows" / "feature-delivery.yaml").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "current_phase": "department-review",
                        "current_status": "department-review",
                        "execution_allowed": True,
                        "testing_allowed": False,
                        "release_allowed": False,
                        "review_cycle_limit_before_cabinet": 4,
                        "review_cycle_count_before_cabinet": 4,
                        "review_cycle_limit_after_cabinet": 1,
                        "review_cycle_count_after_cabinet": 1,
                        "review_phase": "cabinet-replan-review",
                        "cabinet_replan_triggered": True,
                        "primary_goal": "Ship the current governed batch safely.",
                        "active_tasks": [],
                        "workflow_progress": {
                            "completed_steps": [
                                "intake-feature",
                                "confirm-or-replan",
                                "plan-approval",
                                "libu2-implementation",
                                "hubu-implementation",
                                "gongbu-implementation",
                                "libu2-cross-review",
                                "hubu-cross-review",
                                "gongbu-cross-review",
                                "bingbu-cross-review",
                                "libu-cross-review",
                                "xingbu-cross-review",
                                "duchayuan-cross-review",
                            ],
                            "blocked_steps": [],
                            "dispatched_steps": [],
                        },
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            registry: dict[str, dict[str, str]] = {}
            for role in [*orchestrator_local_steps.DEPARTMENT_ROLES, "duchayuan"]:
                active_dir = project_root / "ai" / "handoff" / role / "active"
                active_dir.mkdir(parents=True, exist_ok=True)
                current_path = active_dir / f"{role.upper()}-CURRENT.md"
                status = "blocked" if role == "libu2" else "completed"
                blockers = "api contract still unstable" if role == "libu2" else "none"
                current_path.write_text(
                    f"# Role Handoff\n\n- task_id: {role.upper()}-CURRENT\n- role: {role}\n- status: {status}\n- blockers: {blockers}\n",
                    encoding="utf-8",
                )
                registry[role] = {
                    "agent_id": role,
                    "handoff_path": str(current_path.relative_to(project_root)).replace("\\", "/"),
                    "status": "idle",
                }
            (state_dir / "agent-sessions.json").write_text(
                json.dumps(registry, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            orchestrator_local_steps.execute_local_step(
                project_root,
                workflow_engine.WorkflowStep(id="department-review", role="orchestrator", agent_id="orchestrator"),
                "DEPT-REVIEW-003",
            )

            state = json.loads((state_dir / "orchestrator-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["current_status"], "await-customer-decision")
            self.assertEqual(state["review_escalation_level"], "customer")
            report_text = (reports_dir / "customer-decision-required.md").read_text(encoding="utf-8")
            self.assertIn("当前批次", report_text)
            self.assertIn("api contract still unstable", report_text)
            self.assertIn("interface-contract", report_text)
            review_history = json.loads((reports_dir / "review-history.json").read_text(encoding="utf-8"))
            self.assertEqual(review_history["entries"][-1]["outcome"], "customer-decision-required")

            result = run_orchestrator.run(project_root, max_dispatch=1, transport="outbox")
            self.assertEqual(result["status"], "customer-decision-required")

    def test_configure_review_controls_updates_state_and_config_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            state_dir.mkdir(parents=True)
            (state_dir / "orchestrator-state.json").write_text(
                json.dumps({"current_workflow": "feature-delivery"}, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            payload = configure_review_controls.configure(project_root, before_cabinet=6, after_cabinet=3)
            self.assertEqual(payload["review_cycle_limit_before_cabinet"], 6)
            self.assertEqual(payload["review_cycle_limit_after_cabinet"], 3)

            controls = json.loads((state_dir / "review-controls.json").read_text(encoding="utf-8"))
            self.assertEqual(controls["review_cycle_limit_before_cabinet"], 6)
            state = json.loads((state_dir / "orchestrator-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["review_cycle_limit_before_cabinet"], 6)
            self.assertEqual(state["review_cycle_limit_after_cabinet"], 3)

    def test_resume_customer_decision_restarts_planning_for_scope_reduction(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            workflows_dir = project_root / "workflows"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)
            workflows_dir.mkdir(parents=True)
            (workflows_dir / "feature-delivery.yaml").write_text(
                (REPO_ROOT / "assets" / "project-skeleton" / "workflows" / "feature-delivery.yaml").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_workflow": "feature-delivery",
                        "current_phase": "customer-decision",
                        "current_status": "await-customer-decision",
                        "review_phase": "await-customer-decision",
                        "review_cycle_limit_before_cabinet": 4,
                        "review_cycle_count_before_cabinet": 4,
                        "review_cycle_limit_after_cabinet": 2,
                        "review_cycle_count_after_cabinet": 2,
                        "cabinet_replan_triggered": True,
                        "workflow_progress": {
                            "completed_steps": [
                                "intake-feature",
                                "confirm-or-replan",
                                "plan-approval",
                                "libu2-implementation",
                                "hubu-implementation",
                                "gongbu-implementation",
                                "libu2-cross-review",
                                "hubu-cross-review",
                                "gongbu-cross-review",
                                "bingbu-cross-review",
                                "libu-cross-review",
                                "xingbu-cross-review",
                                "duchayuan-cross-review",
                                "department-review",
                            ],
                            "blocked_steps": [],
                            "dispatched_steps": [],
                        },
                        "active_tasks": [],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "project-handoff.md").write_text("# Project Handoff\n", encoding="utf-8")
            (state_dir / "START_HERE.md").write_text("# Start Here\n", encoding="utf-8")

            payload = resume_customer_decision.apply_customer_decision(
                project_root,
                "scope-reduction",
                "Customer chose a smaller first batch.",
            )
            self.assertEqual(payload["current_status"], "rework")
            state = json.loads((state_dir / "orchestrator-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["next_owner"], "neige")
            self.assertEqual(state["review_cycle_count_before_cabinet"], 0)
            self.assertFalse(state["cabinet_replan_triggered"])
            workflow = workflow_engine.load_workflow(project_root)
            ready = [step.id for step in workflow_engine.ready_steps(workflow, state)]
            self.assertEqual(ready[0], "confirm-or-replan")
            resolution = (reports_dir / "customer-decision-resolution.md").read_text(encoding="utf-8")
            self.assertIn("scope-reduction", resolution)

    def test_validate_state_accepts_review_and_release_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            state_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_phase": "final-audit",
                        "current_status": "final-audit",
                        "current_workflow": "review-and-release",
                        "next_owner": "duchayuan",
                        "active_tasks": [],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "START_HERE.md").write_text(
                "# Start Here\n\n- Stage: final-audit\n- Workflow: review-and-release\n- Next owner: duchayuan\n",
                encoding="utf-8",
            )
            (state_dir / "project-handoff.md").write_text(
                "# Project Handoff\n\n- Status: final-audit\n- Current phase: final-audit\n- Current workflow: review-and-release\n- Next owner: duchayuan\n",
                encoding="utf-8",
            )

            report = validate_state.validate(project_root)
            codes = {item["code"] for item in report["findings"]}
            self.assertNotIn("unknown_current_workflow", codes)
            self.assertTrue(report["state_consistent"])

    def test_validate_state_accepts_resume_orchestrator_step_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            handoff_dir = project_root / "ai" / "handoff" / "orchestrator" / "active"
            state_dir.mkdir(parents=True)
            handoff_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_phase": "recovery",
                        "current_status": "paused",
                        "current_workflow": "resume-orchestrator",
                        "next_owner": "orchestrator",
                        "execution_allowed": True,
                        "testing_allowed": False,
                        "release_allowed": False,
                        "active_tasks": [
                            {
                                "task_id": "RECOVERY-1",
                                "role": "orchestrator",
                                "status": "in-progress",
                                "handoff_path": "ai/handoff/orchestrator/active/RECOVERY-1.md",
                                "workflow_step_id": "read-active-handoffs",
                            }
                        ],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "START_HERE.md").write_text(
                "# Start Here\n\n- Stage: paused\n- Workflow: resume-orchestrator\n- Next owner: orchestrator\n",
                encoding="utf-8",
            )
            (state_dir / "project-handoff.md").write_text(
                "# Project Handoff\n\n- Status: paused\n- Current phase: recovery\n- Current workflow: resume-orchestrator\n- Next owner: orchestrator\n",
                encoding="utf-8",
            )
            (handoff_dir / "RECOVERY-1.md").write_text(
                "# Role Handoff\n\n- task_id: RECOVERY-1\n- role: orchestrator\n- status: in-progress\n- workflow_step_id: read-active-handoffs\n",
                encoding="utf-8",
            )

            report = validate_state.validate(project_root)
            codes = {item["code"] for item in report["findings"]}
            self.assertNotIn("workflow_step_not_in_current_workflow", codes)

    def test_validate_state_accepts_current_feature_delivery_step_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            handoff_dir = project_root / "ai" / "handoff" / "hubu" / "active"
            state_dir.mkdir(parents=True)
            handoff_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_phase": "executing",
                        "current_status": "executing",
                        "current_workflow": "feature-delivery",
                        "next_owner": "hubu",
                        "execution_allowed": True,
                        "testing_allowed": False,
                        "release_allowed": False,
                        "active_tasks": [
                            {
                                "task_id": "DATA-001",
                                "role": "hubu",
                                "status": "in-progress",
                                "handoff_path": "ai/handoff/hubu/active/DATA-001.md",
                                "workflow_step_id": "hubu-implementation",
                            }
                        ],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "START_HERE.md").write_text(
                "# Start Here\n\n- Stage: executing\n- Workflow: feature-delivery\n- Next owner: hubu\n",
                encoding="utf-8",
            )
            (state_dir / "project-handoff.md").write_text(
                "# Project Handoff\n\n- Status: executing\n- Current phase: executing\n- Current workflow: feature-delivery\n- Next owner: hubu\n",
                encoding="utf-8",
            )
            (handoff_dir / "DATA-001.md").write_text(
                "# Role Handoff\n\n- task_id: DATA-001\n- role: hubu\n- status: in-progress\n- workflow_step_id: hubu-implementation\n",
                encoding="utf-8",
            )

            report = validate_state.validate(project_root)
            codes = {item["code"] for item in report["findings"]}
            self.assertNotIn("workflow_step_not_in_current_workflow", codes)

    def test_validate_state_accepts_feature_delivery_cross_review_step_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            handoff_dir = project_root / "ai" / "handoff" / "duchayuan" / "active"
            state_dir.mkdir(parents=True)
            handoff_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_phase": "department-review",
                        "current_status": "department-review",
                        "current_workflow": "feature-delivery",
                        "next_owner": "duchayuan",
                        "execution_allowed": True,
                        "testing_allowed": False,
                        "release_allowed": False,
                        "active_tasks": [
                            {
                                "task_id": "REVIEW-001",
                                "role": "duchayuan",
                                "status": "in-progress",
                                "handoff_path": "ai/handoff/duchayuan/active/REVIEW-001.md",
                                "workflow_step_id": "duchayuan-cross-review",
                            }
                        ],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "START_HERE.md").write_text(
                "# Start Here\n\n- Stage: department-review\n- Workflow: feature-delivery\n- Next owner: duchayuan\n",
                encoding="utf-8",
            )
            (state_dir / "project-handoff.md").write_text(
                "# Project Handoff\n\n- Status: department-review\n- Current phase: department-review\n- Current workflow: feature-delivery\n- Next owner: duchayuan\n",
                encoding="utf-8",
            )
            (handoff_dir / "REVIEW-001.md").write_text(
                "# Role Handoff\n\n- task_id: REVIEW-001\n- role: duchayuan\n- status: in-progress\n- workflow_step_id: duchayuan-cross-review\n",
                encoding="utf-8",
            )

            report = validate_state.validate(project_root)
            codes = {item["code"] for item in report["findings"]}
            self.assertNotIn("workflow_step_not_in_current_workflow", codes)

    def test_validate_state_rejects_formal_department_review_without_full_matrix_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_phase": "department-review",
                        "current_status": "department-review",
                        "current_workflow": "feature-delivery",
                        "next_owner": "bingbu",
                        "next_action": "Dispatch formal testing after review.",
                        "workflow_progress": {
                            "completed_steps": [
                                "intake-feature",
                                "confirm-or-replan",
                                "plan-approval",
                                "libu2-implementation",
                                "hubu-implementation",
                                "gongbu-implementation",
                                "libu2-cross-review",
                                "hubu-cross-review",
                                "gongbu-cross-review",
                                "bingbu-cross-review",
                                "libu-cross-review",
                                "xingbu-cross-review",
                                "duchayuan-cross-review",
                                "department-review",
                            ]
                        },
                        "active_tasks": [],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "START_HERE.md").write_text(
                "# Start Here\n\n- Stage: department-review\n- Workflow: feature-delivery\n- Next owner: bingbu\n",
                encoding="utf-8",
            )
            (state_dir / "project-handoff.md").write_text(
                "# Project Handoff\n\n- Status: department-review\n- Current phase: department-review\n- Current workflow: feature-delivery\n- Next owner: bingbu\n",
                encoding="utf-8",
            )
            (reports_dir / "department-approval-matrix.md").write_text(
                "# Department Approval Matrix\n\n## Reviewer duchayuan\n- libu2: PASS\n- hubu: PASS\n\n## Recommendation\n\n- PASS\n",
                encoding="utf-8",
            )

            report = validate_state.validate(project_root)
            codes = {item["code"] for item in report["findings"]}
            self.assertIn("incomplete_department_review_sources", codes)

    def test_validate_state_rejects_formal_department_review_before_cross_reviews_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_phase": "department-review",
                        "current_status": "department-review",
                        "current_workflow": "feature-delivery",
                        "next_owner": "bingbu",
                        "next_action": "Dispatch formal testing after review.",
                        "workflow_progress": {
                            "completed_steps": [
                                "intake-feature",
                                "confirm-or-replan",
                                "plan-approval",
                                "libu2-implementation",
                                "hubu-implementation",
                                "gongbu-implementation",
                                "libu2-cross-review",
                                "hubu-cross-review",
                                "gongbu-cross-review",
                                "department-review",
                            ]
                        },
                        "active_tasks": [],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "START_HERE.md").write_text(
                "# Start Here\n\n- Stage: department-review\n- Workflow: feature-delivery\n- Next owner: bingbu\n",
                encoding="utf-8",
            )
            (state_dir / "project-handoff.md").write_text(
                "# Project Handoff\n\n- Status: department-review\n- Current phase: department-review\n- Current workflow: feature-delivery\n- Next owner: bingbu\n",
                encoding="utf-8",
            )
            (reports_dir / "department-approval-matrix.md").write_text(
                """# Department Approval Matrix

## Reviewer libu2
- hubu: PASS

## Reviewer hubu
- libu2: PASS

## Reviewer gongbu
- libu2: PASS

## Reviewer bingbu
- libu2: PASS

## Reviewer libu
- libu2: PASS

## Reviewer xingbu
- libu2: PASS

## Reviewer duchayuan
- libu2: PASS

## Recommendation

- PASS
""",
                encoding="utf-8",
            )

            report = validate_state.validate(project_root)
            codes = {item["code"] for item in report["findings"]}
            self.assertIn("department_review_before_cross_reviews_complete", codes)

    def test_validate_state_detects_mismatch_with_lowercase_markdown_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            state_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_phase": "planning",
                        "current_status": "draft",
                        "current_workflow": "feature-delivery",
                        "next_owner": "libu",
                        "active_tasks": [],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "START_HERE.md").write_text(
                "# Start Here\n\n- stage: draft\n- workflow: takeover-project\n- next owner: neige\n",
                encoding="utf-8",
            )
            (state_dir / "project-handoff.md").write_text(
                "# Project Handoff\n\n- status: draft\n- current phase: planning\n- current workflow: takeover-project\n- next owner: neige\n",
                encoding="utf-8",
            )

            report = validate_state.validate(project_root)
            codes = {item["code"] for item in report["findings"]}
            self.assertIn("workflow_mismatch_start_here", codes)
            self.assertIn("workflow_mismatch_handoff", codes)
            self.assertFalse(report["state_consistent"])

    def test_repair_state_fixes_common_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            state_dir.mkdir(parents=True)
            (project_root / "ai" / "handoff" / "neige" / "active").mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_phase": "planning",
                        "current_status": "draft",
                        "current_workflow": "takeover-project",
                        "next_owner": "neige",
                        "execution_allowed": False,
                        "testing_allowed": False,
                        "release_allowed": False,
                        "active_tasks": [
                            {
                                "task_id": "PLAN-001",
                                "role": "neige",
                                "status": "in-progress",
                                "handoff_path": "ai/handoff/neige/active/PLAN-001.md",
                                "workflow_step_id": "planning-repair",
                            }
                        ],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            (state_dir / "orchestrator_state.json").write_text("{}\n", encoding="utf-8")

            (state_dir / "START_HERE.md").write_text(
                """# Start Here

- Stage: executing
- Workflow: new-project
- Next owner: orchestrator
""",
                encoding="utf-8",
            )

            (state_dir / "project-handoff.md").write_text(
                """# Project Handoff

- Status: executing
- Current phase: executing
- Current workflow: new-project
- Next owner: orchestrator
""",
                encoding="utf-8",
            )

            (state_dir / "project-takeover.md").write_text(
                """# Project Takeover

- [fill here]
""",
                encoding="utf-8",
            )

            report = repair_state.repair(project_root)

            self.assertTrue(report["state_consistent"], report)
            self.assertFalse((state_dir / "orchestrator_state.json").exists())
            self.assertTrue((project_root / "ai" / "handoff" / "neige" / "active" / "PLAN-001.md").exists())
            takeover_text = (state_dir / "project-takeover.md").read_text(encoding="utf-8")
            self.assertIn("Proceed in `mid-stream-takeover` mode.", takeover_text)

    def test_project_guard_runner_passes_on_consistent_bootstrapped_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            (project_root / ".git").mkdir(parents=True)

            bootstrap = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "bootstrap_governance.py"),
                    str(project_root),
                    "--scenario",
                    "mid-stream-takeover",
                    "--project-name",
                    "xianyu",
                    "--project-id",
                    "xianyu",
                    "--skill-root",
                    str(REPO_ROOT),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)

            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)

            handoff_text = (state_dir / "project-handoff.md").read_text(encoding="utf-8")
            if "- Status:" not in handoff_text:
                handoff_text += "\n- Status: draft\n"
            (state_dir / "project-handoff.md").write_text(handoff_text, encoding="utf-8")

            gate_report = project_root / "ai" / "reports" / "gate-report.md"
            gate_report.write_text(
                """# Gate Report

## Recommendation

- PASS

- mainline regression passed: YES
- rollback point available: YES
""",
                encoding="utf-8",
            )

            test_report = project_root / "ai" / "reports" / "test-report.md"
            test_report.write_text(
                """# Test Report

## Recommendation

- PASS
""",
                encoding="utf-8",
            )

            runner = subprocess.run(
                [sys.executable, str(project_root / "ai" / "tools" / "run_project_guard.py"), str(project_root)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(runner.returncode, 0, runner.stderr)
            self.assertTrue((project_root / "ai" / "reports" / "state-validation.md").exists())
            self.assertTrue((project_root / "ai" / "reports" / "gate-validation.md").exists())
            self.assertTrue((project_root / "ai" / "reports" / "agent-repair-brief.md").exists())
            repair_brief = (project_root / "ai" / "reports" / "agent-repair-brief.md").read_text(encoding="utf-8")
            self.assertIn("Copy Prompt", repair_brief)
            self.assertIn("使用 $sili-jian-orchestrator", repair_brief)


    def test_ensure_handoff_stub_rejects_paths_outside_project_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            project_root.mkdir(parents=True)
            with self.assertRaises(ValueError):
                ensure_handoff_stub(
                    project_root,
                    "../outside.md",
                    {"task_id": "TASK-001", "target_agent_id": "libu2", "title": "Escape attempt"},
                )

    def test_build_dispatch_payload_rejects_missing_or_unknown_agent(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            project_root.mkdir(parents=True)

            missing_agent_card = project_root / "missing-agent.md"
            missing_agent_card.write_text(
                """# Task Card

- task_id: FEAT-001
- title: Missing agent
- handoff_path: ai/handoff/libu2/active/FEAT-001.md
""",
                encoding="utf-8",
            )
            missing = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "build_dispatch_payload.py"),
                    str(missing_agent_card),
                    "--mode",
                    "spawn",
                    "--project-root",
                    str(project_root),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("missing target_agent_id/target_agent", missing.stderr + missing.stdout)

            unknown_agent_card = project_root / "unknown-agent.md"
            unknown_agent_card.write_text(
                """# Task Card

- task_id: FEAT-002
- target_agent_id: unknown
- title: Unknown agent
- handoff_path: ai/handoff/libu2/active/FEAT-002.md
""",
                encoding="utf-8",
            )
            unknown = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "build_dispatch_payload.py"),
                    str(unknown_agent_card),
                    "--mode",
                    "spawn",
                    "--project-root",
                    str(project_root),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(unknown.returncode, 0)
            self.assertIn("Unsupported target agent", unknown.stderr + unknown.stdout)

    def test_validate_state_rejects_unknown_current_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            state_dir.mkdir(parents=True)
            (project_root / "ai" / "handoff" / "libu" / "active").mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_phase": "planning",
                        "current_status": "draft",
                        "current_workflow": "mystery-flow",
                        "next_owner": "libu",
                        "active_tasks": [],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "START_HERE.md").write_text(
                "# Start Here\n\n- Stage: draft\n- Workflow: mystery-flow\n- Next owner: libu\n",
                encoding="utf-8",
            )
            (state_dir / "project-handoff.md").write_text(
                "# Project Handoff\n\n- Status: draft\n- Current phase: planning\n- Current workflow: mystery-flow\n- Next owner: libu\n",
                encoding="utf-8",
            )

            report = validate_state.validate(project_root)
            codes = {item["code"] for item in report["findings"]}
            self.assertIn("unknown_current_workflow", codes)

    def test_validate_state_rejects_handoff_outside_project_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            state_dir.mkdir(parents=True)

            outside_handoff = Path(tmp) / "outside.md"
            outside_handoff.write_text(
                """# Role Handoff

- task_id: TASK-001
- role: libu2
- status: in-progress
- workflow_step_id: libu2-implementation
""",
                encoding="utf-8",
            )

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_phase": "execution",
                        "current_status": "executing",
                        "current_workflow": "feature-delivery",
                        "next_owner": "libu2",
                        "execution_allowed": True,
                        "testing_allowed": False,
                        "release_allowed": False,
                        "active_tasks": [
                            {
                                "task_id": "TASK-001",
                                "role": "libu2",
                                "status": "in-progress",
                                "handoff_path": str(outside_handoff),
                                "workflow_step_id": "libu2-implementation",
                            }
                        ],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "START_HERE.md").write_text(
                "# Start Here\n\n- Stage: executing\n- Workflow: feature-delivery\n- Next owner: libu2\n",
                encoding="utf-8",
            )
            (state_dir / "project-handoff.md").write_text(
                "# Project Handoff\n\n- Status: executing\n- Current phase: execution\n- Current workflow: feature-delivery\n- Next owner: libu2\n",
                encoding="utf-8",
            )

            report = validate_state.validate(project_root)
            codes = {item["code"] for item in report["findings"]}
            self.assertIn("active_task_handoff_outside_project_root", codes)
            self.assertFalse(report["state_consistent"])

    def test_scenario_from_intent_prefers_session_recovery_over_new_feature(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            runs_dir = project_root / "ai" / "runs" / "run-001"
            state_dir.mkdir(parents=True)
            runs_dir.mkdir(parents=True)
            (project_root / "tests").mkdir()
            (project_root / "workflows").mkdir()
            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_status": "testing",
                        "current_workflow": "feature-delivery",
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            self.assertEqual(scenario_from_intent("auto", project_root), "session-recovery")

    def test_ensure_dual_review_state_adds_defaults(self):
        payload = {"current_status": "draft"}
        common.ensure_dual_review_state(payload)
        self.assertIn("dual_review_enabled", payload)
        self.assertIn("review_pass_1", payload)
        self.assertIn("review_pass_2", payload)
        self.assertIn("review_conflict", payload)
        self.assertIn("review_run_id", payload)
        self.assertIn("review_commit_sha", payload)
        self.assertIn("review_arbitration_required", payload)
        self.assertIn("review_arbitration_status", payload)
        self.assertIn("review_arbitration_evidence", payload)
        self.assertFalse(payload["dual_review_enabled"])
        self.assertIsNone(payload["review_pass_1"])
        self.assertIsNone(payload["review_pass_2"])
        self.assertFalse(payload["review_conflict"])
        self.assertEqual(payload["review_run_id"], "")
        self.assertEqual(payload["review_commit_sha"], "")
        self.assertFalse(payload["review_arbitration_required"])
        self.assertEqual(payload["review_arbitration_status"], "")
        self.assertEqual(payload["review_arbitration_evidence"], "")

    def test_ensure_dual_review_state_marks_conflict_and_pending_arbitration(self):
        payload = {
            "dual_review_enabled": True,
            "review_pass_1": "PASS",
            "review_pass_2": "FAIL",
        }
        common.ensure_dual_review_state(payload)
        self.assertTrue(payload["review_conflict"])
        self.assertTrue(payload["review_arbitration_required"])
        self.assertEqual(payload["review_arbitration_status"], "pending")

    def test_ensure_dual_review_state_keeps_conflict_until_evidence(self):
        payload = {
            "dual_review_enabled": True,
            "review_pass_1": "PASS",
            "review_pass_2": "PASS",
            "review_conflict": True,
            "review_arbitration_required": True,
            "review_arbitration_status": "resolved",
            "review_arbitration_evidence": "",
        }
        common.ensure_dual_review_state(payload)
        self.assertTrue(payload["review_conflict"])
        self.assertTrue(payload["review_arbitration_required"])

        payload["review_arbitration_evidence"] = "ai/reports/arbitration-dual-review.md"
        common.ensure_dual_review_state(payload)
        self.assertFalse(payload["review_conflict"])

    def test_validate_gates_fails_closed_when_state_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)
            (state_dir / "project-handoff.md").write_text("# Project Handoff\n", encoding="utf-8")

            report = validate_gates.validate(project_root)
            self.assertFalse(report["state_present"])
            self.assertFalse(report["state_readable"])
            self.assertFalse(report["phase_gate_passed"])

    def test_validate_gates_blocks_on_doc_coverage_high_risk_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            runtime_dir = project_root / "ai" / "runtime"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)
            runtime_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_phase": "planning",
                        "current_status": "planning",
                        "current_workflow": "feature-delivery",
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "project-handoff.md").write_text("# Project Handoff\n", encoding="utf-8")
            (state_dir / "feature-registry.json").write_text(
                json.dumps(
                    {
                        "version": "v3.1.1",
                        "registry_version": "1.0.0",
                        "repo_id": "demo.repo",
                        "features": [
                            {
                                "feature_id": "auth.login",
                                "name": "Auth Login",
                                "risk_level": "high",
                                "gate_mode": "strict",
                                "owners": ["xingbu"],
                                "doc_targets": [],
                                "evidence": {"code_anchors": ["src/auth.py"]},
                            }
                        ],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (reports_dir / "doc-ir.json").write_text(
                json.dumps({"documents": []}, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (runtime_dir / "doc-gate-config.json").write_text(
                json.dumps({"version": "v3.1.1", "shadowToStrict": {}}, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            report = validate_gates.validate(project_root)
            self.assertTrue(report["doc_coverage_enabled"])
            self.assertIn("doc-coverage-report:high-risk-missing", report["blocker_sources"])
            self.assertFalse(report["phase_gate_passed"])

    def test_validate_gates_blocks_on_unregistered_doc_feature_refs(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            runtime_dir = project_root / "ai" / "runtime"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)
            runtime_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_phase": "planning",
                        "current_status": "planning",
                        "current_workflow": "feature-delivery",
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "project-handoff.md").write_text("# Project Handoff\n", encoding="utf-8")
            (state_dir / "feature-registry.json").write_text(
                json.dumps(
                    {
                        "version": "v3.1.1",
                        "registry_version": "1.0.0",
                        "repo_id": "demo.repo",
                        "features": [],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (reports_dir / "doc-ir.json").write_text(
                json.dumps(
                    {
                        "documents": [
                            {
                                "version": "1.0.0",
                                "repo_id": "demo.repo",
                                "source_format": "md",
                                "doc_path": "docs/auth.md",
                                "line_range": {"start": 1, "end": 10},
                                "anchor": "Auth",
                                "feature_refs": ["unknown.feature.xyz"],
                                "metadata": {
                                    "owner": "",
                                    "last_modified": "2026-04-02T00:00:00+00:00",
                                    "commit_sha": "",
                                    "generated_at": "2026-04-02T00:00:00+00:00",
                                },
                            }
                        ]
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (runtime_dir / "doc-gate-config.json").write_text(
                json.dumps({"version": "v3.1.1", "shadowToStrict": {}}, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            report = validate_gates.validate(project_root)
            self.assertTrue(report["doc_coverage_enabled"])
            self.assertIn("doc-coverage-report:unregistered-feature-ref", report["blocker_sources"])
            self.assertFalse(report["phase_gate_passed"])

    def test_validate_gates_requires_arbitration_evidence_when_needed(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_phase": "final-audit",
                        "current_status": "accepted",
                        "current_workflow": "feature-delivery",
                        "execution_allowed": True,
                        "release_allowed": False,
                        "dual_review_enabled": True,
                        "review_pass_1": "PASS",
                        "review_pass_2": "PASS",
                        "review_conflict": False,
                        "review_arbitration_required": True,
                        "review_arbitration_status": "resolved",
                        "review_arbitration_evidence": "",
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "project-handoff.md").write_text("# Project Handoff\n", encoding="utf-8")
            (reports_dir / "test-report.md").write_text("## Recommendation\n\n- PASS\n", encoding="utf-8")
            (reports_dir / "acceptance-report.md").write_text("## Final Conclusion\n\n- PASS\n", encoding="utf-8")
            (reports_dir / "change-summary.md").write_text("# Change Summary\n", encoding="utf-8")
            (reports_dir / "gate-report.md").write_text(
                "## Recommendation\n\n- PASS\n\n- mainline regression passed: YES\n- rollback point available: N/A\n",
                encoding="utf-8",
            )
            (reports_dir / "department-approval-matrix.md").write_text(
                "# Department Approval Matrix\n\n"
                "## Reviewer libu2\n\n- hubu: PASS\n- gongbu: PASS\n- bingbu: PASS\n- libu: PASS\n- xingbu: PASS\n- findings: none\n- responses: none\n- closure: closed\n\n"
                "## Reviewer hubu\n\n- libu2: PASS\n- gongbu: PASS\n- bingbu: PASS\n- libu: PASS\n- xingbu: PASS\n- findings: none\n- responses: none\n- closure: closed\n\n"
                "## Reviewer gongbu\n\n- libu2: PASS\n- hubu: PASS\n- bingbu: PASS\n- libu: PASS\n- xingbu: PASS\n- findings: none\n- responses: none\n- closure: closed\n\n"
                "## Reviewer bingbu\n\n- libu2: PASS\n- hubu: PASS\n- gongbu: PASS\n- libu: PASS\n- xingbu: PASS\n- findings: none\n- responses: none\n- closure: closed\n\n"
                "## Reviewer libu\n\n- libu2: PASS\n- hubu: PASS\n- gongbu: PASS\n- bingbu: PASS\n- xingbu: PASS\n- findings: none\n- responses: none\n- closure: closed\n\n"
                "## Reviewer xingbu\n\n- libu2: PASS\n- hubu: PASS\n- gongbu: PASS\n- bingbu: PASS\n- libu: PASS\n- findings: none\n- responses: none\n- closure: closed\n\n"
                "## Reviewer duchayuan-pass1\n\n- libu2: PASS\n- hubu: PASS\n- gongbu: PASS\n- bingbu: PASS\n- libu: PASS\n- xingbu: PASS\n- findings: none\n- responses: none\n- closure: closed\n\n"
                "## Reviewer duchayuan-pass2\n\n- libu2: PASS\n- hubu: PASS\n- gongbu: PASS\n- bingbu: PASS\n- libu: PASS\n- xingbu: PASS\n- findings: none\n- responses: none\n- closure: closed\n\n"
                "## Recommendation\n\n- PASS\n",
                encoding="utf-8",
            )

            report = validate_gates.validate(project_root)
            self.assertTrue(report["review_arbitration_required"])
            self.assertFalse(report["review_arbitration_ready"])
            self.assertIn("dual-review:missing-arbitration-evidence", report["blocker_sources"])
            self.assertFalse(report["final_gate_passed"])

    def test_validate_gates_dual_review_conflict_blocks_final_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_phase": "final-audit",
                        "current_status": "accepted",
                        "current_workflow": "feature-delivery",
                        "execution_allowed": True,
                        "release_allowed": False,
                        "dual_review_enabled": True,
                        "review_pass_1": "PASS",
                        "review_pass_2": "FAIL",
                        "review_conflict": True,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "project-handoff.md").write_text("# Project Handoff\n", encoding="utf-8")
            (reports_dir / "test-report.md").write_text("## Recommendation\n\n- PASS\n", encoding="utf-8")
            (reports_dir / "acceptance-report.md").write_text("## Final Conclusion\n\n- PASS\n", encoding="utf-8")
            (reports_dir / "change-summary.md").write_text("# Change Summary\n", encoding="utf-8")
            (reports_dir / "gate-report.md").write_text(
                "## Recommendation\n\n- PASS\n\n- mainline regression passed: YES\n- rollback point available: N/A\n",
                encoding="utf-8",
            )
            (reports_dir / "department-approval-matrix.md").write_text(
                "# Department Approval Matrix\n\n"
                "## Reviewer libu2\n\n- hubu: PASS\n- gongbu: PASS\n- bingbu: PASS\n- libu: PASS\n- xingbu: PASS\n- findings: none\n- responses: none\n- closure: closed\n\n"
                "## Reviewer hubu\n\n- libu2: PASS\n- gongbu: PASS\n- bingbu: PASS\n- libu: PASS\n- xingbu: PASS\n- findings: none\n- responses: none\n- closure: closed\n\n"
                "## Reviewer gongbu\n\n- libu2: PASS\n- hubu: PASS\n- bingbu: PASS\n- libu: PASS\n- xingbu: PASS\n- findings: none\n- responses: none\n- closure: closed\n\n"
                "## Reviewer bingbu\n\n- libu2: PASS\n- hubu: PASS\n- gongbu: PASS\n- libu: PASS\n- xingbu: PASS\n- findings: none\n- responses: none\n- closure: closed\n\n"
                "## Reviewer libu\n\n- libu2: PASS\n- hubu: PASS\n- gongbu: PASS\n- bingbu: PASS\n- xingbu: PASS\n- findings: none\n- responses: none\n- closure: closed\n\n"
                "## Reviewer xingbu\n\n- libu2: PASS\n- hubu: PASS\n- gongbu: PASS\n- bingbu: PASS\n- libu: PASS\n- findings: none\n- responses: none\n- closure: closed\n\n"
                "## Reviewer duchayuan-pass1\n\n- libu2: PASS\n- hubu: PASS\n- gongbu: PASS\n- bingbu: PASS\n- libu: PASS\n- xingbu: PASS\n- findings: none\n- responses: none\n- closure: closed\n\n"
                "## Reviewer duchayuan-pass2\n\n- libu2: PASS\n- hubu: PASS\n- gongbu: PASS\n- bingbu: PASS\n- libu: PASS\n- xingbu: PASS\n- findings: none\n- responses: none\n- closure: closed\n\n"
                "## Recommendation\n\n- PASS\n",
                encoding="utf-8",
            )

            report = validate_gates.validate(project_root)
            self.assertTrue(report["dual_review_enabled"])
            self.assertFalse(report["dual_review_gate_ready"])
            self.assertIn("dual-review:pending-or-conflict", report["blocker_sources"])
            self.assertFalse(report["final_gate_passed"])

    def test_validate_gates_blocks_when_dual_review_sections_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_phase": "department-review",
                        "current_status": "department-review",
                        "current_workflow": "feature-delivery",
                        "dual_review_enabled": True,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "project-handoff.md").write_text("# Project Handoff\n", encoding="utf-8")
            (reports_dir / "test-report.md").write_text("## Recommendation\n\n- PASS\n", encoding="utf-8")
            (reports_dir / "acceptance-report.md").write_text("## Final Conclusion\n\n- PASS\n", encoding="utf-8")
            (reports_dir / "change-summary.md").write_text("# Change Summary\n", encoding="utf-8")
            (reports_dir / "gate-report.md").write_text("## Recommendation\n\n- PASS\n", encoding="utf-8")
            (reports_dir / "department-approval-matrix.md").write_text(
                "# Department Approval Matrix\n\n"
                "## Reviewer libu2\n\n"
                "- hubu: PASS\n- gongbu: PASS\n- bingbu: PASS\n- libu: PASS\n- xingbu: PASS\n"
                "- findings: none\n- responses: none\n- closure: closed\n\n"
                "## Reviewer hubu\n\n"
                "- libu2: PASS\n- gongbu: PASS\n- bingbu: PASS\n- libu: PASS\n- xingbu: PASS\n"
                "- findings: none\n- responses: none\n- closure: closed\n\n"
                "## Reviewer gongbu\n\n"
                "- libu2: PASS\n- hubu: PASS\n- bingbu: PASS\n- libu: PASS\n- xingbu: PASS\n"
                "- findings: none\n- responses: none\n- closure: closed\n\n"
                "## Reviewer bingbu\n\n"
                "- libu2: PASS\n- hubu: PASS\n- gongbu: PASS\n- libu: PASS\n- xingbu: PASS\n"
                "- findings: none\n- responses: none\n- closure: closed\n\n"
                "## Reviewer libu\n\n"
                "- libu2: PASS\n- hubu: PASS\n- gongbu: PASS\n- bingbu: PASS\n- xingbu: PASS\n"
                "- findings: none\n- responses: none\n- closure: closed\n\n"
                "## Reviewer xingbu\n\n"
                "- libu2: PASS\n- hubu: PASS\n- gongbu: PASS\n- bingbu: PASS\n- libu: PASS\n"
                "- findings: none\n- responses: none\n- closure: closed\n\n"
                "## Recommendation\n\n- PASS\n",
                encoding="utf-8",
            )

            report = validate_gates.validate(project_root)
            self.assertTrue(report["dual_review_enabled"])
            self.assertIn("department-approval-matrix.md:missing-dual-review-sections", report["blocker_sources"])
            self.assertFalse(report["matrix_complete"])

    def test_validate_gates_blocks_non_empty_blockers_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_phase": "testing",
                        "current_status": "testing",
                        "current_workflow": "feature-delivery",
                        "next_owner": "libu2",
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "project-handoff.md").write_text(
                "# Project Handoff\n\n- Status: testing\n- Current phase: testing\n- Current workflow: feature-delivery\n- Next owner: libu2\n",
                encoding="utf-8",
            )
            (reports_dir / "test-report.md").write_text(
                """# Test Report

## Blockers

- API contract mismatch with production

## Recommendation

- PASS
""",
                encoding="utf-8",
            )

            report = validate_gates.validate(project_root)
            self.assertIn("test-report.md", report["blocker_sources"])
            self.assertFalse(report["phase_gate_passed"])

    def test_validate_gates_blocks_indented_aggregated_matrix_blockers(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_phase": "department-review",
                        "current_status": "department-review",
                        "current_workflow": "feature-delivery",
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "project-handoff.md").write_text("# Project Handoff\n", encoding="utf-8")
            (reports_dir / "test-report.md").write_text("# Test Report\n\n## Recommendation\n\n- PASS\n", encoding="utf-8")
            (reports_dir / "department-approval-matrix.md").write_text(
                """# Department Approval Matrix

## Reviewer libu2
- hubu: PASS
- gongbu: PASS
- bingbu: PASS
- libu: PASS
- xingbu: PASS
- findings: none
- responses: none
- closure: closed

## Reviewer hubu
- libu2: PASS
- gongbu: PASS
- bingbu: PASS
- libu: PASS
- xingbu: PASS
- findings: none
- responses: none
- closure: closed

## Reviewer gongbu
- libu2: PASS
- hubu: PASS
- bingbu: PASS
- libu: PASS
- xingbu: PASS
- findings: none
- responses: none
- closure: closed

## Reviewer bingbu
- libu2: PASS
- hubu: PASS
- gongbu: PASS
- libu: PASS
- xingbu: PASS
- findings: none
- responses: none
- closure: closed

## Reviewer libu
- libu2: PASS
- hubu: PASS
- gongbu: PASS
- bingbu: PASS
- xingbu: PASS
- findings: none
- responses: none
- closure: closed

## Reviewer xingbu
- libu2: PASS
- hubu: PASS
- gongbu: PASS
- bingbu: PASS
- libu: PASS
- findings: none
- responses: none
- closure: closed

## Aggregated Issues
- blockers:
  schema mismatch unresolved
- warnings: none
- suggestions: none
- conflicts needing arbitration: none

## Recommendation
- PASS
""",
                encoding="utf-8",
            )

            report = validate_gates.validate(project_root)
            self.assertIn("department-approval-matrix.md", report["blocker_sources"])
            self.assertFalse(report["phase_gate_passed"])

    def test_validate_gates_accepts_filled_count_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_phase": "testing",
                        "current_status": "testing",
                        "current_workflow": "feature-delivery",
                        "next_owner": "libu2",
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "project-handoff.md").write_text(
                "# Project Handoff\n\n- Status: testing\n- Current phase: testing\n- Current workflow: feature-delivery\n- Next owner: libu2\n",
                encoding="utf-8",
            )
            (reports_dir / "test-report.md").write_text(
                """# Test Report

## Counts

- passed: 12
- failed: 0
- skipped: 1

## Recommendation

- PASS
""",
                encoding="utf-8",
            )

            report = validate_gates.validate(project_root)
            self.assertNotIn("test-report.md", report["placeholder_sources"])
            self.assertTrue(report["phase_gate_passed"])

    def test_validate_gates_requires_doc_coverage_when_release_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            runtime_dir = project_root / "ai" / "runtime"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)
            runtime_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_phase": "final-audit",
                        "current_status": "final-audit",
                        "current_workflow": "feature-delivery",
                        "release_allowed": True,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "project-handoff.md").write_text("# Project Handoff\n", encoding="utf-8")
            (runtime_dir / "doc-gate-config.json").write_text(
                json.dumps({"version": "v3.1.1", "shadowToStrict": {"coverageRateMin": 0.95}}, indent=2, ensure_ascii=False)
                + "\n",
                encoding="utf-8",
            )

            report = validate_gates.validate(project_root)
            self.assertTrue(report["doc_coverage_required"])
            self.assertIn("doc-coverage-report:missing", report["blocker_sources"])
            self.assertFalse(report["phase_gate_passed"])

    def test_validate_gates_blocks_review_stage_without_required_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_phase": "department-review",
                        "current_status": "department-review",
                        "current_workflow": "feature-delivery",
                        "next_owner": "duchayuan",
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "project-handoff.md").write_text(
                "# Project Handoff\n\n- Status: department-review\n- Current phase: department-review\n- Current workflow: feature-delivery\n- Next owner: duchayuan\n",
                encoding="utf-8",
            )
            (reports_dir / "test-report.md").write_text(
                "# Test Report\n\n## Recommendation\n\n- PASS\n",
                encoding="utf-8",
            )

            report = validate_gates.validate(project_root)
            self.assertFalse(report["approval_matrix_present"])
            self.assertFalse(report["phase_gate_passed"])

    def test_validate_gates_allows_final_audit_before_release_artifacts_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_phase": "final-audit",
                        "current_status": "final-audit",
                        "current_workflow": "feature-delivery",
                        "release_allowed": False,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "project-handoff.md").write_text("# Project Handoff\n", encoding="utf-8")
            (reports_dir / "test-report.md").write_text("# Test Report\n\n## Recommendation\n\n- PASS\n", encoding="utf-8")
            (reports_dir / "department-approval-matrix.md").write_text(
                """# Department Approval Matrix

## Reviewer libu2
- hubu: PASS
- gongbu: PASS
- bingbu: PASS
- libu: PASS
- xingbu: PASS
- findings: none
- responses: none
- closure: closed

## Reviewer hubu
- libu2: PASS
- gongbu: PASS
- bingbu: PASS
- libu: PASS
- xingbu: PASS
- findings: none
- responses: none
- closure: closed

## Reviewer gongbu
- libu2: PASS
- hubu: PASS
- bingbu: PASS
- libu: PASS
- xingbu: PASS
- findings: none
- responses: none
- closure: closed

## Reviewer bingbu
- libu2: PASS
- hubu: PASS
- gongbu: PASS
- libu: PASS
- xingbu: PASS
- findings: none
- responses: none
- closure: closed

## Reviewer libu
- libu2: PASS
- hubu: PASS
- gongbu: PASS
- bingbu: PASS
- xingbu: PASS
- findings: none
- responses: none
- closure: closed

## Reviewer xingbu
- libu2: PASS
- hubu: PASS
- gongbu: PASS
- bingbu: PASS
- libu: PASS
- findings: none
- responses: none
- closure: closed

## Recommendation
- PASS
""",
                encoding="utf-8",
            )

            report = validate_gates.validate(project_root)
            self.assertTrue(report["phase_gate_passed"])

    def test_validate_gates_blocks_release_when_resource_retest_is_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)
            (state_dir / "project-handoff.md").write_text("# Handoff\n", encoding="utf-8")
            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_phase": "release",
                        "current_status": "accepted",
                        "release_allowed": True,
                        "execution_allowed": True,
                        "testing_allowed": True,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (reports_dir / "test-report.md").write_text(
                "# Test Report\n\n## Recommendation\n\n- PASS\n\n- blocker count zero: yes\n",
                encoding="utf-8",
            )
            (reports_dir / "department-approval-matrix.md").write_text(
                "# Matrix\n\n## Recommendation\n\n- PASS\n\n## Reviewer libu2\n- hubu: PASS\n- gongbu: PASS\n- bingbu: PASS\n- libu: PASS\n- xingbu: PASS\n- findings: none\n- responses: none\n- closure: none\n\n## Reviewer hubu\n- libu2: PASS\n- gongbu: PASS\n- bingbu: PASS\n- libu: PASS\n- xingbu: PASS\n- findings: none\n- responses: none\n- closure: none\n\n## Reviewer gongbu\n- libu2: PASS\n- hubu: PASS\n- bingbu: PASS\n- libu: PASS\n- xingbu: PASS\n- findings: none\n- responses: none\n- closure: none\n\n## Reviewer bingbu\n- libu2: PASS\n- hubu: PASS\n- gongbu: PASS\n- libu: PASS\n- xingbu: PASS\n- findings: none\n- responses: none\n- closure: none\n\n## Reviewer libu\n- libu2: PASS\n- hubu: PASS\n- gongbu: PASS\n- bingbu: PASS\n- xingbu: PASS\n- findings: none\n- responses: none\n- closure: none\n\n## Reviewer xingbu\n- libu2: PASS\n- hubu: PASS\n- gongbu: PASS\n- bingbu: PASS\n- libu: PASS\n- findings: none\n- responses: none\n- closure: none\n",
                encoding="utf-8",
            )
            (reports_dir / "acceptance-report.md").write_text(
                "# Acceptance\n\n## Final Conclusion\n\n- PASS\n\n- blocker count zero: yes\n",
                encoding="utf-8",
            )
            (reports_dir / "change-summary.md").write_text("# Change Summary\n\n- ready: yes\n", encoding="utf-8")
            (reports_dir / "gate-report.md").write_text(
                "# Gate Report\n\n## Recommendation\n\n- PASS\n\n- mainline regression passed: YES\n- rollback point available: YES\n",
                encoding="utf-8",
            )
            recorded = resource_requirements.record_gap(
                project_root,
                resource_name="Stripe live callbacks",
                category="real-api",
                policy="mock",
                due_stage="release",
                scope_level="module",
                scope_label="payments",
                notes="Callbacks are still mocked and require a live retest before release.",
            )
            resource_requirements.resolve_gap(
                project_root,
                gap_id=recorded["gap"]["gap_id"],
                resolution_summary="Customer provided the callback secret.",
                supplied_by="customer",
            )

            report = validate_gates.validate(project_root)
            self.assertFalse(report["phase_gate_passed"])
            self.assertFalse(report["final_gate_passed"])
            self.assertIn("resource-gap-report.md", report["blocker_sources"])

    def test_validate_gates_blocks_aggregated_matrix_blockers(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_phase": "department-review",
                        "current_status": "department-review",
                        "current_workflow": "feature-delivery",
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "project-handoff.md").write_text("# Project Handoff\n", encoding="utf-8")
            (reports_dir / "test-report.md").write_text("# Test Report\n\n## Recommendation\n\n- PASS\n", encoding="utf-8")
            (reports_dir / "department-approval-matrix.md").write_text(
                """# Department Approval Matrix

## Reviewer libu2
- hubu: PASS
- gongbu: PASS
- bingbu: PASS
- libu: PASS
- xingbu: PASS
- findings: none
- responses: none
- closure: closed

## Reviewer hubu
- libu2: PASS
- gongbu: PASS
- bingbu: PASS
- libu: PASS
- xingbu: PASS
- findings: none
- responses: none
- closure: closed

## Reviewer gongbu
- libu2: PASS
- hubu: PASS
- bingbu: PASS
- libu: PASS
- xingbu: PASS
- findings: none
- responses: none
- closure: closed

## Reviewer bingbu
- libu2: PASS
- hubu: PASS
- gongbu: PASS
- libu: PASS
- xingbu: PASS
- findings: none
- responses: none
- closure: closed

## Reviewer libu
- libu2: PASS
- hubu: PASS
- gongbu: PASS
- bingbu: PASS
- xingbu: PASS
- findings: none
- responses: none
- closure: closed

## Reviewer xingbu
- libu2: PASS
- hubu: PASS
- gongbu: PASS
- bingbu: PASS
- libu: PASS
- findings: none
- responses: none
- closure: closed

## Aggregated Issues
- blockers: schema mismatch unresolved
- warnings: none
- suggestions: none
- conflicts needing arbitration: none

## Recommendation
- PASS
""",
                encoding="utf-8",
            )

            report = validate_gates.validate(project_root)
            self.assertIn("department-approval-matrix.md", report["blocker_sources"])
            self.assertFalse(report["phase_gate_passed"])

    def test_validate_gates_blocks_acceptance_report_when_blocker_count_not_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_phase": "final-audit",
                        "current_status": "final-audit",
                        "current_workflow": "feature-delivery",
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "project-handoff.md").write_text("# Project Handoff\n", encoding="utf-8")
            (reports_dir / "test-report.md").write_text("# Test Report\n\n## Recommendation\n\n- PASS\n", encoding="utf-8")
            (reports_dir / "department-approval-matrix.md").write_text(
                """# Department Approval Matrix

## Reviewer libu2
- hubu: PASS
- gongbu: PASS
- bingbu: PASS
- libu: PASS
- xingbu: PASS
- findings: none
- responses: none
- closure: closed

## Reviewer hubu
- libu2: PASS
- gongbu: PASS
- bingbu: PASS
- libu: PASS
- xingbu: PASS
- findings: none
- responses: none
- closure: closed

## Reviewer gongbu
- libu2: PASS
- hubu: PASS
- bingbu: PASS
- libu: PASS
- xingbu: PASS
- findings: none
- responses: none
- closure: closed

## Reviewer bingbu
- libu2: PASS
- hubu: PASS
- gongbu: PASS
- libu: PASS
- xingbu: PASS
- findings: none
- responses: none
- closure: closed

## Reviewer libu
- libu2: PASS
- hubu: PASS
- gongbu: PASS
- bingbu: PASS
- xingbu: PASS
- findings: none
- responses: none
- closure: closed

## Reviewer xingbu
- libu2: PASS
- hubu: PASS
- gongbu: PASS
- bingbu: PASS
- libu: PASS
- findings: none
- responses: none
- closure: closed

## Recommendation
- PASS
""",
                encoding="utf-8",
            )
            (reports_dir / "acceptance-report.md").write_text(
                """# Acceptance Report

## Checklist

- blocker count zero: NO

## Final Conclusion

- PASS
""",
                encoding="utf-8",
            )
            (reports_dir / "change-summary.md").write_text("# Change Summary\n", encoding="utf-8")
            (reports_dir / "gate-report.md").write_text(
                "# Gate Report\n\n## Recommendation\n\n- PASS\n\n- mainline regression passed: YES\n- rollback point available: YES\n",
                encoding="utf-8",
            )

            report = validate_gates.validate(project_root)
            self.assertIn("acceptance-report.md", report["blocker_sources"])
            self.assertFalse(report["phase_gate_passed"])
            self.assertFalse(report["final_gate_passed"])

    def test_run_repo_ci_collects_real_entry_points(self):
        script = (
            "import sys; "
            f"sys.path.insert(0, r'{str(SCRIPTS_DIR)}'); "
            "import run_repo_ci; "
            "targets={p.name for p in run_repo_ci.collect_py_targets()}; "
            "required={'common.py','validate_gates.py','ensure_openclaw_agents.py','first_run_check.py','inspect_project.py','generate_takeover_report.py','recovery_summary.py','run_project_guard.py','render_agent_repair_brief.py','sync_project_tools.py','session_registry.py','workflow_engine.py','openclaw_adapter.py','openclaw_runtime_bridge.py','completion_consumer.py','context_rollover.py','run_orchestrator.py','inbox_watcher.py','runtime_loop.py','task_rounds.py','orchestrator_local_steps.py','repo_command_detector.py','provider_evidence.py','host_interface_probe.py','runtime_environment.py','runtime_guardrails.py','environment_bootstrap.py','evidence_collector.py','escalation_manager.py','parent_session_recovery.py','automation_control.py','configure_autonomy.py','git_autocommit.py','natural_language_control.py','change_request_control.py','replan_change_request.py','project_intake.py','configure_review_controls.py','resume_customer_decision.py'}; "
            "missing=sorted(required-targets); "
            "print('\\n'.join(missing)); "
            "raise SystemExit(1 if missing else 0)"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_sync_project_tools_check_passes(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "sync_project_tools.py"), "--check"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("in sync", result.stdout)

    def test_sync_project_tools_detects_and_repairs_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp) / "repo"
            scripts_dir = repo_root / "scripts"
            tools_dir = repo_root / "assets" / "project-skeleton" / "ai" / "tools"
            scripts_dir.mkdir(parents=True)
            tools_dir.mkdir(parents=True)

            for name in sync_project_tools.PROJECT_TOOL_FILES:
                (scripts_dir / name).write_text(f"# source {name}\n", encoding="utf-8")
                (tools_dir / name).write_text(f"# old {name}\n", encoding="utf-8")

            drift_file = sync_project_tools.PROJECT_TOOL_FILES[0]
            (tools_dir / drift_file).write_text("# drifted scaffold\n", encoding="utf-8")

            out_of_sync = sync_project_tools.find_out_of_sync_project_tools(repo_root)
            self.assertIn(drift_file, out_of_sync)

            updated = sync_project_tools.sync_project_tools(repo_root)
            self.assertIn(drift_file, updated)
            self.assertEqual(
                (tools_dir / drift_file).read_text(encoding="utf-8"),
                (scripts_dir / drift_file).read_text(encoding="utf-8"),
            )
            self.assertEqual(sync_project_tools.find_out_of_sync_project_tools(repo_root), [])

    def test_scaffolded_validate_state_catches_handoff_phase_and_step_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            (project_root / ".git").mkdir(parents=True)

            bootstrap = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "bootstrap_governance.py"),
                    str(project_root),
                    "--scenario",
                    "mid-stream-takeover",
                    "--project-name",
                    "xianyu",
                    "--project-id",
                    "xianyu",
                    "--skill-root",
                    str(REPO_ROOT),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)

            state_dir = project_root / "ai" / "state"
            handoff_dir = project_root / "ai" / "handoff" / "neige" / "active"
            handoff_dir.mkdir(parents=True, exist_ok=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_phase": "planning",
                        "current_status": "draft",
                        "current_workflow": "takeover-project",
                        "next_owner": "neige",
                        "execution_allowed": False,
                        "testing_allowed": False,
                        "release_allowed": False,
                        "active_tasks": [
                            {
                                "task_id": "PLAN-001",
                                "role": "neige",
                                "status": "in-progress",
                                "handoff_path": "ai/handoff/neige/active/PLAN-001.md",
                                "workflow_step_id": "planning-repair",
                            }
                        ],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "START_HERE.md").write_text(
                "# Start Here\n\n- Stage: draft\n- Workflow: takeover-project\n- Next owner: neige\n",
                encoding="utf-8",
            )
            (state_dir / "project-handoff.md").write_text(
                "# Project Handoff\n\n- Status: draft\n- Current phase: execution\n- Current workflow: takeover-project\n- Next owner: neige\n",
                encoding="utf-8",
            )
            (handoff_dir / "PLAN-001.md").write_text(
                "# Role Handoff\n\n- task_id: PLAN-001\n- role: neige\n- status: in-progress\n- workflow_step_id: libu-documentation\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(project_root / "ai" / "tools" / "validate_state.py"), str(project_root)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            codes = {item["code"] for item in report["findings"]}
            self.assertIn("phase_mismatch_handoff", codes)
            self.assertIn("workflow_step_not_in_current_workflow", codes)
            self.assertFalse(report["state_consistent"])

    def test_scaffolded_project_guard_blocks_non_empty_blockers_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            (project_root / ".git").mkdir(parents=True)

            bootstrap = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "bootstrap_governance.py"),
                    str(project_root),
                    "--scenario",
                    "mid-stream-takeover",
                    "--project-name",
                    "xianyu",
                    "--project-id",
                    "xianyu",
                    "--skill-root",
                    str(REPO_ROOT),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)

            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)

            (state_dir / "project-handoff.md").write_text(
                "# Project Handoff\n\n- Status: draft\n- Current phase: planning\n- Current workflow: takeover-project\n- Next owner: orchestrator\n",
                encoding="utf-8",
            )
            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_phase": "planning",
                        "current_status": "draft",
                        "current_workflow": "takeover-project",
                        "next_owner": "orchestrator",
                        "execution_allowed": False,
                        "testing_allowed": False,
                        "release_allowed": False,
                        "active_tasks": [],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (reports_dir / "test-report.md").write_text(
                """# Test Report

## Blockers

- API contract mismatch with production

## Recommendation

- PASS
""",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(project_root / "ai" / "tools" / "run_project_guard.py"), str(project_root)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            guard_summary = json.loads((reports_dir / "project-guard-summary.json").read_text(encoding="utf-8"))
            self.assertIn("test-report.md", guard_summary["gates"]["blocker_sources"])

    def test_scaffolded_project_guard_accepts_filled_count_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            (project_root / ".git").mkdir(parents=True)

            bootstrap = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "bootstrap_governance.py"),
                    str(project_root),
                    "--scenario",
                    "mid-stream-takeover",
                    "--project-name",
                    "xianyu",
                    "--project-id",
                    "xianyu",
                    "--skill-root",
                    str(REPO_ROOT),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)

            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_phase": "testing",
                        "current_status": "testing",
                        "current_workflow": "feature-delivery",
                        "next_owner": "orchestrator",
                        "execution_allowed": True,
                        "testing_allowed": True,
                        "release_allowed": False,
                        "active_tasks": [],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "START_HERE.md").write_text(
                "# Start Here\n\n- Stage: testing\n- Workflow: feature-delivery\n- Next owner: orchestrator\n",
                encoding="utf-8",
            )
            (state_dir / "project-handoff.md").write_text(
                "# Project Handoff\n\n- Status: testing\n- Current phase: testing\n- Current workflow: feature-delivery\n- Next owner: orchestrator\n",
                encoding="utf-8",
            )
            (reports_dir / "test-report.md").write_text(
                """# Test Report

## Counts

- passed: 12
- failed: 0
- skipped: 1

## Recommendation

- PASS
""",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(project_root / "ai" / "tools" / "run_project_guard.py"), str(project_root)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            guard_summary = json.loads((reports_dir / "project-guard-summary.json").read_text(encoding="utf-8"))
            self.assertNotIn("test-report.md", guard_summary["gates"]["placeholder_sources"])

    def test_scaffolded_project_guard_fails_when_final_gate_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            (project_root / ".git").mkdir(parents=True)

            bootstrap = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "bootstrap_governance.py"),
                    str(project_root),
                    "--scenario",
                    "mid-stream-takeover",
                    "--project-name",
                    "xianyu",
                    "--project-id",
                    "xianyu",
                    "--skill-root",
                    str(REPO_ROOT),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)

            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            runtime_dir = project_root / "ai" / "runtime"
            reports_dir.mkdir(parents=True, exist_ok=True)
            runtime_dir.mkdir(parents=True, exist_ok=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_phase": "final-audit",
                        "current_status": "final-audit",
                        "current_workflow": "feature-delivery",
                        "next_owner": "duchayuan",
                        "execution_allowed": True,
                        "testing_allowed": True,
                        "release_allowed": True,
                        "active_tasks": [],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "START_HERE.md").write_text(
                "# Start Here\n\n- Stage: final-audit\n- Workflow: feature-delivery\n- Next owner: duchayuan\n",
                encoding="utf-8",
            )
            (state_dir / "project-handoff.md").write_text(
                "# Project Handoff\n\n- Status: final-audit\n- Current phase: final-audit\n- Current workflow: feature-delivery\n- Next owner: duchayuan\n",
                encoding="utf-8",
            )
            (reports_dir / "test-report.md").write_text(
                "# Test Report\n\n## Recommendation\n\n- PASS\n",
                encoding="utf-8",
            )
            (reports_dir / "department-approval-matrix.md").write_text(
                """# Department Approval Matrix

## Reviewer libu2
- hubu: PASS
- gongbu: PASS
- bingbu: PASS
- libu: PASS
- xingbu: PASS
- findings: none
- responses: none
- closure: closed

## Reviewer hubu
- libu2: PASS
- gongbu: PASS
- bingbu: PASS
- libu: PASS
- xingbu: PASS
- findings: none
- responses: none
- closure: closed

## Reviewer gongbu
- libu2: PASS
- hubu: PASS
- bingbu: PASS
- libu: PASS
- xingbu: PASS
- findings: none
- responses: none
- closure: closed

## Reviewer bingbu
- libu2: PASS
- hubu: PASS
- gongbu: PASS
- libu: PASS
- xingbu: PASS
- findings: none
- responses: none
- closure: closed

## Reviewer libu
- libu2: PASS
- hubu: PASS
- gongbu: PASS
- bingbu: PASS
- xingbu: PASS
- findings: none
- responses: none
- closure: closed

## Reviewer xingbu
- libu2: PASS
- hubu: PASS
- gongbu: PASS
- bingbu: PASS
- libu: PASS
- findings: none
- responses: none
- closure: closed

## Recommendation
- PASS
""",
                encoding="utf-8",
            )
            (reports_dir / "acceptance-report.md").write_text(
                "# Acceptance Report\n\n## Final Conclusion\n\n- PASS\n",
                encoding="utf-8",
            )
            (reports_dir / "change-summary.md").write_text("# Change Summary\n\n- updated\n", encoding="utf-8")
            (reports_dir / "gate-report.md").write_text(
                "# Gate Report\n\n## Recommendation\n\n- PASS\n\n- mainline regression passed: NO\n- rollback point available: YES\n",
                encoding="utf-8",
            )

            (state_dir / "feature-registry.json").write_text(
                json.dumps({"version": "v3.1.1", "registry_version": "1.0.0", "repo_id": "xianyu", "features": []}, indent=2, ensure_ascii=False)
                + "\n",
                encoding="utf-8",
            )
            (reports_dir / "doc-ir.json").write_text(json.dumps({"documents": []}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            (runtime_dir / "doc-gate-config.json").write_text(
                json.dumps({"version": "v3.1.1", "shadowToStrict": {"coverageRateMin": 0.95}}, indent=2, ensure_ascii=False)
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(project_root / "ai" / "tools" / "run_project_guard.py"), str(project_root)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            guard_summary = json.loads((reports_dir / "project-guard-summary.json").read_text(encoding="utf-8"))
            self.assertTrue(guard_summary["gates"]["phase_gate_passed"])
            self.assertFalse(guard_summary["gates"]["final_gate_passed"])

    def test_render_agent_repair_brief_includes_final_gate_failure_reasons(self):
        findings = render_agent_repair_brief.build_findings(
            {"findings": [], "state_consistent": True},
            {
                "blocker_sources": [],
                "placeholder_sources": [],
                "phase_gate_passed": True,
                "release_stage": True,
                "final_gate_passed": False,
                "handoff_present": True,
                "test_report_present": True,
                "approval_matrix_present": True,
                "acceptance_report_present": True,
                "change_summary_present": True,
                "gate_report_present": True,
                "matrix_complete": True,
                "test_conclusion": "PASS",
                "matrix_recommendation": "PASS",
                "acceptance_conclusion": "PASS",
                "gate_recommendation": "PASS",
                "mainline_regression": "NO",
                "rollback_point_available": "YES",
                "release_allowed": True,
            },
        )

        self.assertIn(
            "[gates/error] final_gate_mainline_regression: mainline regression passed is `NO`.",
            findings,
        )

    def test_validate_gates_does_not_require_rollback_point_without_release_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            state_dir = project_root / "ai" / "state"
            reports_dir = project_root / "ai" / "reports"
            state_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)

            (state_dir / "orchestrator-state.json").write_text(
                json.dumps(
                    {
                        "current_phase": "accepted",
                        "current_status": "accepted",
                        "current_workflow": "feature-delivery",
                        "release_allowed": False,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "project-handoff.md").write_text("# Project Handoff\n", encoding="utf-8")
            (reports_dir / "test-report.md").write_text("# Test Report\n\n## Recommendation\n\n- PASS\n", encoding="utf-8")
            (reports_dir / "department-approval-matrix.md").write_text(
                """# Department Approval Matrix

## Reviewer libu2
- hubu: PASS
- gongbu: PASS
- bingbu: PASS
- libu: PASS
- xingbu: PASS
- findings: none
- responses: none
- closure: closed

## Reviewer hubu
- libu2: PASS
- gongbu: PASS
- bingbu: PASS
- libu: PASS
- xingbu: PASS
- findings: none
- responses: none
- closure: closed

## Reviewer gongbu
- libu2: PASS
- hubu: PASS
- bingbu: PASS
- libu: PASS
- xingbu: PASS
- findings: none
- responses: none
- closure: closed

## Reviewer bingbu
- libu2: PASS
- hubu: PASS
- gongbu: PASS
- libu: PASS
- xingbu: PASS
- findings: none
- responses: none
- closure: closed

## Reviewer libu
- libu2: PASS
- hubu: PASS
- gongbu: PASS
- bingbu: PASS
- xingbu: PASS
- findings: none
- responses: none
- closure: closed

## Reviewer xingbu
- libu2: PASS
- hubu: PASS
- gongbu: PASS
- bingbu: PASS
- libu: PASS
- findings: none
- responses: none
- closure: closed

## Recommendation
- PASS
""",
                encoding="utf-8",
            )
            (reports_dir / "acceptance-report.md").write_text(
                "# Acceptance Report\n\n## Final Conclusion\n\n- PASS\n",
                encoding="utf-8",
            )
            (reports_dir / "change-summary.md").write_text("# Change Summary\n\n- updated\n", encoding="utf-8")
            (reports_dir / "gate-report.md").write_text(
                "# Gate Report\n\n## Recommendation\n\n- PASS\n\n- mainline regression passed: YES\n- rollback point available: NO\n",
                encoding="utf-8",
            )

            report = validate_gates.validate(project_root)
            self.assertTrue(report["release_stage"])
            self.assertTrue(report["final_gate_passed"])


if __name__ == "__main__":
    unittest.main()
