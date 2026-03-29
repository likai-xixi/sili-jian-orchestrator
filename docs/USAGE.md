# 使用说明

这份文档适合已经安装好技能、准备在 OpenClaw 中正式使用的人。

## 一、使用原则

`sili-jian-orchestrator` 的默认行为不是直接开发，而是先做治理动作：

1. 识别当前目录模式
2. 检查 peer-agent 是否就绪
3. 判断当前属于哪种场景
4. 输出首次引导或首轮接管结果
5. 再决定是否允许进入治理初始化、方案、执行、测试或发布阶段

## 二、目录模式

技能会先判断当前目录属于哪一类：

1. `skill_bundle_mode`
   - 当前目录是技能自身目录
   - 不应在这里创建业务项目治理文件
2. `workspace_root_mode`
   - 当前目录是 OpenClaw workspace 根目录
   - 不应把它误当成单一业务项目目录
3. `project_mode`
   - 当前目录是真实项目目录
   - 可以执行接管、治理初始化、方案推进等动作
4. `unknown_mode`
   - 无法判断
   - 应暂停并要求明确目标项目目录

## 三、首次启用推荐顺序

### 1. 跑首次启用引导

```text
使用 $sili-jian-orchestrator 对当前目录执行首次启用引导。

要求：
1. 先不要直接开发
2. 先判断当前目录是技能目录、项目目录、workspace 根目录还是未知目录
3. 检查 OpenClaw 中司礼监、内阁、都察院、六部 agent 是否已就绪
4. 如果当前目录是项目目录，再继续检查治理状态、tests、workflows、状态文件、恢复入口
5. 输出首次引导结果，至少包含：
   - 当前目录模式
   - peer-agent 是否就绪
   - 当前环境意味着什么
   - 最安全的下一步
   - 建议我下一条输入什么提示词
6. 在完成上述检查前，不要进入实现阶段
```

### 2. 跑首轮接管检查

当目录确认是项目目录后，再执行首轮接管检查。

```text
使用 $sili-jian-orchestrator 对当前项目执行首轮接管检查，不得直接开发。

要求：
1. 检查项目识别、ai/、tests/、workflows/、交接入口、状态文件、审批规则、测试规则、工作流模板、步骤快照、任务卡模板
2. 输出首轮接管结果，至少包含：
   - 当前项目识别结果
   - 当前属于哪种场景
   - ai/ 是否齐全
   - tests/ 是否齐全
   - workflows/ 是否齐全
   - 是否存在显式状态机
   - 是否存在最近步骤快照
   - 缺失的治理文件
   - 缺失的测试体系
   - 缺失的 workflow 模板
   - 缺失的恢复机制
   - 需要先创建的文件和目录
   - 是否具备方案阶段条件
   - 是否具备执行阶段条件
   - 是否具备测试阶段条件
   - 第一轮 next_action
   - 当前是否允许立即进入执行阶段
3. 在完成检查前，不得进入实现阶段
```

## 四、指定项目目录接管

如果当前 agent 的 workspace 不是业务项目目录，推荐显式指定目标项目根目录。

```text
使用 $sili-jian-orchestrator 接管指定项目，不要把当前 workspace 根目录当成业务项目目录。

目标项目根目录：
<项目绝对路径>

要求：
1. 不要把当前 workspace 根目录当成业务项目根目录
2. 将 <项目绝对路径> 视为唯一目标项目目录
3. 先对 <项目绝对路径> 执行首次启用引导
4. 再对 <项目绝对路径> 执行首轮接管检查
5. 如需初始化治理骨架，只允许写入 <项目绝对路径>
6. 在完成检查前，不得进入实现阶段
```

## 五、治理初始化

当首轮接管结果明确指出“治理骨架缺失”时，再批准 `bootstrap governance`。

```text
批准执行 bootstrap governance，但仅限治理骨架初始化，不得进入功能开发。

唯一允许写入的目录：
<项目绝对路径>

要求：
1. 只在 <项目绝对路径> 下补齐治理骨架
2. 不要修改业务代码逻辑
3. 初始化并补齐：
   - ai/state/
   - ai/reports/
   - ai/handoff/
   - ai/runs/
   - ai/prompts/
   - ai/logs/
   - tests/
   - workflows/
   - docs/
4. 完成后输出：
   - 本次创建的目录和文件清单
   - 当前状态机阶段
   - 当前 next_action
   - 当前是否具备方案阶段条件
   - 当前是否允许进入执行阶段
5. 完成治理初始化后停止，不得直接开始实现
```

## 六、状态检查与修复

当你怀疑状态文件、handoff、workflow 发生漂移时，使用下面两类提示词。

### 状态检查

```text
使用 $sili-jian-orchestrator 检查当前项目的状态一致性，不要进入实现阶段。

要求：
1. 检查 orchestrator-state.json、START_HERE.md、project-handoff.md 是否一致
2. 检查 active_tasks 是否都存在对应 handoff
3. 检查 next_owner、workflow、phase、status 是否自洽
4. 检查是否存在 legacy 状态文件 orchestrator_state.json
5. 输出状态检查结果，并明确：
   - state_consistent
   - 错误与警告列表
   - 当前 next_action
```

### 状态修复

```text
使用 $sili-jian-orchestrator 修复当前项目的常见状态漂移，但不要进入实现阶段。

要求：
1. 同步 START_HERE.md 与 project-handoff.md
2. 为缺失的 active handoff 创建 stub
3. 清理 legacy 状态文件 orchestrator_state.json
4. 若为 takeover 场景，补齐最小可用的 project-takeover.md
5. 修复后再次执行状态检查
6. 输出：
   - 修复清单
   - 修复后的 state_consistent
   - 剩余问题
   - 当前 next_action
```

更详细的状态工具说明见：

- [状态检查与修复](./STATE-TOOLS.md)

## 七、文档导航

- [安装说明](./INSTALL.md)
- [简易版文档](./SIMPLE.md)
- [详细版文档](./DETAILED.md)
- [提示词文档](./PROMPTS.md)
- [按推进顺序手册](./FLOWS.md)

## 八、本地与远端 CI

### 本地一键校验

```bash
python scripts/run_repo_ci.py
```

它会自动执行：

1. 关键脚本语法编译检查
2. `tests/` 下的回归测试

### GitHub Actions

仓库已经提供：

- `.github/workflows/skill-ci.yml`

当你推送到 `main` 或发起 Pull Request 时，会自动跑同一套校验。
