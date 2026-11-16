from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import unittest
import zlib
from pathlib import Path

from canonical_zlib_boc import canonical_zlib_boc
from verify_build_matches_manifest import verify_build


class CanonicalZlibBocTests(unittest.TestCase):
    def test_small_vector_is_byte_exact_and_valid_zlib(self) -> None:
        encoded = canonical_zlib_boc(b"abc")
        self.assertEqual(encoded.hex(), "7801010300fcff616263024d0127")
        self.assertEqual(zlib.decompress(encoded), b"abc")

    def test_empty_input_is_valid(self) -> None:
        self.assertEqual(zlib.decompress(canonical_zlib_boc(b"")), b"")

    def test_multiple_stored_blocks_round_trip(self) -> None:
        payload = bytes(range(256)) * 300
        encoded = canonical_zlib_boc(payload)
        self.assertEqual(zlib.decompress(encoded), payload)
        self.assertEqual(encoded, canonical_zlib_boc(payload))
        # The first block is non-final and the second/final block is marked final.
        first_header_offset = 2
        second_header_offset = 2 + 1 + 4 + 65_535
        self.assertEqual(encoded[first_header_offset], 0x00)
        self.assertEqual(encoded[second_header_offset], 0x01)


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
            "compiled_code_boc_zlib_sha256": hashlib.sha256(canonical_zlib_boc(boc)).hexdigest(),
        }))

    def test_accepts_matching_compiler_output_and_all_boc_forms(self) -> None:
        result = verify_build(self.build_path, self.manifest_path)
        self.assertEqual(result["compiled_code_hash"], "ABCD")
        self.assertEqual(
            result["compiled_code_boc_zlib_sha256"],
            hashlib.sha256(canonical_zlib_boc(b"compiled-code-boc")).hexdigest(),
        )

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

    def test_rejects_wrong_canonical_zlib_digest(self) -> None:
        manifest = json.loads(self.manifest_path.read_text())
        manifest["compiled_code_boc_zlib_sha256"] = "0" * 64
        self.manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "canonical zlib digest mismatch"):
            verify_build(self.build_path, self.manifest_path)


if __name__ == "__main__":
    unittest.main()
