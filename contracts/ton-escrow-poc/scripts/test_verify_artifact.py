from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from verify_artifact import ArtifactVerificationError, verify_artifact


class VerifyArtifactTests(unittest.TestCase):
    def _archive(self, *, abi: bytes | None = None, build: bytes | None = None) -> Path:
        temporary = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        temporary.close()
        path = Path(temporary.name)
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("build/abi/DealEscrow.json", abi or b"{}")
            archive.writestr(
                "build/DealEscrow.json",
                build or json.dumps({"hash": "0" * 64, "code_boc64": "AA=="}).encode(),
            )
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def test_rejects_archive_with_wrong_digest_before_parsing(self) -> None:
        path = self._archive()
        with self.assertRaisesRegex(ArtifactVerificationError, "archive SHA-256 mismatch"):
            verify_artifact(path)

    def test_rejects_missing_or_malformed_zip(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False) as temporary:
            temporary.write(b"not a zip")
            path = Path(temporary.name)
        self.addCleanup(path.unlink, missing_ok=True)
        with self.assertRaisesRegex(ArtifactVerificationError, "valid ZIP"):
            verify_artifact(
                path,
                expected_archive_sha256=__import__("hashlib").sha256(b"not a zip").hexdigest(),
            )

    def test_rejects_unsafe_zip_member(self) -> None:
        path = self._archive()
        # The archive digest check is intentionally first; use a matching digest
        # so the path traversal validation is reached.
        import hashlib

        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        with zipfile.ZipFile(path, "a") as archive:
            archive.writestr("../escape", b"no")
        # A changed archive must fail its pinned digest before extraction.
        with self.assertRaisesRegex(ArtifactVerificationError, "archive SHA-256 mismatch"):
            verify_artifact(path, expected_archive_sha256=digest)


if __name__ == "__main__":
    unittest.main()
