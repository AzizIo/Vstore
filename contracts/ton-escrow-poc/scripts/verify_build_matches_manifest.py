#!/usr/bin/env python3
"""Compare the fresh Acton build output to the frozen DealEscrow provenance."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_build(build_path: Path, manifest_path: Path) -> dict[str, str]:
    build = json.loads(build_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    code_boc64 = build.get("code_boc64")
    if not isinstance(code_boc64, str) or not code_boc64:
        raise ValueError("Acton build descriptor has no code_boc64")
    code_boc = base64.b64decode(code_boc64, validate=True)
    expected_hash = manifest.get("compiled_code_hash")
    if build.get("hash") != expected_hash:
        raise ValueError(
            f"compiled code hash mismatch: expected {expected_hash!r}, got {build.get('hash')!r}"
        )
    expected_boc64 = manifest.get("compiled_code_boc_base64_sha256")
    actual_boc64 = sha256(code_boc64.encode("ascii"))
    if actual_boc64 != expected_boc64:
        raise ValueError(f"compiled BOC base64 digest mismatch: expected {expected_boc64}, got {actual_boc64}")
    expected_boc = manifest.get("compiled_code_boc_sha256")
    actual_boc = sha256(code_boc)
    if actual_boc != expected_boc:
        raise ValueError(f"compiled BOC digest mismatch: expected {expected_boc}, got {actual_boc}")
    return {"compiled_code_hash": build["hash"], "compiled_boc_sha256": actual_boc}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build", nargs="?", type=Path, default=Path("build/DealEscrow.json"))
    parser.add_argument(
        "manifest", nargs="?", type=Path,
        default=Path("artifacts/frozen/manifest.json"),
    )
    args = parser.parse_args()
    try:
        result = verify_build(args.build, args.manifest)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("PASS: fresh Acton build matches frozen DealEscrow code and BOC digests")
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
