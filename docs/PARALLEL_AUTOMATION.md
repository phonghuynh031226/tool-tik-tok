# Parallel preparation for automation

After Dashboard metadata is available, automation starts downloading and generating text concurrently. Upload is gated on both branches completing successfully. Files API analysis remains sequential because it requires a downloaded MP4. Cancelling or failing cancels the other branch; late AI callbacks are guarded by the job identity. Contracts are unchanged.

Verification: QT_QPA_PLATFORM=offscreen python -m pytest tests/ui/test_automation_ui.py tests/ui/test_automation_errors.py -q --basetemp=.tmp/test-parallel-final

Mock tests cover overlap with blocked workers, either completion order, exactly one upload after the join, and MP4 analysis waiting for download. No real Gemini request, TikTok download or YouTube upload was performed. No real timing benchmark or executable build was tested.
