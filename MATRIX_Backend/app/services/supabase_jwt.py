from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx
import jwt

from app.core.config import Settings

ALGORITHM = "ES256"
JWKS_CACHE_SECONDS = 300
JWKS_TIMEOUT_SECONDS = 5.0


class JWTVerificationError(Exception):
    """Raised when a bearer token cannot be verified."""


class JWTConfigurationError(Exception):
    """Raised when required JWT verification configuration is missing/unsafe."""


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: UUID
    access_token: str = field(repr=False)


class SupabaseJWTVerifier:
    """Verify Supabase access JWTs using a fixed ES256 policy and configured JWKS."""

    def __init__(
        self,
        settings: Settings,
        *,
        http_client: httpx.AsyncClient | None = None,
        cache_seconds: int = JWKS_CACHE_SECONDS,
    ) -> None:
        self._settings = settings
        self._http_client = http_client
        self._cache_seconds = cache_seconds
        self._jwks: dict[str, dict[str, Any]] = {}
        self._jwks_expires_at = 0.0
        self._cache_lock = asyncio.Lock()

    def _validate_configuration(self) -> None:
        issuer = urlparse(self._settings.supabase_jwt_issuer)
        if issuer.scheme != "https" or not issuer.netloc:
            raise JWTConfigurationError("JWT issuer is not configured")
        if not self._settings.supabase_jwt_audience.strip():
            raise JWTConfigurationError("JWT audience is not configured")
        parsed = urlparse(self._settings.supabase_jwks_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise JWTConfigurationError("An HTTPS JWKS URL is not configured")
        if not 0 <= self._settings.supabase_jwt_leeway_seconds <= 120:
            raise JWTConfigurationError("JWT clock leeway is outside the supported range")

    async def _fetch_jwks(self) -> dict[str, dict[str, Any]]:
        if self._http_client is not None:
            response = await self._http_client.get(self._settings.supabase_jwks_url)
        else:
            async with httpx.AsyncClient(
                timeout=JWKS_TIMEOUT_SECONDS,
                follow_redirects=False,
            ) as client:
                response = await client.get(self._settings.supabase_jwks_url)
        response.raise_for_status()
        body = response.json()
        raw_keys = body.get("keys") if isinstance(body, dict) else None
        if not isinstance(raw_keys, list):
            raise JWTVerificationError("JWKS response is invalid")

        keys: dict[str, dict[str, Any]] = {}
        for raw_key in raw_keys:
            if not isinstance(raw_key, dict):
                continue
            kid = raw_key.get("kid")
            if not isinstance(kid, str) or not kid:
                continue
            # Supabase's configured ECC P-256 key is accepted only for ES256.
            if (
                raw_key.get("kty") != "EC"
                or raw_key.get("crv") != "P-256"
                or raw_key.get("use", "sig") != "sig"
                or raw_key.get("alg", ALGORITHM) != ALGORITHM
                or (
                    "key_ops" in raw_key
                    and (not isinstance(raw_key["key_ops"], list) or "verify" not in raw_key["key_ops"])
                )
            ):
                continue
            if kid in keys:
                raise JWTVerificationError("JWKS contains duplicate key identifiers")
            keys[kid] = raw_key
        if not keys:
            raise JWTVerificationError("JWKS has no supported signing keys")
        return keys

    async def _get_jwks(self, *, force_refresh: bool = False) -> dict[str, dict[str, Any]]:
        async with self._cache_lock:
            if not force_refresh and self._jwks and time.monotonic() < self._jwks_expires_at:
                return self._jwks
            try:
                keys = await self._fetch_jwks()
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                raise JWTVerificationError("Signing keys are unavailable") from exc
            self._jwks = keys
            self._jwks_expires_at = time.monotonic() + self._cache_seconds
            return keys

    async def verify(self, token: str) -> AuthenticatedUser:
        self._validate_configuration()
        if not token or len(token) > 16_384:
            raise JWTVerificationError("Invalid bearer token")

        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise JWTVerificationError("Invalid bearer token") from exc

        kid = header.get("kid")
        if header.get("alg") != ALGORITHM or not isinstance(kid, str) or not kid:
            raise JWTVerificationError("Invalid bearer token")

        keys = await self._get_jwks()
        jwk_data = keys.get(kid)
        if jwk_data is None:
            # Allow for key rotation while keeping the JWKS URL fixed by config.
            keys = await self._get_jwks(force_refresh=True)
            jwk_data = keys.get(kid)
        if jwk_data is None:
            raise JWTVerificationError("Invalid bearer token")

        try:
            jwk = jwt.PyJWK.from_dict(jwk_data, algorithm=ALGORITHM)
            claims = jwt.decode(
                token,
                key=jwk.key,
                algorithms=[ALGORITHM],
                issuer=self._settings.supabase_jwt_issuer,
                audience=self._settings.supabase_jwt_audience,
                leeway=self._settings.supabase_jwt_leeway_seconds,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
            user_id = UUID(claims["sub"])
        except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
            raise JWTVerificationError("Invalid bearer token") from exc

        return AuthenticatedUser(user_id=user_id, access_token=token)
