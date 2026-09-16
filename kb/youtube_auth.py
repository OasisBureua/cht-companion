"""YouTube OAuth credential resolution for caption fetch (CHAT-19/20).

Mirrors store.py's DATABASE_SECRET_ARN pattern: fetch once from Secrets
Manager at cold start, cache for the life of the execution environment.
Unlike the DB secret, this one was created manually (channel-owner OAuth
consent, not something Terraform can generate — see
kb/scripts/get_youtube_refresh_token.py and the data source in
infrastructure/terraform/environments/us-east-1/main.tf), but the read path
is identical.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache

import boto3
from google.oauth2.credentials import Credentials

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
YOUTUBE_OAUTH_SECRET_ARN_ENV = "YOUTUBE_OAUTH_SECRET_ARN"

# youtube.force-ssl is required for captions.download — youtube.readonly is
# not sufficient (confirmed against YouTube Data API v3 docs; readonly can
# list caption tracks but cannot download their text).
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
TOKEN_URI = "https://oauth2.googleapis.com/token"


@lru_cache(maxsize=1)
def _secretsmanager_client():
    return boto3.client("secretsmanager", region_name=AWS_REGION)


class YouTubeAuthError(Exception):
    pass


@lru_cache(maxsize=1)
def _oauth_payload() -> dict[str, str]:
    secret_arn = os.environ.get(YOUTUBE_OAUTH_SECRET_ARN_ENV, "").strip()
    if not secret_arn:
        raise YouTubeAuthError(f"{YOUTUBE_OAUTH_SECRET_ARN_ENV} is not set")

    response = _secretsmanager_client().get_secret_value(SecretId=secret_arn)
    payload = json.loads(response["SecretString"])

    missing = [k for k in ("client_id", "client_secret", "refresh_token") if not payload.get(k)]
    if missing:
        raise YouTubeAuthError(f"YouTube OAuth secret missing fields: {missing}")

    return payload


def get_credentials() -> Credentials:
    """Build a google.oauth2.credentials.Credentials from the stored refresh
    token. google-auth handles exchanging it for a short-lived access token
    (and re-exchanging on expiry) transparently on first use.
    """
    payload = _oauth_payload()
    return Credentials(
        token=None,  # no cached access token — refresh_token forces a fresh exchange
        refresh_token=payload["refresh_token"],
        client_id=payload["client_id"],
        client_secret=payload["client_secret"],
        token_uri=TOKEN_URI,
        scopes=SCOPES,
    )
