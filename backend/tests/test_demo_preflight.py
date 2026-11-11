from __future__ import annotations

import json
from email.message import Message
from urllib.request import Request

import pytest

from scripts.demo_preflight import CORS_PROBE_ORIGIN, PNG_SIGNATURE, run_preflight


class FakeResponse:
    def __init__(
        self,
        url: str,
        body: bytes,
        content_type: str,
        access_control_allow_origin: str | None = None,
    ) -> None:
        self.status = 200
        self._url = url
        self._body = body
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        if access_control_allow_origin is not None:
            self.headers["Access-Control-Allow-Origin"] = access_control_allow_origin

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, _size: int = -1) -> bytes:
        return self._body

    def geturl(self) -> str:
        return self._url


def test_demo_preflight_passes_all_public_endpoint_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    api_origin = "https://api.example.test"
    app_origin = "https://shop.example.test"
    manifest_url = f"{app_origin}/tonconnect-manifest.json"
    icon_url = f"{app_origin}/tonconnect-icon.png"
    responses = {
        f"{api_origin}/api/health/ready": FakeResponse(
            f"{api_origin}/api/health/ready",
            json.dumps({
                "status": "ready",
                "checks": {
                    "database": "ok",
                    "redis": "ok",
                    "authentication": "ok",
                    "ton_connect_proof": "ok",
                },
            }).encode(),
            "application/json",
        ),
        f"{app_origin}/": FakeResponse(
            app_origin + "/",
            b"<!doctype html><html><body>VILTARA</body></html>",
            "text/html",
        ),
        manifest_url: FakeResponse(
            manifest_url,
            json.dumps({"url": app_origin, "name": "VILTARA SHOP", "iconUrl": icon_url}).encode(),
            "application/json",
            access_control_allow_origin="*",
        ),
        icon_url: FakeResponse(icon_url, PNG_SIGNATURE + b"demo", "image/png"),
    }
    requested: list[str] = []

    def fake_urlopen(request: Request, timeout: float) -> FakeResponse:
        assert timeout == 3.0
        requested.append(request.full_url)
        if request.full_url == manifest_url:
            assert request.get_header("Origin") == CORS_PROBE_ORIGIN
        else:
            assert request.get_header("Origin") is None
        return responses[request.full_url]

    monkeypatch.setattr("scripts.demo_preflight.urlopen", fake_urlopen)

    checks = run_preflight(api_origin, app_origin, timeout=3.0)

    assert len(checks) == 5
    assert all(check.ok for check in checks)
    assert requested == [
        f"{api_origin}/api/health/ready",
        f"{app_origin}/",
        manifest_url,
        icon_url,
    ]


