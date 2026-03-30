# 详细使用文档

这份文档面向已经准备正式使用 `sili-jian-orchestrator` 的用户，目标是把“什么时候该用、怎么接管、怎么进入自动运行、遇到问题怎么修”讲清楚。

如果你只想先快速上手，建议先读：

1. [安装说明](./INSTALL.md)
2. [简易版文档](./SIMPLE.md)
3. 本文档

---

## 1. 这是什么

`sili-jian-orchestrator` 不是普通的“写代码技能”，而是一个治理优先的总调度技能。它优先做这些事情：

1. 识别当前目录到底是什么
2. 判断你现在处于哪种项目场景
3. 给项目补齐治理骨架
4. 维护项目状态、handoff、报告和工作流
5. 协调 peer-agent 的派发、恢复、关停和轮换
6. 在进入执行、测试、发布前做阶段性守门

它的核心原则不是“立刻开写”，而是“先确认项目可治理，再推进实现”。

---

## 2. 适合什么场景

建议在下面这些场景使用：

1. 新建项目，但还没有完整的治理骨架
2. 中途接管一个已经做到一半的项目
3. 恢复一个暂停过、换过人、上下文断掉的项目
4. 把新增需求纳入现有治理体系，而不是直接插入实现
5. 希望项目在 GitHub 上具备状态一致性检查和阶段守门

不建议在下面这些场景使用：

1. 只想改一个很小的按钮文案
2. 只修一个孤立的小 bug
3. 明确不需要治理、不需要状态机、不需要交接的临时脚本

---

## 3. 你会看到的目录模式

技能会先识别当前目录模式。这个判断非常重要，因为不同模式下允许做的事情完全不同。

### `skill_bundle_mode`

表示你当前就在技能仓库自身目录。

特点：

1. 这里主要用于维护技能本身
2. 不应该把这里当成业务项目根目录
3. 不应该在这里初始化业务项目的 `ai/` 治理骨架

### `workspace_root_mode`

表示你当前在 OpenClaw workspace 根目录，而不是某个具体业务项目目录。

特点：

1. 这里适合记录新需求
2. 这里适合先做项目 intake
3. 这里不适合直接往业务项目里写治理文件，除非你已经明确指定目标项目目录

### `project_mode`

表示你当前在一个真实业务项目目录里。

特点：

1. 可以做接管和盘点
2. 可以补治理骨架
3. 可以执行状态检查和修复
4. 满足条件后可以进入自动调度和执行

### `unknown_mode`

表示当前目录既不像技能仓库，也不像 workspace 根，也不像真实业务项目。

建议动作：

1. 暂停推进
2. 明确目标目录
3. 不要贸然初始化治理结构

---

## 4. 技能的工作方式

这个技能的默认行为是一个固定顺序：

1. 先识别目录模式
2. 再识别项目场景
3. 再检查治理状态是否完整
4. 再决定是否允许进入规划、执行、测试或发布

也就是说，它不会因为你提了一个开发需求，就默认马上开写。

它会优先判断：

1. 这是新项目、接管项目、恢复项目，还是现有项目加新需求
2. 当前 `ai/state/` 是否可信
3. 当前 `tests/`、`workflows/`、`handoff/` 是否完整
4. 当前项目是否处于允许执行的阶段

---

## 5. 第一次使用时的推荐流程

### 路径 A：你在 workspace 根目录，还没有项目目录

这种情况先做 intake，不要直接当成业务项目处理。

第一步，记录需求：

```bash
python scripts/project_intake.py <workspace-root> --requirement "项目名称叫 xxx，需要实现 yyy"
```

这一步会：

1. 记录原始需求
2. 尝试从需求里提取项目名
3. 生成 intake 摘要和建议方案

第二步，创建项目并进入治理初始化：

```bash
python scripts/project_intake.py <workspace-root> --project-name xxx --activate
```

这一步会：

1. 创建新的项目目录
2. 运行治理骨架初始化
3. 把 intake 内容写入新项目状态文件
4. 按参数决定是否立即进入 autonomous 模式

### 路径 B：你已经在真实项目目录里

