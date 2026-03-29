# Peer Agent Bootstrap

When running inside OpenClaw, 司礼监 should verify that the required peer agents exist before relying on dispatch.

## Required Peer Agents

- `neige`
- `bingbu`
- `libu2`
- `hubu`
- `gongbu`
- `xingbu`
- `libu`
- `duchayuan`

## Detection Rule

Prefer the official CLI:

```bash
openclaw agents list --json
```

If CLI inspection fails, fall back to parsing `~/.openclaw/openclaw.json` and read `agents.list` before deciding that the peer agents are missing.

If the required peer agents are missing and CLI management is healthy, create them with the official CLI:

```bash
openclaw agents add <agentId> --workspace <workspace-dir> --non-interactive
```

## Bootstrap Rule

- Run detection once per installation or on first use.
- Record the bootstrap result in `ai/state/agent-sessions.json` or in the installation notes if running in skill-bundle mode.
- Distinguish runtime readiness from CLI management readiness when reporting results.
- If auto-creation is unavailable, report the missing peer agents explicitly and stop short of claiming peer-agent dispatch readiness.
