# Compact Tools UI

Scope: tool-tik-tok-ui, app/ui/pages/tools_page.py and related UI tests.
TikTok: removed local MP4 picker and session download list/actions. Download button
shares the URL/Paste row. Folder controls, progress/cancel and a compact finished
filename message remain. No downloaded files are deleted.
AI: removed original description, tone, hashtag/tag outputs, copy-all and apply-to-
Dashboard. Model and Generate share a row. Source title/current-job title import,
result title/description, counters and individual copy actions remain.
Callbacks no longer reference removed widgets. Metadata worker is retained through
completion and uses a bound UI slot to start download; this fixes a reproduced
metadata-to-download timeout. Finished download no longer reads nonexistent
DownloadResult.meta. Shared contracts and backend services unchanged.

Verification: new regression suite failed before implementation, passed after.
Mocked metadata->download writes a placeholder file inside pytest temp and verifies
completion without setting the shared job. Title-only AI generation/copy tested.
Final command: project-env.ps1, QT_QPA_PLATFORM=offscreen, STUDIO_USE_FAKES=1,
python -m pytest tests/ui -q with four previously verified Dashboard failures
explicitly deselected: 147 passed, 4 deselected in 41.05 seconds.
Preview images checked at 1366x900 and 1000x720, fake-mode banner preserved:
.tmp/tools-tiktok-compact.png, .tmp/tools-ai-compact.png, .tmp/tools-ai-narrow.png.
No live TikTok/Gemini request, EXE build, commit or push. Restart the source app
with run.bat to load changes; no running user session was forcibly closed.

## Unified workspace follow-up

Removed the two tabs entirely. One scroll area now contains two input cards
side-by-side above a full-width AI result card. At viewport width below 1060
logical pixels, the input cards stack vertically. Input widget instances are
retained during reflow. Card padding reduced locally; shared Clivo styles untouched.
Download and Generate retain their existing same-row buttons. Folder actions have
a separate compact row to fit the narrower download column. Rights reminder and
fake-mode banner preserved. No contracts/backend, build or upload changes.
Preview: .tmp/tools-unified-wide.png and .tmp/tools-unified-narrow.png.
