from __future__ import annotations

from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.core.error_responses import (
    localize_http_detail,
    request_validation_exception_handler,
)
from app.main import app


def test_unknown_http_exception_detail_uses_safe_russian_fallback() -> None:
    secret_error = "Database password=do-not-return; raw provider response"
    assert localize_http_detail(secret_error, 502) == (
        "Внешний сервис вернул некорректный ответ. Попробуйте позже."
    )


def test_known_wallet_error_is_localized_without_changing_status() -> None:
    assert localize_http_detail("Invalid or expired wallet proof", 401) == (
        "Подтверждение TON-кошелька недействительно или устарело. Начните проверку заново."
    )


def test_readiness_response_keeps_its_machine_contract() -> None:
    detail = {
        "status": "not_ready",
        "checks": {
            "database": False,
            "redis": True,
            "authentication": False,
            "ton_connect_proof": "ok",
            "ton_connect_proof_domains": ["shop.example.test"],
            "connection_string": "postgres://user:password@internal",
        },
        "secret": "must-not-leak",
    }
    assert localize_http_detail(detail, 503) == {
        "status": "not_ready",
        "checks": {
            "database": False,
            "redis": True,
            "authentication": False,
            "ton_connect_proof": "ok",
            "ton_connect_proof_domains": ["shop.example.test"],
        },
    }


def test_unhandled_exception_returns_generic_message_without_internal_details() -> None:
    async def fail_with_sensitive_details() -> None:
        raise RuntimeError("password=never-return-this SELECT * FROM private_users")

    route = app.add_api_route(
        "/_test/unhandled-error",
        fail_with_sensitive_details,
        methods=["GET"],
    )
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/_test/unhandled-error")
    finally:
        app.router.routes.remove(route)

    assert response.status_code == 500
    assert response.json() == {
        "detail": "На сервере произошла ошибка. Попробуйте позже."
    }
    assert "never-return-this" not in response.text
    assert "SELECT" not in response.text



async def test_validation_handler_localizes_custom_rule_and_redacts_input_and_context() -> None:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/listings",
            "headers": [],
            "query_string": b"",
            "server": ("test", 80),
            "scheme": "http",
        }
    )
    error = RequestValidationError(
        [
            {
                "type": "value_error",
                "loc": ("body", "expires_at"),
                "msg": "Value error, Expiration must include a timezone",
                "input": "SECRET_PROOF_VALUE",
                "ctx": {"error": ValueError("SECRET_VALIDATOR_CONTEXT")},
            }
        ]
    )

    response = await request_validation_exception_handler(request, error)
    payload = response.body.decode("utf-8")

    assert response.status_code == 422
    assert "SECRET_PROOF_VALUE" not in payload
    assert "SECRET_VALIDATOR_CONTEXT" not in payload
    assert '"input":null' in payload
    assert '"ctx":{}' in payload
    assert "Укажите часовой пояс в дате окончания объявления." in payload
