# Secrets, roles and primary data source

Status: decided 2026-11-09 (user answers recorded below). S1 to S6 are built (ledger rows 1 and 5 to 9). No EGM review of this design is recorded. The plaintext data/secrets.env is not yet deleted (needs the user's yes). The web admin screen is deferred to v2.
Related: `scanner/secrets_store.py` (today's plaintext store), `docs/designs/fundamentals-tables.md`, `docs/designs/home-event-sources.md`.

## Decisions

1. **Bootstrap secrets in Docker secret files.** Only two values: the database password and the master encryption key. The API reads them at start.
2. **Everything else encrypted in database rows.** Upstox key and token, Kite key and token, Screener login, and any key the admin adds. Each value is encrypted with the master key before it is written.
3. **The master key is never stored in the database.** Keeping it next to the encrypted values would give no protection. An offline backup of the master key is required, because losing it makes every encrypted value unrecoverable.
4. **Only the API decrypts.** Decryption happens in the API when a loader needs a value. The UI and browser never receive a secret value. The API shows secrets only as masked values, such as the last four characters.
   - **Admin configuration screen (proposed 2026-11-10):** the admin can enter, replace and delete an app secret, and set its `created_on` and `expires_on` dates. The screen shows the masked value, both dates and `updated_by`. The stored value is never shown again after it is saved.
   - The Upstox analytics token is the first entry: name `upstox_analytics_token`, with its created and expiry dates. The expiry-alert job (`fundamentals-upstox-secondary.md`) reads the dates from here.
5. **Two roles.**
   - **Admin:** creates and deletes user accounts; adds, updates and deletes app keys and secrets; sets the dashboard template; runs first-time configuration.
   - **Named user:** logs in to their own profile; enters and manages their own portfolio secrets and tokens. No access to app secrets, first-time configuration or the dashboard template.
6. **Admin cannot view named users' portfolio tokens.** The admin can reset or delete them, but never read them.
7. **Login is local.** The admin creates each account. Passwords are stored as salted hashes (argon2 or bcrypt), never in plain text.
8. **Fundamentals source order is fixed, not an admin setting.** Screener is the primary source for every fundamentals field it provides. Upstox is secondary and fills only the fields Screener does not provide, as set out in [fundamentals-upstox-secondary.md](fundamentals-upstox-secondary.md). Neither source overwrites the other.

## Data model (proposed, not built)

| Table | Holds | Notes |
|---|---|---|
| `app_secret` | `name` (key), `ciphertext`, `nonce`, `key_version`, `created_on` (date), `expires_on` (date, nullable), `updated_by`, `updated_at` | Admin-managed app keys. Value is encrypted. `created_on` and `expires_on` are plain dates, not secret, and drive expiry alerts. |
| `user_account` | `id`, `username`, `password_hash`, `role` (`admin` or `named`), `created_by`, `created_at` | Admin creates rows. No self-signup. |
| `user_secret` | `user_id`, `name`, `ciphertext`, `nonce`, `key_version`, `updated_at` | Named user's own values. Keyed to the owner; the admin role gets no read path. |
| `app_config` | `key`, `value` | Holds the dashboard template. |

Key rotation: `key_version` lets a new master key be added while old rows are re-encrypted in batches. Rotation is a later step, not part of the first build.

## Bootstrap and start-up order

1. The API reads the database password and master key from Docker secret files.
2. It connects to Postgres.
3. It reads `app_secret` and `user_secret` as needed and decrypts on demand.
4. If no admin account exists, first-time configuration starts and creates the first admin.

## Migration from today

`data/secrets.env` holds plaintext values today. The first build imports them into `app_secret`, then deletes the plaintext file after a successful check. Until then the file remains the fallback.

## Upstox token

No Upstox login credentials are stored or used: no user ID, password, PIN or TOTP secret. The collector uses only the app's API key and secret and the access token that Upstox issues.

Checked 2026-11-10 against the Upstox docs (`https://upstox.com/developer/api-documentation/get-token/` and `.../access-token-request/`):
- Upstox issues no refresh token. The token response has `access_token` and `extended_token`, and neither the response nor the webhook has a refresh field.
- The access token expires at 3:30 AM the following day, whatever time it was issued.
- A new access token needs the user to approve it again in the authorization dialog. The code exchange is `POST https://api.upstox.com/v2/login/authorization/token` (`grant_type=authorization_code`, with `code`, `client_id`, `client_secret`, `redirect_uri`). The v3 request flow (`POST https://api.upstox.com/v3/login/auth/token/request/{client_id}`) returns the token later through a webhook.
- The TOTP route (`POST https://api.upstox.com/v2/totp-login/authorization/token`) would avoid the dialog, but it needs the user's PIN and TOTP. It is not used.

The refresh flow is for order management, not analytics. For the fundamentals feed the collector uses the **analytics token**, which the docs (`https://upstox.com/developer/api-documentation/analytics-token/`, `.../api-overview/`) describe as:
- Generated by hand once on the Developer Apps page (Analytics tab). No login, daily approval or refresh is needed.
- Valid for 1 year from generation. One analytics token per account at a time.
- Covers Fundamentals, Market Quote, Historical Data and News, with no static IP needed. Read-only, GET only.
- Renewal after a year is a manual regeneration by the user. The docs do not describe automatic renewal.

Stored encrypted in `app_secret` as an app-level key, set by the admin (decision 2 and role rules above). The collector reads it when it runs.

## Decisions from the admin-screen review (2026-11-10)

9. **Scope of v1 (amended 2026-11-12, BL-3):** the app's settings page takes the secret values. They are shown masked and saved encrypted in the database. A command-line tool (import, rotate, test) runs inside the API container for operator tasks. Screener login is cut from v1. The full web admin screen is v2.
   - **Credentials the CLI needs (answered 2026-11-10):** no login credentials. It needs two Docker secret files: the master key file (decision 10) and the Postgres password. Secret values (Telegram token, Upstox key and secret, analytics token, LLM provider keys) are entered on the settings page, shown masked, and saved encrypted in the database. The terminal prompt is no longer the entry path for them. They are never passed through chat, shell history, command-line arguments or .env files.
10. **Master key holder:** only the API container holds the master key, mounted as a Docker secret file readable by the API user alone. The CLI runs inside that container, so no second process holds the key. Other services (collector, Telegram sender) receive a decrypted value through an internal API call, authenticated with a service token, and never read the key.
11. **Test before save:** Test runs against the candidate value and the value is saved only if the test passes. Telegram uses `getMe` (no message sent). Upstox uses one fundamentals call. Test runs only on demand, never automatically.
12. **Transport and TLS (revised 2026-11-10):** in v1 the API binds to `127.0.0.1` only, with no TLS. Traffic never leaves the host. An internal CA was rejected because every client (browser, collector, Telegram sender) would need the root trusted. Let's Encrypt with a domain and the DNS challenge is the path for remote access later. At-rest protection is still the master key in decision 10.
13. **Rotation of exposed values:** the admin rotates manually and records the new date. Values to rotate: the Screener password (it appeared in the HAR file that was read in this session) and anything else pasted into chat. Exposure date: 2026-11-11 (session record). Deadline: 2027-05-11 (six months from exposure, user assumption; no documented limit).
14. **Alert dedupe key:** (name, expires_on, offset). The same alert is never sent twice for one expiry.

### S1 built (2026-11-10): master key and encryption layer

- Code: `scanner/secret_crypto.py` (AES-256-GCM, fresh 96-bit nonce per write, associated data `table|name|owner|key_version`). Tests: `tests/test_secret_crypto.py` (16 tests, offline; the mode test is skipped on Windows).
- The UI app's lifespan calls `check_master_key()`, so the API refuses to start without a valid key. Checked in the container: it starts with the key and exits with "Application startup failed" without one.
- Key location: no path is hardcoded. The host folder is set by `APP_MASTER_KEY_DIR` in `.env`. Compose mounts that folder read-only into the `ui` service at `/run/app-keys`, and `APP_MASTER_KEY_FILE` points the code at `/run/app-keys/app_master_key`. If `APP_MASTER_KEY_DIR` is unset, `docker compose` refuses to start. If `APP_MASTER_KEY_FILE` is unset, the code refuses to load a key.
- The key file is a 32-byte random value in base64. It is never in git, the image, or the build context (`.dockerignore` excludes `secrets/`). Only the `ui` service mounts the folder.
- Create the key once, on the host, with `APP_MASTER_KEY_DIR` set in the shell to the folder you chose. The command refuses to overwrite an existing file.

```bash
.venv/Scripts/python.exe -c "import os; from pathlib import Path; from scanner.secret_crypto import write_new_key_file as w; w(Path(os.environ['APP_MASTER_KEY_DIR']) / 'app_master_key')"
```

- Back up the key file separately from the database. Losing it makes every stored secret unreadable. Holding the key next to a database dump defeats the encryption.
- Tradeoff: a OneDrive folder syncs the key file to Microsoft's cloud. The encrypted values stay in local `data/`, so the cloud copy alone cannot read them, but the key does leave the machine. Keep the file downloaded (not "online only"), or the container cannot read it.
- Not in S1: the `app_secret` table (S2), the CLI (S3), import and migration (S4), and loaders (S5).

## Open items for the brainstorm

- Upstox analytics token: confirm one live call to the fundamentals endpoint with the analytics token before the build. Record the expiry date in the admin screen, so the yearly renewal is not missed.
- Admin reset of a named user's password: whether it needs a second confirmation step.
- Audit log: whether every secret read and write is recorded, and who can see the log.
- Session handling for logins: lifetime and how a session ends.
- Migration check: how to confirm the imported values work before the plaintext file is deleted.

## Decision 15: service token delivery (approved by the user, 2026-11-10)
- The collector reads its service token from a file mounted at `/run/app-keys` (same mount folder as the master key). The token is the only credential the collector holds. The master key stays in the API container only.
- The collector requests each secret it needs from the API over the internal endpoint, authenticated with that token. The API decrypts and returns the value.
- Each service gets its own token file. The file is readable by that service's user only.
- Status: approved. Built: S5 (PR #73, merge 8b26503).

## Decision 16: Kite access token is runtime-only (decided 2026-11-10)
- `kite_access_token` is not stored in `app_secret`, not imported from `data/secrets.env`, and not shared with any service. It is issued by Kite at the daily login (`scanner/auth.py`, cached in the git-ignored `.kite_token`).
- Done: the `KITE_ACCESS_TOKEN` mapping in `scanner/secrets_cli.py` (ENV_TO_APP) and the `KITE_ACCESS_TOKEN` line in `env.template` have been removed. The token is read from `.kite_token` (the daily login cache written by `python -m scanner.auth`).
- `KITE_API_KEY` and `KITE_API_SECRET` remain stored app secrets.

## Ingest token roles and the collector service token (proposed 2026-11-10)

Decision A1 (2026-11-10): each source has its own ingest route and token. These roles are proposed, not built. The routes are defined in the design docs named below.

| Role (proposed) | Caller | Route (proposed) | Defined in |
|---|---|---|---|
| `rss_intake_ingest` | RSS fetcher | `POST /internal/events/intake/rss` | `home-events-news-telegram.md` |
| `telegram_intake_ingest` | Telegram reader | `POST /internal/events/intake/telegram` | `home-events-news-telegram.md` |
| `upstox_news_ingest` | Upstox news poller (runs under the collector service token) | `POST /internal/events/intake/upstox` | `home-events-upstox-news.md` |
| `news_events_ingest` | LLM worker | claim, status and `POST /internal/events/news/batch` | `home-events-news-telegram.md` |
| `macro_ingest` | macro source | `POST /internal/events/macro` | `home-events-macro-calendar.md` |

The FRED key row is not added. It waits on overview decision C6.

Service token mapping (Upstox review finding 19): the secret endpoint serves `upstox_analytics_token` to the service token mapped to `collector` and to the `server` identity (`ui/app/internal_secrets.py`, `SERVICE_ALLOWED`). The Upstox poller runs under the collector token. The `server` identity (S3b) reads `upstox_analytics_token` for live feeds and `kite_api_key` for holdings. Fastify no longer reads an Upstox token from the environment (`server/src/index.ts`). The collector-only limit now reads: collector and server (analytics token), server (kite_api_key). `kite_access_token` stays runtime-only and is not served to any service. The location of the ingest tokens is open (see the Upstox doc, Open list).
