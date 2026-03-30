# OpenClaw 使用说明

这份文档只回答一件事：如何在 OpenClaw 里正确使用 `sili-jian-orchestrator`。

如果你想看完整治理手册，请继续阅读：

1. [使用说明](./USAGE.md)
2. [详细使用文档](./DETAILED.md)
3. [按推进顺序手册](./FLOWS.md)

---

## 1. 在 OpenClaw 里它是什么

在 OpenClaw 中，`sili-jian-orchestrator` 不是普通的编码 skill，而是“治理优先”的项目总调度 skill。

它优先做这些事：

1. 判断当前目录是不是目标项目目录
2. 判断当前是首次接管、会话恢复、持续推进，还是新项目 intake
3. 补齐治理骨架和状态文件
4. 组织 peer-agent 的派发、回收、恢复和轮换
5. 在执行、测试、发布前做阶段守门

它不等于“只要调用一次，就自动开发到结束”的全自动代理。

---

## 2. 适合什么场景

适合：

1. 你已经把这个仓库安装到了 OpenClaw 的 `skills/` 目录
2. 你准备在 OpenClaw 中接管一个真实项目
3. 你准备恢复一个已经中断的治理项目
4. 你要把新增需求纳入已有治理体系
5. 你希望让 OpenClaw 中的 peer-agent 有明确的状态、handoff 和 gate 规则

不适合：

1. 只修一个特别小的 bug
2. 只改一行文案
3. 没有治理需求，只想让 agent 直接写代码

---

## 3. 如何安装到 OpenClaw

推荐安装位置：

```text
/home/claw/clawd/skills/sili-jian-orchestrator
```

如果仓库当前在 Windows 路径，例如：

```text
C:\Users\11131\Desktop\auto agent\sili-jian-orchestrator
```

可以在 WSL 中复制到 OpenClaw 的 skills 目录：

```bash
mkdir -p /home/claw/clawd/skills
rm -rf /home/claw/clawd/skills/sili-jian-orchestrator
cp -r "/mnt/c/Users/11131/Desktop/auto agent/sili-jian-orchestrator" /home/claw/clawd/skills/
```

安装后建议检查：

```bash
openclaw skills list | grep sili-jian-orchestrator
openclaw skills info sili-jian-orchestrator
```

---

## 4. 在 OpenClaw 中如何调用

这个 skill 默认关闭隐式调用，所以要显式写出 skill 名。

最基本的调用方式是：

```text
使用 $sili-jian-orchestrator ...
```

也就是说，不建议只说“帮我接管项目”，而是明确告诉 OpenClaw：

```text
使用 $sili-jian-orchestrator 接管当前项目，先不要直接开发。
```

---

## 5. 第一次使用时的推荐顺序

### 5.1 首次启用引导

先不要让它直接进入开发，先确认环境、目录模式和 peer-agent 状态。

推荐提示词：

```text
使用 $sili-jian-orchestrator 对当前目录执行首次启用引导。
要求：
1. 不要直接开始开发
2. 先判断当前目录是 skill 目录、workspace 根目录还是业务项目目录
3. 检查 OpenClaw peer-agent 是否就绪
4. 输出当前模式、最安全的下一步，以及建议我下一条输入什么
```

### 5.2 接管已有项目

如果当前目录已经是业务项目目录：

```text
使用 $sili-jian-orchestrator 接管当前项目，先做首轮接管检查，不要直接进入实现。
```

### 5.3 恢复中断项目

如果项目之前已经治理过，只是当前线程或会话断了：

```text
使用 $sili-jian-orchestrator 恢复当前项目会话，先读取状态、handoff 和最近报告，再给出恢复建议。
```

### 5.4 指定目标项目目录

如果当前 OpenClaw workspace 不是业务项目根目录，而你又不想让它误判：

```text
使用 $sili-jian-orchestrator 接管指定项目。
目标项目根目录：
<项目绝对路径>

要求：
1. 不要把当前 workspace 根目录当成业务项目目录
2. 只把上面的绝对路径视为唯一目标项目
3. 先执行首次启用引导，再执行首轮接管检查
```

---

## 6. 如果你还没有项目目录

如果你现在停在 `workspace_root_mode`，还没有真正的业务项目目录，推荐先走 intake 流程。

脚本入口：

```bash
python scripts/project_intake.py <workspace-root> --requirement "项目名称叫 xxx，需要实现 yyy"
```

如果项目名已经确认，再创建项目：

```bash
python scripts/project_intake.py <workspace-root> --project-name xxx --activate
```

在 OpenClaw 里也可以直接用自然语言告诉 skill：

```text
使用 $sili-jian-orchestrator 在当前 workspace 根目录记录一个新项目需求，先做 intake，不要直接把 workspace 根当成业务项目目录。
```

---

## 7. OpenClaw 里的常用控制口令

除了显式 skill 调用，项目里还提供了自然语言控制入口，主要由 [natural_language_control.py](/C:/Users/11131/Desktop/auto agent/sili-jian-orchestrator/scripts/natural_language_control.py) 负责。

支持的前缀包括：

1. `司礼监：`
2. `sili-jian:`
3. `orchestrator:`

常见例子：

```text
司礼监：进入自动模式
司礼监：暂停自动推进
司礼监：查看当前模式
司礼监：关闭 libu2 当前会话
司礼监：把登录流程改成短信验证码双通道
```

这些控制语句当前主要覆盖：

1. 查看控制状态
2. 切换 `normal / armed / autonomous / paused`
3. 关闭指定子会话
4. 记录中途 change request

