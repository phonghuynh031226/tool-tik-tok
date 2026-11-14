# Integration verification — 2026-11-12

Production ServiceContainer now uses TikTokService, GeminiContentGenerator,
YouTubeService, SQLiteHistoryRepository, KeyringSecretStore and JSONSettingsStore.
main.py opens MainWindow. Contracts unchanged. No commit/push.

Integration fixes: single upload worker dispatch; explicit backend confirmation
only after UI confirmation; OAuth file imported into SecretStore; supported UI
settings persisted; history stores source video identity and YouTube result;
dry-run does not create uploaded history; history save failures are visible.
Build PATH excludes unrelated host tools to avoid collecting incompatible ICU DLLs.

## Executed

- Dot-sourced scripts/project-env.ps1 before installs/runs/tests.
- QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest -q -rs:
  **211 passed, 1 skipped**, 6.50 seconds. Includes tests/ui.
  Skipped: test_rejects_symlink, Windows symlink privilege unavailable.
  Windows junction test passed outside sandbox.
- tests/services/test_integration_pipeline.py: real TikTok and Gemini/YouTube
  service implementations, mocked SDKs/probe/credentials; metadata -> download ->
  generate -> explicit confirmation -> mocked upload -> UI history handler ->
  real SQLite query. Not a live network integration or full mouse-click UI test.
- Real default container and MainWindow initialized outside sandbox, including
  Windows keyring reads. No test credentials written to Windows keyring.
- Installed requirements-dev.txt into project .venv; build.bat succeeded.
- Launched dist/TikTokYouTubeStudio/TikTokYouTubeStudio.exe outside sandbox;
  after 6 seconds, process alive, visible Studio Qt window, no console window.
  PE subsystem = Windows GUI (2). Fake module excluded from archive.
- git diff --check passed; contracts.py has no changes.

## Not verified live / remaining prerequisites

- Gemini API requests: needs real Gemini key.
- YouTube OAuth/refresh/upload/processing: needs Desktop OAuth client and account;
  no video was actually uploaded.
- TikTok real metadata/download: needs real authorized TikTok URL.
- FFmpeg/FFprobe are absent from bin and are not bundled; real download validation
  cannot pass until these executables are provided.
- Actual keyring write/read/delete round-trip was not performed.
- No claim that live integrations are complete.

## Bundle audit

No credential/database/video filenames found before launch. Startup created an
empty runtime data/app.db, subsequently moved to .tmp/exe-smoke-history.db.
Binary/text scan: no Gemini API key or OAuth access-token patterns detected.
Private-key header markers occur in Qt TLS libraries and Google App Engine
API discovery documentation. Complete PEM private key blocks in those files: 0.
These are format/documentation strings. This pattern audit does not prove absence
of every possible secret format.
