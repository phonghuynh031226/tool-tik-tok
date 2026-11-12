# YouTube backend

Only this package and tests/services may change; contracts.py stays frozen.

1. Offline mock tests first for UTF-8 validators, explicit audience/rights/channel
   confirmation, OAuth PKCE/loopback, quota, refresh, retries and resumable sessions.
2. OAuth client JSON is selected/read only, validated as Google Desktop config,
   and stored in SecretStore. Tokens and session state never go into normal files.
3. connect uses saved credentials or system browser, PKCE, 127.0.0.1 random port.
   Show OAUTH_SCOPE_EXPLANATION before connect; get_channel returns target identity.
4. Frozen UploadRequest has a False audience default, which cannot reveal omission.
   Therefore create_upload_request requires made_for_kids, and confirm_upload(req,
   made_for_kids=..., channel_id=...) is mandatory before upload. It binds consent
   to the current metadata; editing invalidates it. This is an implementation API,
   not a modification of the frozen contract. Do not call confirmation automatically.
5. 8 MiB resumable chunks. Save the Location URI to SecretStore in the transport
   BEFORE sending media. On retry/restart restore it and query server offset.
   Bind session to file SHA-256, metadata and confirmed channel. Retain completed
   video id to avoid duplicate upload after lost UI response. No expired-session
   auto-restart: surface an error for explicit user action.
6. One refresh per operation, at most five transient retries (1/2/4/8/16 seconds),
   no internal SDK retries. Quota never retries. Cancellation between requests,
   file-hash blocks and backoff; each blocking HTTP request has a 30-second timeout.
7. Check API video id before reporting upload/processing success. Run offline
   tests/full pytest and verify unchanged contract and pre-existing source files.
