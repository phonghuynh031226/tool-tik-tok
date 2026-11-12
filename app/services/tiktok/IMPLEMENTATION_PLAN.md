# TikTok backend

Scope: only this package and tests/services; contracts.py remains unchanged.

1. Write offline tests for URL validation and redirects, metadata, cancellation,
   transient-only retries, cache reuse, ffprobe and explicit local updating.
2. Implement strict HTTPS canonical URLs and a manual redirect resolver (5 hops).
   Validate every target before requesting it; reject photo posts and credentials.
3. Add Vietnamese error mapping and cancellable local subprocess/ffprobe helpers.
4. Implement synchronous yt-dlp service. Save verified MP4 atomically in the
   requested project-local directory (normally downloads/<video_id>.mp4).
   Download into a fresh staging directory; retain existing file until replacement
   is verified. Retry at most 3 times after the initial attempt (1/2/4 second waits).
   Select best direct HTTP(S) muxed MP4, then video-only MP4 if necessary. Do not
   merge separate streams or start SDK-managed ffmpeg/HLS jobs without cancellation.
5. Keep contract progress float [0,1]; optional implementation-only on_details
   callback carries bytes/speed/ETA. Mark 100% only after verification.
6. Expose version and opt-in updater for project .venv; no automatic network/update.
7. Run offline tests and full pytest, verify unchanged contract hash and edit scope.

No watermark removal, DRM bypass, browser cookies or credential logging. All SDK
logs are suppressed to avoid leaking signed media URLs. ffmpeg/ffprobe are read
only from project bin and are never installed automatically. Updating takes effect
after application restart; it deliberately does not edit shared requirements.txt.
The updater disables pip file configuration with PIP_CONFIG_FILE=os.devnull;
--isolated alone does not disable global/site configuration. Wrapped certificate
errors are permanent; URLError.reason is included in classification.
