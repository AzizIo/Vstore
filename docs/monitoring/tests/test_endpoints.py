from __future__ import annotations

import importlib.util
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("check_endpoints", ROOT / "scripts/check_endpoints.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.end_headers()
        elif self.path == "/ok":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"fixture-body")
        else:
            self.send_response(503)
            self.end_headers()

    def log_message(self, fmt, *args):
        pass


class EndpointProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=2)
        cls.server.server_close()

    def test_plain_local_url_is_allowed(self):
        self.assertTrue(MODULE.safe_url(self.base + "/ok"))

    def test_userinfo_credentials_are_rejected(self):
        self.assertFalse(MODULE.safe_url("https://user:password@example.invalid/"))

    def test_sensitive_query_parameter_is_rejected(self):
        self.assertFalse(MODULE.safe_url(self.base + "/ok?token=dummy"))

    def test_success_status_passes(self):
        self.assertTrue(MODULE.http_probe("fixture", self.base + "/ok"))

    def test_server_error_fails(self):
        self.assertFalse(MODULE.http_probe("fixture", self.base + "/unhealthy"))

    def test_redirect_is_not_followed(self):
        self.assertFalse(MODULE.http_probe("fixture", self.base + "/redirect"))


if __name__ == "__main__":
    unittest.main()
