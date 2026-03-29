from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from common import write_text


def render_template(text: str, project_name: str, project_id: str) -> str:
    normalized = text.lstrip("\ufeff")
    return normalized.replace("{{PROJECT_NAME}}", project_name).replace("{{PROJECT_ID}}", project_id)
def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap governance files into a target project.")
    parser.add_argument("project_root", help="Target project root")
    parser.add_argument("--project-name", help="Explicit project name to write into templates")
    parser.add_argument("--project-id", help="Explicit project id to write into templates")
    parser.add_argument("--force", action="store_true", help="Overwrite existing files")
    parser.add_argument("--skill-root", default=Path(__file__).resolve().parent.parent, help="Skill root path")
    args = parser.parse_args()

    skill_root = Path(args.skill_root).resolve()
    project_root = Path(args.project_root).resolve()
    skeleton_root = skill_root / "assets" / "project-skeleton"
    project_name = args.project_name or project_root.name
    project_id = args.project_id or project_root.name

    project_root.mkdir(parents=True, exist_ok=True)
    for item in skeleton_root.rglob("*"):
        relative = item.relative_to(skeleton_root)
        target = project_root / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if target.exists() and not args.force:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if item.suffix.lower() in {".md", ".json", ".yaml", ".yml"}:
            rendered = render_template(item.read_text(encoding="utf-8"), project_name, project_id)
            write_text(target, rendered)
        else:
            shutil.copy2(item, target)
    print(f"Bootstrapped governance into {project_root}")


if __name__ == "__main__":
    main()
