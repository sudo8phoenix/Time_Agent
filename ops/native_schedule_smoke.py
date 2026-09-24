"""Report actual local MPXJ probe outcomes for the declared native fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from app.ingest.native_schedule.runner import ParserRuntimeError, probe_schedule


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    root = args.manifest.parents[2]
    failed = False
    for fixture in manifest.get("fixtures", []):
        path = root / fixture["path"]
        required = bool(fixture.get("required", True))
        if not path.is_file():
            print(
                json.dumps(
                    {
                        "path": fixture["path"],
                        "status": "failed" if required else "unavailable",
                        "code": "MISSING_FIXTURE",
                    }
                )
            )
            failed = failed or required
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != fixture.get("sha256"):
            print(
                json.dumps(
                    {
                        "path": fixture["path"],
                        "status": "failed" if required else "unavailable",
                        "code": "HASH_MISMATCH",
                    }
                )
            )
            failed = failed or required
            continue
        if "expected_projects" not in fixture:
            print(json.dumps({"path": fixture["path"], "status": "expected_failure"}))
            continue
        try:
            result = probe_schedule(path)
            print(json.dumps({"path": fixture["path"], "status": "passed", **result}))
        except ParserRuntimeError as exc:
            print(
                json.dumps(
                    {
                        "path": fixture["path"],
                        "status": "failed" if required else "unavailable",
                        "code": exc.code,
                        "message": exc.message,
                    }
                )
            )
            failed = failed or required
    mpp = manifest.get("mpp", {})
    print(
        json.dumps(
            {
                "format": "msp_mpp",
                "status": mpp.get("status", "pending"),
                "reason": mpp.get("reason", ""),
            }
        )
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
