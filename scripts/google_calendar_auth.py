"""One-time local OAuth flow to get a Google Calendar refresh token for the
deployed Chronicle server -- run once on your own machine, not something the
server itself does. Prints the Fly secrets to set once it's done.

The server never runs an OAuth web flow of its own (no callback route, no
token storage in the data repo) -- it just holds a long-lived refresh token
as a Fly secret, same place MCP_TOKEN/VIEW_PASSWORD already live. See
google_calendar_service.py for how it's used.

Usage:
  export GOOGLE_CLIENT_ID=...      # from a Desktop-app OAuth client in
  export GOOGLE_CLIENT_SECRET=...  # Google Cloud Console (see README)
  uv run python scripts/google_calendar_auth.py
"""

import http.server
import os
import sys
import urllib.parse
import webbrowser

import httpx

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CALENDAR_LIST_URL = "https://www.googleapis.com/calendar/v3/users/me/calendarList"
SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
CALLBACK_TIMEOUT = 120  # seconds to wait for the browser redirect


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    code: str | None = None
    error: str | None = None

    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _CallbackHandler.code = params.get("code", [None])[0]
        _CallbackHandler.error = params.get("error", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Done -- you can close this tab and return to the terminal.")

    def log_message(self, *args):
        pass  # quiet -- don't spam stdout with HTTP log lines


def main():
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        sys.exit("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET first (see this script's docstring).")

    server = http.server.HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    server.timeout = CALLBACK_TIMEOUT
    redirect_uri = f"http://127.0.0.1:{server.server_port}/"

    auth_url = f"{AUTH_URL}?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",  # forces a refresh_token even on a repeat run
    })

    print(f"Opening your browser for Google sign-in (waiting up to {CALLBACK_TIMEOUT}s)...")
    print(f"If it doesn't open automatically:\n  {auth_url}\n")
    webbrowser.open(auth_url)

    server.handle_request()
    if _CallbackHandler.error:
        sys.exit(f"Google returned an error: {_CallbackHandler.error}")
    if not _CallbackHandler.code:
        sys.exit("Timed out waiting for the browser redirect -- try again.")

    r = httpx.post(TOKEN_URL, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "code": _CallbackHandler.code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }, timeout=15)
    r.raise_for_status()
    tokens = r.json()
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        sys.exit(
            "No refresh_token in the response -- Google only issues one on first "
            "consent for a given client. If you've run this before, revoke prior "
            "access at https://myaccount.google.com/permissions and try again."
        )

    print("\nGot a refresh token.\n")

    r = httpx.get(
        CALENDAR_LIST_URL,
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        timeout=15,
    )
    r.raise_for_status()
    calendars = r.json().get("items", [])

    print("Your calendars:")
    for cal in calendars:
        print(f"  {cal['id']:<55} {cal.get('summary', '')}")

    print(
        "\nSet the calendar IDs you want Chronicle to pull from (comma-separated, "
        "no spaces) below, then run:\n"
    )
    print(
        f"fly secrets set \\\n"
        f"  GOOGLE_CLIENT_ID={client_id} \\\n"
        f"  GOOGLE_CLIENT_SECRET={client_secret} \\\n"
        f"  GOOGLE_CALENDAR_REFRESH_TOKEN={refresh_token} \\\n"
        f"  GOOGLE_CALENDAR_IDS=<comma-separated ids from the list above>"
    )


if __name__ == "__main__":
    main()
