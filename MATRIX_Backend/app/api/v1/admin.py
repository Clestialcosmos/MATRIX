from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies.auth import get_current_admin_user
from app.core.config import get_settings
from app.repositories.admin_profiles import (
    AdminProfileNotFoundError,
    AdminProfilesConfigurationError,
    AdminProfilesDatabaseError,
    InvalidApprovalTransitionError,
    SupabaseAdminProfilesRepository,
)
from app.schemas.activation import ActivationIssuanceResponse
from app.schemas.admin import AdminProfileSummary
from app.services.activation_issuance import (
    ActivationConfigurationError,
    ActivationDatabaseError,
    ActivationEmailDeliveryError,
    ActivationIssuanceError,
    ActivationIssuanceService,
    ActivationProfileIneligibleError,
    ActivationProfileNotFoundError,
    ActivationRecipientError,
    ActivationRevocationError,
)
from app.services.supabase_jwt import AuthenticatedUser

router = APIRouter(prefix="/admin/profiles", tags=["Admin"])


@router.get("/pending", response_model=list[AdminProfileSummary])
async def list_pending_profiles(
    _admin: Annotated[AuthenticatedUser, Depends(get_current_admin_user)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AdminProfileSummary]:
    # Instantiate and use service-role repository only after admin authorization succeeds.
    repository = SupabaseAdminProfilesRepository(get_settings())
    try:
        return await repository.list_pending(limit=limit, offset=offset)
    except AdminProfilesConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin profile service is not configured.",
        ) from exc
    except AdminProfilesDatabaseError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin profile service is unavailable.",
        ) from exc


@router.get("/approved-awaiting-activation", response_model=list[AdminProfileSummary])
async def list_approved_awaiting_activation(
    _admin: Annotated[AuthenticatedUser, Depends(get_current_admin_user)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AdminProfileSummary]:
    # Authorization is complete before the service-role repository is constructed.
    repository = SupabaseAdminProfilesRepository(get_settings())
    try:
        return await repository.list_approved_awaiting_activation(limit=limit, offset=offset)
    except AdminProfilesConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin profile service is not configured.",
        ) from exc
    except AdminProfilesDatabaseError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin profile service is unavailable.",
        ) from exc


@router.post("/{user_id}/approve", response_model=AdminProfileSummary)
async def approve_profile(
    user_id: UUID,
    _admin: Annotated[AuthenticatedUser, Depends(get_current_admin_user)],
) -> AdminProfileSummary:
    # Instantiate and use service-role repository only after admin authorization succeeds.
    repository = SupabaseAdminProfilesRepository(get_settings())
    try:
        return await repository.approve_pending(user_id=user_id)
    except AdminProfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile is not available.",
        ) from exc
    except InvalidApprovalTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Profile is not pending approval.",
        ) from exc
    except AdminProfilesConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin profile service is not configured.",
        ) from exc
    except AdminProfilesDatabaseError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin profile service is unavailable.",
        ) from exc


@router.post("/{user_id}/activation-code", response_model=ActivationIssuanceResponse)
async def issue_activation_code(
    user_id: UUID,
    _admin: Annotated[AuthenticatedUser, Depends(get_current_admin_user)],
) -> ActivationIssuanceResponse:
    # The admin dependency completes before the service reads/uses service-role credentials.
    service = ActivationIssuanceService(get_settings())
    try:
        expires_at = await service.issue(user_id=user_id)
    except ActivationProfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile is not available.",
        ) from exc
    except ActivationProfileIneligibleError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Profile is not eligible for activation.",
        ) from exc
    except ActivationRecipientError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Activation delivery is not available.",
        ) from exc
    except (ActivationEmailDeliveryError, ActivationRevocationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Activation email could not be sent.",
        ) from exc
    except (ActivationConfigurationError, ActivationDatabaseError, ActivationIssuanceError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Activation issuance is unavailable.",
        ) from exc
    return ActivationIssuanceResponse(
        user_id=user_id,
        expires_at=expires_at,
        email_delivery="accepted",
    )
