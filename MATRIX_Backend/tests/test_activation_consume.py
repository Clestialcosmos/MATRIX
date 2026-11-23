import asyncio
import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest

from app.api.dependencies.auth import get_authenticated_user
from app.api.v1.activation import get_activation_repository
from app.api.v1.me import get_profiles_repository
from app.core.config import Settings
from app.main import app
from app.repositories.activation import SupabaseActivationRepository
from app.repositories.profiles import SupabaseProfilesRepository
from app.services.supabase_jwt import AuthenticatedUser

TEST_USER_ID = uuid4()
TEST_CODE = "AbC_def-123"
TEST_TOKEN = "opaque-test-user-token"
ANON_KEY = "test-public-anon-key"
SERVICE_ROLE_KEY = "must-not-be-used-for-consume-test"
PROJECT_URL = "https://project.example.test"


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        supabase_url=PROJECT_URL,
        supabase_anon_key=ANON_KEY,
        supabase_service_role_key=SERVICE_ROLE_KEY,
        supabase_profile_user_id_column="id",
    )


def _access_row(*, activated: bool = True) -> list[dict[str, object]]:
    return [
        {
            "full_name": "Test User",
            "access_status": "approved",
            "activation_completed_at": datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc).isoformat()
            if activated
            else None,
        }
    ]


def test_consume_rpc_uses_user_jwt_anon_key_and_verified_identity() -> None:
    seen: list[httpx.Request] = []
    expected_hash = hashlib.sha256(TEST_CODE.encode("utf-8")).hexdigest()

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=True)

    async def run() -> bool:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            repository = SupabaseActivationRepository(_settings(), client=client)
            return await repository.consume(
                user_id=TEST_USER_ID,
                code_hash=expected_hash,
                access_token=TEST_TOKEN,
            )

    assert asyncio.run(run()) is True
    request = seen[0]
    assert request.method == "POST"
    assert request.url == f"{PROJECT_URL}/rest/v1/rpc/consume_activation_code"
    assert request.headers["apikey"] == ANON_KEY
    assert request.headers["authorization"] == f"Bearer {TEST_TOKEN}"
    assert SERVICE_ROLE_KEY not in request.headers["authorization"]
    assert json.loads(request.content) == {
        "p_user_id": str(TEST_USER_ID),
        "p_code_hash": expected_hash,
    }


@pytest.mark.parametrize("reason", ["invalid", "expired", "revoked", "used", "unapproved"])
def test_rpc_false_maps_to_non_disclosing_failure_for_all_rejection_reasons(reason: str) -> None:
    del reason  # The RPC intentionally returns the same boolean for all rejection reasons.
    rpc_requests: list[httpx.Request] = []

    async def rpc_handler(request: httpx.Request) -> httpx.Response:
        rpc_requests.append(request)
        return httpx.Response(200, json=False)

    async def run() -> httpx.Response:
        rpc_client = httpx.AsyncClient(transport=httpx.MockTransport(rpc_handler))
        profile_requests: list[httpx.Request] = []

        async def profile_handler(request: httpx.Request) -> httpx.Response:
            profile_requests.append(request)
            return httpx.Response(200, json=_access_row())

        profile_client = httpx.AsyncClient(transport=httpx.MockTransport(profile_handler))
        user = AuthenticatedUser(TEST_USER_ID, TEST_TOKEN)
        app.dependency_overrides[get_authenticated_user] = lambda: user
        app.dependency_overrides[get_activation_repository] = lambda: SupabaseActivationRepository(
            _settings(), client=rpc_client
        )
        app.dependency_overrides[get_profiles_repository] = lambda: SupabaseProfilesRepository(
            _settings(), client=profile_client
        )
        try:
            async with rpc_client, profile_client:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://testserver",
                ) as api:
                    return await api.post(
                        "/api/v1/activation/consume",
                        json={"activation_code": TEST_CODE},
                    )
        finally:
            app.dependency_overrides.pop(get_authenticated_user, None)
            app.dependency_overrides.pop(get_activation_repository, None)
            app.dependency_overrides.pop(get_profiles_repository, None)

    response = asyncio.run(run())
    assert response.status_code == 400
    assert response.json()["error"]["message"] == "Activation code is invalid or unavailable."
    assert len(rpc_requests) == 1


