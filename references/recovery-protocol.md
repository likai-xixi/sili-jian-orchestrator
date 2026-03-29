# Recovery Protocol

## Recovery Read Order

For a governed target project, read in this order:

1. `ai/state/START_HERE.md`
2. `ai/state/project-meta.json`
3. `ai/state/project-handoff.md`
4. `ai/state/orchestrator-state.json`
5. `ai/state/agent-sessions.json`
6. `ai/state/task-tree.json`
7. recent `ai/reports/acceptance-report.md`
8. recent `ai/reports/department-approval-matrix.md`
9. recent `ai/reports/test-report.md`
10. latest run snapshot under `ai/runs/`
11. active role handoffs if they exist

## Required Recovery Summary

Produce a recovery summary with:

- current project
- current phase
- completed tasks
- in-progress tasks
- blocked tasks
- latest plan review conclusion
- latest result audit conclusion
- latest test conclusion
- current next action
- who should handle the next step
- whether execution is currently allowed
- active role handoffs tied to `active_tasks`
