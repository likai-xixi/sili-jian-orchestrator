# Project Governance Tools

These scripts are copied into each governed project so GitHub Actions can validate state and gates without depending on the original skill repository.

- `common.py`: shared helpers
- `validate_state.py`: state and handoff consistency check
- `validate_gates.py`: phase and release gate check
- `run_project_guard.py`: CI entrypoint for project push / PR checks
- `render_agent_repair_brief.py`: generate an agent-ready repair brief and copy prompt
