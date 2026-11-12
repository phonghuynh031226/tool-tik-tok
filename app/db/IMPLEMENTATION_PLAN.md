# Database and security implementation

Scope: app/db, app/security, tests/core and tests/services only. Frozen contracts
and existing TikTok work remain unchanged. No commit/push or files outside project.

1. Write offline tests first: SQLite CRUD, v1→v2 migration, duplicates, Unicode,
   parameter binding, keyring-only secrets, settings/path confirmation and logs.
2. Schema v1 contains basic job metadata/content/upload result/status/timestamps.
   Transactional v2 adds upload options, model/prompt/retries and nonsecret extras.
   schema_version has exactly one row. Future versions fail closed. Existing
   legacy duplicate rows are preserved; new duplicates are rejected atomically.
3. SQLiteHistoryRepository maps video_id/url/title/description/status aliases onto
   canonical columns, returns detached values, provides get/delete/export_csv in
   addition to the frozen protocol. Queries use placeholders and fixed identifiers.
4. Resumable upload URI is credential-like: put it in SecretStore; SQLite holds
   only keyring:upload-session:<uuid>. get_upload_session_uri resolves it explicitly;
   regular reads/CSV never expose the URI. Secrets have no plaintext fallback.
5. Select keyring's Windows Credential Manager backend explicitly; never accept an
   ambient plaintext keyring backend. Tests replace the backend factory in memory.
6. JSONSettingsStore whitelists nonsecret keys, uses UTF-8 and atomic replacement,
   defaults to private. assess_download_directory returns requires_user_confirmation
   for external paths, rejects links, and never creates the selected directory.
   set_download_directory requires user_confirmed=True for an external selection;
   this only persists a local setting, never authorizes filesystem writes outside.
7. Rotating logs redact key/value credentials, bearer/JWT/common key patterns,
   signed/session URLs and exceptions. All storage/export/log paths stay project-local.
8. Run full pytest; verify contract SHA-256 and source edit scope against baseline.
