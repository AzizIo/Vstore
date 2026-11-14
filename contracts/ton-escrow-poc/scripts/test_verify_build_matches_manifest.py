from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from verify_build_matches_manifest import verify_build


class VerifyBuildMatchesManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        boc = b"compiled-code-boc"
        boc64 = base64.b64encode(boc).decode("ascii")
        self.build_path = self.directory / "build.json"
        self.manifest_path = self.directory / "manifest.json"
        self.build_path.write_text(json.dumps({"hash": "ABCD", "code_boc64": boc64}))
        self.manifest_path.write_text(json.dumps({
            "compiled_code_hash": "ABCD",
            "compiled_code_boc_base64_sha256": hashlib.sha256(boc64.encode()).hexdigest(),
            "compiled_code_boc_sha256": hashlib.sha256(boc).hexdigest(),
        }))

    def test_accepts_matching_compiler_output(self) -> None:
        result = verify_build(self.build_path, self.manifest_path)
        self.assertEqual(result["compiled_code_hash"], "ABCD")

    def test_rejects_changed_compiled_hash(self) -> None:
        build = json.loads(self.build_path.read_text())
        build["hash"] = "DIFFERENT"
        self.build_path.write_text(json.dumps(build))
        with self.assertRaisesRegex(ValueError, "compiled code hash mismatch"):
            verify_build(self.build_path, self.manifest_path)

    def test_rejects_changed_boc(self) -> None:
        build = json.loads(self.build_path.read_text())
        build["code_boc64"] = base64.b64encode(b"other-code").decode()
        self.build_path.write_text(json.dumps(build))
        with self.assertRaisesRegex(ValueError, "compiled BOC base64 digest mismatch"):
            verify_build(self.build_path, self.manifest_path)


if __name__ == "__main__":
    unittest.main()
