import asyncio
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx
import pytest

from app.api.dependencies.auth import get_app_settings, get_authenticated_user, get_current_admin_user
from app.api.v1 import admin as admin_api
import app.services.activation_issuance as activation_module
from app.core.config import Settings
from app.main import app
from app.services.activation_issuance import (
    ACTIVATION_TTL,
    ActivationConfigurationError,
    ActivationEmailDeliveryError,
    ActivationProfileIneligibleError,
    ActivationRevocationError,
    ActivationIssuanceService,
)
from app.services.supabase_jwt import AuthenticatedUser

TEST_CODE = "test-only-random-code-value"
TEST_SERVICE_KEY = "test-only-service-role-value"
TEST_RESEND_KEY = "test-only-resend-value"
TEST_USER_ID = uuid4()
TEST_RECORD_ID = uuid4()
FIXED_NOW = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "supabase_url": "https://project.example.test",
        "supabase_service_role_key": TEST_SERVICE_KEY,
        "resend_api_key": TEST_RESEND_KEY,
        "matrix_email_from": "MATRIX <matrix@example.test>",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _service(
    *,
    profile_status: str = "approved",
    activation_completed_at: str | None = None,
    resend_status: int = 202,
    revoke_status: int = 200,
    settings: Settings | None = None,
) -> tuple[ActivationIssuanceService, list[httpx.Request], dict[str, object]]:
    requests: list[httpx.Request] = []
    state: dict[str, object] = {"rpc_payload": None, "generated_size": None}

    async def supabase_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/rest/v1/profiles"):
            return httpx.Response(
                200,
                json=[{
                    "id": str(TEST_USER_ID),
                    "access_status": profile_status,
                    "activation_completed_at": activation_completed_at,
                }],
            )
        if "/auth/v1/admin/users/" in request.url.path:
            assert request.url.path.endswith(str(TEST_USER_ID))
            return httpx.Response(200, json={"id": str(TEST_USER_ID), "email": "trusted-user@example.test"})
        if request.url.path.endswith("/rpc/issue_matrix_activation_code"):
            state["rpc_payload"] = json.loads(request.content)
            return httpx.Response(200, json=str(TEST_RECORD_ID))
        if request.url.path.endswith("/rest/v1/activation_codes") and request.method == "PATCH":
            if revoke_status >= 400:
                return httpx.Response(revoke_status, json={"message": "private test failure"})
            return httpx.Response(200, json=[{"id": str(TEST_RECORD_ID)}])
        raise AssertionError("Unexpected mocked Supabase request")

    async def resend_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if resend_status >= 400:
            return httpx.Response(resend_status, json={"message": "private test failure"})
        return httpx.Response(resend_status, json={"id": "test-email-id"})

    supabase_client = httpx.AsyncClient(transport=httpx.MockTransport(supabase_handler))
    resend_client = httpx.AsyncClient(transport=httpx.MockTransport(resend_handler))

    def code_factory(size: int) -> str:
        state["generated_size"] = size
        return TEST_CODE

    service = ActivationIssuanceService(
        settings or _settings(),
        supabase_client=supabase_client,
        resend_client=resend_client,
        code_factory=code_factory,
        clock=lambda: FIXED_NOW,
    )
    service.test_clients = (supabase_client, resend_client)
    return service, requests, state


