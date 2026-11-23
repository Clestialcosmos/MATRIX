import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
import pytest

from app.api.dependencies.auth import get_authenticated_user
from app.api.v1.me import get_profiles_repository
from app.core.config import Settings
from app.main import app
from app.repositories.profiles import SupabaseProfilesRepository
from app.services.supabase_jwt import AuthenticatedUser

BASE_URL = "http://testserver"
PROFILE_URL = "https://matrix-project.example.test/rest/v1/profiles"
ANON_KEY = "public-test-anon-key"


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "supabase_url": "https://matrix-project.example.test",
        "supabase_anon_key": ANON_KEY,
        "supabase_profile_user_id_column": "auth_user_id",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _run_request(
    *,
    user_id: UUID | None,
    token: str = "test-access-token",
    response_status: int = 200,
    response_json: object | None = None,
    extra_query: str = "",
) -> tuple[httpx.Response, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            response_status,
            json=(response_json if response_json is not None else []),
        )

    async def run() -> httpx.Response:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        repository = SupabaseProfilesRepository(_settings(), client=client)

        async def authenticated_user() -> AuthenticatedUser:
            assert user_id is not None
            return AuthenticatedUser(user_id, token)

        app.dependency_overrides[get_profiles_repository] = lambda: repository
        if user_id is not None:
            app.dependency_overrides[get_authenticated_user] = authenticated_user
        try:
            async with client:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url=BASE_URL,
                ) as api_client:
                    return await api_client.get(f"/api/v1/me/access{extra_query}")
        finally:
            app.dependency_overrides.pop(get_profiles_repository, None)
            app.dependency_overrides.pop(get_authenticated_user, None)

    return asyncio.run(run()), seen


def test_authenticated_user_reads_only_own_profile_and_global_access() -> None:
    user_id = uuid4()
    activated_at = datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc).isoformat()
    response, seen = _run_request(
        user_id=user_id,
        response_json=[
            {
                "full_name": "Test User",
                "access_status": "approved",
                "activation_completed_at": activated_at,
            }
        ],
    )

    assert response.status_code == 200
    assert response.json() == {
        "user_id": str(user_id),
        "full_name": "Test User",
        "access_status": "approved",
        "activation_completed_at": "2026-01-02T03:04:00Z",
        "has_matrix_access": True,
    }
    assert len(seen) == 1
    request = seen[0]
    assert request.url == httpx.URL(PROFILE_URL).copy_with(
        params={
            "select": "full_name,access_status,activation_completed_at",
            "auth_user_id": f"eq.{user_id}",
            "limit": "2",
        }
    )
    assert request.headers["authorization"] == "Bearer test-access-token"
    assert request.headers["apikey"] == ANON_KEY
    assert "service-role" not in request.headers["apikey"].lower()


def test_activation_timestamp_alone_controls_global_access_flag() -> None:
    user_id = uuid4()
    response, _ = _run_request(
        user_id=user_id,
        response_json=[
            {
                "full_name": None,
                "access_status": "approved",
                "activation_completed_at": None,
            }
        ],
    )

    assert response.status_code == 200
    assert response.json()["has_matrix_access"] is False
    assert response.json()["access_status"] == "approved"


def test_client_cannot_select_another_users_profile_with_query_parameter() -> None:
    authenticated_id = uuid4()
    attacker_selected_id = uuid4()
    response, seen = _run_request(
        user_id=authenticated_id,
        response_json=[
            {
                "full_name": "Own profile",
                "access_status": "pending",
                "activation_completed_at": None,
            }
        ],
        extra_query=f"?user_id={attacker_selected_id}",
    )

    assert response.status_code == 200
    assert response.json()["user_id"] == str(authenticated_id)
    assert str(attacker_selected_id) not in str(seen[0].url)
    assert str(authenticated_id) in str(seen[0].url)


def test_missing_profile_returns_safe_not_found_envelope() -> None:
    response, seen = _run_request(user_id=uuid4(), response_json=[])

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Profile is not available."
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert len(seen) == 1


def test_unauthenticated_request_returns_401_without_supabase_call() -> None:
    response, seen = _run_request(user_id=None)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "http_error"
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert seen == []


def test_database_failure_returns_generic_error_envelope() -> None:
    response, seen = _run_request(
        user_id=uuid4(),
        response_status=500,
        response_json={"message": "private database detail"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["message"] == "Profile service is unavailable."
    assert "private database detail" not in response.text
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert len(seen) == 1


def test_duplicate_profile_rows_fail_closed() -> None:
    row = {
        "full_name": "Duplicate",
        "access_status": "approved",
        "activation_completed_at": None,
    }
    response, _ = _run_request(user_id=uuid4(), response_json=[row, row])

    assert response.status_code == 503
    assert response.json()["error"]["message"] == "Profile service is unavailable."


def test_invalid_profile_identity_column_fails_closed_before_request() -> None:
    user_id = uuid4()
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[])

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            repository = SupabaseProfilesRepository(
                _settings(supabase_profile_user_id_column="id) OR 1=1"),
                client=client,
            )
            from app.repositories.profiles import ProfileConfigurationError

            with pytest.raises(ProfileConfigurationError):
                await repository.get_for_user(user_id=user_id, access_token="opaque-test-token")

    asyncio.run(run())
    assert requests == []
