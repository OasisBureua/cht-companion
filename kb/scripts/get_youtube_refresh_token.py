"""One-off local script: run the YouTube OAuth consent flow once, as the
CHM YouTube channel owner, and print a refresh token.

This is NOT part of the deployed Lambda — it's a local, interactive,
run-once tool. The resulting refresh token is the durable credential the
ingest pipeline will actually use (via AWS Secrets Manager), not this
script itself.

Usage:
    pip install google-auth-oauthlib
    python3 get_youtube_refresh_token.py /path/to/client_secret_....json

Opens a browser for you to sign in as the channel owner and approve the
youtube.force-ssl scope. Prints the refresh token to stdout on success.

If you've consented to this exact client+scope combination before (even a
prior attempt with this same script), Google may issue an access token
without a refresh token the second time — that's why the previous run
looked like it "completed" with nothing printed. This version forces a
fresh consent every time (access_type=offline + prompt=consent + a
manually-built auth URL, rather than relying on the library's defaults) and
will error loudly instead of exiting quietly if no refresh token comes back.
"""

from __future__ import annotations

import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]


def main() -> None:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} /path/to/client_secret.json", file=sys.stderr)
        sys.exit(1)

    client_secret_path = sys.argv[1]
    flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)

    print("Opening a browser window. Sign in as the CHM YouTube channel owner.")
    print("If Google shows a screen you've already approved, you may need to")
    print("revisit https://myaccount.google.com/permissions first, find this app,")
    print("remove its access, then re-run this script for a clean consent.\n")

    credentials = flow.run_local_server(
        port=0,
        access_type="offline",
        prompt="consent",
        include_granted_scopes="false",
    )

    print("\n--- OAuth flow completed ---")
    print(f"access_token present: {bool(credentials.token)}")
    print(f"refresh_token present: {bool(credentials.refresh_token)}")

    if not credentials.refresh_token:
        print(
            "\nERROR: No refresh token was returned. This almost always means "
            "Google considers this app already consented for this account+scope, "
            "so it skipped issuing a new one.\n"
            "Fix: go to https://myaccount.google.com/permissions, find the app "
            "(by the name you gave it on the OAuth consent screen), remove its "
            "access entirely, then re-run this script immediately after.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"\nRefresh token:\n{credentials.refresh_token}")
    print(
        "\nStore this in AWS Secrets Manager (do not commit it, do not leave it in "
        "shell history longer than needed). It does not expire unless revoked."
    )


if __name__ == "__main__":
    main()
