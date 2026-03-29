# Agent Repair Brief

## Summary

- project_root:
- state_consistent:
- phase_gate_passed:
- final_gate_passed:

## Findings

- [fill here]

## Suggested Next Action

- [fill here]

## Copy Prompt

```text
使用 $sili-jian-orchestrator 处理当前项目的治理问题，不要直接开始新功能开发。

目标项目根目录：
<项目绝对路径>

已检测到的问题如下：
<粘贴 Findings>

要求：
1. 先基于问题输出修复方案
2. 再执行必要修复
3. 修复后重新执行状态检查与门禁检查
4. 若修复通过，再整理变更摘要并提交
5. 输出：
   - 修复方案
   - 实际修复清单
   - 修复后的检查结果
   - 是否建议提交
```
