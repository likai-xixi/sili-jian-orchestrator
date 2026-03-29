# 状态检查与修复

这份文档说明如何使用技能内置的状态检查与自动修复能力。

它主要解决这些问题：

- `orchestrator-state.json`、`START_HERE.md`、`project-handoff.md` 不一致
- `active_tasks` 里登记了任务，但 handoff 文件不存在
- `orchestrator_state.json` 和 `orchestrator-state.json` 并存
- takeover 场景下 `project-takeover.md` 仍是模板
- `next_owner`、workflow、phase、status 发生漂移

## 一、什么时候该跑状态检查

建议在这些时机使用：

1. 治理初始化刚完成后
2. first-run 后发现状态不一致
3. 多个部门任务并行后，怀疑 state / handoff 漂移
4. 恢复会话前
5. 正式进入执行或测试前

## 二、状态检查脚本

脚本：

- `scripts/validate_state.py`

它会检查：

1. `orchestrator-state.json` 是否存在且可读
2. `START_HERE.md` / `project-handoff.md` 是否存在
3. workflow / phase / status / next owner 是否一致
4. `active_tasks` 里的每个任务是否存在 handoff
5. handoff 里的 `task_id`、`role`、`status` 是否和 state 匹配
6. takeover 场景下 `project-takeover.md` 是否仍是模板
7. 是否存在 legacy `orchestrator_state.json`
8. 放行开关是否被过早打开

### JSON 输出

```bash
python scripts/validate_state.py <项目根目录>
```

### Markdown 输出

```bash
python scripts/validate_state.py <项目根目录> --format markdown
```

### 输出到文件

```bash
python scripts/validate_state.py <项目根目录> --format markdown --output ai/reports/state-validation.md
```

## 三、状态修复脚本

脚本：

- `scripts/repair_state.py`

它会修复常见问题：

1. 同步 `START_HERE.md`
2. 同步 `project-handoff.md`
3. 为缺失的 active handoff 自动创建 stub
4. 清理或归并 `orchestrator_state.json`
5. 在 takeover 场景下补齐最小可用的 `project-takeover.md`
6. 修复后自动再次校验

### JSON 输出

```bash
python scripts/repair_state.py <项目根目录>
```

### Markdown 输出

```bash
python scripts/repair_state.py <项目根目录> --format markdown
```

### 输出到文件

```bash
python scripts/repair_state.py <项目根目录> --format markdown --output ai/reports/state-repair.md
```

## 四、推荐使用顺序

推荐按这个顺序走：

1. 先执行 `validate_state.py`
2. 查看 error 与 warning
3. 如果问题属于常见漂移，再执行 `repair_state.py`
4. 修复后再次执行 `validate_state.py`
5. 当 `state_consistent = yes` 时，再继续后续推进

## 五、在 OpenClaw 中直接使用

### 1. 状态检查提示词

```text
使用 $sili-jian-orchestrator 检查当前项目的状态一致性，不要进入实现阶段。

要求：
1. 检查 orchestrator-state.json、START_HERE.md、project-handoff.md 是否一致
2. 检查 active_tasks 是否都存在对应 handoff
3. 检查 workflow、phase、status、next_owner 是否一致
4. 检查是否存在 legacy 状态文件 orchestrator_state.json
5. 输出状态检查结果，并明确：
   - state_consistent
   - 错误列表
   - 警告列表
   - 当前 next_action
```

### 2. 状态修复提示词

```text
使用 $sili-jian-orchestrator 修复当前项目的常见状态漂移，但不要进入实现阶段。

要求：
1. 以 orchestrator-state.json 为准
2. 同步 START_HERE.md 与 project-handoff.md
3. 为缺失的 active handoff 自动创建 stub
4. 清理 legacy 状态文件 orchestrator_state.json
5. 若为 takeover 场景，补齐最小可用的 project-takeover.md
6. 修复后再次执行状态检查
7. 输出：
   - 修复清单
   - 修复后的 state_consistent
   - 剩余问题
   - 当前 next_action
```

### 3. 针对指定项目目录的提示词

```text
使用 $sili-jian-orchestrator 检查并修复指定项目目录的状态一致性，不要进入实现阶段。

目标项目根目录：
<项目绝对路径>

要求：
1. 只对 <项目绝对路径> 执行状态检查与修复
2. 不要把当前 workspace 根目录当成业务项目目录
3. 先执行状态检查
4. 如果发现常见漂移，再执行自动修复
5. 输出：
   - 检查结果
   - 修复清单
   - 修复后的状态
   - 当前 next_action
```

## 六、注意事项

状态修复的目标是收口常见漂移，不是替代人工审查。以下情况修复后仍建议人工复核：

1. workflow 与场景判断明显冲突
2. 多个 active task 同时指向不同部门，但 next owner 单一
3. 方案与执行状态同时被打开
4. 发布门禁被提前放开

一句话理解：

**先检查，再修复；修复后再检查；确认一致后再继续推进。**
