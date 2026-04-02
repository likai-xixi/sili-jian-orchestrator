from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

SUPPORTED_EXTS = {".md", ".mdx", ".rst", ".adoc", ".wiki"}
HEADING_PATTERNS = [
    re.compile(r"^(#{1,6})\s+(.+?)\s*$"),
    re.compile(r"^=+\s+(.+?)\s*$"),
]
FEATURE_PATTERNS = [
    re.compile(r"feature[_-]?id\s*[:=]\s*([A-Za-z0-9._-]+)", re.IGNORECASE),
    re.compile(r"covers_feature_ids\s*[:=]\s*([A-Za-z0-9._,\-\s]+)", re.IGNORECASE),
    re.compile(r"feature:([A-Za-z0-9._-]+)", re.IGNORECASE),
]


@dataclass
class Heading:
    line_no: int
    title: str


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def detect_format(path: Path) -> str:
    return path.suffix.lstrip(".").lower()


def list_docs(root: Path) -> list[Path]:
    docs: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in SUPPORTED_EXTS:
            docs.append(path)
    return sorted(docs)


def extract_headings(lines: list[str]) -> list[Heading]:
    out: list[Heading] = []
    for idx, raw in enumerate(lines, start=1):
        text = raw.strip()
        for pattern in HEADING_PATTERNS:
            m = pattern.match(text)
            if m:
                title = m.group(m.lastindex or 1).strip()
                out.append(Heading(line_no=idx, title=title))
                break
    if not out:
        out.append(Heading(line_no=1, title="document-root"))
    return out


def split_csv_like(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[\s,]+", value.strip()) if item.strip()]


def extract_feature_refs(text: str) -> list[str]:
    refs: list[str] = []
    for pattern in FEATURE_PATTERNS:
        for m in pattern.finditer(text):
            token = m.group(1)
            refs.extend(split_csv_like(token))
    uniq: list[str] = []
    seen = set()
    for ref in refs:
        if ref not in seen:
            seen.add(ref)
            uniq.append(ref)
    return uniq


def git_last_commit(project_root: Path, rel_path: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(project_root), "log", "-1", "--format=%H", "--", str(rel_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except Exception:
        pass
    return ""


def build_ir_entry(
    project_root: Path,
    repo_id: str,
    doc_path: Path,
    heading: Heading,
    next_line: int,
    feature_refs: list[str],
) -> dict:
    rel_path = doc_path.relative_to(project_root)
    commit_sha = git_last_commit(project_root, rel_path)
    stat = doc_path.stat()
    return {
        "version": "1.0.0",
        "repo_id": repo_id,
        "source_format": detect_format(doc_path),
        "doc_path": str(rel_path).replace("\\", "/"),
        "line_range": {"start": heading.line_no, "end": max(heading.line_no, next_line - 1)},
        "anchor": heading.title,
        "feature_refs": feature_refs,
        "metadata": {
            "owner": "",
            "last_modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).replace(microsecond=0).isoformat(),
            "commit_sha": commit_sha,
            "generated_at": utc_now(),
        },
    }


def parse_doc(project_root: Path, repo_id: str, doc_path: Path) -> list[dict]:
    text = doc_path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    headings = extract_headings(lines)
    refs = extract_feature_refs(text)

    items: list[dict] = []
    for idx, heading in enumerate(headings):
        next_line = headings[idx + 1].line_no if idx + 1 < len(headings) else max(heading.line_no + 1, len(lines) + 1)
        items.append(build_ir_entry(project_root, repo_id, doc_path, heading, next_line, refs))
    return items


def infer_repo_id(project_root: Path) -> str:
    return project_root.name.lower().replace(" ", "-")


def build_ir(project_root: Path, repo_id: str) -> dict:
    docs = list_docs(project_root)
    entries: list[dict] = []
    for doc in docs:
        entries.extend(parse_doc(project_root, repo_id, doc))
    return {
        "schema_version": "ir-v1",
        "generated_at": utc_now(),
        "project_root": str(project_root),
        "repo_id": repo_id,
        "documents": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse project docs to unified IR")
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--repo-id", default="", help="repo identifier; default inferred from project root")
    parser.add_argument("--out", type=Path, default=None, help="output json path")
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    if not project_root.exists() or not project_root.is_dir():
        print(f"ERROR: invalid project root: {project_root}")
        return 2

    repo_id = args.repo_id.strip() or infer_repo_id(project_root)
    payload = build_ir(project_root, repo_id)

    out_path = args.out or (project_root / "ai" / "reports" / "doc-ir.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"DOC_IR_OK: {out_path}")
    print(f"DOC_IR_COUNT: {len(payload['documents'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
