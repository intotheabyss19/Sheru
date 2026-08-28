"""One-time import of Google Contacts (name → phone) into Sheru's own book, via the Google People API.

No macOS Contacts involved. Run: `uv run sheru import-contacts` (opens a browser to consent once).

First-time setup (see docs/google-contacts-setup.md for the click-by-click):
  1. console.cloud.google.com → new project → enable the **People API**.
  2. OAuth consent screen → External → add yourself as a test user.
  3. Credentials → Create OAuth client ID → **Desktop app** → download the JSON.
  4. Save it as  data/google_credentials.json  (gitignored). Then run the import.

Credentials + the cached token stay in gitignored data/.
"""
from __future__ import annotations

from . import config
from .actions import contacts_book

SCOPES = ["https://www.googleapis.com/auth/contacts.readonly"]


def _paths():
    return config.DATA_DIR / "google_credentials.json", config.DATA_DIR / "google_token.json"


def _authenticate():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    cred_path, token_path = _paths()
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not cred_path.exists():
                raise FileNotFoundError(
                    f"Missing {cred_path.name}. Download an OAuth 'Desktop app' client JSON from Google Cloud "
                    "(People API enabled) and save it to data/google_credentials.json — see docs/google-contacts-setup.md.")
            creds = InstalledAppFlow.from_client_secrets_file(str(cred_path), SCOPES).run_local_server(port=0)
        token_path.write_text(creds.to_json())
    return creds


def _best_number(phones: list[dict]) -> str | None:
    def val(p):
        return p.get("canonicalForm") or p.get("value")     # canonicalForm is E.164 (+country) — best for WhatsApp
    for p in phones:
        if (p.get("type") or "").lower() == "mobile":
            return val(p)
    for p in phones:
        if p.get("metadata", {}).get("primary"):
            return val(p)
    return val(phones[0]) if phones else None


def import_all() -> int:
    try:
        creds = _authenticate()
    except Exception as e:
        print(f"Google auth failed: {e}")
        return 1
    from googleapiclient.discovery import build
    service = build("people", "v1", credentials=creds, cache_discovery=False)
    imported = skipped = 0
    page = None
    while True:
        resp = service.people().connections().list(
            resourceName="people/me", pageSize=1000,
            personFields="names,phoneNumbers", pageToken=page).execute()
        for person in resp.get("connections", []):
            names = person.get("names") or []
            name = names[0].get("displayName") if names else None
            number = _best_number(person.get("phoneNumbers") or [])
            if name and number:
                contacts_book.add(name, number)
                imported += 1
            else:
                skipped += 1
        page = resp.get("nextPageToken")
        if not page:
            break
    print(f"Imported {imported} contacts into Sheru's book (skipped {skipped} with no name+number).")
    return 0
