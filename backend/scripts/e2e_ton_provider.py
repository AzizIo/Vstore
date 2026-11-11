"""Local deterministic TON Center v3 fixture for API-backed E2E tests.

This server is only started by the isolated GitHub Actions E2E job. It binds to
loopback and never forwards requests to a public TON provider.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

E2E_SELLER_WALLET_ADDRESS = "0:" + "11" * 32
E2E_NFT_ITEM_ADDRESS = "0:" + "22" * 32
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

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        if parsed.path != "/api/v3/nft/items":
            self.send_error(404)
            return

        query = parse_qs(parsed.query)
        by_address = query.get("address") == [E2E_NFT_ITEM_ADDRESS]
        by_owner = query.get("owner_address") == [E2E_SELLER_WALLET_ADDRESS]
        rows = [_item()] if by_address or by_owner else []
        body = json.dumps({"nft_items": rows}).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

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
