# Secrets, roles and primary data source

Status: decided 2026-11-09 (user answers recorded below). Not built. The design goes to the EGM brainstorm before any task is dispatched.
Related: `scanner/secrets_store.py` (today's plaintext store), `docs/designs/fundamentals-tables.md`, `docs/designs/home-event-sources.md`.

## Decisions

1. **Bootstrap secrets in Docker secret files.** Only two values: the database password and the master encryption key. The API reads them at start.
2. **Everything else encrypted in database rows.** Upstox key and token, Kite key and token, Screener login, and any key the admin adds. Each value is encrypted with the master key before it is written.
3. **The master key is never stored in the database.** Keeping it next to the encrypted values would give no protection. An offline backup of the master key is required, because losing it makes every encrypted value unrecoverable.
4. **Only the API decrypts.** Decryption happens in the API when a loader needs a value. The UI and browser never receive a secret value. The API shows secrets only as masked values, such as the last four characters.
5. **Two roles.**
   - **Admin:** creates and deletes user accounts; adds, updates and deletes app keys and secrets; sets the dashboard template; runs first-time configuration; chooses the primary data source.
   - **Named user:** logs in to their own profile; enters and manages their own portfolio secrets and tokens. No access to app secrets, first-time configuration or the dashboard template.
6. **Admin cannot view named users' portfolio tokens.** The admin can reset or delete them, but never read them.
7. **Login is local.** The admin creates each account. Passwords are stored as salted hashes (argon2 or bcrypt), never in plain text.
8. **Fundamentals source order is fixed, not an admin setting.** Screener is the primary source for every fundamentals field it provides. Upstox is secondary and fills only the fields Screener does not provide, as set out in [fundamentals-upstox-secondary.md](fundamentals-upstox-secondary.md). Neither source overwrites the other.

## Data model (proposed, not built)

| Table | Holds | Notes |
|---|---|---|
| `app_secret` | `name` (key), `ciphertext`, `nonce`, `key_version`, `updated_by`, `updated_at` | Admin-managed app keys. Value is encrypted. |
| `user_account` | `id`, `username`, `password_hash`, `role` (`admin` or `named`), `created_by`, `created_at` | Admin creates rows. No self-signup. |
| `user_secret` | `user_id`, `name`, `ciphertext`, `nonce`, `key_version`, `updated_at` | Named user's own values. Keyed to the owner; the admin role gets no read path. |
| `app_config` | `key`, `value` | Holds the primary data source choice and the dashboard template. |

Key rotation: `key_version` lets a new master key be added while old rows are re-encrypted in batches. Rotation is a later step, not part of the first build.

## Bootstrap and start-up order

1. The API reads the database password and master key from Docker secret files.
2. It connects to Postgres.
3. It reads `app_secret` and `user_secret` as needed and decrypts on demand.
4. If no admin account exists, first-time configuration starts and creates the first admin.

## Migration from today

`data/secrets.env` holds plaintext values today. The first build imports them into `app_secret`, then deletes the plaintext file after a successful check. Until then the file remains the fallback.

## Upstox token

The Upstox daily token expires every day. Storing it encrypted does not keep it valid. The design needs a refresh step, or the feed stops each morning. Refresh mechanics are an open item for the brainstorm.

## Open items for the brainstorm

- Upstox token refresh: how the daily token is renewed, and who must act when it fails.
- Admin reset of a named user's password: whether it needs a second confirmation step.
- Audit log: whether every secret read and write is recorded, and who can see the log.
- Session handling for logins: lifetime and how a session ends.
- Migration check: how to confirm the imported values work before the plaintext file is deleted.
