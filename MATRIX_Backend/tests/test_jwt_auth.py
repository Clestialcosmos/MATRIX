import asyncio
import base64
import time
from uuid import UUID, uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request

from app.api.dependencies.auth import get_authenticated_user, get_current_user_id
from app.core.config import Settings
from app.main import http_exception_handler
from app.services.supabase_jwt import (
    AuthenticatedUser,
    JWTConfigurationError,
    JWTVerificationError,
    SupabaseJWTVerifier,
)

ISSUER = "https://matrix-project.example.test/auth/v1"
JWKS_URL = "https://matrix-project.example.test/auth/v1/.well-known/jwks.json"
AUDIENCE = "authenticated-test"


def _b64url_int(value: int) -> str:
    raw = value.to_bytes(32, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _jwk(private_key: ec.EllipticCurvePrivateKey, kid: str = "test-key") -> dict[str, str]:
    numbers = private_key.public_key().public_numbers()
    return {
        "kty": "EC",
        "crv": "P-256",
        "use": "sig",
        "alg": "ES256",
        "kid": kid,
        "x": _b64url_int(numbers.x),
        "y": _b64url_int(numbers.y),
    }


def _token(
    private_key: ec.EllipticCurvePrivateKey,
    *,
    kid: str = "test-key",
    overrides: dict[str, object] | None = None,
    algorithm: str = "ES256",
) -> str:
    now = int(time.time())
    claims: dict[str, object] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": str(uuid4()),
        "iat": now,
        "nbf": now - 1,
        "exp": now + 3600,
    }
    claims.update(overrides or {})
    headers = {"kid": kid} if kid else {}
    signing_key: ec.EllipticCurvePrivateKey | str = private_key
    if algorithm != "ES256":
        signing_key = "x" * 32
    return jwt.encode(claims, signing_key, algorithm=algorithm, headers=headers)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "supabase_jwt_issuer": ISSUER,
        "supabase_jwks_url": JWKS_URL,
        "supabase_jwt_audience": AUDIENCE,
        "supabase_jwt_leeway_seconds": 0,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _mock_verifier(
    keys: list[dict[str, str]],
    settings: Settings | None = None,
    *,
    response_sequence: list[list[dict[str, str]]] | None = None,
) -> tuple[SupabaseJWTVerifier, list[int]]:
    calls = [0]

    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == JWKS_URL
        index = calls[0]
        calls[0] += 1
        selected = response_sequence[min(index, len(response_sequence) - 1)] if response_sequence else keys
        return httpx.Response(200, json={"keys": selected})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    verifier = SupabaseJWTVerifier(settings or _settings(), http_client=client)
    # Tests own this client and close it in each async test body.
    verifier.test_http_client = client
    return verifier, calls


def test_es256_token_is_verified_and_jwks_is_cached() -> None:
    private_key = ec.generate_private_key(ec.SECP256R1())
    token = _token(private_key)
    verifier, calls = _mock_verifier([_jwk(private_key)])

    async def run() -> UUID:
        async with verifier.test_http_client:
            first = await verifier.verify(token)
            second = await verifier.verify(token)
            assert first == second
            return first.user_id

    user_id = asyncio.run(run())
    assert isinstance(user_id, UUID)
    assert calls == [1]


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "https://wrong.example.test"},
        {"aud": "wrong-audience"},
        {"exp": int(time.time()) - 30},
        {"nbf": int(time.time()) + 300},
        {"sub": "not-a-uuid"},
        {"exp": None},
    ],
)
def test_claim_validation_rejects_invalid_tokens(overrides: dict[str, object]) -> None:
    private_key = ec.generate_private_key(ec.SECP256R1())
    token = _token(private_key, overrides=overrides)
    verifier, _ = _mock_verifier([_jwk(private_key)])

    async def run() -> None:
        async with verifier.test_http_client:
            with pytest.raises(JWTVerificationError):
                await verifier.verify(token)

    asyncio.run(run())


def test_non_es256_algorithm_is_rejected_before_jwks_fetch() -> None:
    private_key = ec.generate_private_key(ec.SECP256R1())
    token = _token(private_key, algorithm="HS256")
    verifier, calls = _mock_verifier([_jwk(private_key)])

    async def run() -> None:
        async with verifier.test_http_client:
            with pytest.raises(JWTVerificationError):
                await verifier.verify(token)

    asyncio.run(run())
    assert calls == [0]


def test_signature_must_match_published_jwk() -> None:
    published_key = ec.generate_private_key(ec.SECP256R1())
    different_key = ec.generate_private_key(ec.SECP256R1())
    token = _token(different_key)
    verifier, _ = _mock_verifier([_jwk(published_key)])

    async def run() -> None:
        async with verifier.test_http_client:
            with pytest.raises(JWTVerificationError):
                await verifier.verify(token)

    asyncio.run(run())


def test_unknown_kid_refreshes_jwks_once_for_key_rotation() -> None:
    old_key = ec.generate_private_key(ec.SECP256R1())
    new_key = ec.generate_private_key(ec.SECP256R1())
    token = _token(new_key, kid="rotated-key")
    verifier, calls = _mock_verifier(
        [_jwk(old_key)],
        response_sequence=[[_jwk(old_key)], [_jwk(new_key, "rotated-key")]],
    )

    async def run() -> UUID:
        async with verifier.test_http_client:
            return (await verifier.verify(token)).user_id

    assert isinstance(asyncio.run(run()), UUID)
    assert calls == [2]


def test_unsupported_jwks_curve_is_rejected() -> None:
    private_key = ec.generate_private_key(ec.SECP256R1())
    jwk = _jwk(private_key)
    jwk["crv"] = "P-384"
    token = _token(private_key)
    verifier, _ = _mock_verifier([jwk])

    async def run() -> None:
        async with verifier.test_http_client:
            with pytest.raises(JWTVerificationError):
                await verifier.verify(token)

    asyncio.run(run())


def test_missing_required_verification_configuration_fails_closed() -> None:
    verifier = SupabaseJWTVerifier(_settings(supabase_jwt_audience=""))

    async def run() -> None:
        with pytest.raises(JWTConfigurationError):
            await verifier.verify("not-a-token")

    asyncio.run(run())


def test_auth_dependency_returns_generic_401_and_existing_error_envelope() -> None:
    verifier = SupabaseJWTVerifier(_settings())

    async def run() -> None:
        cases = [
            (None, "Authentication required."),
            (HTTPAuthorizationCredentials(scheme="Bearer", credentials="not-a-jwt"), "Invalid or expired bearer token."),
        ]
        for credentials, expected_message in cases:
            with pytest.raises(HTTPException) as caught:
                await get_authenticated_user(credentials, verifier)
            assert caught.value.status_code == 401
            assert caught.value.headers == {"WWW-Authenticate": "Bearer"}

            request = Request({"type": "http", "method": "GET", "path": "/protected", "headers": []})
            response = await http_exception_handler(request, caught.value)
            body = response.body.decode("utf-8")
            assert response.status_code == 401
            assert '"code":"http_error"' in body
            assert expected_message in body
            assert "not-a-jwt" not in body

    asyncio.run(run())


def test_current_user_id_dependency_returns_verified_uuid() -> None:
    user_id = uuid4()

    async def run() -> UUID:
        return await get_current_user_id(AuthenticatedUser(user_id, "test-token"))

    assert asyncio.run(run()) == user_id
