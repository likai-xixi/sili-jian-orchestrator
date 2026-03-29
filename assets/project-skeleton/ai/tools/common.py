from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PASS_CONCLUSIONS = {"PASS", "PASS_WITH_WARNING", "YES", "APPROVED", "ALLOW"}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig") if path.exists() else ""


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {}


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def text_has_placeholders(text: str) -> bool:
    lowered = text.lower()
    markers = [
        "[fill here]",
        "[define the problem]",
        "[define the primary user or system path]",
        "[list major risks]",
        "[list milestone-level acceptance criteria]",
        "[new incoming requirements]",
        "[approved for current delivery]",
        "[deferred or postponed]",
        "[gray / full / hotfix / rollback]",
    ]
    return any(marker in lowered for marker in markers)


def extract_field_value(markdown: str, field_name: str) -> str:
    target = field_name.strip().lower() + ":"
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("- " + target):
            return stripped[len("- " + target):].strip()
        if stripped.lower().startswith(target):
            return stripped[len(target):].strip()
    return ""


def extract_conclusion(markdown: str, heading: str) -> str:
    lines = markdown.splitlines()
    capture = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            capture = stripped[3:].strip().lower() == heading.strip().lower()
            continue
        if not capture or not stripped:
            continue
        if stripped.startswith("- "):
            value = stripped[2:].strip()
            if value and " / " not in value and "[fill here]" not in value.lower():
                return value
        if " / " not in stripped and "[fill here]" not in stripped.lower():
            return stripped
    return ""