建议先做“首次启用引导”和“首轮接管检查”，不要直接让技能开始实现。

推荐提示词：

```text
使用 $sili-jian-orchestrator 对当前项目执行首次启用引导，不要直接开发。
先识别目录模式、场景、治理状态、peer-agent 是否就绪，再给出最安全的下一步。
```

接着再做接管盘点：

```text
使用 $sili-jian-orchestrator 对当前项目执行首轮接管检查，不得直接进入实现阶段。
要求输出当前项目识别结果、缺失治理项、测试体系完整度、workflow 完整度、状态机可信度，以及建议的 next_action。
```

---

## 6. 项目治理骨架包含什么

执行 `bootstrap governance` 后，目标项目通常会具备这些目录：

1. `ai/state/`
2. `ai/reports/`
3. `ai/handoff/`
4. `ai/runs/`
5. `ai/prompts/`
6. `ai/logs/`
7. `tests/`
8. `workflows/`
9. `docs/`

其中最关键的状态文件包括：

1. `ai/state/START_HERE.md`
2. `ai/state/project-meta.json`
3. `ai/state/project-handoff.md`
4. `ai/state/orchestrator-state.json`
5. `ai/state/task-tree.json`
6. `ai/state/agent-sessions.json`
7. `ai/state/review-controls.json`

最关键的报告文件包括：

1. `ai/reports/test-report.md`
2. `ai/reports/department-approval-matrix.md`
3. `ai/reports/acceptance-report.md`
4. `ai/reports/gate-report.md`
5. `ai/reports/change-summary.md`

最关键的 workflow 包括：

1. `new-project.yaml`
2. `takeover-project.yaml`
3. `resume-orchestrator.yaml`
4. `feature-delivery.yaml`
5. `review-and-release.yaml`

---

## 7. 四类核心场景

### 新建项目

目标是先建立治理，再进入规划和执行。

典型顺序：

1. intake
2. 创建项目
3. bootstrap governance
4. 规划
5. 方案审批
6. 执行

### 中途接管项目

目标是先盘点、再补治理、再恢复推进。

典型顺序：

1. 识别项目状态
2. 生成当前实现总结
3. 补齐治理骨架
4. 修复 state / handoff 漂移
5. 重建计划或恢复执行

### 恢复会话

目标是从已有状态和报告恢复上下文，而不是重新猜测。

典型顺序：

1. 读取 `START_HERE.md`
2. 读取 `project-handoff.md`
3. 读取 `orchestrator-state.json`
4. 读取 `agent-sessions.json`
5. 读取最近的 rollover / recovery 报告
6. 决定继续派发、等待完成、还是先修状态

### 现有项目新增需求

目标是把变更纳入治理，而不是直接插入实现。

典型顺序：

1. 记录 change request
2. 判断是 incremental 还是 significant
3. 决定是否需要 replan
4. 如需 replan，则冻结执行并重新进入规划

---

## 8. peer-agent 角色与职责

当前默认角色映射如下：

1. `neige`：内阁，负责方案、任务树、规划修复
2. `duchayuan`：都察院，负责审批、终审、裁决
3. `libu2`：吏部，负责后端和业务逻辑
4. `hubu`：户部，负责数据库、迁移、schema
5. `gongbu`：工部，负责前端和交互
6. `bingbu`：兵部，负责测试、回归、阶段校验
7. `libu`：礼部，负责文档、交接、change summary
8. `xingbu`：刑部，负责构建、发布、回滚、守门

调度时通常遵循这些规则：

1. 初次派发优先 `spawn`
2. 可复用会话优先 `send`
3. 派发前必须生成 task card
4. 派发后必须有对应 handoff
5. 会话状态要持久化到 `agent-sessions.json`

---

## 9. 状态机与放行开关

项目推进依赖两类状态。

### 阶段状态

例如：

1. `current_workflow`
2. `current_phase`
3. `current_status`

它们描述项目目前处于哪条 workflow、哪个阶段、什么状态。

### 放行开关

例如：

1. `execution_allowed`
2. `testing_allowed`
3. `release_allowed`

这三个不是“阶段名”，而是守门开关。

例如：

