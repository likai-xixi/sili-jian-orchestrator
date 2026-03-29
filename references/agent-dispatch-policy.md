# Agent Dispatch Policy

Use real peer-agent dispatch when the runtime supports `sessions_spawn` and `sessions_send`.

## Dispatch Modes

### `sessions_spawn`

Use `sessions_spawn` for one-off delegated tasks.

Use it when:
- dispatching a new task card to a department
- running testing in parallel after implementation is ready
- requesting a final audit from `duchayuan`
- starting a fresh planning or review round in `neige`

Preferred payload shape:

```javascript
sessions_spawn({
  task: "[Bingbu task] Run governed test execution and update the required handoff.",
  runtime: "subagent",
  agentId: "bingbu",
  mode: "run",
  cleanup: "delete"
})
```

### `sessions_send`

Use `sessions_send` to continue an existing department session.

Use it when:
- extending an active `neige` planning session
- asking a department to address review findings
- following up on blockers in an already-open session
- continuing a long-running audit or review thread

Preferred payload shape:

```javascript
sessions_send({
  sessionKey: "agent:neige:...",
  agentId: "neige",
  message: "Continue the existing planning thread using the updated requirements and task tree."
})
```

## Cleanup Policy

For `sessions_spawn`:
- default to `cleanup: "delete"` for one-off tasks
- use `cleanup: "keep"` only when the task card explicitly sets `cleanup_policy: keep`

For `sessions_send`:
- no cleanup parameter is needed because the session is intentionally reused

## Selection Rule

Use `sessions_spawn` by default.
Use `sessions_send` only when `ai/state/agent-sessions.json` already contains a valid `sessionKey` for the target agent and continuity matters.

## Parallelism Rule

Safe to parallelize:
- `libu2`, `hubu`, and `gongbu` when write scopes do not overlap
- `bingbu` after implementation handoff exists
- `libu` and `xingbu` after implementation is stable enough for docs and release prep

Prefer serial order when:
- architecture is not frozen
- data model decisions are unresolved
- blockers are B2 or B3
- release-stage risk is high

## Orchestrator Rule

司礼监 should:
- generate or update the task card first
- choose the target peer agent from the mapping table
- dispatch using `sessions_spawn` or `sessions_send`
- record the session in `ai/state/agent-sessions.json`
- wait for completion events only when the next critical step is blocked on the result
- update `project-handoff.md` and `orchestrator-state.json` after receiving the result
