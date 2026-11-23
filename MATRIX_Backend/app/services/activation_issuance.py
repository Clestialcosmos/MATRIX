from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import UUID

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.services.activation_codes import hash_activation_code, normalize_activation_code

ACTIVATION_TTL = timedelta(days=7)
RESEND_API_URL = "https://api.resend.com/emails"
HTTP_TIMEOUT_SECONDS = 8.0


class ActivationIssuanceError(Exception):
    """Base class for safe activation issuance errors."""


class ActivationConfigurationError(ActivationIssuanceError):
    """Required backend or email configuration is missing."""


class ActivationProfileNotFoundError(ActivationIssuanceError):
    """The requested profile does not exist."""


class ActivationProfileIneligibleError(ActivationIssuanceError):
    """The profile is not approved or has already activated."""


class ActivationRecipientError(ActivationIssuanceError):
    """The trusted Auth user record has no usable email address."""


class ActivationDatabaseError(ActivationIssuanceError):
    """A Supabase request failed or returned an invalid response."""


class ActivationEmailDeliveryError(ActivationIssuanceError):
    """Email delivery failed; the newly issued code was revoked if possible."""


class ActivationRevocationError(ActivationEmailDeliveryError):
    """Email failed and the newly issued code could not be confirmed revoked."""


class _ProfileStatus(BaseModel):
    id: UUID
    access_status: str
    activation_completed_at: datetime | None = None