def test_demo_preflight_fails_when_manifest_does_not_allow_cross_origin_get(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_origin = "https://api.example.test"
    app_origin = "https://shop.example.test"
    manifest_url = f"{app_origin}/tonconnect-manifest.json"
    icon_url = f"{app_origin}/tonconnect-icon.png"
    responses = {
        f"{api_origin}/api/health/ready": FakeResponse(
            f"{api_origin}/api/health/ready",
            json.dumps({
                "status": "ready",
                "checks": {
                    "database": "ok",
                    "redis": "ok",
                    "authentication": "ok",
                    "ton_connect_proof": "ok",
                },
            }).encode(),
            "application/json",
        ),
        f"{app_origin}/": FakeResponse(
            app_origin + "/",
            b"<!doctype html><html><body>VILTARA</body></html>",
            "text/html",
        ),
        manifest_url: FakeResponse(
            manifest_url,
            json.dumps({"url": app_origin, "name": "VILTARA SHOP", "iconUrl": icon_url}).encode(),
            "application/json",
        ),
        icon_url: FakeResponse(icon_url, PNG_SIGNATURE + b"demo", "image/png"),
    }

    monkeypatch.setattr(
        "scripts.demo_preflight.urlopen",
        lambda request, timeout: responses[request.full_url],
    )

    checks = run_preflight(api_origin, app_origin)

    assert all(check.ok for check in checks[:2])
    assert not checks[3].ok
    assert "Access-Control-Allow-Origin" in checks[3].detail
    assert checks[4].ok


def test_demo_preflight_fails_readiness_when_one_dependency_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_origin = "https://api.example.test"
    app_origin = "https://shop.example.test"

    class UnreadyResponse(FakeResponse):
        def __init__(self) -> None:
            super().__init__(
                f"{api_origin}/api/health/ready",
                json.dumps({
                    "detail": {
                        "status": "not_ready",
                        "checks": {
                            "database": "ok",
                            "redis": "error",
                            "authentication": "ok",
                        },
                    },
                }).encode(),
                "application/json",
            )
            self.status = 503

    responses = {
        f"{api_origin}/api/health/ready": UnreadyResponse(),
        f"{app_origin}/": FakeResponse(app_origin + "/", b"<html/>", "text/html"),
        f"{app_origin}/tonconnect-manifest.json": FakeResponse(
            f"{app_origin}/tonconnect-manifest.json",
            json.dumps({
                "url": app_origin,
                "iconUrl": f"{app_origin}/tonconnect-icon.png",
            }).encode(),
            "application/json",
            access_control_allow_origin="*",
        ),
        f"{app_origin}/tonconnect-icon.png": FakeResponse(
            f"{app_origin}/tonconnect-icon.png",
            PNG_SIGNATURE + b"demo",
            "image/png",
        ),
    }

    monkeypatch.setattr(
        "scripts.demo_preflight.urlopen",
        lambda request, timeout: responses[request.full_url],
    )

    checks = run_preflight(api_origin, app_origin)

    assert not checks[0].ok
    assert "redis" in checks[0].detail
    assert all(check.ok for check in checks[1:])


@pytest.mark.parametrize(
    ("value", "label"),
    [
        ("http://market.example.test", "API URL"),
        ("https://user:pass@market.example.test", "API URL"),
        ("https://market.example.test/path", "Mini App URL"),
        ("https://market.example.test/?token=secret", "Mini App URL"),
    ],
)
def test_demo_preflight_rejects_unsafe_or_non_origin_urls(value: str, label: str) -> None:
    api = value if label == "API URL" else "https://api.example.test"
    app = value if label == "Mini App URL" else "https://shop.example.test"

    with pytest.raises(ValueError):
        run_preflight(api, app)


def test_demo_preflight_rejects_manifest_from_another_origin() -> None:
    with pytest.raises(ValueError, match="Manifest URL must be"):
        run_preflight(
            "https://api.example.test",
            "https://shop.example.test",
            "https://attacker.example.test/tonconnect-manifest.json",
        )



def test_demo_preflight_fails_when_backend_wallet_proof_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_origin = "https://api.example.test"
    app_origin = "https://shop.example.test"
    manifest_url = f"{app_origin}/tonconnect-manifest.json"
    icon_url = f"{app_origin}/tonconnect-icon.png"
    responses = {
        f"{api_origin}/api/health/ready": FakeResponse(
            f"{api_origin}/api/health/ready",
            json.dumps({
                "status": "ready",
                "checks": {
                    "database": "ok",
                    "redis": "ok",
                    "authentication": "ok",
                    "ton_connect_proof": "error",
                },
            }).encode(),
            "application/json",
        ),
        f"{app_origin}/": FakeResponse(
            app_origin + "/",
            b"<!doctype html><html><body>VILTARA</body></html>",
            "text/html",
        ),
        manifest_url: FakeResponse(
            manifest_url,
            json.dumps({"url": app_origin, "name": "VILTARA SHOP", "iconUrl": icon_url}).encode(),
            "application/json",
            access_control_allow_origin="*",
        ),
        icon_url: FakeResponse(icon_url, PNG_SIGNATURE + b"demo", "image/png"),
    }

    monkeypatch.setattr(
        "scripts.demo_preflight.urlopen",
        lambda request, timeout: responses[request.full_url],
    )

    checks = run_preflight(api_origin, app_origin)

    assert checks[0].ok
    assert not checks[1].ok
    assert "TON_CONNECT_ALLOWED_DOMAINS" in checks[1].detail
    assert all(check.ok for check in checks[2:])