def test_issuance_hashes_secure_code_sets_expiry_calls_rpc_and_emails_plaintext() -> None:
    service, requests, state = _service()

    async def run() -> datetime:
        async with service.test_clients[0], service.test_clients[1]:
            return await service.issue(user_id=TEST_USER_ID)

    expires_at = asyncio.run(run())
    assert state["generated_size"] == 32
    assert expires_at == FIXED_NOW + timedelta(days=7)
    assert expires_at - FIXED_NOW == ACTIVATION_TTL

    rpc = next(request for request in requests if request.url.path.endswith("/rpc/issue_matrix_activation_code"))
    rpc_payload = json.loads(rpc.content)
    expected_hash = hashlib.sha256(TEST_CODE.encode("utf-8")).hexdigest()
    assert re.fullmatch(r"[0-9a-f]{64}", rpc_payload["p_code_hash"])
    assert rpc_payload["p_code_hash"] == expected_hash
    assert rpc_payload["p_user_id"] == str(TEST_USER_ID)
    assert rpc_payload["p_expires_at"] == expires_at.isoformat()
    assert not any(
        request.method == "POST" and request.url.path.endswith("/rest/v1/activation_codes")
        for request in requests
    )

    email_request = next(request for request in requests if request.url.host == "api.resend.com")
    email_payload = json.loads(email_request.content)
    assert email_request.headers["authorization"] == f"Bearer {TEST_RESEND_KEY}"
    assert email_payload["to"] == ["trusted-user@example.test"]
    assert email_payload["from"] == "MATRIX <matrix@example.test>"
    assert TEST_CODE in email_payload["text"]
    assert expected_hash not in email_payload["text"]

    db_payloads = [json.loads(r.content) for r in requests if r.url.host == "project.example.test" and r.content]
    assert all(TEST_CODE not in json.dumps(payload) for payload in db_payloads)
    assert all(TEST_CODE not in str(r.url) for r in requests)


def test_ineligible_profile_is_rejected_before_auth_lookup_or_issuance() -> None:
    service, requests, _ = _service(profile_status="rejected")

    async def run() -> None:
        async with service.test_clients[0], service.test_clients[1]:
            with pytest.raises(ActivationProfileIneligibleError):
                await service.issue(user_id=TEST_USER_ID)

    asyncio.run(run())
    assert len(requests) == 1
    assert requests[0].url.path.endswith("/rest/v1/profiles")


def test_default_code_generator_uses_secrets_with_256_bits_requested(monkeypatch) -> None:
    calls: list[int] = []

    def fake_token_urlsafe(number_of_bytes: int) -> str:
        calls.append(number_of_bytes)
        return TEST_CODE

    monkeypatch.setattr(activation_module.secrets, "token_urlsafe", fake_token_urlsafe)
    service = ActivationIssuanceService(_settings())
    assert service._code_factory(32) == TEST_CODE
    assert calls == [32]


def test_already_activated_profile_is_rejected_before_issuance() -> None:
    service, requests, _ = _service(activation_completed_at=FIXED_NOW.isoformat())

    async def run() -> None:
        async with service.test_clients[0], service.test_clients[1]:
            with pytest.raises(ActivationProfileIneligibleError):
                await service.issue(user_id=TEST_USER_ID)

    asyncio.run(run())
    assert len(requests) == 1


def test_missing_email_configuration_blocks_before_database_access() -> None:
    service, requests, _ = _service(settings=_settings(resend_api_key=None))

    async def run() -> None:
        async with service.test_clients[0], service.test_clients[1]:
            with pytest.raises(ActivationConfigurationError):
                await service.issue(user_id=TEST_USER_ID)

    asyncio.run(run())
    assert requests == []


def test_resend_failure_revokes_new_code_and_does_not_leak_plaintext_or_hash() -> None:
    service, requests, state = _service(resend_status=500)
    expected_hash = hashlib.sha256(TEST_CODE.encode("utf-8")).hexdigest()

    async def run() -> None:
        async with service.test_clients[0], service.test_clients[1]:
            with pytest.raises(ActivationEmailDeliveryError) as caught:
                await service.issue(user_id=TEST_USER_ID)
            assert TEST_CODE not in str(caught.value)
            assert expected_hash not in str(caught.value)

    asyncio.run(run())
    assert state["rpc_payload"] is not None
    revoke = next(request for request in requests if request.method == "PATCH")
    assert revoke.url.path.endswith("/rest/v1/activation_codes")
    assert revoke.url.params["id"] == f"eq.{TEST_RECORD_ID}"
    assert revoke.url.params["user_id"] == f"eq.{TEST_USER_ID}"
    assert json.loads(revoke.content).keys() == {"revoked_at"}
    assert "used_at" not in json.loads(revoke.content)


