#!/usr/bin/env python3
"""Read-only HTTP/TLS probes. Does not follow redirects or emit response content."""
from __future__ import annotations

import argparse
import socket
import ssl
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlsplit
from urllib.request import HTTPHandler, HTTPSHandler, HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def safe_url(url: str) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return False
    sensitive = {"token", "secret", "password", "api_key", "apikey", "auth", "authorization"}
    return not any(key.lower() in sensitive for key, _ in parse_qsl(parsed.query, keep_blank_values=True))


def http_probe(label: str, url: str) -> bool:
    if not safe_url(url):
        print(f"{label}: FAIL invalid/credential-bearing URL")
        return False
    started = time.monotonic()
    opener = build_opener(NoRedirect(), HTTPHandler(), HTTPSHandler(context=ssl.create_default_context()))
    try:
        response = opener.open(Request(url, method="GET", headers={"User-Agent": "viltara-monitoring-probe/1.0"}), timeout=5)
        status, ok = response.status, 200 <= response.status < 300
        response.close()
    except HTTPError as exc:
        status, ok = exc.code, False
        exc.close()
    except (URLError, TimeoutError, OSError):
        status, ok = "unreachable", False
    print(f"{label}: {'OK' if ok else 'FAIL'} status={status} latency_ms={int((time.monotonic()-started)*1000)}")
    return ok


def tls_probe(host: str, port: int) -> bool:
    try:
        raw = socket.create_connection((host, port), timeout=5)
        with ssl.create_default_context().wrap_socket(raw, server_hostname=host) as conn:
            expiry_text = conn.getpeercert()["notAfter"]
        expiry = datetime.strptime(expiry_text, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
        days = (expiry - datetime.now(timezone.utc)).total_seconds() / 86400
        state = "OK" if days >= 21 else "EXPIRING" if days > 0 else "EXPIRED"
        print(f"TLS: {state} days_remaining={days:.1f}")
        return days > 0
    except (OSError, ssl.SSLError, KeyError, ValueError):
        print("TLS: FAIL certificate probe unsuccessful")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api")
    parser.add_argument("--miniapp")
    parser.add_argument("--tls-host")
    parser.add_argument("--tls-port", type=int, default=443)
    args = parser.parse_args()
    checks = []
    if args.api:
        checks.append(http_probe("API readiness", args.api))
    if args.miniapp:
        checks.append(http_probe("Mini App", args.miniapp))
    if args.tls_host:
        checks.append(tls_probe(args.tls_host, args.tls_port))
    if not checks:
        parser.error("provide an explicit --api, --miniapp or --tls-host target")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
