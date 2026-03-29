from __future__ import annotations

import argparse
import json
from pathlib import Path

import automation_control
import change_request_control
import close_session
import runtime_loop
from common import HANDOFF_DIRS


CONTROL_PREFIXES = (
    "司礼监：",
    "司礼监:",
    "司礼监 ",
    "sili-jian:",
    "sili-jian ",
    "orchestrator:",
    "orchestrator ",
)
AGENT_IDS = ("orchestrator", *HANDOFF_DIRS)
CLOSE_SESSION_ACTIONS = ("关闭", "关掉", "结束", "终止", "close", "terminate", "retire")
SESSION_TERMS = ("会话", "session", "当前会话", "current session", "child session")


def normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


def contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def strip_control_prefix(request: str) -> str:
    stripped = request.strip()
    lowered = stripped.lower()
    for prefix in CONTROL_PREFIXES:
        if lowered.startswith(prefix.lower()):
            return stripped[len(prefix):].strip()
    return stripped


def intends_close_session(text: str) -> bool:
    return contains_any(text, CLOSE_SESSION_ACTIONS) and contains_any(text, SESSION_TERMS)


def classify_request(request: str) -> str:
    text = normalize(strip_control_prefix(request))
    if not text:
        return "status"

    if contains_any(text, ("暂停自动推进", "暂停自动模式", "暂停司礼监", "先暂停", "pause automation", "pause autonomous", "pause orchestrator")):
        return "pause"
    if contains_any(text, ("退出自动模式", "关闭自动模式", "回到普通模式", "停止自动模式", "stop automation", "disable automation", "back to normal mode")):
        return "normal"
    if contains_any(text, ("查看自动模式", "查看状态", "现在是什么模式", "当前模式", "status", "show status", "automation status")):
        return "status"
    if intends_close_session(text):
        return "close_session"
    if contains_any(text, ("进入自动模式", "开启自动模式", "开始自动推进", "开始全自动推进", "恢复自动推进", "恢复司礼监", "进入司礼监模式", "start automation", "enable automation", "resume automation", "start autonomous", "resume autonomous")):
        return "autonomous"
    if contains_any(text, ("准备自动模式", "预备自动模式", "armed mode", "arm automation")):
        return "armed"
    return "change_request"


def extract_agent_id(request: str) -> str:
    lowered = normalize(strip_control_prefix(request))
    for agent_id in AGENT_IDS:
        if agent_id.lower() in lowered:
            return agent_id
    if "当前会话" in lowered or "current session" in lowered:
        return "orchestrator"
    return ""


def execute_request(
    project_root: Path,
    request: str,
    actor: str = "user",
    transport: str = "outbox",
    max_cycles: int = 1,
    max_dispatch: int = 3,
) -> dict:
    cleaned_request = strip_control_prefix(request)
    intent = classify_request(cleaned_request)
    reason = request.strip() or "Natural language automation control request."
    payload: dict[str, object] = {
        "request": request,
        "cleaned_request": cleaned_request,
        "intent": intent,
        "project_root": str(project_root.resolve()),
    }

    if intent == "status":
        payload["control"] = automation_control.current_status(project_root)
        return payload

    if intent == "pause":
        payload["control"] = automation_control.set_mode(project_root, "paused", actor=actor, reason=reason)
        return payload

    if intent == "normal":
        payload["control"] = automation_control.set_mode(project_root, "normal", actor=actor, reason=reason)
        return payload

    if intent == "armed":
        payload["control"] = automation_control.set_mode(project_root, "armed", actor=actor, reason=reason)
        return payload

    if intent == "close_session":
        agent_id = extract_agent_id(cleaned_request)
        if not agent_id:
            payload["error"] = "No target agent id could be inferred from the close-session request."
            payload["control"] = automation_control.current_status(project_root)
            return payload
        payload["session_close"] = close_session.apply_close(project_root, agent_id, reason, force_native=True)
        payload["control"] = automation_control.current_status(project_root)
        return payload

    if intent == "change_request":
        payload["change_request"] = change_request_control.apply_change_request(project_root, cleaned_request, actor=actor)
        payload["control"] = automation_control.current_status(project_root)
        return payload

    payload["control"] = automation_control.set_mode(project_root, "autonomous", actor=actor, reason=reason)
    payload["runtime_loop"] = runtime_loop.run_loop(
        project_root,
        max_cycles=max_cycles,
        max_dispatch=max_dispatch,
        transport=transport,
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description='Control automation mode, close child sessions, or submit mid-flight change requests from a single natural-language sentence.')
    parser.add_argument("project_root", help="Target project root")
    parser.add_argument("request", help='Natural-language request such as "司礼监：进入自动模式", "司礼监：关闭 libu2 当前会话", or "司礼监：把登录流程改成短信验证码双通道"')
    parser.add_argument("--actor", default="user", help="Who initiated the request")
    parser.add_argument("--transport", choices=["outbox", "command"], default="outbox", help="Transport mode when entering autonomous mode")
    parser.add_argument("--max-cycles", type=int, default=1, help="Loop cycles to run immediately after entering autonomous mode")
    parser.add_argument("--max-dispatch", type=int, default=3, help="Maximum ready steps to dispatch when entering autonomous mode")
    args = parser.parse_args()

    payload = execute_request(
        Path(args.project_root).resolve(),
        args.request,
        actor=args.actor,
        transport=args.transport,
        max_cycles=args.max_cycles,
        max_dispatch=args.max_dispatch,
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
