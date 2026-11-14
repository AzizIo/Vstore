#!/usr/bin/env python3
"""Verify the source-controlled frozen DealEscrow ABI snapshot."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


class FrozenArtifactError(ValueError):
    pass


def verify_frozen_abi(directory: Path) -> dict[str, str]:
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        abi = json.loads((directory / "DealEscrow.abi.json").read_bytes())
        canonical_abi = json.dumps(abi, separators=(",", ":"), ensure_ascii=False).encode()
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FrozenArtifactError(f"cannot read frozen ABI set: {exc}") from exc

    actual = hashlib.sha256(canonical_abi).hexdigest()
    expected = manifest.get("abi_compact_sha256")
    if not isinstance(expected, str) or actual != expected:
        raise FrozenArtifactError(f"ABI SHA-256 mismatch: expected {expected!r}, got {actual}")
    if abi.get("contract_name") != "DealEscrow" or abi.get("version") != "1.0.0":
        raise FrozenArtifactError("unexpected ABI contract identity/version")
    if abi.get("compiler_name") != "tolk" or abi.get("compiler_version") != manifest.get("tolk_version"):
        raise FrozenArtifactError("ABI compiler metadata does not match manifest")
    if manifest.get("contract") != "DealEscrow" or manifest.get("network_scope") != "TON testnet only":
        raise FrozenArtifactError("manifest contract or network scope is invalid")
    return {"abi_compact_sha256": actual, "source_commit": str(manifest.get("source_commit"))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "directory", nargs="?", type=Path,
        default=Path(__file__).resolve().parents[1] / "artifacts" / "frozen",
    )
    args = parser.parse_args()
    try:
        result = verify_frozen_abi(args.directory)
    except FrozenArtifactError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("PASS: source-controlled DealEscrow ABI matches frozen manifest")
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
