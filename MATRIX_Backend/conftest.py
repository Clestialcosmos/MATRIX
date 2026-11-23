"""conftest.py — pytest configuration and shared fixtures for the MATRIX backend."""
from __future__ import annotations

import pytest


# Ensure the app module resolves settings from environment without a real .env
# during test runs. All settings that need non-empty values are overridden
# inside individual test modules using monkeypatch or the Settings constructor.
