# 提示词文档

这份文档集中整理可直接复制的中文提示词，按常见场景归类。

## 一、首次启用引导

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
6. 如果当前目录已经是项目目录，再继续输出首轮接管结果
7. 在完成上述检查前，不要进入实现阶段
```

## 二、技能目录测试

```text
使用 $sili-jian-orchestrator 对当前目录执行首次启用引导。

当前目录大概率是技能封装目录，不是业务项目目录。

要求：
1. 不要直接开发
2. 先判断当前目录模式
3. 检查 OpenClaw 中司礼监、内阁、都察院、六部 agent 是否已就绪
4. 如果这里是技能目录，只输出首次引导结果，不要创建 ai/、tests/、workflows/ 等项目治理文件
5. 输出：
   - 当前目录模式
   - peer-agent 就绪情况
   - 当前环境说明
   - 最安全的下一步
   - 建议我下一条输入什么提示词
```

## 三、新建项目接管

```text
使用 $sili-jian-orchestrator 将当前目录作为新建项目处理，不要直接开发。

要求：
1. 将当前场景识别为 new-project
2. 检查 ai/、tests/、workflows/、docs/ 是否存在
3. 检查是否已有状态文件、交接入口、恢复机制、审批规则、测试规则、workflow 模板
4. 输出首轮接管结果，至少包含：
   - 当前项目识别结果
   - 当前场景
   - 缺失的治理文件
   - 缺失的测试体系
   - 缺失的 workflow 模板
   - 需要先创建的目录和文件
   - 当前是否具备方案阶段条件
   - 当前是否允许进入执行阶段
   - 第一轮 next_action
5. 在完成检查前，不得进入实现阶段
```

## 四、中途接管项目

```text
使用 $sili-jian-orchestrator 接管当前项目，场景按 mid-stream-takeover 处理，不得直接开发。

要求：
1. 执行首轮接管检查
2. 检查项目识别、ai/、tests/、workflows/、交接入口、状态文件、审批规则、测试规则、工作流模板、步骤快照、任务卡模板
3. 输出首轮接管结果，至少包含：
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
4. 在完成检查前，不得进入实现阶段
```

## 五、指定项目目录接管

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

## 六、批准治理骨架初始化

```text
批准执行 bootstrap governance，但仅限治理骨架初始化，不得进入功能开发。

唯一允许写入的目录：
<项目绝对路径>

要求：
1. 只在 <项目绝对路径> 下补齐治理骨架
2. 不要修改业务代码逻辑
3. 如发现已有 ai/ 残留文件，先保留并兼容，不要粗暴覆盖未知内容
4. 初始化并补齐：
   - ai/state/
   - ai/reports/
   - ai/handoff/
   - ai/runs/
   - ai/prompts/
   - ai/logs/
   - tests/
   - workflows/
   - docs/
5. 完成后输出：
   - 本次创建的目录和文件清单
   - 当前状态机阶段
   - 当前 next_action
   - 当前是否具备方案阶段条件
   - 当前是否允许进入执行阶段
6. 完成治理初始化后停止，不得直接开始实现
```

## 七、进入方案阶段

```text
使用 $sili-jian-orchestrator 进入方案阶段。

要求：
1. 基于当前初始需求补全 architecture.md
2. 补全 task-tree.json
3. 明确主链路、边界、风险、验收标准
4. 更新 orchestrator-state.json 和 project-handoff.md
5. 输出：
   - 当前方案是否形成冻结版本
   - 当前是否具备进入 department-approval / plan-approved 的条件
   - 下一步应派给哪个部门
6. 在方案未通过审批前，不得进入实现阶段
```

## 八、状态检查

```text
使用 $sili-jian-orchestrator 检查当前项目的状态一致性，不要进入实现阶段。

要求：
1. 检查 orchestrator-state.json、START_HERE.md、project-handoff.md 是否一致
2. 检查 active_tasks 是否都存在对应 handoff
3. 检查 workflow、phase、status、next_owner 是否一致
4. 检查是否存在 legacy 状态文件 orchestrator_state.json
5. 输出：
   - state_consistent
   - 错误列表
   - 警告列表
   - 当前 next_action
```

## 九、状态修复

```text
使用 $sili-jian-orchestrator 修复当前项目的常见状态漂移，但不要进入实现阶段。

要求：
1. 同步 START_HERE.md 与 project-handoff.md
2. 为缺失的 active handoff 自动创建 stub
3. 清理 legacy 状态文件 orchestrator_state.json
4. 若为 takeover 场景，补齐最小可用的 project-takeover.md
5. 修复后再次执行状态检查
6. 输出：
   - 修复清单
   - 修复后的 state_consistent
   - 剩余问题
   - 当前 next_action
```

## 十、目录识别纠偏

```text
先不要执行 bootstrap governance。
请先确认当前目录是否为真实业务项目根目录，而不是 OpenClaw workspace 根目录。
如果不是，请停止初始化，并提示我切换到真正的项目目录后再重新执行 first-run 引导。
```
