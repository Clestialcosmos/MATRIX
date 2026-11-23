import asyncio
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import HTTPException

from app.api.dependencies.auth import (
    get_app_settings,
    get_authenticated_user,
    get_current_admin_user,
)
from app.api.v1 import admin as admin_api
from app.core.config import Settings
from app.main import app
from app.repositories.admin_profiles import (
    AdminProfileNotFoundError,
    AdminProfilesConfigurationError,
    AdminProfilesDatabaseError,
    ApprovalRaceError,
    InvalidApprovalTransitionError,
    SupabaseAdminProfilesRepository,
)
from app.schemas.admin import AdminProfileSummary
from app.services.supabase_jwt import AuthenticatedUser

PROJECT_URL = "https://matrix-project.example.test"
SERVICE_ROLE_TEST_VALUE = "test-only-service-role-credential"


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "supabase_url": PROJECT_URL,
        "supabase_service_role_key": SERVICE_ROLE_TEST_VALUE,
        "matrix_admin_user_id": str(UUID("00000000-0000-4000-8000-000000000001")),
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _profile(
    user_id: UUID,
    *,
    status: str = "pending",
    activated_at: str | None = None,
) -> dict[str, object]:
    return {
        "id": str(user_id),
        "full_name": "Example Profile",
        "access_status": status,
        "activation_completed_at": activated_at,
    }


def _mock_repository(
    responses: list[tuple[int, object]],
) -> tuple[SupabaseAdminProfilesRepository, list[httpx.Request]]:
    seen: list[httpx.Request] = []
    remaining = list(responses)

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if not remaining:
            return httpx.Response(500, json={"message": "unexpected extra request"})
        code, payload = remaining.pop(0)
        return httpx.Response(code, json=payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    repository = SupabaseAdminProfilesRepository(_settings(), client=client)
    repository.test_http_client = client
    return repository, seen


def test_verified_admin_uuid_is_required() -> None:
    admin_id = UUID("00000000-0000-4000-8000-000000000001")
    settings = _settings(matrix_admin_user_id=str(admin_id))

    async def run() -> AuthenticatedUser:
        return await get_current_admin_user(
            AuthenticatedUser(admin_id, "test-token"),
            settings,
        )

    assert asyncio.run(run()).user_id == admin_id


def test_non_admin_subject_gets_403() -> None:
    settings = _settings()

    async def run() -> None:
        with pytest.raises(HTTPException) as caught:
            await get_current_admin_user(AuthenticatedUser(uuid4(), "test-token"), settings)
        assert caught.value.status_code == 403

    asyncio.run(run())


def test_non_admin_api_request_is_denied_before_repository_construction(monkeypatch) -> None:
    admin_id = UUID("00000000-0000-4000-8000-000000000001")

    async def authenticated_non_admin() -> AuthenticatedUser:
        return AuthenticatedUser(uuid4(), "test-token")

    class MustNotConstructRepository:
        def __init__(self, _settings: Settings) -> None:
            raise AssertionError("service-role repository constructed before admin authorization")

    app.dependency_overrides[get_authenticated_user] = authenticated_non_admin
    app.dependency_overrides[get_app_settings] = lambda: _settings(matrix_admin_user_id=str(admin_id))
    monkeypatch.setattr(admin_api, "SupabaseAdminProfilesRepository", MustNotConstructRepository)

    async def run() -> httpx.Response:
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
            ) as client:
                return await client.get("/api/v1/admin/profiles/pending")
        finally:
            app.dependency_overrides.pop(get_authenticated_user, None)
            app.dependency_overrides.pop(get_app_settings, None)

    response = asyncio.run(run())
    assert response.status_code == 403
    assert response.json()["error"]["message"] == "Administrator authorization required."


@pytest.mark.parametrize("admin_id", ["", "not-a-uuid"])
def test_missing_or_invalid_admin_configuration_fails_closed(admin_id: str) -> None:
    settings = _settings(matrix_admin_user_id=admin_id)

    async def run() -> None:
        with pytest.raises(HTTPException) as caught:
            await get_current_admin_user(
                AuthenticatedUser(uuid4(), "test-token"),
                settings,
            )
        assert caught.value.status_code == 503

    asyncio.run(run())


