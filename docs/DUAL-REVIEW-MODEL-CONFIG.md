# 双审模型配置说明（pass1/pass2）

## 目标
在双审模式下，让 `duchayuan-pass1` 与 `duchayuan-pass2` 使用不同模型运行审查。

## 一、确保 reviewer agents 存在
运行：

```bash
python3 scripts/ensure_openclaw_agents.py --create-missing
```

该脚本会确保以下 agent 存在：
- `duchayuan-pass1`
- `duchayuan-pass2`

> 具体模型可在 OpenClaw agent 配置中单独设置，不需要修改 gate 规则代码。

## 二、设置双审 reviewer 绑定
运行：

```bash
python3 scripts/configure_review_controls.py \
  <project_root> \
  --pass1-agent duchayuan-pass1 \
  --pass2-agent duchayuan-pass2
```

配置写入：
- `ai/state/review-controls.json`
- `ai/state/orchestrator-state.json`

关键字段：
- `review_pass_1_agent_id`
- `review_pass_2_agent_id`

## 三、门禁不变
双审门禁仍要求：
1. 双审区块完整（pass1/pass2）
2. 双PASS且无冲突
3. 仲裁证据完备（若触发仲裁）
4. 审查对象一致（run_id + commit_sha）

模型仅影响“谁审”，不影响门禁判定标准。
