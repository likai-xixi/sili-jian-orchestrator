# Completion Handling

When a completion event returns from a peer agent, 司礼监 should do all of the following before moving to the next phase:

1. identify the source department and task id
2. read or create the department handoff under `ai/handoff/<role>/active/`
3. update `ai/state/orchestrator-state.json`
4. update `ai/state/project-handoff.md`
5. if the task finished, archive or replace the handoff and update `active_tasks`
6. if blockers were reported, record them in state and handoff
7. if testing, review, or final audit became unblocked, dispatch the next department

## Expected Completion Inputs

A useful completion should provide:
- task id
- department
- status
- summary
- files touched
- blockers
- next recommended reviewer or owner

## Session Registry Update

If the completion event reveals a stable session to reuse, persist it in `ai/state/agent-sessions.json`.
