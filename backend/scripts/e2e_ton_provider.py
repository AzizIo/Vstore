"""Local deterministic TON Center v3 fixture for API-backed E2E tests.

This server is only started by the isolated GitHub Actions E2E job. It binds to
loopback and never forwards requests to a public TON provider.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

E2E_SELLER_WALLET_ADDRESS = "0:" + "11" * 32
E2E_BUYER_WALLET_ADDRESS = "0:" + "33" * 32
E2E_NFT_ITEM_ADDRESS = "0:" + "22" * 32
_delivery_lock = threading.Lock()
_delivery_fixture: dict[str, object] | None = None
E2E_SELLER_TELEGRAM_ID = 990000001
E2E_BUYER_TELEGRAM_ID = 990000002
E2E_NFT_NAME = "E2E Verified NFT"


def _item() -> dict[str, object]:
    return {
        "address": E2E_NFT_ITEM_ADDRESS,
        "owner_address": E2E_SELLER_WALLET_ADDRESS,
        "index": 0,
        "init": True,
        "collection_address": None,
        "content": {
            "metadata": {
                "name": E2E_NFT_NAME,
                "description": "Deterministic NFT fixture served only inside API-backed E2E CI.",
            }
        },
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "ViltaraE2ETONFixture/1.0"

    def _send_json(self, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        global _delivery_fixture
        parsed = urlsplit(self.path)
        if parsed.path != "/__e2e__/delivery":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 16_384:
                self.send_error(413)
                return
            payload = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError):
            self.send_error(400)
            return
        required = ("item_address", "seller_address", "buyer_address", "query_id")
        if not isinstance(payload, dict) or any(key not in payload for key in required):
            self.send_error(400)
            return
        if not isinstance(payload["query_id"], str) or not payload["query_id"].isdecimal():
            self.send_error(400)
            return
        with _delivery_lock:
            _delivery_fixture = {
                "item_address": str(payload["item_address"]),
                "seller_address": str(payload["seller_address"]),
                "buyer_address": str(payload["buyer_address"]),
                "query_id": int(payload["query_id"]),
                "transaction_hash": "ab" * 32,
                "trace_id": "cd" * 32,
            }
        self._send_json({"configured": True})

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query)

        if parsed.path == "/api/v3/nft/items":
            by_address = query.get("address") == [E2E_NFT_ITEM_ADDRESS]
            by_owner = query.get("owner_address") == [E2E_SELLER_WALLET_ADDRESS]
            self._send_json({"nft_items": [_item()] if by_address or by_owner else []})
            return

        with _delivery_lock:
            fixture = dict(_delivery_fixture) if _delivery_fixture is not None else None
        if parsed.path == "/api/v3/nft/transfers":
            if fixture and query.get("item_address") == [fixture["item_address"]] and query.get("owner_address") == [fixture["seller_address"]]:
                row = {
                    "nft_address": fixture["item_address"],
                    "query_id": str(fixture["query_id"]),
                    "transaction_hash": fixture["transaction_hash"],
                    "trace_id": fixture["trace_id"],
                    "old_owner": fixture["seller_address"],
                    "new_owner": fixture["buyer_address"],
                    "transaction_aborted": False,
                }
                self._send_json({"nft_transfers": [row]})
            else:
                self._send_json({"nft_transfers": []})
            return

        if parsed.path == "/api/v3/traces":
            if fixture and query.get("trace_id") == [fixture["trace_id"]]:
                item_transaction = {
                    "account": fixture["item_address"],
                    "hash": fixture["transaction_hash"],
                    "in_msg": {
                        "source": fixture["seller_address"],
                        "destination": fixture["item_address"],
                        "opcode": "0x5fcc3d14",
                    },
                    "description": {
                        "aborted": False,
                        "compute_ph": {"success": True},
                        "action": {"success": True},
                    },
                }
                self._send_json({
                    "traces": [{
                        "trace_id": fixture["trace_id"],
                        "is_incomplete": False,
                        "mc_seqno_end": 123456,
                        "actions": [{"transactions_full": [item_transaction]}],
                    }]
                })
            else:
                self._send_json({"traces": []})
            return

        self.send_error(404)

    def log_message(self, format: str, *args: object) -> None:
        # Keep routine fixture traffic out of CI logs.
        return


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 8999), Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
