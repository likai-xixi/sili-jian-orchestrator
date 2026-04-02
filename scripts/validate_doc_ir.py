from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REQUIRED_DOC_FIELDS = [
    "version",
    "repo_id",
    "source_format",
    "doc_path",
    "line_range",
    "anchor",
    "feature_refs",
    "metadata",
]


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def validate(payload: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["payload must be object"]

    docs = payload.get("documents")
    if not isinstance(docs, list):
        return ["documents must be list"]

    for i, doc in enumerate(docs):
        if not isinstance(doc, dict):
            errors.append(f"documents[{i}] must be object")
            continue
        for field in REQUIRED_DOC_FIELDS:
            if field not in doc:
                errors.append(f"documents[{i}] missing field: {field}")

        line_range = doc.get("line_range", {})
        if not isinstance(line_range, dict):
            errors.append(f"documents[{i}].line_range must be object")
        else:
            start = line_range.get("start")
            end = line_range.get("end")
            if not isinstance(start, int) or not isinstance(end, int):
                errors.append(f"documents[{i}].line_range start/end must be int")
            elif start <= 0 or end < start:
                errors.append(f"documents[{i}].line_range invalid: start={start}, end={end}")

        refs = doc.get("feature_refs")
        if not isinstance(refs, list):
            errors.append(f"documents[{i}].feature_refs must be list")

        metadata = doc.get("metadata", {})
        if not isinstance(metadata, dict):
            errors.append(f"documents[{i}].metadata must be object")
        else:
            for key in ["owner", "last_modified", "commit_sha", "generated_at"]:
                if key not in metadata:
                    errors.append(f"documents[{i}].metadata missing {key}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate document IR output")
    parser.add_argument("ir_json", type=Path)
    args = parser.parse_args()

    if not args.ir_json.exists():
        print(f"ERROR: missing IR file: {args.ir_json}")
        return 2

    try:
        payload = load(args.ir_json)
    except Exception as exc:
        print(f"ERROR: parse failed: {exc}")
        return 2

    errors = validate(payload)
    if errors:
        print("DOC_IR_INVALID")
        for err in errors:
            print(f"- {err}")
        return 1

    print("DOC_IR_VALID")
    print(f"DOC_IR_DOCS: {len(payload.get('documents', []))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