def test_success_returns_updated_global_access_state_and_no_code_or_hash() -> None:
    rpc_requests: list[httpx.Request] = []
    profile_requests: list[httpx.Request] = []

    async def rpc_handler(request: httpx.Request) -> httpx.Response:
        rpc_requests.append(request)
        return httpx.Response(200, json=True)

    async def profile_handler(request: httpx.Request) -> httpx.Response:
        profile_requests.append(request)
        return httpx.Response(200, json=_access_row())

    async def run() -> httpx.Response:
        rpc_client = httpx.AsyncClient(transport=httpx.MockTransport(rpc_handler))
        profile_client = httpx.AsyncClient(transport=httpx.MockTransport(profile_handler))
        app.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(
            TEST_USER_ID, TEST_TOKEN
        )
        app.dependency_overrides[get_activation_repository] = lambda: SupabaseActivationRepository(
            _settings(), client=rpc_client
        )
        app.dependency_overrides[get_profiles_repository] = lambda: SupabaseProfilesRepository(
            _settings(), client=profile_client
        )
        try:
            async with rpc_client, profile_client:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://testserver",
                ) as api:
                    return await api.post(
                        "/api/v1/activation/consume",
                        json={"activation_code": f"  {TEST_CODE}  "},
                    )
        finally:
            app.dependency_overrides.pop(get_authenticated_user, None)
            app.dependency_overrides.pop(get_activation_repository, None)
            app.dependency_overrides.pop(get_profiles_repository, None)

    response = asyncio.run(run())
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "activated"
    assert body["access"]["user_id"] == str(TEST_USER_ID)
    assert body["access"]["has_matrix_access"] is True
    assert body["access"]["activation_completed_at"] is not None
    assert TEST_CODE not in response.text
    assert hashlib.sha256(TEST_CODE.encode("utf-8")).hexdigest() not in response.text
    assert len(rpc_requests) == 1
    assert len(profile_requests) == 1
    assert profile_requests[0].url.params["id"] == f"eq.{TEST_USER_ID}"


def test_missing_code_and_user_uuid_body_are_rejected() -> None:
    async def run() -> tuple[httpx.Response, httpx.Response]:
        app.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(
            TEST_USER_ID, TEST_TOKEN
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as api:
            try:
                missing = await api.post("/api/v1/activation/consume", json={})
                supplied_identity = await api.post(
                    "/api/v1/activation/consume",
                    json={"activation_code": TEST_CODE, "user_id": str(uuid4())},
                )
                return missing, supplied_identity
            finally:
                app.dependency_overrides.pop(get_authenticated_user, None)

    missing, supplied_identity = asyncio.run(run())
    assert missing.status_code == 422
    assert supplied_identity.status_code == 422
    assert TEST_CODE not in missing.text
    assert TEST_CODE not in supplied_identity.text


def test_unauthenticated_call_is_401_and_does_not_reach_supabase() -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=True)

    async def run() -> httpx.Response:
        rpc_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        app.dependency_overrides[get_activation_repository] = lambda: SupabaseActivationRepository(
            _settings(), client=rpc_client
        )
        try:
            async with rpc_client:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://testserver",
                ) as api:
                    return await api.post(
                        "/api/v1/activation/consume",
                        json={"activation_code": TEST_CODE},
                    )
        finally:
            app.dependency_overrides.pop(get_activation_repository, None)

    response = asyncio.run(run())
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "http_error"
    assert seen == []


def test_rpc_and_followup_profile_failures_return_safe_errors() -> None:
    async def rpc_error_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "private RPC error"})

    async def profile_ok(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_access_row())

    async def profile_null(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_access_row(activated=False))

    async def request_with(rpc_handler, profile_handler) -> httpx.Response:
        rpc_client = httpx.AsyncClient(transport=httpx.MockTransport(rpc_handler))
        profile_client = httpx.AsyncClient(transport=httpx.MockTransport(profile_handler))
        app.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(
            TEST_USER_ID, TEST_TOKEN
        )
        app.dependency_overrides[get_activation_repository] = lambda: SupabaseActivationRepository(
            _settings(), client=rpc_client
        )
        app.dependency_overrides[get_profiles_repository] = lambda: SupabaseProfilesRepository(
            _settings(), client=profile_client
        )
        try:
            async with rpc_client, profile_client:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://testserver",
                ) as api:
                    return await api.post(
                        "/api/v1/activation/consume",
                        json={"activation_code": TEST_CODE},
                    )
        finally:
            app.dependency_overrides.pop(get_authenticated_user, None)
            app.dependency_overrides.pop(get_activation_repository, None)
            app.dependency_overrides.pop(get_profiles_repository, None)

    async def run_both() -> tuple[httpx.Response, httpx.Response]:
        first = await request_with(rpc_error_handler, profile_ok)

        async def rpc_success(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=True)

        second = await request_with(rpc_success, profile_null)
        return first, second

    rpc_response, profile_response = asyncio.run(run_both())
    assert rpc_response.status_code == 503
    assert "private RPC error" not in rpc_response.text
    assert profile_response.status_code == 503
    assert profile_response.json()["error"]["message"] == (
        "Activation succeeded, but access status is temporarily unavailable."
    )
