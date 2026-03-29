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
import validate_state  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
