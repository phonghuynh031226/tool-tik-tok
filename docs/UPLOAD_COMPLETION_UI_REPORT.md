# Upload completion notification and fresh form

Successful upload/scheduled upload now records history first, shows a nonblocking
6.5-second success toast with a captured Open YouTube action, and resets Dashboard
to NEW. Fields, rights/kids confirmations, schedule, result panel, progress and
video preview clear; privacy resets to private and page scrolls to the URL field.
Account connection and downloaded files remain intact. A scheduled upload toast
states that the video is private until the scheduled local date/time.

History add failures now produce a warning and preserve the form. Errors and
dry runs do not trigger the success reset. Existing backend history entries are
deduplicated before reset. Contracts and backend APIs unchanged.

Toast sizing was also corrected: polished layout/height-for-width sizing before
showing, wrapping titles, and stacking by actual height. Preview inspection found
the prior 30px default frame clipped the contents.

Verification (mock uploads only, no live upload):
- New success/schedule/history-failure tests failed before implementation and pass
  after. Includes saved title/video ID, safe fresh defaults, original file retained,
  and toast action URL still valid after reset.
- Upload/reset, dry-run, v2 UI, real backend with SDK mocks and pipeline suites:
  30 passed in 8.58s. Background teardown logged deleted worker signals in that run.
- Final toast sizing + upload reset tests: 17 passed in 3.75s.
- Full UI run result recorded in .tmp/upload-reset-ui-tests.log; four known baseline
  Dashboard layout failures explicitly deselected.
- Inspected .tmp/upload-toast-reset.png showing scheduled-success toast and blank
  Dashboard. No real YouTube upload, build, commit or push.
