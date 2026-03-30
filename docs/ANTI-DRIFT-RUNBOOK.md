# 防跑偏运行规范

这份规范面向 `sili-jian-orchestrator` 的自动推进、会话恢复、子 agent 协同和 OpenClaw 操作。

目标只有三个：

- 控制上下文膨胀
- 降低 agent 偏移主线的概率
- 一旦偏移，尽快熔断、回收、重建

## 1. 总原则

1. 以项目内状态为准，不以聊天记忆为准。
2. 先校验当前 workflow、status、handoff，再执行。
3. 只在授权路径内改动，只做当前步骤要求的事。
4. 遇到冲突、歧义、缺文档、缺状态时，先阻塞，不要脑补。
5. 不允许跳过 plan、review、gate、handoff 直接宣称完成。

## 2. 每次启动或恢复都必须先读

- `ai/state/START_HERE.md`
- `ai/state/project-handoff.md`
- `ai/state/orchestrator-state.json`
- `ai/state/agent-sessions.json`
- `docs/ANTI-DRIFT-RUNBOOK.md`

如果是恢复线程或 rollover 之后继续，还必须读：

- `ai/reports/orchestrator-rollover.md`
- `ai/reports/parent-session-recovery.md`
- 最近一次相关 handoff

## 3. 什么算跑偏

出现下面任意一种，都按跑偏处理：

- 输出和当前 `workflow_step_id` 无关
- 修改超出 `allowed_paths`
- 绕过当前 workflow 顺序，提前进入实现、测试或发布
- 没有更新 handoff 就回报完成
- completion 无法对应当前 `active_tasks`
- `agent_id`、`task_id`、`workflow_step_id` 与当前任务不匹配
- 长时间只做边角优化，没有推进 `next_action`
- 把旧上下文当作当前事实，忽略最新 state / handoff

## 4. 遇到不确定时怎么做

优先顺序固定如下：

1. 重新读取 `START_HERE`、`project-handoff`、`orchestrator-state`
2. 对照当前 task card 的 `goal`、`allowed_paths`、`expected_output`
3. 如果仍冲突，写 handoff 并明确 blockers
4. 不继续猜测，不擅自改 scope

## 5. completion 规则

所有 completion 必须满足：

- 能命中现有 `active_tasks`
- `agent_id` 与 active task 的 `role` 一致
- `workflow_step_id` 与 active task 一致
- 带 summary
- blockers 有则明确写出
- handoff 可落回项目内 `ai/handoff/`

违反这些规则的 completion，视为无效 completion。

## 6. 无效 completion 的处理

第一次无效 completion：

- 记录 drift 事件
- 保留失败 payload
- 不接受状态推进

连续无效 completion 达到熔断阈值后：

- 自动熔断该子会话
- 标记 `rebuild_required`
- 关闭旧 session
- 将当前任务回收到可重新派发状态
- 下一轮改为重新 spawn，而不是继续 send 到旧会话

## 7. 上下文过长的处理

当运行时估算到上下文接近预算上限时：

- 立即生成 `orchestrator-rollover`
- 写入新的 resume prompt
- 停止继续向当前会话追加上下文
- 交给下一线程或下一会话继续

子 agent 长会话也一样：

- 同一 session 的复用次数有限
- 超过复用预算后，不再继续 send
- 改为关闭旧会话并重新 spawn

## 8. 哪些情况必须暂停自动推进

- 需求中途重大变更，需要重规划
- 当前状态文件、handoff、workflow 发生漂移
- gate 或证据链明确阻塞
- 关键路径存在 customer decision
- 连续 drift 触发熔断，需要会话重建

## 9. OpenClaw 中的建议操作

先用显式 skill 入口，不要一上来就直接开发：

```text
使用 $sili-jian-orchestrator 对当前目录执行首次启用引导，不要直接开始开发。
```

进入自动推进前，先确认目录、workflow、handoff、peer-agent 都正确。

进入自动模式后，如果你需要人工打断，优先用：

```text
司礼监：暂停自动推进
司礼监：查看当前模式
司礼监：关闭 libu2 当前会话
```

## 10. 一句话判断标准

如果一个动作不能清楚回答下面 4 个问题，就不要执行：

1. 我现在属于哪个 workflow step
2. 我允许改哪些路径
3. 我完成后要把结果交给谁
4. 我现在依据的是哪份最新状态，而不是旧聊天记忆