class ActivationIssuanceService:
    """Issue one global activation code and deliver it without returning plaintext."""

    def __init__(
        self,
        settings: Settings,
        *,
        supabase_client: httpx.AsyncClient | None = None,
        resend_client: httpx.AsyncClient | None = None,
        code_factory: Callable[[int], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._supabase_client = supabase_client
        self._resend_client = resend_client
        self._code_factory = code_factory or secrets.token_urlsafe
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _configuration(self) -> tuple[str, str, str, str]:
        project_url = self._settings.supabase_url.rstrip("/")
        service_key = self._settings.supabase_service_role_key
        resend_key = self._settings.resend_api_key
        sender = self._settings.matrix_email_from.strip()
        if not project_url.startswith("https://"):
            raise ActivationConfigurationError("Supabase project is not configured")
        if service_key is None or not service_key.get_secret_value():
            raise ActivationConfigurationError("Supabase admin access is not configured")
        if resend_key is None or not resend_key.get_secret_value():
            raise ActivationConfigurationError("Email delivery is not configured")
        if "@" not in sender or sender.startswith("replace-with"):
            raise ActivationConfigurationError("Email sender is not configured")
        return (
            project_url,
            service_key.get_secret_value(),
            resend_key.get_secret_value(),
            sender,
        )

    async def _supabase_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        payload: dict[str, str] | None = None,
        prefer: str | None = None,
    ) -> object:
        project_url, service_key, _, _ = self._configuration()
        headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Accept": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        url = f"{project_url}{path}"
        try:
            if self._supabase_client is not None:
                response = await self._supabase_client.request(
                    method,
                    url,
                    params=params,
                    headers=headers,
                    json=payload,
                )
            else:
                async with httpx.AsyncClient(
                    timeout=HTTP_TIMEOUT_SECONDS,
                    follow_redirects=False,
                ) as client:
                    response = await client.request(
                        method,
                        url,
                        params=params,
                        headers=headers,
                        json=payload,
                    )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ActivationDatabaseError("Activation database operation failed") from exc

    async def _resend(self, *, recipient: str, code: str) -> None:
        _, _, resend_key, sender = self._configuration()
        headers = {
            "Authorization": f"Bearer {resend_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "from": sender,
            "to": [recipient],
            "subject": "Your MATRIX activation code",
            "text": (
                "Your MATRIX activation code is below. It expires in seven days.\n\n"
                f"{code}\n\n"
                "If you did not request access, you can ignore this email."
            ),
        }
        try:
            if self._resend_client is not None:
                response = await self._resend_client.post(
                    RESEND_API_URL,
                    headers=headers,
                    json=payload,
                )
            else:
                async with httpx.AsyncClient(
                    timeout=HTTP_TIMEOUT_SECONDS,
                    follow_redirects=False,
                ) as client:
                    response = await client.post(
                        RESEND_API_URL,
                        headers=headers,
                        json=payload,
                    )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ActivationEmailDeliveryError("Activation email delivery failed") from exc

    async def _profile_status(self, *, user_id: UUID) -> _ProfileStatus:
        payload = await self._supabase_request(
            "GET",
            "/rest/v1/profiles",
            params={
                "select": "id,access_status,activation_completed_at",
                "id": f"eq.{user_id}",
                "limit": "2",
            },
        )
        if not isinstance(payload, list):
            raise ActivationDatabaseError("Profile response is invalid")
        if not payload:
            raise ActivationProfileNotFoundError("Profile does not exist")
        if len(payload) != 1 or not isinstance(payload[0], dict):
            raise ActivationDatabaseError("Profile identity is not unique")
        try:
            profile = _ProfileStatus.model_validate(payload[0])
        except ValidationError as exc:
            raise ActivationDatabaseError("Profile response is invalid") from exc
        if profile.access_status != "approved" or profile.activation_completed_at is not None:
            raise ActivationProfileIneligibleError("Profile is not eligible for activation")
        return profile

    async def _auth_user_email(self, *, user_id: UUID) -> str:
        payload = await self._supabase_request(
            "GET",
            f"/auth/v1/admin/users/{user_id}",
        )
        if not isinstance(payload, dict):
            raise ActivationRecipientError("Auth user email is unavailable")
        email = payload.get("email")
        if not isinstance(email, str) or "@" not in email:
            raise ActivationRecipientError("Auth user email is unavailable")
        return email

    async def _issue_rpc(self, *, user_id: UUID, code_hash: str, expires_at: datetime) -> UUID:
        payload = await self._supabase_request(
            "POST",
            "/rest/v1/rpc/issue_matrix_activation_code",
            payload={
                "p_user_id": str(user_id),
                "p_code_hash": code_hash,
                "p_expires_at": expires_at.isoformat(),
            },
        )
        try:
            # PostgREST represents a scalar UUID return as a JSON string.
            if not isinstance(payload, str):
                raise ValueError("RPC result is not a UUID string")
            return UUID(payload)
        except (ValueError, TypeError) as exc:
            raise ActivationDatabaseError("Activation issuance result is invalid") from exc

    async def _revoke_issued_code(self, *, user_id: UUID, record_id: UUID) -> None:
        payload = await self._supabase_request(
            "PATCH",
            "/rest/v1/activation_codes",
            params={
                "id": f"eq.{record_id}",
                "user_id": f"eq.{user_id}",
                "used_at": "is.null",
                "revoked_at": "is.null",
                "select": "id",
            },
            payload={"revoked_at": self._clock().astimezone(timezone.utc).isoformat()},
            prefer="return=representation",
        )
        if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
            raise ActivationRevocationError("New activation code revocation was not confirmed")
        if payload[0].get("id") != str(record_id):
            raise ActivationRevocationError("New activation code revocation was not confirmed")

    async def issue(self, *, user_id: UUID) -> datetime:
        # Validate all required credentials before creating any activation record.
        self._configuration()
        await self._profile_status(user_id=user_id)
        recipient = await self._auth_user_email(user_id=user_id)

        code = self._code_factory(32)
        if not isinstance(code, str) or not code:
            raise ActivationIssuanceError("Activation code generation failed")
        code = normalize_activation_code(code)
        if not code:
            raise ActivationIssuanceError("Activation code generation failed")
        code_hash = hash_activation_code(code)
        expires_at = self._clock().astimezone(timezone.utc) + ACTIVATION_TTL
        record_id = await self._issue_rpc(user_id=user_id, code_hash=code_hash, expires_at=expires_at)

        try:
            await self._resend(recipient=recipient, code=code)
        except ActivationEmailDeliveryError as exc:
            try:
                await self._revoke_issued_code(user_id=user_id, record_id=record_id)
            except ActivationIssuanceError as revoke_exc:
                raise ActivationRevocationError(
                    "Activation email failed and code revocation could not be confirmed"
                ) from revoke_exc
            raise ActivationEmailDeliveryError("Activation email failed; issued code was revoked") from exc

        # Do not return or retain plaintext/hash beyond this operation.
        return expires_at
