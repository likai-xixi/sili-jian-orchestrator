from __future__ import annotations

import argparse
import json
from pathlib import Path
from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def collect_expected_features(registry: dict) -> set[str]:
    out: set[str] = set()
    for item in registry.get("features", []):
        feature_id = str(item.get("feature_id", "")).strip()
        if feature_id:
            out.add(feature_id)
    return out


def collect_doc_features(ir_payload: dict) -> set[str]:
    out: set[str] = set()
    for doc in ir_payload.get("documents", []):
        for ref in doc.get("feature_refs", []):
            value = str(ref).strip()
            if value:
                out.add(value)
    return out


def _resolve_target_path(project_root: Path, target: str) -> Path:
    p = Path(target)
    return p if p.is_absolute() else (project_root / p)


def build_doc_target_coverage(registry: dict, project_root: Path) -> dict[str, object]:
    features = registry.get("features", [])
    total_targets = 0
    covered_targets = 0
    missing_targets: list[dict] = []

    for item in features:
        feature_id = str(item.get("feature_id", "")).strip()
        targets = [str(t).strip() for t in item.get("doc_targets", []) if str(t).strip()]
        if not targets:
            continue
        for target in targets:
            total_targets += 1
            path = _resolve_target_path(project_root, target)
            if not path.exists():
                missing_targets.append(
                    {"feature_id": feature_id, "doc_target": target, "reason": "file-not-found"}
                )
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if feature_id in text:
                covered_targets += 1
            else:
                missing_targets.append(
                    {"feature_id": feature_id, "doc_target": target, "reason": "feature-id-not-found"}
                )

    rate = 1.0 if total_targets == 0 else covered_targets / total_targets
    return {
        "doc_target_total": total_targets,
        "doc_target_covered": covered_targets,
        "doc_target_coverage_rate": round(rate, 4),
        "missing_doc_targets": missing_targets,
    }


def resolve_risk(feature_id: str, registry: dict) -> str:
    for item in registry.get("features", []):
        if str(item.get("feature_id", "")).strip() == feature_id:
            return str(item.get("risk_level", "low")).strip().lower() or "low"
    return "low"


def build_report(registry: dict, ir_payload: dict, project_root: Path, config: dict | None = None) -> dict:
    expected = collect_expected_features(registry)
    observed = collect_doc_features(ir_payload)

    missing_in_docs = sorted(expected - observed)
    unregistered_in_docs = sorted(observed - expected)

    total = len(expected)
    covered = len(expected & observed)
    feature_ref_coverage = 1.0 if total == 0 else covered / total

    doc_target_stats = build_doc_target_coverage(registry, project_root)

    high_risk_missing = [fid for fid in missing_in_docs if resolve_risk(fid, registry) == "high"]

    return {
        "version": "v1",
        "generated_at": utc_now(),
        "repo_id": registry.get("repo_id", ""),
        "summary": {
            "expected_feature_count": total,
            "observed_feature_count": len(observed),
            "covered_feature_count": covered,
            "feature_ref_coverage_rate": round(feature_ref_coverage, 4),
            "doc_target_total": doc_target_stats["doc_target_total"],
            "doc_target_covered": doc_target_stats["doc_target_covered"],
            "doc_target_coverage_rate": doc_target_stats["doc_target_coverage_rate"],
        },
        "missing_in_docs": missing_in_docs,
        "high_risk_missing_in_docs": high_risk_missing,
        "missing_doc_targets": doc_target_stats["missing_doc_targets"],
        "unregistered_in_docs": unregistered_in_docs,
        "decision_hint": {
            "block_high_risk_if_missing": len(high_risk_missing) > 0,
            "conditional_block_if_medium_missing": any(resolve_risk(fid, registry) == "medium" for fid in missing_in_docs),
            "high_risk_alert_if_unregistered_in_docs": len(unregistered_in_docs) > 0,
        },
        "config_ref": {
            "version": (config or {}).get("version", ""),
            "shadowToStrict": (config or {}).get("shadowToStrict", {}),
        },
    }


def append_history(history_path: Path, report: dict) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "generated_at": report.get("generated_at", ""),
        "repo_id": report.get("repo_id", ""),
        "feature_ref_coverage_rate": report.get("summary", {}).get("feature_ref_coverage_rate", 0),
        "doc_target_coverage_rate": report.get("summary", {}).get("doc_target_coverage_rate", 0),
        "missing_in_docs": len(report.get("missing_in_docs", [])),
        "high_risk_missing_in_docs": len(report.get("high_risk_missing_in_docs", [])),
        "unregistered_in_docs": len(report.get("unregistered_in_docs", [])),
    }
    with history_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check doc coverage against feature registry")
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--doc-ir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--config", required=False, type=Path)
    parser.add_argument("--project-root", required=False, type=Path, help="project root for resolving doc_targets")
    parser.add_argument("--history", required=False, type=Path, help="optional jsonl history output")
    args = parser.parse_args()

    if not args.registry.exists():
        print(f"ERROR: registry not found: {args.registry}")
        return 2
    if not args.doc_ir.exists():
        print(f"ERROR: doc IR not found: {args.doc_ir}")
        return 2

    registry = load_json(args.registry)
    ir_payload = load_json(args.doc_ir)
    config = load_json(args.config) if args.config and args.config.exists() else {}
    project_root = args.project_root.resolve() if args.project_root else args.registry.resolve().parents[2]
    report = build_report(registry, ir_payload, project_root=project_root, config=config)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if args.history:
        append_history(args.history, report)

    print(f"DOC_COVERAGE_OK: {args.out}")
    print(f"FEATURE_REF_COVERAGE_RATE: {report['summary']['feature_ref_coverage_rate']}")
    print(f"DOC_TARGET_COVERAGE_RATE: {report['summary']['doc_target_coverage_rate']}")
    print(f"MISSING_IN_DOCS: {len(report['missing_in_docs'])}")
    print(f"UNREGISTERED_IN_DOCS: {len(report['unregistered_in_docs'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
