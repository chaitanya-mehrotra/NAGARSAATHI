from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import jwt
import pytest
from app.auth import OIDCTokens
from app.settings import Settings
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException


@pytest.fixture(scope="module")
def keys():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def verifier(keys):
    settings = Settings(
        _env_file=None,
        app_mode="test",
        auth_provider="oidc",
        oidc_issuer="https://issuer.example.invalid",
        oidc_audience="nagarsaathi",
        oidc_jwks_url="https://issuer.example.invalid/jwks",
    )
    jwks = Mock()
    jwks.get_signing_key_from_jwt.return_value.key = keys.public_key()
    return OIDCTokens(settings, jwks)


def token(keys, **changes):
    now = datetime.now(UTC)
    claims = {
        "sub": "demo-citizen",
        "iss": "https://issuer.example.invalid",
        "aud": "nagarsaathi",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    return jwt.encode({**claims, **changes}, keys, algorithm="RS256", headers={"kid": "test"})


def test_signed_identity_with_untrusted_roles(keys, verifier):
    assert verifier.subject(token(keys, roles=["admin"])) == "demo-citizen"


@pytest.mark.parametrize(
    "changes",
    [
        {"iss": "https://wrong.example.invalid"},
        {"aud": "different-service"},
        {"exp": datetime(2020, 1, 1, tzinfo=UTC)},
        {"sub": ""},
        {"sub": 42},
        {"iat": datetime(2099, 1, 1, tzinfo=UTC)},
    ],
)
def test_rejects_invalid_claims(keys, verifier, changes):
    with pytest.raises(HTTPException) as error:
        verifier.subject(token(keys, **changes))
    assert error.value.status_code == 401


def test_rejects_wrong_signature_and_algorithm(keys, verifier):
    wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    for bad in [
        token(wrong_key),
        jwt.encode({"sub": "demo-citizen"}, "x" * 32, algorithm="HS256"),
        "not-a-token",
        jwt.encode({"sub": "demo-citizen"}, keys, algorithm="RS256"),
    ]:
        with pytest.raises(HTTPException) as error:
            verifier.subject(bad)
        assert error.value.status_code == 401


def test_jwks_outage_does_not_authenticate(keys, verifier):
    verifier.jwks.get_signing_key_from_jwt.side_effect = jwt.PyJWKClientConnectionError("offline")
    with pytest.raises(HTTPException) as error:
        verifier.subject(token(keys))
    assert error.value.status_code == 503
