from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def validate(config: dict) -> list[str]:
    errors: list[str] = []

    required_top = [
        "version",
        "riskThresholds",
        "shadowToStrict",
        "adapterFailureThreshold",
        "arbitration",
    ]
    for key in required_top:
        if key not in config:
            errors.append(f"missing top-level key: {key}")

    thresholds = config.get("adapterFailureThreshold", {})
    for key in ["dailyFailureRateMax", "rolling1hFailureRateMax"]:
        value = thresholds.get(key)
        if value is None:
            errors.append(f"missing adapterFailureThreshold.{key}")
            continue
        if not isinstance(value, (int, float)):
            errors.append(f"{key} must be number")
            continue
        if value < 0 or value > 1:
            errors.append(f"{key} must be within [0,1]")

    shadow = config.get("shadowToStrict", {})
    must = {
        "observationDaysMin": int,
        "highRiskMissesMustBe": int,
        "coverageRateMin": (int, float),
        "falsePositiveRateMax": (int, float),
        "auditCompletenessMustBe": (int, float),
    }
    for key, typ in must.items():
        value = shadow.get(key)
        if value is None:
            errors.append(f"missing shadowToStrict.{key}")
            continue
        if not isinstance(value, typ):
            errors.append(f"shadowToStrict.{key} has invalid type")

    arbitration = config.get("arbitration", {})
    if not isinstance(arbitration.get("mediumRiskWindowHours"), int):
        errors.append("arbitration.mediumRiskWindowHours must be int")
    if not isinstance(arbitration.get("holidayExtensionToNextBusinessDay"), bool):
        errors.append("arbitration.holidayExtensionToNextBusinessDay must be bool")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate doc gate config")
    parser.add_argument("config_path", type=Path)
    args = parser.parse_args()

    if not args.config_path.exists():
        print(f"ERROR: config not found: {args.config_path}")
        return 2

    try:
        config = load_json(args.config_path)
    except Exception as exc:  # pragma: no cover
        print(f"ERROR: failed to parse json: {exc}")
        return 2

    errors = validate(config)
    if errors:
        print("DOC_GATE_CONFIG_INVALID")
        for err in errors:
            print(f"- {err}")
        return 1

    print("DOC_GATE_CONFIG_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
