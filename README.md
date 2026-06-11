# TikTok Slideshow MCP

An MCP server that assembles TikTok photo **slideshows** and sends them to your TikTok **inbox as drafts** (to verify and make any final changes). You (or an automation, e.g. another Claude agent that generates images) call the `create_slideshow` tool with local image paths. The server hosts the images and uses TikTok's Content Posting API in `MEDIA_UPLOAD` mode, so the slideshow shows up as a draft notification in your TikTok app, ready to finish editing and post.

It is designed to be driven by an AI agent over MCP, but also ships with plain CLI scripts so you can use it standalone.

```
local images ──► Cloudflare R2 (served from YOUR verified domain) ──► TikTok content/init
                                                                       (MEDIA_UPLOAD, PHOTO)
                                                                              │
                                                                draft lands in your TikTok inbox
```

---

## Note:

**Photos must be hosted on a domain you verify — there's no direct upload.**
TikTok's photo endpoint only accepts images via `PULL_FROM_URL` (it fetches public URLs).
Direct byte upload (`FILE_UPLOAD`) is **video-only**. So the images must sit at public URLs on
a domain you've verified in the developer portal. This server uses Cloudflare R2 for
that. You need a domain you own (any domain — it can be a subdomain of an unrelated site).

---

## What you need

- Python 3.10+
- A **TikTok for Developers** account (free)
- A **domain you own** (any domain; you'll use a subdomain like `tt-media.yourdomain.com`)
- A **Cloudflare** account with that domain's DNS on Cloudflare (free), plus R2 enabled (R2 has a generous free tier, but enabling it will require adding a payment method)

---

## Setup

### 1. Create the TikTok app + sandbox
1. Go to <https://developers.tiktok.com> → Manage apps → create an app.
2. Create a Sandbox (Tab on top of page, next to production). Inside the sandbox:
   - Add the login Kit and Content Posting API products
   - Configure Login Kit: add the Redirect URI (see below), enable scopes
     **`user.info.basic`** and **`video.upload`**.
   - Add your TikTok account as a target user.
4. Rest of info (icon, description, etc.) can be filled with any random placeholders since we won't actually be submitting this to TikTok
   - A valid URL will need to be verified for some of the placeholder info (see below) 
3. Note the sandbox's Client key + Client secret (they start with `sb...`).

> Posting to your inbox uses the `video.upload` scope. You do **not** need `video.publish`
> (that's for direct auto-posting and requires the audit).

### 2. Cloudflare R2 + a verified subdomain
1. Make sure your domain's DNS is on Cloudflare (add the domain as a zone if it isn't).
2. Cloudflare dashboard → R2 → enable it → Create bucket (e.g. `tiktok-slideshows`).
3. Open the bucket → Settings → Custom Domains → Connect Domain → enter a subdomain like `tt-media.yourdomain.com`. Cloudflare auto-creates the DNS record + SSL. Wait until it shows **Active**. (Leave the `r2.dev` URL disabled.)
4. R2 → Manage R2 API Tokens → Create API Token (Object Read & Write, scoped to the bucket). This gives you an Access Key ID + Secret Access Key. Your Account ID is on the R2 overview page.

### 3. Verify the domain with TikTok
TikTok won't pull images from an unverified domain. In your sandbox → URL properties / domain verification → add `tt-media.yourdomain.com` and verify it:
- **DNS method (easiest on Cloudflare):** TikTok gives a `TXT` value → add a TXT record in
  Cloudflare DNS (Name `tt-media`) → click Verify.
- **File method:** upload TikTok's verification `.txt` to your R2 bucket so it's reachable at
  `https://tt-media.yourdomain.com/<file>.txt` → click Verify.

### 4. Configure `.env`
Copy `.env.example` to `.env` and fill in (use the **sandbox** TikTok credentials):

```
TIKTOK_CLIENT_KEY=sb...
TIKTOK_CLIENT_SECRET=...

# make sure this is added to the tiktok sandbox settings as well
TIKTOK_REDIRECT_URI=https://tt-media.yourdomain.com/oauth/callback

R2_ACCOUNT_ID=...
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET=tiktok-slideshows
R2_PUBLIC_BASE_URL=https://tt-media.yourdomain.com
```

### 5. Install
```bash
python -m venv .venv
# Windows:
.venv\Scripts\python.exe -m pip install -e .
# macOS/Linux:
.venv/bin/python -m pip install -e .
```

### 6. Verify setup + log in
Run the preflight (checks config and that R2 serves images over your domain):
```bash
.venv/Scripts/python.exe scripts/preflight.py     # use .venv/bin/python on macOS/Linux
```
Then connect your TikTok account:
```bash
.venv/Scripts/python.exe scripts/login.py
```
It opens TikTok's authorization page → approve (with the account you added as a target user) → copy the full redirect URL from the address bar (it does **not** need to serve a real page (a 404 is fine) → paste it back. On success it prints your granted scopes (`user.info.basic,video.upload`) and verifies your display name. **You log in once**; tokens are saved to `~/.tiktok_slideshow_mcp/tokens.json` and auto-refresh (~1 year).

---

## Usage

### As an MCP server (recommended)
Register it wherever your agent runs.

**Claude Desktop** (`claude_desktop_config.json`) or **Claude Code** (`.mcp.json`):
```json
{
  "mcpServers": {
    "tiktok-slideshow": {
      "command": "/abs/path/to/.venv/Scripts/python.exe",
      "args": ["-m", "tiktok_slideshow_mcp.server"],
      "cwd": "/abs/path/to/tiktok_auto_uploader"
    }
  }
}
```
`cwd` must point at the project so the server finds your `.env`. Tools exposed:

| Tool | What it does |
|------|--------------|
| `start_login` | Returns a TikTok OAuth URL to open in your browser. |
| `finish_login` | Paste the redirect URL (or `code`) to save tokens. |
| `list_accounts` | Lists connected accounts and verifies the default one. |
| `create_slideshow` | Hosts images + sends the slideshow to your TikTok inbox. |
| `check_status` | Tracks delivery (`SEND_TO_USER_INBOX` = ready in your inbox). |

`create_slideshow(image_paths, title, description="", cover_index=0, account=None)` — paths are
local files in slideshow order (max 35). Images are assumed TikTok-ready (JPEG/PNG/WebP,
≤20 MB, ≤1080p); the server does **not** resize them.

### As a CLI (standalone)
```bash
.venv/Scripts/python.exe scripts/post.py "My title" img1.jpg img2.jpg img3.jpg
# options: --description "caption #fyp"  --cover 0
```
On success you'll see `status: SEND_TO_USER_INBOX`, then the draft appears in your TikTok app
inbox — tap the notification to finish editing and post.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Login page: **"correct the following: client_key"** | You're using **production** creds, or the **sandbox** isn't fully configured. Use the sandbox's `sb...` key/secret, and ensure Login Kit + redirect URI + scopes + your target user are all set **inside the sandbox**. |
| `.env` changes seem ignored | A real **environment variable** is overriding it. Clear `$env:TIKTOK_*` / `export TIKTOK_*`, or open a fresh shell. |
| Granted scopes missing `video.upload` | You authorized before the scope was requested/enabled. Make sure `video.upload` is in `TIKTOK_SCOPES` and enabled in the sandbox, then re-run `login.py` and approve all permissions. |
| `scope_not_authorized` on `creator_info` | Expected — `creator_info` needs `video.publish` (direct-post). This tool uses `video.upload`; account verification uses the user-info endpoint instead. Harmless. |
| Post fails with `url_ownership_unverified` (or similar) | The image domain isn't verified in the sandbox. Complete **step 3** (domain verification). |
| `redirect_uri` mismatch | The URI in the request must match the sandbox's registered URI **exactly** (scheme, trailing slash). |

---

## How it stays connected
- Tokens persist at `~/.tiktok_slideshow_mcp/tokens.json`.
- Access tokens (~24h) auto-refresh; refresh tokens (~1 year) roll forward on each use.
- You only re-run `login.py` if you change scopes, revoke access, or go a full year unused.

## Limits & notes
- Up to **35** images per slideshow; **6** API requests/min per account.
- Add an R2 **lifecycle rule** (e.g. delete objects after 7 days) so pulled images don't
  accumulate — TikTok fetches them at post time and doesn't need them afterward.
- Until your app passes TikTok's audit, posting works only for **sandbox target users** (i.e.
  your own account) — which is all you need for personal use.

## Development
```bash
.venv/Scripts/python.exe -m pip install -e ".[dev]"
.venv/Scripts/python.exe -m pytest
```
Tests cover the R2 uploader (mocked S3), PKCE/OAuth + token store, and the exact `content/init`
request body — everything that doesn't require live TikTok approval.

## Security
- `.env` and `~/.tiktok_slideshow_mcp/tokens.json` contain secrets — never commit them
  (`.env` is gitignored).
- The R2 bucket is public-read by design (TikTok must fetch the images); don't store anything
  sensitive in it.

## License
MIT
