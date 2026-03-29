# Runtime

This directory is reserved for the OpenClaw-backed orchestrator runtime.

- `outbox/` stores prepared dispatch envelopes for peer agents.
- `inbox/` stores completion payloads before they are consumed.
- `rollover/` may store context rollover packages when sessions rotate.
- `reattach/` stores parent-session reattach payloads and auto-reattach envelopes.
- `runtime-config.json` stores project-local runtime defaults that can be auto-generated when environment variables are missing.

Recommended control loop:

0. `python ai/tools/natural_language_control.py <project-root> "进入自动模式"`
1. `python ai/tools/automation_control.py <project-root> --mode autonomous --actor user --reason "Start background orchestrator loop"`
2. `python ai/tools/runtime_loop.py <project-root> --transport outbox`
2. or run the pieces separately:
3. `python ai/tools/run_orchestrator.py <project-root> --transport outbox`
4. `python ai/tools/openclaw_adapter.py <project-root> --drain-outbox`
5. write peer completions into `ai/runtime/inbox/`
6. `python ai/tools/inbox_watcher.py <project-root>`
7. `python ai/tools/evidence_collector.py <project-root> --force`
8. `python ai/tools/provider_evidence.py <project-root>`
9. `python ai/tools/escalation_manager.py <project-root>`
10. `python ai/tools/runtime_environment.py <project-root>`
11. `python ai/tools/host_interface_probe.py <project-root>`
12. `python ai/tools/environment_bootstrap.py <project-root>`
13. `python ai/tools/parent_session_recovery.py <project-root>`
14. `python ai/tools/automation_control.py <project-root> --mode paused --actor user --reason "Need interactive clarification"`
15. repeat until no ready workflow steps remain

`host_interface_probe.py` now reads machine-visible host interfaces such as OpenClaw-related environment variables and host config files, then syncs the discovered `spawn`, `send`, and `parent-attach` commands into `ai/runtime/runtime-config.json`. `runtime_environment.py` builds on top of that and auto-generates any remaining project-local bridge defaults. `environment_bootstrap.py` auto-installs project dependencies like `requirements.txt` or `package.json` dependencies when the runtime loop starts, and it can also attempt configured host-side helper installers when needed. The skill assumes it is already running inside an OpenClaw host, so it does not try to install OpenClaw itself. If `OPENCLAW_PARENT_ATTACH_COMMAND` is not configured, `parent_session_recovery.py`, `runtime_loop.py`, and `openclaw_adapter.py` can now fall back to the probed commands stored in the project-local runtime config. Set `SILIJIAN_AUTO_REATTACH=0` or pass `--no-auto-reattach` to disable automatic parent reattach for a specific run.

Natural-language examples:

- Canonical prefix: `司礼监：`
- `python ai/tools/natural_language_control.py <project-root> "司礼监：进入自动模式"`
- `python ai/tools/natural_language_control.py <project-root> "司礼监：暂停自动推进"`
- `python ai/tools/natural_language_control.py <project-root> "司礼监：查看当前模式"`
- `python ai/tools/natural_language_control.py <project-root> "司礼监：退出自动模式"`
- `python ai/tools/natural_language_control.py <project-root> "司礼监：把登录流程改成短信验证码 + 邮箱验证码双通道"`
- `python ai/tools/replan_change_request.py <project-root> CR-001`
