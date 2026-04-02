# DOC-GATE P0 落地验收报告

- 项目：sili-jian-orchestrator
- 阶段：P0（可运行基线）
- 日期：2026-04-02
- 结论：✅ 通过（都察院逐步审查通过）

## 一、已落地范围

### Step 1 配置与校验基座
- `references/doc-gate-config.schema.json`
- `assets/project-skeleton/ai/runtime/doc-gate-config.json`
- `scripts/validate_doc_gate_config.py`

### Step 2 多格式文档转 IR
- `scripts/parse_docs_to_ir.py`
- `scripts/validate_doc_ir.py`
- 支持：md/mdx/rst/adoc/wiki
- 已修复：`covers_feature_ids` 多值切分问题

### Step 3 Registry 与覆盖差异报告
- `references/feature-registry.schema.json`
- `assets/project-skeleton/ai/state/feature-registry.json`
- `scripts/check_doc_coverage.py`
- 输出指标：
  - `feature_ref_coverage_rate`
  - `doc_target_coverage_rate`
  - `missing_in_docs`
  - `high_risk_missing_in_docs`
  - `unregistered_in_docs`
  - `decision_hint`

### Step 4 门禁集成
- `scripts/validate_gates.py` 集成 doc coverage
- `assets/project-skeleton/ai/tools/validate_gates.py` 已同步
- 高风险缺失与未注册引用会注入 blocker 并影响 gate 判定

### Step 5 回归测试
- 新增测试：
  - `test_validate_gates_blocks_on_doc_coverage_high_risk_missing`
- 回归通过：新增用例 + 既有 validate_gates 用例

## 二、审查结论汇总（都察院）

- Step1：✅通过（附建议）
- Step2：✅通过，修复后复核✅
- Step3：⚠️建议修改，修复后复核✅
- Step4：✅通过
- Step5：✅通过（阶段验收完成）

## 三、当前能力边界（P0）

已具备：
1. 配置可校验
2. 文档可统一解析为 IR
3. Registry 可建模并输出覆盖差异
4. Gate 已接入高风险阻断
5. 测试具备最小回归保障

尚未完成（留给 P1/P2）：
1. 更强的 evidence 语义校验（结构化对象而非字符串）
2. 历史趋势看板（coverage/false-positive over time）
3. 自动仲裁工作流（48h 时窗内自动追踪）
4. 更完整的 unregistered 场景测试矩阵

## 四、P1 建议（下一阶段）

1. 增加 `unregistered_in_docs` 高风险回归测试
2. 引入 `coverage history` 时间序列输出（按日聚合）
3. 将 `doc_target` 由“文件存在”升级为“内容命中 feature_id”
4. 把 Gate 报告写入 `ai/reports/gate-report.md` 的标准段落模板

---

本报告对应实现提交（技能仓库 main）：
- `85dde94` P0 config + IR pipeline
- `84add11` registry + coverage checker
- `33b5871` gate integration
- `6bfdf56` regression test

（另：`a1b9c78` 已将 v3.1.1 策略纳入技能引用）