1. `execution_allowed = false` 说明当前还不应进入正式实现
2. `testing_allowed = false` 说明当前还不应进入正式测试
3. `release_allowed = false` 说明当前还不应进入发布

如果项目还在规划阶段，这三个字段为 `false` 是正常的。

---

## 10. autonomous 模式怎么用

这个仓库支持 normal、armed、autonomous、paused 四种控制模式。

### `normal`

默认交互模式，不自动推进。

### `armed`

准备自动推进，但还没有真正进入 runtime loop。

### `autonomous`

真正进入自动调度模式，允许 runtime loop 驱动：

1. 派发
2. outbox 投递
3. inbox 消费
4. 证据采集
5. 升级判断
6. 自动提交

### `paused`

自动推进暂停，等待人工决策或恢复。

---

## 11. 常用控制方式

### 方式一：自然语言控制

可以通过 `scripts/natural_language_control.py` 走统一入口。

例如：

```bash
python scripts/natural_language_control.py <project-root> "司礼监：进入自动模式"
```

```bash
python scripts/natural_language_control.py <project-root> "司礼监：暂停自动推进"
```

```bash
python scripts/natural_language_control.py <project-root> "司礼监：关闭 libu2 当前会话"
```

### 方式二：直接控制自动模式

```bash
python scripts/automation_control.py <project-root> --mode autonomous
```

```bash
python scripts/automation_control.py <project-root> --mode paused --reason "等待客户确认范围"
```

### 方式三：直接跑 runtime loop

```bash
python scripts/runtime_loop.py <project-root> --activate --max-cycles 3 --max-dispatch 2
```

含义：

1. `--activate`：如果当前不是 autonomous，先切进去
2. `--max-cycles`：本次最多执行几轮 runtime cycle
3. `--max-dispatch`：每轮最多派发多少个 ready step

---

## 12. 常用脚本与用途

### 项目接入与初始化

1. `scripts/project_intake.py`
2. `scripts/bootstrap_governance.py`
3. `scripts/inspect_project.py`
4. `scripts/first_run_check.py`

### 状态检查与修复

1. `scripts/validate_state.py`
2. `scripts/repair_state.py`
3. `scripts/recovery_summary.py`
4. `scripts/context_rollover.py`

### 自动运行主链路

1. `scripts/automation_control.py`
2. `scripts/run_orchestrator.py`
3. `scripts/runtime_loop.py`
4. `scripts/openclaw_adapter.py`
5. `scripts/completion_consumer.py`
6. `scripts/inbox_watcher.py`

### 环境与宿主接口

1. `scripts/host_interface_probe.py`
2. `scripts/runtime_environment.py`
3. `scripts/environment_bootstrap.py`

### 审批、证据与守门

1. `scripts/evidence_collector.py`
2. `scripts/provider_evidence.py`
3. `scripts/escalation_manager.py`
4. `scripts/validate_gates.py`
5. `scripts/run_project_guard.py`

---

## 13. 推荐操作顺序

### 新项目

1. intake
2. 创建项目
3. bootstrap governance
4. 规划
5. 审批
6. autonomous 执行
7. 测试
8. 审核
9. 发布准备

### 接管项目

1. 首次启用引导
2. 首轮接管检查
3. 如有缺口，先补治理
4. 运行状态检查
5. 如有漂移，先修状态
6. 明确 next_action
7. 再决定进入规划还是执行

### 恢复项目

1. 读取恢复入口
2. 看最近 runtime-loop-summary
3. 看最近 orchestrator-rollover
4. 看 agent-sessions
5. 再决定继续派发还是先修复

---

## 14. 状态检查与修复

当你怀疑状态文件已经漂移时，优先使用下面两个脚本。

### 状态检查

```bash
python scripts/validate_state.py <project-root>
```

主要检查：

1. `orchestrator-state.json`、`START_HERE.md`、`project-handoff.md` 是否一致
2. `active_tasks` 指向的 handoff 是否存在
3. workflow step 是否属于当前 workflow
4. 是否存在 legacy 状态文件

### 状态修复

```bash
python scripts/repair_state.py <project-root>
```

主要修复：

