from app.orders import refund_worker


def test_refund_worker_uses_telegram_test_api_for_methods_and_files() -> None:
    api = refund_worker._test_api_server()
    token = "123456:test-token"

    assert api.api_url(token, "refundStarPayment") == (
        "https://api.telegram.org/bot123456:test-token/test/refundStarPayment"
    )
    assert api.file_url(token, "documents/example.pdf") == (
        "https://api.telegram.org/file/bot123456:test-token/test/documents/example.pdf"
    )