---

## 8. 在 OpenClaw 中会自动做什么

当项目已经具备治理状态，而且你明确让它进入自动推进后，运行时会自动做这些事情：

1. 读取 workflow 和当前状态
2. 找出 ready step
3. 生成 task card 和 dispatch payload
4. 把任务投递给 peer-agent
5. 消费 completion
6. 更新 `ai/state`、`ai/handoff`、`ai/reports`
7. 收集测试与 gate 证据
8. 在阻塞时切入暂停、恢复或升级流程

关键脚本包括：

1. [run_orchestrator.py](/C:/Users/11131/Desktop/auto agent/sili-jian-orchestrator/scripts/run_orchestrator.py)
2. [runtime_loop.py](/C:/Users/11131/Desktop/auto agent/sili-jian-orchestrator/scripts/runtime_loop.py)
3. [completion_consumer.py](/C:/Users/11131/Desktop/auto agent/sili-jian-orchestrator/scripts/completion_consumer.py)

---

## 9. 在 OpenClaw 中不会自动做什么

这是最容易误解的地方。

当前这套能力没有把下面这些动作默认接进 OpenClaw 的自然语言闭环：

1. 自动 `git commit`
2. 自动 `git push`
3. 只因为你“指定了一个目录”，就立刻无条件开始开发

更准确地说：

1. “指定目录”只是确定治理对象
2. “首次启用引导 / 接管检查”是在确认能不能推进
3. “进入自动模式”才表示运行时开始持续推进

所以它更接近“自动治理与调度”，而不是“全自动 Git 交付机器人”。

---

## 10. OpenClaw peer-agent 映射

当前默认按真实 `agentId` 派发：

1. `neige`：方案与架构
2. `duchayuan`：终审与裁决
3. `libu2`：后端与业务逻辑
4. `hubu`：数据库与迁移
5. `gongbu`：前端与交互
6. `bingbu`：测试
7. `libu`：文档、交接、变更摘要
8. `xingbu`：构建、发布、安全与回滚

注意：

1. `libu2` 不是 `libu`
2. `libu2` 和 `libu` 在 workflow 里承担的职责不同

---

## 11. 最推荐直接复制的 8 条提示词

### 11.1 首次启用引导

```text
使用 $sili-jian-orchestrator 对当前目录执行首次启用引导，不要直接开始开发，并遵守 docs/ANTI-DRIFT-RUNBOOK.md。
```

### 11.2 接管当前项目

```text
使用 $sili-jian-orchestrator 接管当前项目，先做首轮接管检查，不要直接进入实现。
```

### 11.3 恢复当前项目

```text
使用 $sili-jian-orchestrator 恢复当前项目会话，先读取状态和 handoff，再告诉我下一步。
```

### 11.4 指定项目目录接管

```text
使用 $sili-jian-orchestrator 接管指定项目。
目标项目根目录：
<项目绝对路径>
先做首次启用引导和接管检查，不要直接开发。
```

### 11.5 做 workspace intake

```text
使用 $sili-jian-orchestrator 在当前 workspace 根目录记录一个新项目需求，先做 intake，再告诉我创建项目的下一步。
```

### 11.6 检查状态一致性

```text
使用 $sili-jian-orchestrator 检查当前项目的状态一致性，不要进入实现阶段。
```

### 11.7 开始自动推进

```text
司礼监：进入自动模式
```

### 11.8 暂停自动推进

```text
司礼监：暂停自动推进
```

---

## 12. 常见误区

### 12.1 把 skill 仓库目录当成业务项目目录

这是最常见错误。

如果当前目录是：

```text
.../sili-jian-orchestrator
```

通常应该先让它识别目录模式，而不是直接把这个目录当成要治理的业务项目。

### 12.2 以为“指定目录”就会自动写代码

不会。

它通常会先做：

1. 目录判断
2. peer-agent 检查
3. 状态检查
4. 接管或恢复判断
5. 必要时治理骨架初始化

然后才会进入后续推进。

### 12.3 以为 OpenClaw 协同会自动 commit / push

当前不会。

项目定义了 commit 前置治理条件，但没有把 `git commit / push` 默认接进运行时控制器。

---

## 13. 遇到问题先看哪里

如果你在 OpenClaw 里遇到“没有继续推进”“状态漂移”“不知道下一条该怎么说”，优先看这些文档：

1. [使用说明](./USAGE.md)
2. [详细使用文档](./DETAILED.md)
3. [提示词文档](./PROMPTS.md)
4. [按推进顺序手册](./FLOWS.md)
5. [状态检查与修复](./STATE-TOOLS.md)
6. [OpenClaw 自治蓝图](./OPENCLAW-AUTONOMY-BLUEPRINT.md)

如果你在排查运行期问题，优先看这些输出：

1. `ai/reports/runtime-loop-summary.json`
2. `ai/reports/orchestrator-dispatch-plan.json`
3. `ai/reports/provider-evidence-summary.json`
4. `ai/reports/runtime-environment.json`
5. `ai/state/orchestrator-state.json`

---

## 14. 一句话结论

在 OpenClaw 中，最稳妥的使用方式不是一上来就说“帮我开发”，而是：

1. 显式调用 `使用 $sili-jian-orchestrator ...`
2. 先跑首次启用引导或接管检查
3. 确认目录、状态和 peer-agent 都正确
4. 再用 `司礼监：进入自动模式` 开始持续推进

这样它才能在 OpenClaw 里稳定发挥价值。
