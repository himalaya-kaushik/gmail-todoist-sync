#!/usr/bin/env python3
"""
One-time helper: OAuth2 browser flow → token.json

Run this script ONCE on a machine with a browser to generate a
token.json file.  Then copy its contents into the GitHub Secret
named GOOGLE_TOKEN_JSON.

Prerequisites:
  1. Download your OAuth2 client credentials from Google Cloud Console
     and save them as  credentials.json  in this directory.
  2. pip install google-auth google-auth-oauthlib
"""

import json
import os
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"


def main():
    if not os.path.exists(CREDENTIALS_FILE):
        print(
            f"ERROR: '{CREDENTIALS_FILE}' not found in the current directory.\n"
            "Download it from Google Cloud Console → APIs & Services → Credentials → "
            "OAuth 2.0 Client IDs → Download JSON, and save it here.",
            file=sys.stderr,
        )
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
    creds = flow.run_local_server(port=0)

    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }

    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f, indent=2)

    print(f"\n✅ Token saved to {TOKEN_FILE}")
    print(
        "\n📋 Next step:\n"
        "   Copy the ENTIRE contents of token.json into your GitHub Secret\n"
        "   named  GOOGLE_TOKEN_JSON\n"
        "\n   Settings → Secrets and variables → Actions → New repository secret"
    )


if __name__ == "__main__":
    main()