def test_pending_list_uses_service_role_and_minimal_fields_after_admin(monkeypatch) -> None:
    user_id = uuid4()
    repository, seen = _mock_repository(
        [(200, [_profile(user_id)])]
    )

    async def run() -> list[AdminProfileSummary]:
        async with repository.test_http_client:
            rows = await repository.list_pending(limit=100, offset=0)
            return rows

    rows = asyncio.run(run())
    assert rows == [AdminProfileSummary(user_id=user_id, full_name="Example Profile", access_status="pending")]
    request = seen[0]
    assert request.method == "GET"
    assert request.url.path == "/rest/v1/profiles"
    assert request.url.params["select"] == "id,full_name,access_status"
    assert request.url.params["access_status"] == "eq.pending"
    assert request.url.params["activation_completed_at"] == "is.null"
    assert request.headers["apikey"] == SERVICE_ROLE_TEST_VALUE
    assert request.headers["authorization"] == f"Bearer {SERVICE_ROLE_TEST_VALUE}"
    assert "activation_completed_at" not in rows[0].model_dump()


def test_approval_updates_only_pending_access_status_conditionally() -> None:
    user_id = uuid4()
    repo, seen = _mock_repository(
        [
            (200, [_profile(user_id)]),
            (200, [{"id": str(user_id), "full_name": "Example Profile", "access_status": "approved"}]),
        ]
    )

    async def run() -> AdminProfileSummary:
        async with repo.test_http_client:
            return await repo.approve_pending(user_id=user_id)

    result = asyncio.run(run())
    assert result.access_status == "approved"
    assert len(seen) == 2
    update = seen[1]
    assert update.method == "PATCH"
    assert update.url.params["id"] == f"eq.{user_id}"
    assert update.url.params["access_status"] == "eq.pending"
    assert update.url.params["activation_completed_at"] == "is.null"
    assert json.loads(update.content) == {"access_status": "approved"}
    assert "activation_completed_at" not in json.loads(update.content)


@pytest.mark.parametrize(
    "current_profile",
    [
        lambda uid: _profile(uid, status="approved"),
        lambda uid: _profile(uid, status="rejected"),
        lambda uid: _profile(uid, status="pending", activated_at=datetime.now(timezone.utc).isoformat()),
    ],
)
def test_ineligible_profiles_are_not_updated(current_profile) -> None:
    user_id = uuid4()
    repo, seen = _mock_repository([(200, [current_profile(user_id)])])

    async def run() -> None:
        async with repo.test_http_client:
            with pytest.raises(InvalidApprovalTransitionError):
                await repo.approve_pending(user_id=user_id)

    asyncio.run(run())
    assert len(seen) == 1
    assert seen[0].method == "GET"


def test_missing_profile_is_distinguished_safely() -> None:
    repo, seen = _mock_repository([(200, [])])
    user_id = uuid4()

    async def run() -> None:
        async with repo.test_http_client:
            with pytest.raises(AdminProfileNotFoundError):
                await repo.approve_pending(user_id=user_id)

    asyncio.run(run())
    assert len(seen) == 1


def test_conditional_update_detects_race() -> None:
    user_id = uuid4()
    repo, seen = _mock_repository([(200, [_profile(user_id)]), (200, [])])

    async def run() -> None:
        async with repo.test_http_client:
            with pytest.raises(ApprovalRaceError):
                await repo.approve_pending(user_id=user_id)

    asyncio.run(run())
    assert len(seen) == 2


def test_database_failures_are_generic_and_do_not_leak_credentials() -> None:
    repo, seen = _mock_repository([(500, {"message": SERVICE_ROLE_TEST_VALUE})])
    user_id = uuid4()

    async def run() -> None:
        async with repo.test_http_client:
            with pytest.raises(AdminProfilesDatabaseError) as caught:
                await repo.list_pending(limit=100, offset=0)
            assert SERVICE_ROLE_TEST_VALUE not in str(caught.value)

    asyncio.run(run())
    assert len(seen) == 1


