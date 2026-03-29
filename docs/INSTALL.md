# 安装说明

本文档说明如何把 `sili-jian-orchestrator` 安装到 OpenClaw 中。

## 一、安装前提

建议先确认以下条件：

1. OpenClaw 已可正常运行
2. 当前主司礼监 workspace 已可用
3. `openclaw agents list --json` 能正常执行
4. OpenClaw 中已经存在以下核心 agent，或至少允许后续自动补齐：
   - `silijian`
   - `neige`
   - `duchayuan`
   - `libu2`
   - `hubu`
   - `gongbu`
   - `bingbu`
   - `libu`
   - `xingbu`

## 二、推荐安装位置

对你当前环境，推荐安装到：

```text
/home/claw/clawd/skills/sili-jian-orchestrator
```

原因是：

- `silijian` 当前 workspace 是 `/home/claw/clawd`
- OpenClaw 当前会从该 workspace 下的 `skills/` 目录读取本地技能

## 三、从本地目录安装

如果你当前已经有本地技能目录，例如：

```text
C:\Users\11131\Desktop\auto agent\sili-jian-orchestrator
```

在 WSL 中可执行：

```bash
mkdir -p /home/claw/clawd/skills
rm -rf /home/claw/clawd/skills/sili-jian-orchestrator
cp -r "/mnt/c/Users/11131/Desktop/auto agent/sili-jian-orchestrator" /home/claw/clawd/skills/
```

## 四、从 GitHub 仓库安装

如果你已经把仓库上传到 GitHub，可以先 clone，再复制到 skills 目录。

示例：

```bash
cd /tmp
rm -rf sili-jian-orchestrator
git clone <你的 GitHub 仓库地址>
mkdir -p /home/claw/clawd/skills
rm -rf /home/claw/clawd/skills/sili-jian-orchestrator
cp -r sili-jian-orchestrator /home/claw/clawd/skills/
```

注意：

- `openclaw skills install <slug>` 主要用于 ClawHub 远程技能
- 对自定义 GitHub 技能，最稳方式仍然是 `git clone + cp -r`

## 五、安装后验证

### 1. 检查目录

```bash
ls /home/claw/clawd/skills/sili-jian-orchestrator
```

应该至少存在：

- `SKILL.md`
- `agents/`
- `references/`
- `assets/`
- `scripts/`

### 2. 检查是否能被识别

```bash
openclaw skills list | grep sili-jian-orchestrator
```

### 3. 查看技能信息

```bash
openclaw skills info sili-jian-orchestrator
```

## 六、首次使用前建议

安装完成后，不要一上来就让技能直接开发。

建议先执行：

1. first-run 引导
2. peer-agent 就绪检查
3. 首轮接管检查

## 七、常见问题

### 1. 为什么不是安装到 `~/.openclaw/`

因为：

- `~/.openclaw` 更偏系统状态目录
- 当前主 workspace 的本地技能目录是 `/home/claw/clawd/skills`

### 2. 如果我在其他 agent workspace 中也要使用怎么办

可以复制到对应 workspace 的 `skills/` 目录下，例如：

- `/home/claw/clawd-neige/skills/`
- `/home/claw/clawd-bingbu/skills/`

但通常主入口技能优先安装到 `silijian` 所在的主 workspace 即可。

### 3. 如果安装后技能没被识别怎么办

依次检查：

1. 目录名是否正确：`sili-jian-orchestrator`
2. 根目录是否存在 `SKILL.md`
3. `agents/openai.yaml` 是否存在
4. 是否复制到了当前 workspace 的 `skills/` 目录
5. 当前会话是否需要重开一轮
