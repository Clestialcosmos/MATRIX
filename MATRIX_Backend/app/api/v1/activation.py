from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies.auth import get_app_settings, get_authenticated_user
from app.api.v1.me import get_profiles_repository
from app.core.config import Settings
from app.repositories.activation import ActivationRPCError, SupabaseActivationRepository
from app.repositories.profiles import (
    ProfileConfigurationError,
    ProfileDataError,
    ProfileDatabaseError,
    ProfileNotFoundError,
    SupabaseProfilesRepository,
)
from app.schemas.access import UserAccessResponse
from app.schemas.activation import ActivationConsumeRequest, ActivationConsumeResponse
from app.services.activation_codes import hash_activation_code
from app.services.supabase_jwt import AuthenticatedUser

router = APIRouter(prefix="/activation", tags=["Activation"])


def get_activation_repository(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> SupabaseActivationRepository:
    return SupabaseActivationRepository(settings)


@router.post("/consume", response_model=ActivationConsumeResponse)
async def consume_activation_code(
    body: ActivationConsumeRequest,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    repository: Annotated[SupabaseActivationRepository, Depends(get_activation_repository)],
    profiles: Annotated[SupabaseProfilesRepository, Depends(get_profiles_repository)],
) -> ActivationConsumeResponse:
    normalized_code = body.activation_code.get_secret_value().strip()
    # Case and symbols are preserved because generated codes are case-sensitive.
    code_hash = hash_activation_code(normalized_code)
    try:
        consumed = await repository.consume(
            user_id=user.user_id,
            code_hash=code_hash,
            access_token=user.access_token,
        )
    except ActivationRPCError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Activation service is unavailable.",
        ) from exc
    if not consumed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Activation code is invalid or unavailable.",
        )

    try:
        profile = await profiles.get_for_user(
            user_id=user.user_id,
            access_token=user.access_token,
        )
    except (ProfileConfigurationError, ProfileDataError, ProfileDatabaseError, ProfileNotFoundError) as exc:
        # The consume RPC has completed; the caller can retry GET /api/v1/me/access.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Activation succeeded, but access status is temporarily unavailable.",
        ) from exc

    if profile.activation_completed_at is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Activation succeeded, but access status is temporarily unavailable.",
        )

    access = UserAccessResponse(
        user_id=user.user_id,
        full_name=profile.full_name,
        access_status=profile.access_status,
        activation_completed_at=profile.activation_completed_at,
        has_matrix_access=True,
    )
    return ActivationConsumeResponse(status="activated", access=access)
