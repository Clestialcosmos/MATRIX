from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import Settings

_PROFILE_COLUMN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PROFILE_SELECT = "full_name,access_status,activation_completed_at"
DATABASE_TIMEOUT_SECONDS = 5.0


class ProfileRepositoryError(Exception):
    """Base exception for safe profile lookup failures."""


class ProfileConfigurationError(ProfileRepositoryError):
    """Required Supabase/profile lookup configuration is unavailable."""


class ProfileNotFoundError(ProfileRepositoryError):
    """No visible profile is linked to the authenticated user."""


class ProfileDataError(ProfileRepositoryError):
    """Supabase returned an invalid or ambiguous profile result."""


class ProfileDatabaseError(ProfileRepositoryError):
    """Supabase could not complete the read request."""


class ProfileFields(BaseModel):
    full_name: str | None = None
    access_status: str | None = None
    activation_completed_at: datetime | None = None


class SupabaseProfilesRepository:
    """Read a caller's profile using the caller JWT and existing RLS policies."""

    def __init__(self, settings: Settings, *, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client

    def _request_details(self) -> tuple[str, str, str]:
        project_url = self._settings.supabase_url.rstrip("/")
        anon_key = self._settings.supabase_anon_key
        column = self._settings.supabase_profile_user_id_column
        if not project_url.startswith("https://"):
            raise ProfileConfigurationError("Supabase URL is not configured")
        if anon_key is None or not anon_key.get_secret_value():
            raise ProfileConfigurationError("Supabase public key is not configured")
        if not _PROFILE_COLUMN.fullmatch(column):
            raise ProfileConfigurationError("Profile identity column is not configured")
        return f"{project_url}/rest/v1/profiles", anon_key.get_secret_value(), column

    async def get_for_user(self, *, user_id: UUID, access_token: str) -> ProfileFields:
        url, anon_key, column = self._request_details()
        params = {
            "select": PROFILE_SELECT,
            column: f"eq.{user_id}",
            "limit": "2",
        }
        headers = {
            "apikey": anon_key,
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }

        try:
            if self._client is not None:
                response = await self._client.get(url, params=params, headers=headers)
            else:
                async with httpx.AsyncClient(
                    timeout=DATABASE_TIMEOUT_SECONDS,
                    follow_redirects=False,
                ) as client:
                    response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProfileDatabaseError("Profile lookup failed") from exc

        if not isinstance(payload, list):
            raise ProfileDataError("Profile response has an invalid shape")
        if not payload:
            raise ProfileNotFoundError("No profile is visible for this user")
        if len(payload) != 1 or not isinstance(payload[0], dict):
            raise ProfileDataError("Profile identity is not unique")

        try:
            return ProfileFields.model_validate(payload[0])
        except ValidationError as exc:
            raise ProfileDataError("Profile response has invalid fields") from exc
