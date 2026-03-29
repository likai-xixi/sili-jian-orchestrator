from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def collect_py_targets() -> list[Path]:
    targets: set[Path] = set()
    roots = [
        REPO_ROOT / "scripts",
        REPO_ROOT / "tests",
        REPO_ROOT / "assets" / "project-skeleton" / "ai" / "tools",
    ]
    for base in roots:
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if path.name == "__init__.py":
                continue
            targets.add(path)
    return sorted(targets)


def run_step(label: str, command: list[str]) -> None:
    print(f"[CI] {label}")
    completed = subprocess.run(command, cwd=REPO_ROOT, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def main() -> None:
    py_compile_targets = collect_py_targets()
    if not py_compile_targets:
        raise SystemExit("No Python targets found for repository CI.")
    compile_command = [sys.executable, "-m", "py_compile", *[str(path) for path in py_compile_targets]]
    run_step("Compile critical scripts", compile_command)
    run_step("Run regression tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"])
    print("[CI] All checks passed.")


if __name__ == "__main__":
    main()
