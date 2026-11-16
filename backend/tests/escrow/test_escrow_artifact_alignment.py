from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ARTIFACTS = ROOT / "backend" / "app" / "escrow" / "abi_artifacts"
CONTRACT_MANIFEST = (
    ROOT / "contracts" / "ton-escrow-poc" / "artifacts" / "frozen" / "manifest.json"
)


def test_backend_pin_matches_frozen_tolk_artifact_provenance() -> None:
    """Prevent a green backend adapter from silently targeting another contract build."""
    backend = json.loads((BACKEND_ARTIFACTS / "manifest.json").read_text(encoding="utf-8"))
    contract = json.loads(CONTRACT_MANIFEST.read_text(encoding="utf-8"))

    identity_fields = (
        "contract",
        "protocol_version",
        "network_scope",
        "source_commit",
        "workflow_run_id",
        "artifact_id",
        "original_archive_sha256",
        "abi_original_sha256",
        "build_descriptor_original_sha256",
        "compiled_code_hash",
        "compiled_code_boc_base64_sha256",
        "compiled_code_boc_sha256",
        "compiled_code_boc_zlib_sha256",
        "abi_compact_sha256",
        "acton_version",
        "tolk_version",
        "state_init_hash",
        "raw_address",
        "data_hash",
    )
    mismatches = {
        field: (backend.get(field), contract.get(field))
        for field in identity_fields
        if backend.get(field) != contract.get(field)
    }
    assert not mismatches, (
        "Backend DealEscrow pin and frozen Tolk artifact are from different builds: "
        f"{mismatches}"
    )

    assert backend["contract"] == "DealEscrow"
    assert backend["network_scope"] == "TON testnet only"
    assert backend.get("warning") is None
    assert contract.get("warning") is None

    for field in (
        "original_archive_sha256",
        "abi_original_sha256",
        "build_descriptor_original_sha256",
        "compiled_code_boc_base64_sha256",
        "compiled_code_boc_sha256",
        "compiled_code_boc_zlib_sha256",
        "abi_compact_sha256",
        "state_init_hash",
        "data_hash",
    ):
        value = backend.get(field)
        assert isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value), (
            f"{field} must be a populated SHA-256 digest"
        )

    source_commit = backend.get("source_commit")
    assert isinstance(source_commit, str) and re.fullmatch(r"[0-9a-f]{40}", source_commit)
    assert isinstance(backend.get("workflow_run_id"), int) and backend["workflow_run_id"] > 0
    assert isinstance(backend.get("artifact_id"), int) and backend["artifact_id"] > 0
    assert backend["raw_address"] == f"0:{backend['state_init_hash']}"

    compiler_boc_path = BACKEND_ARTIFACTS / "DealEscrow.code.boc.b64"
    compiler_boc_b64 = compiler_boc_path.read_text(encoding="ascii").strip()
    raw_boc = base64.b64decode(compiler_boc_b64, validate=True)
    assert base64.b64encode(raw_boc).decode("ascii") == compiler_boc_b64
    assert (
        hashlib.sha256(compiler_boc_b64.encode("ascii")).hexdigest()
        == backend["compiled_code_boc_base64_sha256"]
    )
    assert hashlib.sha256(raw_boc).hexdigest() == backend["compiled_code_boc_sha256"]
