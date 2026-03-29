# 司礼监总调度技能

[![Skill CI](https://github.com/likai-xixi/sili-jian-orchestrator/actions/workflows/skill-ci.yml/badge.svg)](https://github.com/likai-xixi/sili-jian-orchestrator/actions/workflows/skill-ci.yml)

`sili-jian-orchestrator` 是一个面向 OpenClaw 的项目治理型技能。它不是普通编码助手，而是“司礼监 / 总调度 Agent”的技能封装：优先负责项目识别、场景分流、治理初始化、状态维护、交接恢复、门禁检查，以及对内阁、都察院、六部的真实调度。

## 这个技能能做什么

- 接管一个做到一半的项目
- 恢复一个暂停中的项目或新会话
- 给旧项目补齐治理骨架
- 将模糊需求先整理成方案，再决定是否执行
- 把新增功能纳入既有治理体系
- 维护项目内状态、交接、报告、workflow、测试与门禁
- 在 OpenClaw 提供同级部门 agent 时，按真实 `agentId` 派发任务

## 什么时候适合使用

推荐在这些场景使用：

1. 新建项目，需要先建立治理体系
2. 中途接管项目，需要先盘点现状再推进
3. 恢复一个暂停中的项目，需要先读状态和交接
4. 需求比较模糊，需要先方案化而不是直接开发
5. 已有项目要长期维护，需要持续状态、交接、测试、审批闭环

不推荐在这些场景使用：

1. 单纯改一个按钮
2. 修一个很小的 bug
3. 写一个不需要治理流程的小接口

## OpenClaw 部门映射

当前技能默认使用这些真实 `agentId`：

- `neige` = 内阁
- `duchayuan` = 都察院
- `libu2` = 吏部
- `hubu` = 户部
- `gongbu` = 工部
- `bingbu` = 兵部
- `libu` = 礼部
- `xingbu` = 刑部

注意：

- `libu2` 是 **吏部**
- `libu` 是 **礼部**

## 仓库内容

- `SKILL.md`：技能入口与强规则
- `agents/`：OpenClaw 技能元数据
- `references/`：制度规则、调度规则、恢复规则
- `assets/project-skeleton/`：治理骨架模板
- `assets/output-templates/`：首轮接管、状态修复、任务卡等输出模板
- `scripts/`：治理初始化、状态检查、修复、门禁、调度 payload 生成等脚本
- `tests/`：技能自身脚本的回归测试
- `docs/`：中文安装、使用、提示词与状态工具说明

## 目标项目 push 后会不会自动守门

会，但前提是目标项目已经通过本技能完成治理初始化。

治理初始化时，技能现在会一并落地：

- `ai/tools/validate_state.py`
- `ai/tools/validate_gates.py`
- `ai/tools/run_project_guard.py`
- `.github/workflows/project-guard.yml`

这样目标项目后续在 GitHub 上执行 `push / pull request` 时，就会自动检查：

1. 状态文件是否一致
2. active handoff 是否存在
3. 当前阶段门禁是否通过

另外，目标项目还会得到一个可手动点击的 workflow：

- `.github/workflows/project-repair-brief.yml`

它会生成：

- `ai/reports/agent-repair-brief.md`
- `ai/reports/agent-repair-brief.json`

其中包含：

1. 当前问题清单
2. 建议的修复方向
3. 一段可直接复制给 agent 的中文提示词

也就是说：

- 本仓库自己的 CI：守这个技能仓库本身
- 目标项目里的 `project-guard.yml`：守被接管的业务项目

## 文档入口

- [安装说明](./docs/INSTALL.md)
- [使用说明](./docs/USAGE.md)
- [简易版文档](./docs/SIMPLE.md)
- [详细版文档](./docs/DETAILED.md)
- [提示词文档](./docs/PROMPTS.md)
- [按推进顺序手册](./docs/FLOWS.md)
- [状态检查与修复](./docs/STATE-TOOLS.md)

## 第一次使用建议

第一次不要直接让技能开发，建议先跑首次启用引导：

```text
使用 $sili-jian-orchestrator 对当前目录执行首次启用引导。

要求：
1. 先不要直接开发
2. 先判断当前目录是技能目录、项目目录、workspace 根目录还是未知目录
3. 检查 OpenClaw 中司礼监与同级部门 agent 是否已就绪
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

## 维护说明

如果你要继续增强这个技能，建议优先跑：

```bash
python scripts/run_repo_ci.py
```

再修改这些关键脚本：

- `scripts/bootstrap_governance.py`
- `scripts/build_dispatch_payload.py`
- `scripts/validate_state.py`
- `scripts/repair_state.py`
- `scripts/ensure_openclaw_agents.py`

GitHub 端也已经接入自动校验：

- `.github/workflows/skill-ci.yml`

只要向 `main` 推送或发起 Pull Request，就会自动执行：

1. 关键脚本 `py_compile`
2. `tests/` 下的回归测试
