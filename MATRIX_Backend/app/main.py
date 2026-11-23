from __future__ import annotations

import logging
import time
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.health import router as v1_health_router
from app.api.v1.admin import router as admin_router
from app.api.v1.activation import router as activation_router
from app.api.v1.me import router as me_router
from app.api.v1.assessments import router as assessments_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.schemas.errors import ErrorDetail, ErrorResponse
from app.schemas.health import HealthResponse
from app.services.supabase_jwt import SupabaseJWTVerifier

settings = get_settings()
configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(
    title="MATRIX API",
    description="MATRIX API with authenticated Agent Layer assessments and private reports.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)
app.state.supabase_jwt_verifier = SupabaseJWTVerifier(settings)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.frontend_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid4().hex
    request.state.request_id = request_id
    started_at = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
    logger.info(
        "request_complete method=%s path=%s status=%s duration_ms=%s request_id=%s",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
        request_id,
    )
    return response


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, object]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", uuid4().hex)
    body = ErrorResponse(
        error=ErrorDetail(code=code, message=message, details=details),
        request_id=request_id,
    )
    response_headers = dict(headers or {})
    response_headers["X-Request-ID"] = request_id
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json", exclude_none=True),
        headers=response_headers,
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    if isinstance(exc.detail, str):
        code, message, details = "http_error", exc.detail, None
    elif isinstance(exc.detail, dict):
        code = str(exc.detail.get("code", "http_error"))
        message = str(exc.detail.get("message", "Request failed."))
        details = [{key: value for key, value in exc.detail.items() if key not in {"code", "message"}}]
    else:
        code, message, details = "http_error", "Request failed.", None
    return _error_response(
        request,
        status_code=exc.status_code,
        code=code,
        message=message,
        details=details,
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    safe_errors = [
        {
            "location": [str(part) for part in error.get("loc", ())],
            "message": str(error.get("msg", "Invalid value.")),
            "type": str(error.get("type", "value_error")),
        }
        for error in exc.errors()
    ]
    return _error_response(
        request,
        status_code=422,
        code="validation_error",
        message="The request did not pass validation.",
        details=safe_errors,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    logger.error(
        "unhandled_exception request_id=%s",
        request_id,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return _error_response(
        request,
        status_code=500,
        code="internal_error",
        message="An unexpected error occurred.",
    )


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check() -> HealthResponse:
    """Return the basic process health status."""
    return HealthResponse()


app.include_router(v1_health_router, prefix="/api/v1")
app.include_router(me_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(activation_router, prefix="/api/v1")
app.include_router(assessments_router, prefix="/api/v1")


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"name": "MATRIX API", "docs": "/docs", "health": "/health"}