def test_missing_service_role_configuration_fails_closed() -> None:
    repo, seen = _mock_repository([])
    repo._settings = _settings(supabase_service_role_key=None)

    async def run() -> None:
        async with repo.test_http_client:
            with pytest.raises(AdminProfilesConfigurationError):
                await repo.list_pending(limit=100, offset=0)

    asyncio.run(run())
    assert seen == []


def test_api_maps_missing_profile_to_not_found_and_uses_no_real_database(monkeypatch) -> None:
    user_id = uuid4()

    class MissingProfileRepository:
        async def approve_pending(self, *, user_id: UUID) -> AdminProfileSummary:
            raise AdminProfileNotFoundError("hidden detail")

    response = _admin_request(
        monkeypatch,
        f"/api/v1/admin/profiles/{user_id}/approve",
        MissingProfileRepository(),
    )
    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Profile is not available."
    assert "hidden detail" not in response.text


def test_admin_api_lists_pending_profiles(monkeypatch) -> None:
    profile = AdminProfileSummary(
        user_id=uuid4(),
        full_name="Pending Example",
        access_status="pending",
    )

    class PendingRepository:
        async def list_pending(self, *, limit: int, offset: int) -> list[AdminProfileSummary]:
            assert limit == 100
            assert offset == 0
            return [profile]

    response = _admin_request(
        monkeypatch,
        "/api/v1/admin/profiles/pending",
        PendingRepository(),
    )
    assert response.status_code == 200
    assert response.json() == [
        {
            "user_id": str(profile.user_id),
            "full_name": "Pending Example",
            "access_status": "pending",
        }
    ]


def test_admin_api_approves_profile_without_activation_side_effect(monkeypatch) -> None:
    user_id = uuid4()

    class ApproveRepository:
        async def approve_pending(self, *, user_id: UUID) -> AdminProfileSummary:
            assert user_id == expected_id
            return AdminProfileSummary(
                user_id=user_id,
                full_name="Pending Example",
                access_status="approved",
            )

    expected_id = user_id
    response = _admin_request(
        monkeypatch,
        f"/api/v1/admin/profiles/{user_id}/approve",
        ApproveRepository(),
    )
    assert response.status_code == 200
    assert response.json() == {
        "user_id": str(user_id),
        "full_name": "Pending Example",
        "access_status": "approved",
    }


def test_invalid_profile_uuid_is_rejected_before_repository_call(monkeypatch) -> None:
    class UnusedRepository:
        async def approve_pending(self, *, user_id: UUID) -> AdminProfileSummary:
            raise AssertionError("repository must not be called for invalid UUID")

    response = _admin_request(
        monkeypatch,
        "/api/v1/admin/profiles/not-a-uuid/approve",
        UnusedRepository(),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_api_maps_database_error_to_standard_envelope(monkeypatch) -> None:
    class BrokenRepository:
        async def list_pending(self, *, limit: int, offset: int) -> list[AdminProfileSummary]:
            raise AdminProfilesDatabaseError("private upstream detail")

    response = _admin_request(
        monkeypatch,
        "/api/v1/admin/profiles/pending",
        BrokenRepository(),
    )
    assert response.status_code == 503
    assert response.json()["error"]["message"] == "Admin profile service is unavailable."
    assert "private upstream detail" not in response.text


def _admin_request(monkeypatch, path: str, repository: object) -> httpx.Response:
    admin_id = UUID("00000000-0000-4000-8000-000000000001")

    async def authorized_admin() -> AuthenticatedUser:
        return AuthenticatedUser(admin_id, "test-token")

    monkeypatch.setattr(admin_api, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        admin_api,
        "SupabaseAdminProfilesRepository",
        lambda _settings: repository,
    )
    app.dependency_overrides[get_current_admin_user] = authorized_admin

    async def run() -> httpx.Response:
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
            ) as client:
                return await client.get(path) if path.endswith("/pending") else await client.post(path)
        finally:
            app.dependency_overrides.pop(get_current_admin_user, None)

    return asyncio.run(run())
