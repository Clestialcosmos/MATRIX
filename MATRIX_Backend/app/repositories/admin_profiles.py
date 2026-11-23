from __future__ import annotations

from datetime import datetime
from uuid import UUID

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.schemas.admin import AdminProfileSummary

ADMIN_PROFILE_SELECT = "id,full_name,access_status"
ADMIN_APPROVAL_SELECT = "id,full_name,access_status,activation_completed_at"
DATABASE_TIMEOUT_SECONDS = 5.0
PENDING_PAGE_LIMIT_MAX = 500


class AdminProfilesError(Exception):
    """Base class for safe admin profile operation errors."""


class AdminProfilesConfigurationError(AdminProfilesError):
    """Required server-side Supabase configuration is unavailable."""


class AdminProfileNotFoundError(AdminProfilesError):
    """The target profile does not exist."""


class InvalidApprovalTransitionError(AdminProfilesError):
    """The profile is not eligible for approval."""


class ApprovalRaceError(InvalidApprovalTransitionError):
    """The profile changed after eligibility was checked."""


class AdminProfilesDatabaseError(AdminProfilesError):
    """Supabase failed or returned invalid profile data."""


class ApprovalState(BaseModel):
    id: UUID
    full_name: str | None = None
    access_status: str
    activation_completed_at: datetime | None = None


class SupabaseAdminProfilesRepository:
    """Admin-only profile operations. Construct/call only after admin authorization."""

    def __init__(self, settings: Settings, *, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client

    def _request_details(self) -> tuple[str, str]:
        project_url = self._settings.supabase_url.rstrip("/")
        service_role_key = self._settings.supabase_service_role_key
        if not project_url.startswith("https://"):
            raise AdminProfilesConfigurationError("Supabase project URL is unavailable")
        if service_role_key is None or not service_role_key.get_secret_value():
            raise AdminProfilesConfigurationError("Supabase admin access is unavailable")
        return f"{project_url}/rest/v1/profiles", service_role_key.get_secret_value()

    async def _request(
        self,
        method: str,
        *,
        params: dict[str, str],
        json_body: dict[str, str] | None = None,
        prefer: str | None = None,
        range_header: str | None = None,
    ) -> object:
        url, service_role_key = self._request_details()
        headers = {
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Accept": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        if range_header:
            headers["Range"] = range_header

        try:
            if self._client is not None:
                response = await self._client.request(
                    method,
                    url,
                    params=params,
                    headers=headers,
                    json=json_body,
                )
            else:
                async with httpx.AsyncClient(
                    timeout=DATABASE_TIMEOUT_SECONDS,
                    follow_redirects=False,
                ) as client:
                    response = await client.request(
                        method,
                        url,
                        params=params,
                        headers=headers,
                        json=json_body,
                    )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AdminProfilesDatabaseError("Profile operation failed") from exc

    @staticmethod
    def _parse_summaries(payload: object) -> list[AdminProfileSummary]:
        if not isinstance(payload, list):
            raise AdminProfilesDatabaseError("Supabase returned an invalid profile list")
        if any(not isinstance(row, dict) for row in payload):
            raise AdminProfilesDatabaseError("Supabase returned invalid profile rows")
        try:
            return [
                AdminProfileSummary.model_validate(
                    {
                        "user_id": row["id"],
                        "full_name": row.get("full_name"),
                        "access_status": row["access_status"],
                    }
                )
                for row in payload
            ]
        except (KeyError, TypeError, ValidationError) as exc:
            raise AdminProfilesDatabaseError("Supabase returned invalid profile data") from exc

    async def list_pending(self, *, limit: int, offset: int) -> list[AdminProfileSummary]:
        if not 1 <= limit <= PENDING_PAGE_LIMIT_MAX or offset < 0:
            raise ValueError("Invalid pagination values")
        payload = await self._request(
            "GET",
            params={
                "select": ADMIN_PROFILE_SELECT,
                "access_status": "eq.pending",
                "activation_completed_at": "is.null",
                "order": "id.asc",
                "limit": str(limit),
                "offset": str(offset),
            },
        )
        return self._parse_summaries(payload)

    async def list_approved_awaiting_activation(
        self, *, limit: int, offset: int
    ) -> list[AdminProfileSummary]:
        if not 1 <= limit <= PENDING_PAGE_LIMIT_MAX or offset < 0:
            raise ValueError("Invalid pagination values")
        payload = await self._request(
            "GET",
            params={
                "select": ADMIN_APPROVAL_SELECT,
                "access_status": "eq.approved",
                "activation_completed_at": "is.null",
                "order": "id.asc",
                "limit": str(limit),
                "offset": str(offset),
            },
        )
        if not isinstance(payload, list):
            raise AdminProfilesDatabaseError("Supabase returned an invalid profile list")
        if any(not isinstance(row, dict) for row in payload):
            raise AdminProfilesDatabaseError("Supabase returned invalid profile rows")
        try:
            eligible = [
                ApprovalState.model_validate(row)
                for row in payload
            ]
        except ValidationError as exc:
            raise AdminProfilesDatabaseError("Supabase returned invalid profile data") from exc
        return [
            AdminProfileSummary(
                user_id=profile.id,
                full_name=profile.full_name,
                access_status=profile.access_status,
            )
            for profile in eligible
            if profile.access_status == "approved" and profile.activation_completed_at is None
        ]

    async def approve_pending(self, *, user_id: UUID) -> AdminProfileSummary:
        current_payload = await self._request(
            "GET",
            params={
                "select": ADMIN_APPROVAL_SELECT,
                "id": f"eq.{user_id}",
                "limit": "2",
            },
        )
        if not isinstance(current_payload, list):
            raise AdminProfilesDatabaseError("Supabase returned an invalid profile")
        if not current_payload:
            raise AdminProfileNotFoundError("Profile does not exist")
        if len(current_payload) != 1 or not isinstance(current_payload[0], dict):
            raise AdminProfilesDatabaseError("Profile identity is not unique")
        try:
            current = ApprovalState.model_validate(current_payload[0])
        except ValidationError as exc:
            raise AdminProfilesDatabaseError("Supabase returned invalid profile data") from exc

        if current.access_status != "pending" or current.activation_completed_at is not None:
            raise InvalidApprovalTransitionError("Profile is not eligible for approval")

        updated_payload = await self._request(
            "PATCH",
            params={
                "select": ADMIN_PROFILE_SELECT,
                "id": f"eq.{user_id}",
                "access_status": "eq.pending",
                "activation_completed_at": "is.null",
            },
            json_body={"access_status": "approved"},
            prefer="return=representation",
        )
        if not isinstance(updated_payload, list):
            raise AdminProfilesDatabaseError("Supabase returned an invalid approval result")
        if not updated_payload:
            raise ApprovalRaceError("Profile changed during approval")
        summaries = self._parse_summaries(updated_payload)
        if len(summaries) != 1 or summaries[0].access_status != "approved":
            raise AdminProfilesDatabaseError("Supabase returned an invalid approval result")
        return summaries[0]