1. 同步 `START_HERE.md`
2. 同步 `project-handoff.md`
3. 为缺失的 active handoff 创建 stub
4. 清理常见 legacy 漂移
5. 必要时补最小恢复文档

如果你要更系统地了解这些脚本，继续读：

- [状态检查与修复](./STATE-TOOLS.md)

---

## 15. 变更请求与 replan

当项目已经在执行中，但需求又发生变化时，不建议直接塞到实现里。

应该通过 change request 流程处理。

典型入口：

1. `scripts/change_request_control.py`
2. `scripts/replan_change_request.py`

这套流程会做这些事：

1. 给变更分配 `CR-xxx`
2. 判断是 `add`、`modify` 还是 `remove`
3. 判断是 `incremental` 还是 `significant`
4. 决定放入 `current_batch`、`future_batch` 还是要求 replan
5. 必要时暂停自动推进并回到规划阶段

---

## 16. GitHub 守门机制

执行治理初始化后，目标项目会被注入项目级守门脚本与 workflow。

通常会得到：

1. `ai/tools/common.py`
2. `ai/tools/validate_state.py`
3. `ai/tools/validate_gates.py`
4. `ai/tools/run_project_guard.py`
5. `.github/workflows/project-guard.yml`
6. `.github/workflows/project-repair-brief.yml`

这意味着目标项目后续在 GitHub 上：

1. `push`
2. `pull request`

都会自动检查：

1. 状态是否一致
2. 当前阶段所需报告是否齐全
3. blocker 是否清空
4. 最终发布门禁是否通过

---

## 17. 常见排障建议

### 情况 1：`runtime_loop` 没有进入自动推进

先看：

1. `automation_mode` 是否是 `autonomous`
2. `ai/reports/runtime-loop-summary.json`
3. `ai/reports/runtime-environment.json`

### 情况 2：有 active task，但没有新的 step 被派发

先确认是不是正常等待态，不一定是故障。

检查：

1. `ai/state/orchestrator-state.json` 的 `active_tasks`
2. `ai/runtime/outbox/` 是否还有待投递 envelope
3. `ai/reports/orchestrator-dispatch-plan.json`

### 情况 3：provider 证据采集中断

检查：

1. provider JSON 路径是否存在
2. provider JSON 是否可读、是否是合法 JSON
3. `ai/reports/provider-evidence-summary.json`

### 情况 4：状态文件损坏

现在关键脚本会在读取到非法 JSON 时直接失败，并把原文件备份为：

```text
*.corrupt-<timestamp>.bak
```

你应该：

1. 先保留损坏文件
2. 查看 `.bak`
3. 手工修复或结合 `repair_state.py` 恢复
4. 不要用空对象覆盖掉状态

---

## 18. 本地回归与 CI

### 本地一键检查

```bash
python scripts/run_repo_ci.py
```

它会执行：

1. 关键脚本编译检查
2. 回归测试
3. scaffolded `ai/tools` 同步检查

### GitHub Actions

仓库自带：

1. `.github/workflows/skill-ci.yml`

在推送到 `main` 或发起 Pull Request 时会自动运行。

---

## 19. 推荐阅读顺序

如果你准备长期使用这个技能，建议按下面顺序阅读：

1. [安装说明](./INSTALL.md)
2. [简易版文档](./SIMPLE.md)
3. [使用说明](./USAGE.md)
4. [详细使用文档](./DETAILED.md)
5. [提示词文档](./PROMPTS.md)
6. [按推进顺序手册](./FLOWS.md)
7. [状态检查与修复](./STATE-TOOLS.md)
8. [OpenClaw 专用说明](./OPENCLAW-GUIDE.md)
9. [无人值守自治说明](./UNATTENDED-AUTONOMY.md)

---

## 20. 一句话总结

把它理解成“项目治理总调度器”，而不是“普通编码助手”。

正确的使用方式是：

1. 先识别目录和场景
2. 再确认治理是否可信
3. 再决定是否允许进入自动推进
4. 遇到漂移先修状态，遇到变更先 replan，遇到发布先守门

这样它才能真正发挥价值，而不是把一个本来就混乱的项目更快地推向混乱。
