from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from verify_artifact import ArtifactVerificationError, verify_artifact


class VerifyArtifactTests(unittest.TestCase):
    def _archive(
        self,
        *,
        abi: bytes | None = None,
        build: bytes | None = None,
        extra_member: tuple[str, bytes] | None = None,
    ) -> Path:
        temporary = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        temporary.close()
        path = Path(temporary.name)
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                "build/abi/DealEscrow.json",
                abi
                or json.dumps({"contract_name": "DealEscrow", "version": "1.0.0"}).encode(),
            )
            archive.writestr(
                "build/DealEscrow.json",
                build
                or json.dumps({"hash": "A" * 64, "code_boc64": "AA=="}).encode(),
            )
            if extra_member is not None:
                archive.writestr(*extra_member)
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def test_accepts_valid_archive_when_all_digests_are_pinned(self) -> None:
        path = self._archive()
        with zipfile.ZipFile(path) as archive:
            abi = archive.read("build/abi/DealEscrow.json")
            build = archive.read("build/DealEscrow.json")
        result = verify_artifact(
            path,
            expected_archive_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            expected_abi_sha256=hashlib.sha256(abi).hexdigest(),
            expected_build_sha256=hashlib.sha256(build).hexdigest(),
            expected_code_hash="A" * 64,
        )
        self.assertEqual(result["code_hash"], "A" * 64)

    def test_rejects_archive_with_wrong_digest_before_parsing(self) -> None:
        with self.assertRaisesRegex(ArtifactVerificationError, "archive SHA-256 mismatch"):
            verify_artifact(self._archive())

    def test_rejects_malformed_zip(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False) as temporary:
            temporary.write(b"not a zip")
            path = Path(temporary.name)
        self.addCleanup(path.unlink, missing_ok=True)
        with self.assertRaisesRegex(ArtifactVerificationError, "valid ZIP"):
            verify_artifact(
                path,
                expected_archive_sha256=hashlib.sha256(b"not a zip").hexdigest(),
            )

    def test_rejects_unsafe_zip_member(self) -> None:
        path = self._archive(extra_member=("../escape", b"no"))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ArtifactVerificationError, "unsafe member path"):
            verify_artifact(path, expected_archive_sha256=digest)

    def test_rejects_duplicate_zip_member(self) -> None:
        path = self._archive()
        with zipfile.ZipFile(path, "a") as archive:
            archive.writestr("build/abi/DealEscrow.json", b"duplicate")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ArtifactVerificationError, "duplicate member paths"):
            verify_artifact(path, expected_archive_sha256=digest)


if __name__ == "__main__":
    unittest.main()
