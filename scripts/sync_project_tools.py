from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_TOOL_FILES = [
    "common.py",
    "validate_state.py",
    "validate_gates.py",
    "check_doc_coverage.py",
    "render_agent_repair_brief.py",
    "run_project_guard.py",
]


def resolve_repo_root(root: Path | None = None) -> Path:
    return (root or Path(__file__).resolve().parent.parent).resolve()


def iter_project_tool_mappings(repo_root: Path | None = None) -> list[tuple[Path, Path]]:
    resolved_root = resolve_repo_root(repo_root)
    scripts_dir = resolved_root / "scripts"
    tools_dir = resolved_root / "assets" / "project-skeleton" / "ai" / "tools"
    return [(scripts_dir / name, tools_dir / name) for name in PROJECT_TOOL_FILES]


def find_out_of_sync_project_tools(repo_root: Path | None = None) -> list[str]:
    out_of_sync: list[str] = []
    for source, target in iter_project_tool_mappings(repo_root):
        if not source.exists():
            out_of_sync.append(f"missing source: {source.name}")
            continue
        if not target.exists():
            out_of_sync.append(f"missing target: {target.name}")
            continue
        if source.read_text(encoding="utf-8") != target.read_text(encoding="utf-8"):
            out_of_sync.append(source.name)
    return out_of_sync


def sync_project_tools(repo_root: Path | None = None) -> list[str]:
    updated: list[str] = []
    for source, target in iter_project_tool_mappings(repo_root):
        if not source.exists():
            raise FileNotFoundError(f"Project tool source is missing: {source}")
        content = source.read_text(encoding="utf-8")
        if not target.exists() or target.read_text(encoding="utf-8") != content:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            updated.append(target.name)
    return updated


def assert_project_tools_synced(repo_root: Path | None = None) -> None:
    out_of_sync = find_out_of_sync_project_tools(repo_root)
    if out_of_sync:
        raise RuntimeError(
            "Scaffolded ai/tools are out of sync with scripts. "
            f"Run `python scripts/sync_project_tools.py` to update: {', '.join(out_of_sync)}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync scaffolded ai/tools from the repository scripts source-of-truth.")
    parser.add_argument("--check", action="store_true", help="Fail if scaffolded ai/tools differ from scripts.")
    parser.add_argument("--repo-root", help="Optional repository root override")
    args = parser.parse_args()

    repo_root = resolve_repo_root(Path(args.repo_root) if args.repo_root else None)
    if args.check:
        out_of_sync = find_out_of_sync_project_tools(repo_root)
        if out_of_sync:
            print("Scaffolded ai/tools are out of sync:")
            for item in out_of_sync:
                print(f"- {item}")
            raise SystemExit(1)
        print("Scaffolded ai/tools are in sync.")
        return

    updated = sync_project_tools(repo_root)
    if updated:
        print("Updated scaffolded ai/tools:")
        for name in updated:
            print(f"- {name}")
        return
    print("Scaffolded ai/tools are already up to date.")


if __name__ == "__main__":
    main()
