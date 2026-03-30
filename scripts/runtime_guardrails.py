from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

from common import read_text, utc_now, write_json, write_text


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def context_soft_limit_tokens() -> int:
    return _env_int("SILIJIAN_CONTEXT_SOFT_LIMIT_TOKENS", 12000)


def context_hard_limit_tokens() -> int:
    hard = _env_int("SILIJIAN_CONTEXT_HARD_LIMIT_TOKENS", 16000)
    return max(hard, context_soft_limit_tokens() + 1)


def session_completion_limit() -> int:
    return _env_int("SILIJIAN_SESSION_COMPLETION_LIMIT", 4)


def session_dispatch_limit() -> int:
    return _env_int("SILIJIAN_SESSION_DISPATCH_LIMIT", 6)


def invalid_completion_fuse_threshold() -> int:
    return _env_int("SILIJIAN_INVALID_COMPLETION_FUSE_THRESHOLD", 2)


def estimate_tokens(text: str) -> int:
    return int(math.ceil(len(text) / 4.0)) if text else 0


def _source_payload(project_root: Path, path: Path) -> dict[str, Any]:
    text = read_text(path)
    return {
        "path": str(path.resolve()),
        "relative_path": str(path.resolve().relative_to(project_root.resolve())).replace("\\", "/"),
        "chars": len(text),
        "estimated_tokens": estimate_tokens(text),
    }


def _append_source(project_root: Path, sources: list[dict[str, Any]], path: Path) -> None:
    if not path.exists() or not path.is_file():
        return
    sources.append(_source_payload(project_root, path))


def collect_context_sources(project_root: Path, agent_id: str = "orchestrator") -> list[dict[str, Any]]:
    project_root = project_root.resolve()
    sources: list[dict[str, Any]] = []
    state_dir = project_root / "ai" / "state"
    reports_dir = project_root / "ai" / "reports"

    for path in [
        state_dir / "START_HERE.md",
        state_dir / "project-handoff.md",
        state_dir / "orchestrator-state.json",
        state_dir / "agent-sessions.json",
        project_root / "docs" / "ANTI-DRIFT-RUNBOOK.md",
        reports_dir / "runtime-loop-summary.json",
        reports_dir / "orchestrator-rollover.md",
        reports_dir / "parent-session-recovery.md",
        reports_dir / "orchestrator-dispatch-plan.md",
    ]:
        _append_source(project_root, sources, path)

    if agent_id == "orchestrator":
        handoff_files = sorted((project_root / "ai" / "handoff").glob("*/active/*.md"))
    else:
        handoff_files = sorted((project_root / "ai" / "handoff" / agent_id / "active").glob("*.md"))
    for path in handoff_files[:8]:
        _append_source(project_root, sources, path)

    prompt_files = sorted((project_root / "ai" / "prompts" / "dispatch").glob("*.md"))
    for path in prompt_files[:4]:
        _append_source(project_root, sources, path)

    return sources


def context_budget_snapshot(project_root: Path, agent_id: str = "orchestrator") -> dict[str, Any]:
    sources = collect_context_sources(project_root, agent_id=agent_id)
    total_estimated_tokens = sum(int(item.get("estimated_tokens", 0)) for item in sources)
    soft_limit = context_soft_limit_tokens()
    hard_limit = context_hard_limit_tokens()
    reasons: list[str] = []

    if total_estimated_tokens >= hard_limit:
        reasons.append(
            f"Estimated context {total_estimated_tokens} tokens exceeded the hard limit of {hard_limit}."
        )
    elif total_estimated_tokens >= soft_limit:
        reasons.append(
            f"Estimated context {total_estimated_tokens} tokens reached the rollover threshold of {soft_limit}."
        )
    if len(sources) >= 12 and total_estimated_tokens >= max(int(soft_limit * 0.6), 4000):
        reasons.append("Context fan-out is high; too many active artifacts would need to be reloaded.")

    largest_sources = sorted(
        sources,
        key=lambda item: (int(item.get("estimated_tokens", 0)), int(item.get("chars", 0))),
        reverse=True,
    )[:5]
    status = "ok"
    if total_estimated_tokens >= hard_limit:
        status = "hard-limit"
    elif total_estimated_tokens >= soft_limit:
        status = "soft-limit"

    return {
        "created_at": utc_now(),
        "agent_id": agent_id,
        "status": status,
        "should_rollover": bool(reasons),
        "soft_limit_tokens": soft_limit,
        "hard_limit_tokens": hard_limit,
        "total_estimated_tokens": total_estimated_tokens,
        "source_count": len(sources),
        "utilization": round(total_estimated_tokens / float(hard_limit), 3) if hard_limit else 0.0,
        "reasons": reasons,
        "largest_sources": largest_sources,
        "sources": sources,
    }


def render_context_budget_markdown(payload: dict[str, Any]) -> str:
    reasons = "\n".join(f"- {item}" for item in payload.get("reasons", [])) or "- none"
    largest = "\n".join(
        f"- {item.get('relative_path', item.get('path', ''))}: ~{item.get('estimated_tokens', 0)} tokens"
        for item in payload.get("largest_sources", [])
    ) or "- none"
    return f"""# Context Budget

- created_at: {payload.get('created_at', '')}
- agent_id: {payload.get('agent_id', 'orchestrator')}
- status: {payload.get('status', 'ok')}
- should_rollover: {'yes' if payload.get('should_rollover') else 'no'}
- total_estimated_tokens: {payload.get('total_estimated_tokens', 0)}
- soft_limit_tokens: {payload.get('soft_limit_tokens', 0)}
- hard_limit_tokens: {payload.get('hard_limit_tokens', 0)}
- source_count: {payload.get('source_count', 0)}

## Reasons

{reasons}

## Largest Sources

{largest}
"""


def write_context_budget_report(project_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    reports_dir = project_root / "ai" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    agent_slug = str(payload.get("agent_id") or "orchestrator").replace("/", "-")
    write_json(reports_dir / f"context-budget-{agent_slug}.json", payload)
    write_text(reports_dir / f"context-budget-{agent_slug}.md", render_context_budget_markdown(payload))
    return payload


def session_reuse_budget_decision(
    record: dict[str, Any],
    *,
    completion_limit: int | None = None,
    dispatch_limit: int | None = None,
    task_round_limit: int | None = None,
) -> tuple[bool, str]:
    if bool(record.get("rebuild_required")):
        return False, str(record.get("rebuild_reason") or "session rebuild is required after guardrail intervention")

    effective_completion_limit = max(1, int(completion_limit or session_completion_limit()))
    completion_count = int(record.get("completion_count") or 0)
    if completion_count >= effective_completion_limit:
        return (
            False,
            f"session completion_count {completion_count} reached the reuse limit of {effective_completion_limit}",
        )

    effective_dispatch_limit = max(1, int(dispatch_limit or session_dispatch_limit()))
    dispatch_count = int(record.get("dispatch_count") or 0)
    if dispatch_count >= effective_dispatch_limit:
        return (
            False,
            f"session dispatch_count {dispatch_count} reached the reuse limit of {effective_dispatch_limit}",
        )

    effective_task_round_limit = max(1, int(task_round_limit or 3))
    task_round_count = int(record.get("task_round_count") or 0)
    if task_round_count >= effective_task_round_limit:
        return (
            False,
            f"session task_round_count {task_round_count} reached the reuse limit of {effective_task_round_limit}",
        )

    return True, "session is within the configured reuse budget"