def test_resend_and_revocation_failure_reports_failure_without_exposing_code() -> None:
    service, requests, _ = _service(resend_status=500, revoke_status=500)
    expected_hash = hashlib.sha256(TEST_CODE.encode("utf-8")).hexdigest()

    async def run() -> None:
        async with service.test_clients[0], service.test_clients[1]:
            with pytest.raises(ActivationRevocationError) as caught:
                await service.issue(user_id=TEST_USER_ID)
            assert TEST_CODE not in str(caught.value)
            assert expected_hash not in str(caught.value)

    asyncio.run(run())
    assert any(request.method == "PATCH" for request in requests)


def test_non_admin_endpoint_denies_before_issuance_service_is_constructed(monkeypatch) -> None:
    admin_id = UUID("00000000-0000-4000-8000-000000000001")

    async def non_admin() -> AuthenticatedUser:
        return AuthenticatedUser(uuid4(), "test-token")

    class MustNotIssue:
        def __init__(self, _settings: Settings) -> None:
            raise AssertionError("issuance service must not be constructed for non-admin")

    app.dependency_overrides[get_authenticated_user] = non_admin
    app.dependency_overrides[get_app_settings] = lambda: _settings(matrix_admin_user_id=str(admin_id))
    monkeypatch.setattr(admin_api, "ActivationIssuanceService", MustNotIssue)

    async def run() -> httpx.Response:
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
            ) as client:
                return await client.post(f"/api/v1/admin/profiles/{TEST_USER_ID}/activation-code")
        finally:
            app.dependency_overrides.pop(get_authenticated_user, None)
            app.dependency_overrides.pop(get_app_settings, None)

    response = asyncio.run(run())
    assert response.status_code == 403
    assert response.json()["error"]["message"] == "Administrator authorization required."


def test_successful_endpoint_response_contains_no_plaintext_or_hash(monkeypatch) -> None:
    async def authorized_admin() -> AuthenticatedUser:
        return AuthenticatedUser(UUID("00000000-0000-4000-8000-000000000001"), "test-token")

    class SuccessfulService:
        def __init__(self, _settings: Settings) -> None:
            pass

        async def issue(self, *, user_id: UUID) -> datetime:
            assert user_id == TEST_USER_ID
            return FIXED_NOW + timedelta(days=7)

    app.dependency_overrides[get_current_admin_user] = authorized_admin
    monkeypatch.setattr(admin_api, "get_settings", lambda: _settings())
    monkeypatch.setattr(admin_api, "ActivationIssuanceService", SuccessfulService)

    async def run() -> httpx.Response:
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
            ) as client:
                return await client.post(f"/api/v1/admin/profiles/{TEST_USER_ID}/activation-code")
        finally:
            app.dependency_overrides.pop(get_current_admin_user, None)

    response = asyncio.run(run())
    assert response.status_code == 200
    assert response.json() == {
        "user_id": str(TEST_USER_ID),
        "expires_at": "2026-05-08T12:00:00Z",
        "email_delivery": "accepted",
    }
    assert TEST_CODE not in response.text
    assert hashlib.sha256(TEST_CODE.encode("utf-8")).hexdigest() not in response.text


def test_email_failure_endpoint_returns_generic_failure(monkeypatch) -> None:
    async def authorized_admin() -> AuthenticatedUser:
        return AuthenticatedUser(UUID("00000000-0000-4000-8000-000000000001"), "test-token")

    class FailedDeliveryService:
        def __init__(self, _settings: Settings) -> None:
            pass

        async def issue(self, *, user_id: UUID) -> datetime:
            raise ActivationEmailDeliveryError(TEST_CODE)

    app.dependency_overrides[get_current_admin_user] = authorized_admin
    monkeypatch.setattr(admin_api, "get_settings", lambda: _settings())
    monkeypatch.setattr(admin_api, "ActivationIssuanceService", FailedDeliveryService)

    async def run() -> httpx.Response:
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
            ) as client:
                return await client.post(f"/api/v1/admin/profiles/{TEST_USER_ID}/activation-code")
        finally:
            app.dependency_overrides.pop(get_current_admin_user, None)

    response = asyncio.run(run())
    assert response.status_code == 503
    assert response.json()["error"]["message"] == "Activation email could not be sent."
    assert TEST_CODE not in response.text

