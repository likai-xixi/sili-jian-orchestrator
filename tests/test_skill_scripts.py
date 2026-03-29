import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import repair_state  # noqa: E402
import validate_gates  # noqa: E402
import validate_state  # noqa: E402
from common import ensure_handoff_stub, scenario_from_intent  # noqa: E402


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
            self.assertTrue((project_root / ".github" / "workflows" / "project-guard.yml").exists())
            self.assertTrue((project_root / ".github" / "workflows" / "project-repair-brief.yml").exists())

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
            "required={'common.py','validate_gates.py','ensure_openclaw_agents.py','first_run_check.py','inspect_project.py','generate_takeover_report.py','recovery_summary.py'}; "
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


if __name__ == "__main__":
    unittest.main()
