# Native startup investigation

User supplied Windows 0xC0000005 during Python SSL handshake in YouTube restore,
while other workers waited on the service RLock. Standalone urllib/httplib HTTPS
succeeded. The waiting workers are not evidence of concurrent shared transport
requests: YouTubeService serializes them.

Observed locally: real app startup with inherited host PATH emitted native
0xC0000139 during Qt avatar request; with isolated PATH the same 35-second startup
completed without native exceptions. Minimal Qt/Python HTTPS and Qt Multimedia
HTTPS probes with isolated PATH returned 200 and exited 0.

Change: main.py calls app.core.runtime_env.configure_native_environment before
Qt/FFmpeg/Google imports. Windows process PATH contains the active interpreter
folder plus System32/Windows, matching the existing launcher. No system PATH
modification, credential changes, contract changes or TLS validation changes.

Tests: tests/core/test_runtime_env.py tests/ui/test_main.py
 tests/ui/test_main_window.py tests/ui/test_channel_layout.py: 11 passed, 2.25s.
Real startup after change, inherited host environment: 35 seconds, STARTUP_OK,
exit 0. Loaded OpenSSL DLLs from the Python base DLLs directory and ICU from
System32. Visible real Clivo window also opened and reported Responding=True.

Limits: the exact user-reported 0xC0000005 was not reproduced identically, so this
verifies removal of the observed DLL-load failure rather than proof against all
future native crashes. No real upload performed. No build/commit/push.
