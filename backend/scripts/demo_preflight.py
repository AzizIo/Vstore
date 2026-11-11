#!/usr/bin/env python3
"""Check public VILTARA deployment endpoints before a live product demo.

This is a read-only network check. It never reads .env, prints response bodies,
or sends credentials. Run it from a laptop or any host with outbound HTTPS.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class HttpResult:
    status: int
    content_type: str
    body: bytes
    final_url: str


def _origin(value: str, label: str) -> str:
    parsed = urlsplit(value.strip())
    if not parsed.scheme or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError(f"{label} must be an absolute URL without credentials.")
    is_local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (is_local and parsed.scheme == "http"):
        raise ValueError(f"{label} must use HTTPS (HTTP is allowed only for localhost).")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError(f"{label} must contain only the origin, without path or query.")
    return f"{parsed.scheme}://{parsed.netloc}"


def _content_type(headers: Any) -> str:
    getter = getattr(headers, "get_content_type", None)
    if callable(getter):
        return str(getter()).lower()
    return str(headers.get("Content-Type", "")).split(";", 1)[0].strip().lower()


def _get(url: str, timeout: float) -> HttpResult:
    request = Request(url, headers={"User-Agent": "VILTARA-Demo-Preflight/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise ValueError("Response exceeded the 2 MiB safety limit.")
            return HttpResult(
                status=int(response.status),
                content_type=_content_type(response.headers),
                body=body,
                final_url=str(response.geturl()),
            )
    except HTTPError as error:
        body = error.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            body = b""
        return HttpResult(
            status=int(error.code),
            content_type=_content_type(error.headers),
            body=body,
            final_url=str(error.geturl()),
        )
    except OSError as error:
        raise RuntimeError("The endpoint could not be reached.") from error


def _same_origin(final_url: str, expected_origin: str) -> bool:
    try:
        parsed = urlsplit(final_url)
        return f"{parsed.scheme}://{parsed.netloc}" == expected_origin
    except ValueError:
        return False


def run_preflight(
    api_url: str,
    mini_app_url: str,
    manifest_url: str | None = None,
    *,
    timeout: float = 8.0,
) -> list[CheckResult]:
    api_origin = _origin(api_url, "API URL")
    app_origin = _origin(mini_app_url, "Mini App URL")
    expected_manifest_url = f"{app_origin}/tonconnect-manifest.json"
    manifest_target = manifest_url or expected_manifest_url
    parsed_manifest = urlsplit(manifest_target)
    if (
        f"{parsed_manifest.scheme}://{parsed_manifest.netloc}" != app_origin
        or parsed_manifest.path != "/tonconnect-manifest.json"
        or parsed_manifest.query
        or parsed_manifest.fragment
    ):
        raise ValueError("Manifest URL must be /tonconnect-manifest.json on the Mini App origin.")

    checks: list[CheckResult] = []

    # API readiness includes database, Redis and the authentication configuration.
    try:
        health = _get(f"{api_origin}/api/health/ready", timeout)
        if health.content_type != "application/json":
            checks.append(CheckResult("API readiness", False, f"Expected JSON; got HTTP {health.status} {health.content_type or 'unknown content type'}."))
        elif not _same_origin(health.final_url, api_origin):
            checks.append(CheckResult("API readiness", False, "Readiness endpoint redirected to a different origin."))
        else:
            try:
                payload = json.loads(health.body)
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload = {}
            components = payload.get("checks", {}) if isinstance(payload, dict) else {}
            required = ("database", "redis", "authentication")
            missing_or_failed = [name for name in required if components.get(name) != "ok"]
            ready = health.status == 200 and isinstance(payload, dict) and payload.get("status") == "ready" and not missing_or_failed
            if ready:
                checks.append(CheckResult("API readiness", True, "API, database, Redis and authentication are ready."))
            else:
                failed = ", ".join(missing_or_failed) or "overall readiness"
                checks.append(CheckResult("API readiness", False, f"API is not ready (HTTP {health.status}): {failed}."))
    except (RuntimeError, ValueError) as error:
        checks.append(CheckResult("API readiness", False, str(error)))

    # The root document must be served as HTML from the expected app origin.
    try:
        app = _get(f"{app_origin}/", timeout)
        ok = (
            app.status == 200
            and app.content_type == "text/html"
            and bool(app.body.strip())
            and _same_origin(app.final_url, app_origin)
        )
        detail = "Mini App entry page is reachable." if ok else f"Expected HTTP 200 HTML on the same origin; got HTTP {app.status} {app.content_type or 'unknown content type'}."
        checks.append(CheckResult("Mini App page", ok, detail))
    except (RuntimeError, ValueError) as error:
        checks.append(CheckResult("Mini App page", False, str(error)))

    # Manifest and icon must be the public build artifacts expected by TON Connect.
    manifest_ok = False
    icon_url = f"{app_origin}/tonconnect-icon.png"
    try:
        manifest = _get(manifest_target, timeout)
        if manifest.status != 200 or manifest.content_type != "application/json":
            detail = f"Expected HTTP 200 JSON; got HTTP {manifest.status} {manifest.content_type or 'unknown content type'}."
        elif not _same_origin(manifest.final_url, app_origin):
            detail = "Manifest redirected to a different origin."
        else:
            try:
                payload = json.loads(manifest.body)
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            manifest_ok = (
                payload.get("url") == app_origin
                and payload.get("iconUrl") == icon_url
            )
            detail = (
                "Manifest origin and icon URL match the deployed Mini App."
                if manifest_ok
                else "Manifest URL/iconUrl do not match the deployed Mini App origin."
            )
            if manifest_ok:
                icon_url = str(payload["iconUrl"])
        checks.append(CheckResult("TON Connect manifest", manifest_ok, detail))
    except (RuntimeError, ValueError) as error:
        checks.append(CheckResult("TON Connect manifest", False, str(error)))

    if manifest_ok:
        try:
            icon = _get(icon_url, timeout)
            ok = (
                icon.status == 200
                and icon.content_type == "image/png"
                and icon.body.startswith(PNG_SIGNATURE)
                and _same_origin(icon.final_url, app_origin)
            )
            detail = "TON Connect icon is a valid PNG served from the Mini App origin." if ok else f"Expected HTTP 200 PNG on the same origin; got HTTP {icon.status} {icon.content_type or 'unknown content type'}."
            checks.append(CheckResult("TON Connect icon", ok, detail))
        except (RuntimeError, ValueError) as error:
            checks.append(CheckResult("TON Connect icon", False, str(error)))
    else:
        checks.append(CheckResult("TON Connect icon", False, "Skipped because the manifest did not validate."))

    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only VILTARA live-demo preflight.")
    parser.add_argument("--api-url", required=True, help="Public API origin, for example https://api.example.com")
    parser.add_argument("--mini-app-url", required=True, help="Public Mini App origin, for example https://shop.example.com")
    parser.add_argument("--manifest-url", help="Optional manifest URL; defaults to <Mini App origin>/tonconnect-manifest.json")
    parser.add_argument("--timeout", type=float, default=8.0, help="Per-request timeout in seconds (default: 8)")
    args = parser.parse_args()

    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero.")

    try:
        checks = run_preflight(
            args.api_url,
            args.mini_app_url,
            args.manifest_url,
            timeout=args.timeout,
        )
    except ValueError as error:
        parser.error(str(error))

    for check in checks:
        marker = "PASS" if check.ok else "FAIL"
        print(f"[{marker}] {check.name}: {check.detail}")

    passed = sum(check.ok for check in checks)
    print(f"\nDemo preflight: {passed}/{len(checks)} checks passed.")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
