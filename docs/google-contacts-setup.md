# Import Google Contacts into Sheru (one-time)

Sheru pulls your contacts (name → phone number) straight from Google — no macOS Contacts, no typing numbers.
You do the Google side **once**; after that `uv run sheru import-contacts` refreshes anytime.

## 1. Google Cloud — create an OAuth client (~5 min, once)

1. Go to **https://console.cloud.google.com** → top bar → **Create Project** (name it e.g. "Sheru"). Select it.
2. **Enable the API:** search bar → "People API" → **Enable** (or visit
   https://console.cloud.google.com/apis/library/people.googleapis.com).
3. **OAuth consent screen** (left menu → *APIs & Services → OAuth consent screen*):
   - User type: **External** → Create.
   - App name "Sheru", your email for support + developer contact → Save and continue.
   - **Scopes:** skip (we request it in code) → Save and continue.
   - **Test users:** click **Add users**, add **your own Google address** → Save and continue.
4. **Create the credential** (*APIs & Services → Credentials* → **+ Create credentials → OAuth client ID**):
   - Application type: **Desktop app** → Create.
   - In the dialog, **Download JSON**.
5. Save that file as:  **`~/Projects/Sheru/data/google_credentials.json`**  (this folder is gitignored).

## 2. Run the import

```sh
cd ~/Projects/Sheru
uv run sheru import-contacts
```

- A browser opens → sign in → you'll see **"Google hasn't verified this app"** (expected — it's your own
  unverified app) → **Advanced → Go to Sheru (unsafe)** → **Allow**.
- Sheru pulls every contact with a name + number into its book (`data/contacts.json`) and prints the count.

That's it. Now "message <anyone in your contacts>" resolves their number automatically — including Yashika.

## Notes
- **Refreshing:** re-run `uv run sheru import-contacts` whenever you want to pick up new/changed contacts. The
  saved token (`data/google_token.json`) means no re-consent unless it expires (test-mode tokens last ~7 days;
  re-running just re-opens the consent once).
- **Numbers must have a country code** for WhatsApp. Google usually stores them in `+91…` form; any that don't
  will fail to send and can be fixed in Google Contacts, then re-imported.
- **Firewall:** the college wifi's Sophos TLS interception blocks the Google auth call — run the import on home
  wifi / hotspot.
- **Privacy:** credentials, token, and the contact book all live in gitignored `data/` — never pushed to GitHub.
