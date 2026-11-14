from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from verify_frozen_files import FrozenArtifactError, verify_frozen_artifacts


class VerifyFrozenFilesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        abi = {
            "contract_name": "DealEscrow",
            "version": "1.0.0",
            "compiler_name": "tolk",
            "compiler_version": "1.5.0",
        }
        abi_bytes = json.dumps(abi, separators=(",", ":"), ensure_ascii=False).encode()
        boc = b"frozen-test-boc"
        boc_text = base64.b64encode(boc).decode("ascii")
        manifest = {
            "contract": "DealEscrow",
            "network_scope": "TON testnet only",
            "source_commit": "test-source",
            "compiled_code_hash": "A" * 64,
            "tolk_version": "1.5.0",
            "abi_compact_sha256": hashlib.sha256(abi_bytes).hexdigest(),
            "compiled_code_boc_base64_sha256": hashlib.sha256(boc_text.encode()).hexdigest(),
            "compiled_code_boc_sha256": hashlib.sha256(boc).hexdigest(),
        }
        (self.directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (self.directory / "DealEscrow.abi.json").write_bytes(abi_bytes)
        (self.directory / "DealEscrow.code.boc.base64").write_text(boc_text + "\n", encoding="ascii")

    def test_accepts_matching_frozen_files(self) -> None:
        result = verify_frozen_artifacts(self.directory)
        self.assertEqual(result["compiled_code_hash"], "A" * 64)

    def test_rejects_modified_boc(self) -> None:
        (self.directory / "DealEscrow.code.boc.base64").write_text("ZmFrZQ==\n", encoding="ascii")
        with self.assertRaisesRegex(FrozenArtifactError, "compiled_code_boc_base64_sha256 mismatch"):
            verify_frozen_artifacts(self.directory)

    def test_rejects_modified_abi(self) -> None:
        (self.directory / "DealEscrow.abi.json").write_text('{"contract_name":"Other"}', encoding="utf-8")
        with self.assertRaisesRegex(FrozenArtifactError, "abi_compact_sha256 mismatch"):
            verify_frozen_artifacts(self.directory)

    def test_rejects_invalid_base64(self) -> None:
        (self.directory / "DealEscrow.code.boc.base64").write_text("not base64!", encoding="ascii")
        with self.assertRaisesRegex(FrozenArtifactError, "invalid ABI JSON or BOC base64"):
            verify_frozen_artifacts(self.directory)


if __name__ == "__main__":
    unittest.main()
