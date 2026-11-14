#!/usr/bin/env python3
"""Verify the frozen TON escrow contract artifact before it is consumed.

This validates provenance and file integrity only. It does not establish contract
safety, address derivation correctness, or on-chain finality.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

SOURCE_COMMIT = "2913ea7d53ea7344f57d6503142c08e0b328bc7d"
WORKFLOW_RUN_ID = "43634396094"
ARTIFACT_ID = "14129775225"
EXPECTED_ARCHIVE_SHA256 = "80db85f1dfc91450e6e7e47990bd89bf2ff80e0ecb99d17d8f40a07f33feba58"
EXPECTED_ABI_SHA256 = "05d3bc9b7aafc7fc71889cffc6d4fea2f607ea14aa48f3854c8e432747623597"
EXPECTED_BUILD_SHA256 = "f38b6c867af8ed13d95bc7fed75136961eb97c21290360197ccf9520907ffc3b"
EXPECTED_CODE_HASH = "E9358DAA6FFCC8FCEC979FBD631C7FC0BE336347D1DD44F3F06113E7B2A37548"
ABI_PATH = "build/abi/DealEscrow.json"
BUILD_PATH = "build/DealEscrow.json"


class ArtifactVerificationError(ValueError):
    """The supplied artifact does not match the reviewed frozen baseline."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts and "\\" not in name


def verify_artifact(
    archive_path: Path,
    *,
    expected_archive_sha256: str = EXPECTED_ARCHIVE_SHA256,
    expected_abi_sha256: str = EXPECTED_ABI_SHA256,
    expected_build_sha256: str = EXPECTED_BUILD_SHA256,
    expected_code_hash: str = EXPECTED_CODE_HASH,
) -> dict[str, str]:
    archive_bytes = archive_path.read_bytes()
    actual_archive_sha256 = _sha256(archive_bytes)
    if actual_archive_sha256 != expected_archive_sha256:
        raise ArtifactVerificationError(
            f"archive SHA-256 mismatch: expected {expected_archive_sha256}, "
            f"got {actual_archive_sha256}"
        )

    try:
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ArtifactVerificationError("archive contains duplicate member paths")
            if any(not _safe_member(name) for name in names):
                raise ArtifactVerificationError("archive contains an unsafe member path")
            corrupt_member = archive.testzip()
            if corrupt_member is not None:
                raise ArtifactVerificationError(f"corrupt ZIP member: {corrupt_member}")
            if ABI_PATH not in names or BUILD_PATH not in names:
                raise ArtifactVerificationError("required ABI/build descriptor is missing")
            abi_bytes = archive.read(ABI_PATH)
            build_bytes = archive.read(BUILD_PATH)
    except zipfile.BadZipFile as exc:
        raise ArtifactVerificationError("input is not a valid ZIP archive") from exc

    actual_abi_sha256 = _sha256(abi_bytes)
    if actual_abi_sha256 != expected_abi_sha256:
        raise ArtifactVerificationError(
            f"ABI SHA-256 mismatch: expected {expected_abi_sha256}, got {actual_abi_sha256}"
        )

    actual_build_sha256 = _sha256(build_bytes)
    if actual_build_sha256 != expected_build_sha256:
        raise ArtifactVerificationError(
            "build descriptor SHA-256 mismatch: "
            f"expected {expected_build_sha256}, got {actual_build_sha256}"
        )

    try:
        abi: dict[str, Any] = json.loads(abi_bytes)
        build: dict[str, Any] = json.loads(build_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtifactVerificationError("ABI or build descriptor is not valid JSON") from exc

    if abi.get("contract_name") != "DealEscrow" or abi.get("version") != "1.0.0":
        raise ArtifactVerificationError("unexpected ABI contract identity/version")
    if build.get("hash") != expected_code_hash:
        raise ArtifactVerificationError("compiled contract code hash does not match baseline")
    if not isinstance(build.get("code_boc64"), str) or not build["code_boc64"]:
        raise ArtifactVerificationError("compiled code BOC is missing")

    return {
        "archive_sha256": actual_archive_sha256,
        "abi_sha256": actual_abi_sha256,
        "build_sha256": actual_build_sha256,
        "code_hash": build["hash"],
        "source_commit": SOURCE_COMMIT,
        "workflow_run_id": WORKFLOW_RUN_ID,
        "artifact_id": ARTIFACT_ID,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="downloaded TON escrow artifact ZIP")
    args = parser.parse_args()
    try:
        result = verify_artifact(args.archive)
    except (OSError, ArtifactVerificationError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("PASS: frozen DealEscrow artifact integrity and provenance checks")
    for key, value in result.items():
        print(f"{key}: {value}")
    print("NOTE: this is not an independent contract security review or live testnet acceptance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
