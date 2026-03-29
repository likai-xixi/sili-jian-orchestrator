from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

PY_COMPILE_TARGETS = [
    REPO_ROOT / "scripts" / "bootstrap_governance.py",
    REPO_ROOT / "scripts" / "build_dispatch_payload.py",
    REPO_ROOT / "scripts" / "validate_state.py",
    REPO_ROOT / "scripts" / "repair_state.py",
    REPO_ROOT / "assets" / "project-skeleton" / "ai" / "tools" / "common.py",
    REPO_ROOT / "assets" / "project-skeleton" / "ai" / "tools" / "validate_state.py",
    REPO_ROOT / "assets" / "project-skeleton" / "ai" / "tools" / "validate_gates.py",
    REPO_ROOT / "assets" / "project-skeleton" / "ai" / "tools" / "run_project_guard.py",
    REPO_ROOT / "assets" / "project-skeleton" / "ai" / "tools" / "render_agent_repair_brief.py",
    REPO_ROOT / "tests" / "test_skill_scripts.py",
]


def run_step(label: str, command: list[str]) -> None:
    print(f"[CI] {label}")
    completed = subprocess.run(command, cwd=REPO_ROOT, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def main() -> None:
    compile_command = [sys.executable, "-m", "py_compile", *[str(path) for path in PY_COMPILE_TARGETS]]
    run_step("Compile critical scripts", compile_command)
    run_step("Run regression tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"])
    print("[CI] All checks passed.")


if __name__ == "__main__":
    main()
