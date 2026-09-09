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


def refresh_from_env() -> None:
    """Re-read env vars (used by tests after monkeypatch)."""
    global BFF_AUTH_SECRET, BFF_AUTH_SECRET_PREVIOUS, IMAGE_TAG, CHT_ENVIRONMENT
    BFF_AUTH_SECRET = os.environ.get("COMPANION_INTERNAL_SECRET", "").strip()
    BFF_AUTH_SECRET_PREVIOUS = os.environ.get(
        "COMPANION_INTERNAL_SECRET_PREVIOUS", ""
    ).strip()
    IMAGE_TAG = os.environ.get("IMAGE_TAG", "local")
    CHT_ENVIRONMENT = os.environ.get("CHT_ENVIRONMENT", "development").lower()


def is_dev() -> bool:
    return CHT_ENVIRONMENT in {"development", "dev", "local"} or os.environ.get(
        "ALLOW_KB_DEBUG", ""
    ).lower() in {"1", "true", "yes"}
