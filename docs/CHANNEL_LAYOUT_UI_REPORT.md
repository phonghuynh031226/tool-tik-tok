# Channel layout in Clivo UI repository

Target: D:/DU AN CA NHAN/tool-tik-tok-ui.
Approved design: compact account rows, HTTPS channel avatar with initial fallback,
inline channel statistics and per-account action menu. No initial channel
selection. Selecting a channel updates the video panel BELOW the complete list.
Refresh buttons and open-video button removed; double-click remains.

Changes limited to channel page and matching tests. Existing Clivo branding,
styles, three-step Dashboard workflow tests, column sizing and empty-video state
preserved. No contracts/backend changes, commit, push or EXE build.

Verification:
- Initial full offscreen pytest: 440 passed, 5 failed, 1 skipped.
- One obsolete toolbar expectation updated for its removal.
- Remaining 4 failures are Dashboard width-1000 horizontal overflow (three scale
  parametrizations) and Dashboard wide-grid reflow. All four reproduced with the
  original channel-page class loaded from HEAD in memory, without changing files.
- Symlink test skipped due Windows privilege; junction test passed.
- Final run excludes exactly those four baseline failures; output in
  .tmp/channel-layout-tests.log.
- Preview checked at 1366x900 and 1000x720 with fake-mode banner and Clivo logo:
  .tmp/channels-overview.png, .tmp/channels-selected.png, .tmp/channels-narrow.png.
- Avatar fetching/decoding is mock-tested; live channel-logo retrieval was not
  tested. Fake preview accounts use initial-letter fallback avatars.
- Changes from the earlier run in tool-tik-tok are left intact, not reverted.

Final offscreen run: 441 passed, 1 skipped, 4 deselected in 89.21s. The four deselected Dashboard tests were separately reproduced as failures with the old channel page. No claim that the entire suite is green.
