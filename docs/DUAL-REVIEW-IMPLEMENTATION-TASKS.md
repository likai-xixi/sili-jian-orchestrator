# 双审改造任务卡（最小闭环）

- 日期：2026-04-02
- 目标：在不写死模型的前提下，为司礼监技能增加可审计的双审机制（pass1/pass2）

## Task 1 — 状态机与迁移兼容
- 改动点：
  - `orchestrator-state.json` 增字段：
    - `dual_review_enabled` (bool)
    - `review_pass_1` (null|PASS|FAIL)
    - `review_pass_2` (null|PASS|FAIL)
    - `review_conflict` (bool)
  - 增迁移逻辑：旧 state 无字段时自动补默认值。
- 验收：旧项目不报错，字段自动补齐。

## Task 2 — 审批矩阵模板双审区块
- 改动点：
  - `department-approval-matrix` 模板新增：
    - `Reviewer duchayuan-pass1`
    - `Reviewer duchayuan-pass2`
  - 每段必须包含：结论、证据、发现项。
- 验收：缺任一区块触发 gate 阻断。

## Task 3 — 双审门禁判定
- 改动点：`validate_gates.py`
  - `dual_review_enabled=true` 时：
    - 必须 pass1=PASS 且 pass2=PASS 且 `review_conflict=false`
  - 否则 `final_gate_passed=false`。
- 验收：冲突状态一律阻断。

## Task 4 — 冲突仲裁闭环
- 改动点：
  - 当 pass1/pass2 冲突，自动置 `review_conflict=true`
  - 仅在“仲裁完成并留证据”后允许清除冲突。
- 验收：无仲裁证据不得解锁。

## Task 5 — 审查对象一致性
- 改动点：
  - pass1/pass2 必须绑定同一 `review_run_id` + `commit_sha`
  - 不一致直接 blocker（防止审不同版本）。
- 验收：跨版本审查被阻断。

## Task 6 — 测试矩阵（最小6条）
1. pass1=PASS, pass2=PASS -> 放行
2. pass1=PASS, pass2=FAIL -> 阻断+conflict
3. pass1=FAIL, pass2=PASS -> 阻断+conflict
4. 缺 pass2 区块 -> 阻断
5. 旧 state 迁移后行为正确
6. release_allowed=false 不误触双审强制

## 交付顺序
1. Task1/2（结构）
2. Task3/4/5（逻辑）
3. Task6（回归）
4. 都察院终审

## 说明
- 模型分配保持在运行时配置层，不写入技能逻辑。
- 技能仅负责流程与门禁规则。