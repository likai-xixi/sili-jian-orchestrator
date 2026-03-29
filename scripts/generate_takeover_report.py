from __future__ import annotations

import argparse
from pathlib import Path

from common import inspect_project, list_markdown_summary, write_text


def build_report(info: dict) -> str:
    create_first: list[str] = []
    if not info["ai_exists"]:
        create_first.append("ai/")
    if not info["tests_exists"]:
        create_first.append("tests/")
    if not info["workflows_exists"]:
        create_first.append("workflows/")
    if "docs" in info.get("missing_top_level_dirs", []):
        create_first.append("docs/")
    create_first.extend([f"ai/state/{name}" for name in info["missing_state_files"][:5]])
    create_first.extend([f"ai/reports/{name}" for name in info["missing_report_files"][:3]])
    create_first.extend([f"tests/{name}/" for name in info["missing_test_layers"][:3]])
    create_first.extend([f"workflows/{name}" for name in info["missing_workflows"][:3]])
    create_first_text = list_markdown_summary(create_first)

    return f"""# First-Round Takeover Result

1. Current project identification result
   - Project root: {info['project_root']}
   - Project id: {info['project_id']}
   - Project name: {info['project_name']}

2. Current scenario
   - {info['scenario']}

3. `ai/` completeness
   - {'Present' if info['ai_exists'] else 'Missing'}

4. `tests/` completeness
   - {'Present' if info['tests_exists'] else 'Missing'}

5. `workflows/` completeness
   - {'Present' if info['workflows_exists'] else 'Missing'}

6. Explicit state machine
   - {'Present' if info['state_machine_exists'] else 'Missing'}

7. Most recent run snapshot
   - {info['recent_run_id'] or 'None'}

8. Missing governance files
{list_markdown_summary(info['missing_state_files'] + info['missing_report_files'])}

9. Missing testing layers
{list_markdown_summary(info['missing_test_layers'])}

10. Missing workflow templates
{list_markdown_summary(info['missing_workflows'])}

11. Missing recovery assets
{list_markdown_summary(info['missing_handoff_dirs'])}

12. Create first
{create_first_text}

13. Planning-stage entry conditions
   - {'Yes' if info['planning_ready'] else 'No'}

13a. Current implementation summary ready
   - {'Yes' if info.get('implementation_summary_ready') else 'No'}

13b. Customer acknowledged current implementation baseline
   - {'Yes' if info.get('customer_acknowledged_implementation') else 'No'}

14. Execution-stage entry conditions
   - {'Yes' if info['execution_ready'] else 'No'}

15. Testing-stage entry conditions
   - {'Yes' if info['testing_ready'] else 'No'}

16. First next_action
   - {info['next_action']}

17. Immediate execution allowed
   - {'Yes' if info['execution_ready'] else 'No'}

18. Latest plan review conclusion
   - {info['plan_review_conclusion'] or 'None'}

18a. Customer confirmed requirement and scope
   - {'Yes' if info.get('customer_confirmed_requirement') else 'No'}

18b. Approved to start development
   - {'Yes' if info.get('development_approved') else 'No'}

19. Latest result audit conclusion
   - {info['final_audit_conclusion'] or 'None'}

20. Latest test conclusion
   - {info['test_conclusion'] or 'None'}
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate first-round takeover markdown report.")
    parser.add_argument("project_root", help="Target project root")
    parser.add_argument(
        "--intent",
        default="auto",
        choices=["auto", "vague-requirement", "new-project", "mid-stream-takeover", "session-recovery", "new-feature"],
        help="Request intent to combine with directory inspection",
    )
    parser.add_argument("--output", help="Markdown output path")
    args = parser.parse_args()

    info = inspect_project(Path(args.project_root), intent=args.intent)
    report = build_report(info)
    if args.output:
        write_text(Path(args.output), report)
    else:
        print(report)


if __name__ == "__main__":
    main()
