from fastapi.testclient import TestClient

from app.main import app


def test_cors_allows_configured_local_frontend_origin() -> None:
    with TestClient(app) as client:
        response = client.options(
            "/api/listings",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["access-control-allow-credentials"] == "false"
    assert "GET" in response.headers["access-control-allow-methods"]
    allowed_headers = response.headers["access-control-allow-headers"].lower()
    assert "authorization" in allowed_headers
    assert "content-type" in allowed_headers


def test_cors_rejects_unconfigured_origin() -> None:
    with TestClient(app) as client:
        response = client.options(
            "/api/listings",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_cors_does_not_allow_unlisted_http_methods() -> None:
    with TestClient(app) as client:
        response = client.options(
            "/api/listings",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "PUT",
            },
        )

    assert response.status_code == 400
