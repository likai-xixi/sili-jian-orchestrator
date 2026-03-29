from __future__ import annotations

import argparse
from pathlib import Path

from common import utc_now, write_json, write_text


def slugify(text: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in text).strip("-")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a run snapshot for a governed project.")
    parser.add_argument("project_root", help="Target project root")
    parser.add_argument("--label", default="heartbeat", help="Run label")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    run_id = f"{utc_now().replace(':', '').replace('+00:00', 'Z')}-{slugify(args.label)}"
    run_dir = project_root / "ai" / "runs" / run_id
    steps_dir = run_dir / "steps"
    steps_dir.mkdir(parents=True, exist_ok=True)

    write_json(
        run_dir / "metadata.json",
        {
            "run_id": run_id,
            "label": args.label,
            "created_at": utc_now(),
            "project_root": str(project_root),
        },
    )
    write_text(
        run_dir / "summary.md",
        f"""# Run Summary

- Run id: {run_id}
- Label: {args.label}
- Created at: {utc_now()}
- Main objective: [fill this during the round]
- Next action: [fill this during the round]
""",
    )
    print(run_id)


if __name__ == "__main__":
    main()
