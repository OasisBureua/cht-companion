"""Runtime config for cht-companion (SCRUM-195)."""

from __future__ import annotations

import os

API_VERSION = "1.0.0"
PROMPT_VERSION = "chat/v0-placeholder"

# Secrets Manager → env at task start (placeholder until wired in Terraform).
BFF_AUTH_SECRET = os.environ.get("COMPANION_INTERNAL_SECRET", "").strip()
BFF_AUTH_SECRET_PREVIOUS = os.environ.get("COMPANION_INTERNAL_SECRET_PREVIOUS", "").strip()

IMAGE_TAG = os.environ.get("IMAGE_TAG", "local")
CHT_ENVIRONMENT = os.environ.get("CHT_ENVIRONMENT", "development").lower()

# Inbound auth. "secret": X-BFF-Auth only. "m2m": Cognito bearer token only.
# "either": bearer token when the caller sends one, otherwise X-BFF-Auth.
AUTH_MODES = ("secret", "either", "m2m")
AUTH_MODE = os.environ.get("COMPANION_AUTH_MODE", "secret").strip().lower()
M2M_ISSUER = os.environ.get("COMPANION_M2M_ISSUER", "").strip()
M2M_JWKS_URL = os.environ.get("COMPANION_M2M_JWKS_URL", "").strip()
M2M_RESOURCE = os.environ.get("COMPANION_M2M_RESOURCE", "companion").strip().strip("/")
# HS256 key for unit tests only; never set in AWS.
M2M_TEST_SECRET = os.environ.get("COMPANION_M2M_TEST_SECRET", "").strip()


def refresh_from_env() -> None:
    """Re-read env vars (used by tests after monkeypatch)."""
    global BFF_AUTH_SECRET, BFF_AUTH_SECRET_PREVIOUS, IMAGE_TAG, CHT_ENVIRONMENT
    global AUTH_MODE, M2M_ISSUER, M2M_JWKS_URL, M2M_RESOURCE, M2M_TEST_SECRET
    BFF_AUTH_SECRET = os.environ.get("COMPANION_INTERNAL_SECRET", "").strip()
    BFF_AUTH_SECRET_PREVIOUS = os.environ.get(
        "COMPANION_INTERNAL_SECRET_PREVIOUS", ""
    ).strip()
    IMAGE_TAG = os.environ.get("IMAGE_TAG", "local")
    CHT_ENVIRONMENT = os.environ.get("CHT_ENVIRONMENT", "development").lower()
    AUTH_MODE = os.environ.get("COMPANION_AUTH_MODE", "secret").strip().lower()
    M2M_ISSUER = os.environ.get("COMPANION_M2M_ISSUER", "").strip()
    M2M_JWKS_URL = os.environ.get("COMPANION_M2M_JWKS_URL", "").strip()
    M2M_RESOURCE = os.environ.get("COMPANION_M2M_RESOURCE", "companion").strip().strip("/")
    M2M_TEST_SECRET = os.environ.get("COMPANION_M2M_TEST_SECRET", "").strip()


def is_dev() -> bool:
    return CHT_ENVIRONMENT in {"development", "dev", "local"} or os.environ.get(
        "ALLOW_KB_DEBUG", ""
    ).lower() in {"1", "true", "yes"}
