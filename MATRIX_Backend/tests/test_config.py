from app.core.config import Settings


def test_settings_defaults_are_local_and_non_secret() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_env == "development"
    assert settings.app_host == "127.0.0.1"
    assert settings.app_port == 8000
    assert settings.frontend_origin_list == ["http://localhost:5173"]
    assert settings.supabase_url == ""
    assert settings.supabase_service_role_key is None


def test_settings_load_environment_and_parse_frontend_origins(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_HOST", "127.0.0.2")
    monkeypatch.setenv("APP_PORT", "8123")
    monkeypatch.setenv("FRONTEND_ORIGINS", "http://localhost:5173, https://matrix.example.test ")
    monkeypatch.setenv("MATRIX_ADMIN_USER_ID", "00000000-0000-4000-8000-000000000001")

    settings = Settings(_env_file=None)

    assert settings.app_env == "test"
    assert settings.app_host == "127.0.0.2"
    assert settings.app_port == 8123
    assert settings.frontend_origin_list == [
        "http://localhost:5173",
        "https://matrix.example.test",
    ]
    assert settings.matrix_admin_user_id == "00000000-0000-4000-8000-000000000001"
