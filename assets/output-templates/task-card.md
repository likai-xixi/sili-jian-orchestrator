# Task Card

Use this template for every formally dispatched task.

Rules:
- `target_agent`: governance role name such as `neige`, `libu2`, `hubu`, `gongbu`, `bingbu`, `libu`, `xingbu`, `duchayuan`
- `target_agent_id`: exact OpenClaw `agentId`
- `dispatch_mode`: `spawn` or `send`
- `cleanup_policy`: for `spawn`, use `delete` by default; set `keep` only when session reuse is intentionally needed
- `session_key`: required when `dispatch_mode` is `send`
- `allowed_paths`: comma-separated repo-relative paths only
- `forbidden_paths`: comma-separated protected or out-of-scope paths
- `handoff_path`: must point to `ai/handoff/<role>/active/<task-id>.md`
- The payload builder will create the handoff stub automatically when the file does not exist yet
- `review_required`: `yes` or `no`
- `priority`: one of `P0`, `P1`, `P2`, `P3`, `P4`
- `testing_requirement`: name the exact test layer(s) and expected coverage
- `return_to`: usually `orchestrator`
- For long fields such as `goal`, `acceptance`, `expected_output`, or `testing_requirement`, continue on indented lines beneath the field.
- When using continuation lines, indent each extra line by two spaces so the payload builder can preserve the full value.

- task_id:
- target_agent:
- target_agent_id:
- dispatch_mode:
- cleanup_policy:
- session_key:
- return_to:
- title:
- goal:
- allowed_paths:
- forbidden_paths:
- dependencies:
- acceptance:
- handoff_path:
- expected_output:
- review_required:
- upstream_dependencies:
- downstream_reviewers:
- testing_requirement:
- workflow_step_id:
- priority:
