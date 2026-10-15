"""Inbound Cognito M2M (client_credentials) access tokens.

Same scheme as cht-content-hub's backend/src/auth/m2m.py: RS256 via the
pool's JWKS in AWS, HS256 via COMPANION_M2M_TEST_SECRET in unit tests.
Companion owns the `companion` resource server, so token scopes look like
`companion/chat.invoke`.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

import jwt
from jwt import PyJWKClient

from api import config

logger = logging.getLogger("cht-companion.auth")


class InvalidToken(Exception):
    pass


@lru_cache(maxsize=4)
def _jwks_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url, cache_jwk_set=True, lifespan=3600)


def _jwks_url() -> str:
    if config.M2M_JWKS_URL:
        return config.M2M_JWKS_URL.rstrip("/")
    return f"{config.M2M_ISSUER.rstrip('/')}/.well-known/jwks.json"


def issuer_aliases(issuer: str) -> list[str]:
    """Cognito access tokens may carry either the cognito-idp or the
    issuer-cognito-idp host in `iss`; accept both."""
    value = issuer.strip().rstrip("/")
    if not value:
        return []
    aliases = {value}
    if "://issuer-cognito-idp." in value:
        aliases.add(value.replace("://issuer-cognito-idp.", "://cognito-idp.", 1))
    elif "://cognito-idp." in value:
        aliases.add(value.replace("://cognito-idp.", "://issuer-cognito-idp.", 1))
    return sorted(aliases)


def token_scopes(payload: dict[str, Any]) -> set[str]:
    raw = payload.get("scope") or payload.get("scp") or ""
    if isinstance(raw, list):
        return {str(item) for item in raw if item}
    return {part for part in str(raw).split() if part}


def full_scope(name: str) -> str:
    return f"{config.M2M_RESOURCE}/{name}"


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        if config.M2M_TEST_SECRET:
            kwargs: dict[str, Any] = {"algorithms": ["HS256"], "options": {"require": ["exp"]}}
            if config.M2M_ISSUER:
                kwargs["issuer"] = config.M2M_ISSUER
            payload = jwt.decode(token, config.M2M_TEST_SECRET, **kwargs)
        else:
            if not config.M2M_ISSUER:
                raise InvalidToken("M2M issuer is not configured")
            signing_key = _jwks_client(_jwks_url()).get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                issuer=issuer_aliases(config.M2M_ISSUER),
                # Cognito access tokens have no `aud`; scopes are the access check.
                options={"verify_aud": False, "require": ["exp", "iss"]},
            )
    except InvalidToken:
        raise
    except Exception as exc:  # noqa: BLE001 — any decode/JWKS failure is a 401
        logger.info("m2m_token_rejected: %s", exc)
        raise InvalidToken("invalid bearer token") from exc

    if payload.get("token_use", "access") != "access":
        raise InvalidToken("not an access token")
    return payload
