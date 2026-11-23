import asyncio

import httpx

from app.main import app


def request(method: str, path: str, **kwargs) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(send())


def test_root_health_check() -> None:
    response = request("GET", "/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers.get("x-request-id")


def test_versioned_health_check() -> None:
    response = request("GET", "/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_swagger_openapi_is_available() -> None:
    docs = request("GET", "/docs")
    schema = request("GET", "/openapi.json")

    assert docs.status_code == 200
    assert "Swagger UI" in docs.text
    assert schema.status_code == 200
    assert "/api/v1/health" in schema.json()["paths"]


def test_http_errors_use_consistent_json_envelope() -> None:
    response = request("GET", "/route-that-does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "http_error"
    assert response.json()["error"]["message"] == "Not Found"
    assert response.json()["request_id"] == response.headers["x-request-id"]


def test_cors_allows_configured_frontend_origin() -> None:
    response = request(
        "OPTIONS",
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
