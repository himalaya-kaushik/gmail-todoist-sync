# 📬 Gmail → Todoist Sync

Automatically syncs Gmail calendar invite emails into Todoist tasks — runs headlessly on **GitHub Actions** every 2 hours.

When a new meeting invite arrives in Gmail (with an `.ics` attachment), this project:

1. Extracts the **title**, **start time**, and **meeting link** (Google Meet / Zoom).
2. Creates a **Todoist task** with those details.
3. Marks the email as **read** so it's never processed twice.

---

## 🚀 Setup

### 1. Enable the Gmail API

1. Go to [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project (or select an existing one).
3. Navigate to **APIs & Services → Library** and enable **Gmail API**.
4. Go to **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**.
   - Application type: **Desktop app**
5. Click **Download JSON** and save the file as `credentials.json` in this repo's root.

### 2. Generate Your Token (one-time, local)

```bash
pip install google-auth google-auth-oauthlib
python generate_token.py
```

This opens a browser for Google sign-in. After consent, a `token.json` file is saved locally.

> **Copy the entire contents of `token.json`** — you'll need it in Step 4.

### 3. Get Your Todoist API Key

1. Go to [Todoist Integrations Settings](https://todoist.com/app/settings/integrations/developer).
2. Copy your **API token**.

### 4. Add GitHub Secrets

Go to your repo → **Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret Name              | Value                                            |
|--------------------------|--------------------------------------------------|
| `GOOGLE_CREDENTIALS_JSON`| Contents of `credentials.json` (the full JSON)  |
| `GOOGLE_TOKEN_JSON`      | Contents of `token.json` (from Step 2)           |
| `TODOIST_API_KEY`         | Your Todoist API token (from Step 3)             |

### 5. Test It

1. Go to **Actions** tab in your GitHub repo.
2. Select **Gmail → Todoist Sync** workflow.
3. Click **Run workflow** → **Run workflow**.
4. Check the run log to confirm emails were processed (or that no matching emails were found).

---

## 🔄 How It Works

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│    Gmail API      │────▶│  Parse .ics file  │────▶│  Todoist API v2  │
│  (search unread)  │     │  (icalendar lib)  │     │  (create task)   │
└──────────────────┘     └──────────────────┘     └──────────────────┘
                                                          │
                                                          ▼
                                                   Mark email as read
```

- **Search query:** `newer_than:1d is:unread has:attachment filename:invite.ics`
- **Meeting links:** extracted from `.ics` fields (`URL`, `LOCATION`), with regex fallback on the email body.
- **Idempotency:** each Todoist request includes a unique `X-Request-Id` header.
- **Error isolation:** a failure on one email is logged and skipped — the rest continue.

---

## 🛠 Troubleshooting

### Token expired / `invalid_grant`

The OAuth2 refresh token can expire if:
- You haven't used it in **6 months**.
- You **revoked** access in [Google Account Permissions](https://myaccount.google.com/permissions).
- Your Google Cloud project is in **Testing** mode (tokens expire after 7 days).

**Fix:** Re-run `generate_token.py` locally and update the `GOOGLE_TOKEN_JSON` secret.

> **Tip:** To avoid 7-day expiry on test projects, go to Google Cloud Console → **OAuth consent screen → Publishing status** and click **Publish App**.

### Missing scopes / `Insufficient Permission`

Ensure the OAuth consent screen includes the scope:

```
https://www.googleapis.com/auth/gmail.modify
```

If you initially used `gmail.readonly`, you must re-run `generate_token.py` to grant the new scope.

### Todoist `403 Forbidden`

- Double-check that `TODOIST_API_KEY` is set correctly (no extra spaces or quotes).
- Verify the token at: [Todoist Sync API test](https://developer.todoist.com/rest/v2/#get-all-projects) — try `curl -H "Authorization: Bearer YOUR_KEY" https://api.todoist.com/rest/v2/projects`.

### No emails found

- Make sure you actually have **unread** emails **with `.ics` attachments** from the **last 24 hours**.
- The Gmail query is strict: `newer_than:1d is:unread has:attachment filename:invite.ics`.

### GitHub Actions not running

- Scheduled workflows only run on the **default branch** (usually `main`).
- GitHub may disable scheduled workflows on repos with **no activity for 60 days**. Push a commit to re-enable.

---

## 📁 Project Structure

```
├── main.py                 # Core sync logic
├── generate_token.py       # One-time OAuth helper (run locally)
├── requirements.txt        # Python dependencies
├── README.md               # This file
└── .github/
    └── workflows/
        └── sync.yml        # GitHub Actions cron workflow
```

---

## 📄 License

MIT
