import asyncio
from uuid import UUID, uuid4

import httpx

from app.api.dependencies.auth import get_app_settings, get_authenticated_user
from app.api.v1 import admin as admin_api
from app.core.config import Settings
from app.main import app
from app.repositories.admin_profiles import SupabaseAdminProfilesRepository
from app.schemas.admin import AdminProfileSummary
from app.services.supabase_jwt import AuthenticatedUser

ADMIN_ID = UUID("00000000-0000-4000-8000-000000000001")


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        supabase_url="https://matrix-project.example.test",
        supabase_service_role_key="test-only-service-role-credential",
        matrix_admin_user_id=str(ADMIN_ID),
    )


def _row(user_id: UUID, *, status: str, activated_at: str | None) -> dict[str, object]:
    return {
        "id": str(user_id),
        "full_name": "MATRIX Profile",
        "access_status": status,
        "activation_completed_at": activated_at,
        "email": "must-not-be-returned@example.test",
    }


def _repository(responses: list[tuple[int, object]]):
    seen: list[httpx.Request] = []
    pending = list(responses)

    async def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        code, payload = pending.pop(0)
        return httpx.Response(code, json=payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    repo = SupabaseAdminProfilesRepository(_settings(), client=client)
    return repo, client, seen


def test_repository_returns_only_approved_not_activated_profiles_and_minimal_fields() -> None:
    approved_id, pending_id, active_id = uuid4(), uuid4(), uuid4()
    repo, client, seen = _repository([
        (200, [
            _row(approved_id, status="approved", activated_at=None),
            _row(pending_id, status="pending", activated_at=None),
            _row(active_id, status="approved", activated_at="2026-01-01T00:00:00Z"),
        ])
    ])

    async def run():
        async with client:
            return await repo.list_approved_awaiting_activation(limit=50, offset=10)

    profiles = asyncio.run(run())
    assert profiles == [AdminProfileSummary(user_id=approved_id, full_name="MATRIX Profile", access_status="approved")]
    params = seen[0].url.params
    assert params["access_status"] == "eq.approved"
    assert params["activation_completed_at"] == "is.null"
    assert params["select"] == "id,full_name,access_status,activation_completed_at"
    assert params["limit"] == "50" and params["offset"] == "10"
    assert "activation_completed_at" not in profiles[0].model_dump()
    assert "email" not in profiles[0].model_dump()


def test_repository_returns_empty_results() -> None:
    repo, client, _ = _repository([(200, [])])

    async def run():
        async with client:
            return await repo.list_approved_awaiting_activation(limit=100, offset=0)

    assert asyncio.run(run()) == []


def test_authorized_admin_can_list_and_result_is_available_on_a_fresh_request(monkeypatch) -> None:
    user_id = uuid4()
    calls = []

    class ApprovedProfiles:
        async def list_approved_awaiting_activation(self, *, limit: int, offset: int):
            calls.append((limit, offset))
            return [AdminProfileSummary(user_id=user_id, full_name="Existing User", access_status="approved")]

    async def authenticated_admin():
        return AuthenticatedUser(ADMIN_ID, "mock-token")

    app.dependency_overrides[get_authenticated_user] = authenticated_admin
    app.dependency_overrides[get_app_settings] = _settings
    monkeypatch.setattr(admin_api, "get_settings", _settings)
    monkeypatch.setattr(admin_api, "SupabaseAdminProfilesRepository", lambda _settings: ApprovedProfiles())

    async def run():
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
                first = await client.get("/api/v1/admin/profiles/approved-awaiting-activation")
                second = await client.get("/api/v1/admin/profiles/approved-awaiting-activation")
                return first, second
        finally:
            app.dependency_overrides.pop(get_authenticated_user, None)
            app.dependency_overrides.pop(get_app_settings, None)

    first, second = asyncio.run(run())
    expected = [{"user_id": str(user_id), "full_name": "Existing User", "access_status": "approved"}]
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == expected
    assert calls == [(100, 0), (100, 0)]


def test_non_admin_is_rejected_before_repository_is_constructed(monkeypatch) -> None:
    class MustNotConstruct:
        def __init__(self, _settings):
            raise AssertionError("repository must not be constructed for a non-admin")

    async def authenticated_user():
        return AuthenticatedUser(uuid4(), "mock-token")

    app.dependency_overrides[get_authenticated_user] = authenticated_user
    app.dependency_overrides[get_app_settings] = _settings
    monkeypatch.setattr(admin_api, "get_settings", _settings)
    monkeypatch.setattr(admin_api, "SupabaseAdminProfilesRepository", MustNotConstruct)

    async def run():
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
                return await client.get("/api/v1/admin/profiles/approved-awaiting-activation")
        finally:
            app.dependency_overrides.pop(get_authenticated_user, None)
            app.dependency_overrides.pop(get_app_settings, None)

    response = asyncio.run(run())
    assert response.status_code == 403

