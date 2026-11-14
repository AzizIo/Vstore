from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from verify_frozen_files import FrozenArtifactError, verify_frozen_abi


class VerifyFrozenAbiTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        abi = {
            "contract_name": "DealEscrow",
            "version": "1.0.0",
            "compiler_name": "tolk",
            "compiler_version": "1.5.0",
        }
        abi_bytes = json.dumps(abi, separators=(",", ":"), ensure_ascii=False).encode()
        manifest = {
            "contract": "DealEscrow",
            "network_scope": "TON testnet only",
            "source_commit": "test-source",
            "tolk_version": "1.5.0",
            "abi_compact_sha256": hashlib.sha256(abi_bytes).hexdigest(),
        }
        (self.directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (self.directory / "DealEscrow.abi.json").write_bytes(abi_bytes)

    def test_accepts_matching_frozen_abi(self) -> None:
        result = verify_frozen_abi(self.directory)
        self.assertEqual(result["source_commit"], "test-source")

    def test_rejects_modified_abi(self) -> None:
        (self.directory / "DealEscrow.abi.json").write_text('{"contract_name":"Other"}', encoding="utf-8")
        with self.assertRaisesRegex(FrozenArtifactError, "ABI SHA-256 mismatch"):
            verify_frozen_abi(self.directory)

    def test_rejects_wrong_contract_identity_even_with_matching_digest(self) -> None:
        abi = {"contract_name": "Other", "version": "1.0.0", "compiler_name": "tolk", "compiler_version": "1.5.0"}
        data = json.dumps(abi, separators=(",", ":")).encode()
        (self.directory / "DealEscrow.abi.json").write_bytes(data)
        manifest = json.loads((self.directory / "manifest.json").read_text())
        manifest["abi_compact_sha256"] = hashlib.sha256(data).hexdigest()
        (self.directory / "manifest.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(FrozenArtifactError, "unexpected ABI contract"):
            verify_frozen_abi(self.directory)


if __name__ == "__main__":
    unittest.main()
