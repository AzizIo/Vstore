#!/usr/bin/env python3
"""Verify source-controlled frozen DealEscrow ABI and compiled code BOC."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path


class FrozenArtifactError(ValueError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_frozen_artifacts(directory: Path) -> dict[str, str]:
    manifest_path = directory / "manifest.json"
    abi_path = directory / "DealEscrow.abi.json"
    boc_path = directory / "DealEscrow.code.boc.base64"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        abi_bytes = abi_path.read_bytes()
        boc_text = boc_path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FrozenArtifactError(f"cannot read frozen artifact set: {exc}") from exc

    try:
        abi = json.loads(abi_bytes)
        canonical_abi = json.dumps(abi, separators=(",", ":"), ensure_ascii=False).encode()
        boc_bytes = base64.b64decode(boc_text, validate=True)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise FrozenArtifactError(f"invalid ABI JSON or BOC base64: {exc}") from exc

    checks = {
        "abi_compact_sha256": sha256(canonical_abi),
        "compiled_code_boc_base64_sha256": sha256(boc_text.encode("ascii")),
        "compiled_code_boc_sha256": sha256(boc_bytes),
    }
    for field, actual in checks.items():
        expected = manifest.get(field)
        if not isinstance(expected, str) or actual != expected:
            raise FrozenArtifactError(
                f"{field} mismatch: expected {expected!r}, got {actual}"
            )

    if abi.get("contract_name") != "DealEscrow" or abi.get("version") != "1.0.0":
        raise FrozenArtifactError("unexpected ABI contract identity/version")
    if abi.get("compiler_name") != "tolk" or abi.get("compiler_version") != manifest.get("tolk_version"):
        raise FrozenArtifactError("ABI compiler metadata does not match manifest")
    if manifest.get("contract") != "DealEscrow" or manifest.get("network_scope") != "TON testnet only":
        raise FrozenArtifactError("manifest contract or network scope is invalid")

    return {
        **checks,
        "compiled_code_hash": str(manifest.get("compiled_code_hash")),
        "source_commit": str(manifest.get("source_commit")),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "directory",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "artifacts" / "frozen",
    )
    args = parser.parse_args()
    try:
        result = verify_frozen_artifacts(args.directory)
    except FrozenArtifactError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("PASS: source-controlled DealEscrow ABI and code BOC match frozen manifest")
    for key, value in result.items():
        print(f"{key}: {value}")
    print("NOTE: integrity verification is not a contract audit or StateInit/address proof.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
