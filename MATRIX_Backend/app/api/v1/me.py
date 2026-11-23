from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies.auth import get_app_settings, get_authenticated_user
from app.core.config import Settings
from app.repositories.profiles import (
    ProfileConfigurationError,
    ProfileDataError,
    ProfileDatabaseError,
    ProfileNotFoundError,
    SupabaseProfilesRepository,
)
from app.schemas.access import UserAccessResponse
from app.services.supabase_jwt import AuthenticatedUser

router = APIRouter(tags=["Account"])


def get_profiles_repository(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> SupabaseProfilesRepository:
    return SupabaseProfilesRepository(settings)


@router.get("/me/access", response_model=UserAccessResponse)
async def get_my_access(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    repository: Annotated[SupabaseProfilesRepository, Depends(get_profiles_repository)],
) -> UserAccessResponse:
    try:
        profile = await repository.get_for_user(
            user_id=user.user_id,
            access_token=user.access_token,
        )
    except ProfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile is not available.",
        ) from exc
    except ProfileConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Profile service is not configured.",
        ) from exc
    except (ProfileDataError, ProfileDatabaseError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Profile service is unavailable.",
        ) from exc

    return UserAccessResponse(
        user_id=user.user_id,
        full_name=profile.full_name,
        access_status=profile.access_status,
        activation_completed_at=profile.activation_completed_at,
        has_matrix_access=profile.activation_completed_at is not None,
    )
