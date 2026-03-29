# 详细版文档

这份文档面向正式接手项目、长期推进、需要恢复与门禁闭环的使用者。

## 一、技能定位

`sili-jian-orchestrator` 不是普通编码技能，而是“治理优先”的总调度技能。它的核心职责是：

1. 接收需求
2. 识别项目
3. 判断场景
4. 建立和维护治理体系
5. 组织方案
6. 组织执行
7. 组织测试
8. 组织评审
9. 组织恢复
10. 维护状态、交接、门禁和归档

## 二、四类核心场景

### 1. 新建项目

目标是先建立治理骨架，再进入方案阶段。

### 2. 中途接管项目

目标是先盘点现状、补齐治理、恢复状态，再继续推进。

### 3. 恢复会话

目标是先读取恢复入口、状态、报告、handoff，再生成 recovery summary。

### 4. 新功能接入既有治理体系

目标是先进入 requirements pool，再判断是否需要重新进入方案审批。

## 三、目录模式与项目目录

技能会区分：

1. `skill_bundle_mode`
2. `workspace_root_mode`
3. `project_mode`
4. `unknown_mode`

只有在 `project_mode` 下，才允许往业务项目写入 `ai/`、`tests/`、`workflows/` 等治理骨架。

如果当前 agent 的 workspace 不是业务项目根目录，应使用“指定项目目录接管”的提示词，把明确的项目绝对路径告诉技能。

## 四、治理骨架内容

治理初始化后，项目目录至少应出现：

- `ai/state/`
- `ai/reports/`
- `ai/handoff/`
- `ai/runs/`
- `ai/prompts/`
- `ai/logs/`
- `tests/`
- `workflows/`
- `docs/`

其中核心文件至少包括：

- `ai/state/START_HERE.md`
- `ai/state/project-meta.json`
- `ai/state/project-handoff.md`
- `ai/state/orchestrator-state.json`
- `ai/state/task-tree.json`
- `ai/state/approval-policy.md`
- `ai/state/gate-rules.md`
- `ai/state/testing-guidelines.md`
- `ai/reports/test-report.md`
- `ai/reports/acceptance-report.md`
- `ai/reports/department-approval-matrix.md`

## 五、状态机与放行开关

状态文件里至少有两类信息：

### 1. 阶段 / 状态

例如：

- `current_phase`
- `current_status`
- `current_workflow`

### 2. 放行开关

例如：

- `execution_allowed`
- `testing_allowed`
- `release_allowed`

后面这三个不是阶段名，而是门禁开关：

- `execution_allowed = false`：当前不能进入实现
- `testing_allowed = false`：当前不能进入正式测试
- `release_allowed = false`：当前不能进入发布

这三项在 `planning / draft` 阶段为 `false` 是正常的。

## 六、真实 peer-agent 调度

当 OpenClaw 提供同级部门 agent 时，技能默认按真实 `agentId` 派发：

- `neige`：内阁，负责方案与架构
- `duchayuan`：都察院，负责终审与裁决
- `libu2`：吏部，负责后端与业务逻辑
- `hubu`：户部，负责数据库与迁移
- `gongbu`：工部，负责前端与交互
- `bingbu`：兵部，负责测试
- `libu`：礼部，负责文档、交接、变更摘要
- `xingbu`：刑部，负责构建、发布、安全与回滚

### 派发规则

1. 一次性任务优先 `sessions_spawn`
2. 多轮持续会话优先 `sessions_send`
3. `spawn` 默认 `cleanup: "delete"`
4. 派发前先生成任务卡
5. 派发后必须有 handoff
6. 长期会话的 `sessionKey` 写入 `ai/state/agent-sessions.json`

## 七、推荐推进顺序

### 新建项目

1. 首次启用引导
2. 首轮接管检查
3. 批准治理骨架初始化
4. 进入方案阶段
5. 方案审批
6. 再进入执行

### 中途接管项目

1. 首次启用引导
2. 首轮盘点
3. 批准治理补齐
4. 执行 recovery summary
5. 决定恢复后优先动作
6. 再进入方案或执行

完整提示词顺序见：

- [按推进顺序手册](./FLOWS.md)

## 八、状态检查与修复

技能已经内置：

- `scripts/validate_state.py`
- `scripts/repair_state.py`

适用情况：

1. `orchestrator-state.json`、`START_HERE.md`、`project-handoff.md` 互相打架
2. `active_tasks` 指向的 handoff 缺失
3. legacy `orchestrator_state.json` 与新文件并存
4. takeover 项目缺少 `project-takeover.md`

对应文档见：

- [状态检查与修复](./STATE-TOOLS.md)

## 九、门禁与终审

技能不会因为治理骨架存在就默认放行。

进入执行、测试、发布前，会分别依赖：

- 方案冻结
- `architecture.md`
- `task-tree.json`
- 测试报告
- 审批矩阵
- 终审报告
- 门禁报告
- blocker 清零
- 主链路回归通过

## 十、建议阅读顺序

如果你第一次接触这个技能，推荐按这个顺序看：

1. [安装说明](./INSTALL.md)
2. [简易版文档](./SIMPLE.md)
3. [使用说明](./USAGE.md)
4. [提示词文档](./PROMPTS.md)
5. [按推进顺序手册](./FLOWS.md)
6. [状态检查与修复](./STATE-TOOLS.md)
