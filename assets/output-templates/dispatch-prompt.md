# Dispatch Prompt Template

Use this structure when sending work to a peer agent.

## Header

- Department:
- AgentId:
- Task mode: `spawn` or `send`
- Task id:
- Workflow step:

## Prompt Body

【<部门>任务】
- task_id: <task_id>
- title: <title>
- goal: <goal>
- allowed_paths: <allowed_paths>
- forbidden_paths: <forbidden_paths>
- dependencies: <dependencies>
- acceptance: <acceptance>
- handoff_path: <handoff_path>
- expected_output: <expected_output>
- review_required: <review_required>
- downstream_reviewers: <downstream_reviewers>
- testing_requirement: <testing_requirement>
- priority: <priority>

完成后必须：
1. 更新 handoff
2. 明确 blockers
3. 明确是否可进入下一阶段
4. 给出回传给司礼监的 summary
