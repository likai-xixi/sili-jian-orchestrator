# OpenClaw 专用使用说明

这份文档只讲一件事：如何在 OpenClaw 里正确使用 `sili-jian-orchestrator`。

它适合这几类场景：

- 你已经把本仓库安装到了 OpenClaw 的 `skills/` 目录
- 你准备在 OpenClaw 中接管一个真实项目
- 你想知道哪些动作会自动推进，哪些不会
- 你想直接复制可用提示词，而不是先读整套治理文档

## 1. 先理解它是什么

`sili-jian-orchestrator` 不是普通编码助手，而是一个面向 OpenClaw 的项目治理 skill。它优先做的是：

- 识别当前目录是不是目标项目目录
- 判断当前属于首次接管、恢复、继续推进还是新项目 intake
- 补齐治理骨架
- 生成和派发任务
- 收集 completion、报告、handoff 和 gate 结果

它不是“只要给一个目录，就无条件自动开发到结束”的全自动代理。

## 2. 安装到 OpenClaw

推荐安装位置：

```text
/home/claw/clawd/skills/sili-jian-orchestrator
```

如果仓库当前在 Windows 路径：

```text
C:\Users\11131\Desktop\auto agent\sili-jian-orchestrator
```

可在 WSL 中执行：

```bash
mkdir -p /home/claw/clawd/skills
rm -rf /home/claw/clawd/skills/sili-jian-orchestrator
cp -r "/mnt/c/Users/11131/Desktop/auto agent/sili-jian-orchestrator" /home/claw/clawd/skills/
```

安装后检查：

```bash
openclaw skills list | grep sili-jian-orchestrator
openclaw skills info sili-jian-orchestrator
```

## 3. 在 OpenClaw 中怎么调用

这个 skill 默认关闭隐式调用，所以要显式写出 skill 名。

配置定义见 [openai.yaml](/C:/Users/11131/Desktop/auto%20agent/sili-jian-orchestrator/agents/openai.yaml)：

- `allow_implicit_invocation: false`
- 默认提示词要求先做 first-use guidance，再接管或恢复项目

最基本的调用方式：

```text
使用 $sili-jian-orchestrator ...
```

## 4. 第一次使用的推荐顺序

### 4.1 首次启用引导

先不要让它直接开发，先让它判断环境和目录模式：

```text
使用 $sili-jian-orchestrator 对当前目录执行首次启用引导。
要求：
1. 不要直接开始开发
2. 先判断当前目录是 skill 目录、workspace 根目录还是项目目录
3. 检查 OpenClaw peer-agent 是否就绪
4. 输出当前模式、最安全的下一步、以及建议我下一条输入什么
```

### 4.2 接管已有项目

如果当前目录已经是业务项目目录：

```text
使用 $sili-jian-orchestrator 接管当前项目，先做首轮接管检查，不要直接进入实现。
```

### 4.3 恢复中断项目

如果项目之前已经治理过：

```text
使用 $sili-jian-orchestrator 恢复当前项目会话，先读取状态、handoff 和最近报告，再给出恢复结论。
```

### 4.4 指定目标项目目录

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

## 5. OpenClaw 里有哪些常用快捷口令

除了显式 skill 调用，项目里还定义了自然语言控制前缀，见 [natural_language_control.py](/C:/Users/11131/Desktop/auto%20agent/sili-jian-orchestrator/scripts/natural_language_control.py)。

支持的控制前缀：

- `司礼监：`
- `sili-jian:`
- `orchestrator:`

常用例子：

```text
司礼监：进入自动模式
司礼监：暂停自动推进
司礼监：查看当前模式
司礼监：关闭 libu2 当前会话
司礼监：把登录流程改成短信验证码双通道
```

这些控制语句当前主要覆盖：

- 查看控制状态
- 切换 `paused / normal / armed / autonomous`
- 关闭指定子会话
- 追加变更请求

## 6. 它在 OpenClaw 中会自动做什么

当项目已经进入治理状态，而且你明确让它进入自动推进后，运行时会自动做这些事：

- 读取工作流和当前状态
- 找出 ready step
- 生成任务卡和派发 payload
- 向 peer-agent 投递任务
- 消费 completion
- 更新 `ai/state`、`ai/handoff`、`ai/reports`
- 收集 gate 与测试证据
- 在阻塞时进入 blocked 或恢复流程

相关脚本主要是：

