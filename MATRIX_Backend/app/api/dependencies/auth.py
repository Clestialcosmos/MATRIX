from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings
from app.services.supabase_jwt import (
    AuthenticatedUser,
    JWTConfigurationError,
    JWTVerificationError,
    SupabaseJWTVerifier,
)

_bearer_scheme = HTTPBearer(auto_error=False, scheme_name="SupabaseAccessToken")


def get_jwt_verifier(request: Request) -> SupabaseJWTVerifier:
    verifier = getattr(request.app.state, "supabase_jwt_verifier", None)
    if verifier is None:
        verifier = SupabaseJWTVerifier(get_settings())
        request.app.state.supabase_jwt_verifier = verifier
    return verifier


def get_app_settings() -> Settings:
    return get_settings()


async def get_authenticated_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    verifier: Annotated[SupabaseJWTVerifier, Depends(get_jwt_verifier)],
) -> AuthenticatedUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return await verifier.verify(credentials.credentials)
    except JWTConfigurationError as exc:
        # Misconfiguration is a server failure, not an invalid-credential response.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is unavailable.",
        ) from exc
    except JWTVerificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def get_current_user_id(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
) -> UUID:
    """Reusable identity dependency; the UUID comes only from the verified JWT."""
    return user.user_id


async def get_current_admin_user(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> AuthenticatedUser:
    """Require the verified JWT subject to match the configured admin UUID."""
    configured_admin_id = settings.matrix_admin_user_id.strip()
    try:
        admin_user_id = UUID(configured_admin_id)
    except (ValueError, AttributeError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin authorization is not configured.",
        ) from exc
    if admin_user_id != user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator authorization required.",
        )
    return user
