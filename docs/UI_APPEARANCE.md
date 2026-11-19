# Language and appearance preferences — 2026-11-17

Active application identified from running pythonw processes: `D:/DU AN CA NHAN/tool-tik-tok-ui`.

The language/theme selectors previously only wrote settings. Startup did not restore their selections; the stylesheet always used dark colors.

Settings now restore `ui_language` and `ui_theme` under blocked signals. Selection changes persist and apply immediately through the window-owned `UiPreferences`. No page reconstruction or task restart is needed. Light colors cover the shared stylesheet and inline widget styles, including newly opened child dialogs. Switching back restores original dark styles.

Application copy has explicit bindings in `app/ui/i18n.py` and an English catalog in `app/ui/translations.py`. Placeholders, navigation, field labels, enum captions, table headers and bound status labels update without changing combo item identifiers, model IDs, history rows, editable prompts, titles, descriptions or secrets. Formatted labels keep inserted content unchanged. External service errors and uncatalogued messages retain their original language; this is not a translation service for video content.

Verification (fake services, Qt offscreen):

- `python -m pytest tests/ui/test_appearance_preferences.py tests/ui/test_upload_completion_reset.py -q --basetemp=.tmp/test-appearance-final`: 10 passed.
- `python -m pytest tests/ui -q --basetemp=.tmp/test-appearance-all-ui-final`: 190 passed, 10 failed. Nine failures are horizontal overflow on Dashboard at widths 1000/1280/1366 and three scales; one is Dashboard wide-layout reflow.
- Diagnostic run disabling the new UiPreferences apply/event filter, selecting those responsive tests: the same 10 failed, 6 passed, 17 deselected. These layout failures remain unresolved; the complete UI suite is not green.
- Offscreen visual checks: `.tmp/appearance-light-en.png`, `.tmp/appearance-dashboard-light-en.png`, `.tmp/appearance-dark-vi.png`.
- `git diff --check`: no whitespace errors. `app/contracts.py` unchanged.

No real Gemini requests, TikTok downloads or YouTube uploads were performed for this fix. No screen control was used. No executable build was tested in this task.
