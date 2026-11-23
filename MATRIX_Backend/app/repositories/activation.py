from __future__ import annotations

from uuid import UUID

import httpx
from pydantic import SecretStr

from app.core.config import Settings

DATABASE_TIMEOUT_SECONDS = 8.0


class ActivationRPCError(Exception):
    """A safe activation RPC failure without request/token details."""


class SupabaseActivationRepository:
    """Call consume_activation_code with the authenticated user's JWT and anon key."""

    def __init__(self, settings: Settings, *, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client

    async def consume(
        self,
        *,
        user_id: UUID,
        code_hash: str,
        access_token: str,
    ) -> bool:
        project_url = self._settings.supabase_url.rstrip("/")
        anon_key: SecretStr | None = self._settings.supabase_anon_key
        if not project_url.startswith("https://") or anon_key is None or not anon_key.get_secret_value():
            raise ActivationRPCError("Activation service is not configured")

        headers = {
            "apikey": anon_key.get_secret_value(),
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }
        payload = {
            "p_user_id": str(user_id),
            "p_code_hash": code_hash,
        }
        url = f"{project_url}/rest/v1/rpc/consume_activation_code"
        try:
            if self._client is not None:
                response = await self._client.post(url, headers=headers, json=payload)
            else:
                async with httpx.AsyncClient(
                    timeout=DATABASE_TIMEOUT_SECONDS,
                    follow_redirects=False,
                ) as client:
                    response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ActivationRPCError("Activation service is unavailable") from exc

        if not isinstance(result, bool):
            raise ActivationRPCError("Activation service returned an invalid response")
        return result
