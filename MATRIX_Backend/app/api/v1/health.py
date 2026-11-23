from fastapi import APIRouter

from app.schemas.health import HealthResponse

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
async def versioned_health_check() -> HealthResponse:
    """Return the versioned API health status."""
    return HealthResponse()
