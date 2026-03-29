from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import inspect_project


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect target project governance readiness.")
    parser.add_argument("project_root", help="Target project root")
    parser.add_argument(
        "--intent",
        default="auto",
        choices=["auto", "vague-requirement", "new-project", "mid-stream-takeover", "session-recovery", "new-feature"],
        help="Request intent to combine with directory inspection",
    )
    parser.add_argument("--output", help="Optional JSON output path")
    args = parser.parse_args()

    result = inspect_project(Path(args.project_root), intent=args.intent)
    payload = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)


if __name__ == "__main__":
    main()
