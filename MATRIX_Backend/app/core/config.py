from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed settings. Secret values are masked when represented."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    frontend_origins: str = "http://localhost:5173"

    # JWT verification and caller-scoped profile reads; service-role access remains unused.
    supabase_url: str = ""
    supabase_anon_key: SecretStr | None = None
    supabase_service_role_key: SecretStr | None = None
    supabase_jwt_issuer: str = ""
    supabase_jwks_url: str = ""
    supabase_jwt_audience: str = ""
    supabase_jwt_leeway_seconds: int = 30
    supabase_profile_user_id_column: str = ""
    matrix_admin_user_id: str = ""
    resend_api_key: SecretStr | None = None
    matrix_email_from: str = ""

    # Server-only MATRIX Agent Layer integration. Never expose these to Vite.
    n8n_webhook_url: str = ""
    n8n_auth_header_name: str = ""
    n8n_auth_header_value: SecretStr | None = None
    n8n_timeout_seconds: int = 240
    matrix_report_bucket: str = "matrix-reports"

    @property
    def frontend_origin_list(self) -> list[str]:
        """Parse a comma-separated allowlist without accepting an implicit wildcard."""
        return [origin.strip() for origin in self.frontend_origins.split(",") if origin.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