- [run_orchestrator.py](/C:/Users/11131/Desktop/auto%20agent/sili-jian-orchestrator/scripts/run_orchestrator.py)
- [runtime_loop.py](/C:/Users/11131/Desktop/auto%20agent/sili-jian-orchestrator/scripts/runtime_loop.py)
- [completion_consumer.py](/C:/Users/11131/Desktop/auto%20agent/sili-jian-orchestrator/scripts/completion_consumer.py)

## 7. 它在 OpenClaw 中不会自动做什么

这是最容易误解的地方。

当前仓库没有把下面这些动作接入 OpenClaw 的自然语言控制闭环：

- 自动执行 `git commit`
- 自动执行 `git push`
- 只因为你“指定了一个项目目录”，就立刻开始无条件开发

更准确地说：

- “指定项目目录”是确定治理对象
- “首次启用引导 / 接管检查”是确认能不能推进
- “进入自动模式”才表示运行时开始持续推进

所以它更接近“自动治理与调度”，不是“全自动 Git 交付机器人”。

## 8. OpenClaw peer-agent 映射

当前默认按真实 `agentId` 派发：

- `neige`：方案与架构
- `duchayuan`：终审与裁决
- `libu2`：后端与业务逻辑
- `hubu`：数据库与迁移
- `gongbu`：前端与交互
- `bingbu`：测试
- `libu`：文档、交接、变更摘要
- `xingbu`：构建、发布、安全与回滚

注意：

- `libu2` 不是 `libu`
- `libu2` 和 `libu` 在工作流里承担不同职责

## 9. 最推荐的 6 条可直接复制提示词

### 9.1 首次引导

```text
使用 $sili-jian-orchestrator 对当前目录执行首次启用引导，不要直接开始开发。
```

### 9.2 接管项目

```text
使用 $sili-jian-orchestrator 接管当前项目，先做首轮接管检查，不要直接进入实现。
```

### 9.3 恢复项目

```text
使用 $sili-jian-orchestrator 恢复当前项目会话，先读取状态和 handoff，再告诉我下一步。
```

### 9.4 检查状态一致性

```text
使用 $sili-jian-orchestrator 检查当前项目的状态一致性，不要进入实现阶段。
```

### 9.5 开始自动推进

```text
司礼监：进入自动模式
```

### 9.6 暂停自动推进

```text
司礼监：暂停自动推进
```

## 10. 常见误区

### 10.1 把 skill 仓库目录当成业务项目目录

这是最常见错误。skill 仓库本身不是你要治理的业务项目。

如果当前目录是：

```text
.../sili-jian-orchestrator
```

通常应该先让它识别目录模式，而不是直接 bootstrap 某个业务项目。

### 10.2 以为“指定目录”就会自动写代码

不会。它通常会先做：

1. 目录判断
2. peer-agent 检查
3. 状态检查
4. 接管或恢复判断
5. 必要时治理骨架初始化

然后才会进入后续推进。

### 10.3 以为 agent 协同会自动 commit

当前不会。项目定义了 commit 的治理前置条件，但还没有把 `git commit / push` 接进运行时控制器。

## 11. 遇到问题先看哪里

如果你在 OpenClaw 中遇到“没有继续推进”“状态漂移”“不确定当前该说什么”，优先看：

- [USAGE.md](/C:/Users/11131/Desktop/auto%20agent/sili-jian-orchestrator/docs/USAGE.md)
- [PROMPTS.md](/C:/Users/11131/Desktop/auto%20agent/sili-jian-orchestrator/docs/PROMPTS.md)
- [FLOWS.md](/C:/Users/11131/Desktop/auto%20agent/sili-jian-orchestrator/docs/FLOWS.md)
- [STATE-TOOLS.md](/C:/Users/11131/Desktop/auto%20agent/sili-jian-orchestrator/docs/STATE-TOOLS.md)
- [OPENCLAW-AUTONOMY-BLUEPRINT.md](/C:/Users/11131/Desktop/auto%20agent/sili-jian-orchestrator/docs/OPENCLAW-AUTONOMY-BLUEPRINT.md)

## 12. 一句话结论

在 OpenClaw 中，最稳妥的使用方式不是一上来就说“帮我开发”，而是：

1. 显式调用 `使用 $sili-jian-orchestrator ...`
2. 先跑首次启用引导或接管检查
3. 确认目录、状态和 peer-agent 都正确
4. 再用 `司礼监：进入自动模式` 开始自动推进
