# YouTube Studio: connected channels and reviewed publishing

The owner approved YouTube first on 27 October 2026. TikTok/Instagram and
continuous generation/channel agents remain later milestones. This extends the
existing Upload-Post integration; it does not introduce direct Google OAuth,
Google password collection, a replacement task system or a new editor.

## Start here

1. Open MoneyPrinter **Settings → Auto-Publish**. Enable Upload-Post and configure
   the existing API key. `UPLOAD_POST_API_KEY` can supply it through the server
   environment instead of the ignored operator config file. Your Upload-Post
   account/plan limits apply. Legacy automatic upload is a separate setting; leave
   it off when using this reviewed workflow.
2. Open **YouTube Studio** in the generator's top navigation (or `?view=youtube`).
   In **Channels**, refresh existing profiles or create one with a permanent
   identifier and a friendly label. Each profile connects one YouTube channel.
3. Choose **Connect / reconnect YouTube**, then **Continue to YouTube sign-in**.
   Complete the provider-hosted Google authorization yourself in the new tab.
   Return and refresh channels. Check the displayed channel name and stable ID.
4. In **Compose & review**, choose a generated final video or a completed OpenCut
   MP4/WebM export, the destination channel, title, description, tags, visibility,
   audience and content declarations. Default visibility is **private**. The
   made-for-children declaration requires an explicit selection.
5. Choose immediate delivery or scheduling. Enter a date, time and IANA timezone
   (for example `Asia/Karachi`). The review shows the exact UTC instant. Ambiguous
   or nonexistent DST times are rejected; choose another time or UTC. Scheduling
   requires at least two minutes' notice and allows at most 365 days ahead.
6. **Prepare for review** freezes a local copy. Inspect that video, its channel ID
   and settings, then check the review confirmation and explicitly approve.
   Rendering, navigation, reload and draft preparation never approve a post.
7. **Delivery history** restores drafts after reload and shows delivery state,
   timestamps, provider-confirmed YouTube links and a short event log. Active
   delivery status refreshes every ten seconds in a small fragment; video review
   is outside timed fragments. Provider schedules are polled when due, or manually.

The service uploads the frozen bytes to Upload-Post. An accepted schedule is
owned by Upload-Post and can execute while MoneyPrinter is stopped; an approved
local job still queued or uploading needs the application running until accepted.
This schedules an upload with the chosen visibility, not an automatic change of
an existing YouTube video's visibility. Editing in OpenCut does not upload a video.

## Channels and authorization

The provider owns social OAuth tokens. MoneyPrinter stores sanitized channel IDs,
labels and last-checked metadata, never Google passwords or social refresh tokens.
Connection URLs are transient session state and are not saved in job history.
Credential caches are isolated by an API-key fingerprint. Jobs are bound to that
fingerprint plus the approved profile/channel identity; key changes, expired
connections or a different channel block dispatch. Restoring the original API key
is necessary to manage records created under it.

Profile/channel identity is checked when preparing, approving and dispatching.
The in-app connect/disconnect controls block changes while a profile has pending
deliveries. Accepted future schedules use the provider's profile: do not repoint
that profile through Upload-Post's dashboard or an earlier connection link while
it has pending posts. External changes after provider acceptance are outside
MoneyPrinter's local locking/approval boundary. Use a separate profile per channel.
Disconnecting YouTube never disconnects another social platform or deletes a profile.

## Durable delivery and duplicate protection

Metadata lives under ignored `storage/publishing/jobs/`; immutable video snapshots
live under `storage/publishing/assets/`. They are deliberately outside task/project
archives: importing an editable video does not import publishing approval, secrets
or a queue entry. Original videos, task state, scene manifests, narration, captions
and native editor drafts are not changed by publishing.

A cross-process catalogue lock serializes approvals and same-video/channel checks;
per-job OS leases serialize uploads, status changes, cancellations and retries.
One bounded background queue processes uploads without blocking editor/generation
workers. Approved queued jobs resume after reopening the studio. Interrupted
submitting/retrying/cancelling jobs become **unknown**, then reconcile against the
saved provider request ID; they are not automatically uploaded again. Expired
status records also check provider history by exact external ID and profile.

Local duplicate checks use video SHA-256 plus channel ID, independent of editable
post titles and task IDs. The provider additionally receives a stable
`Idempotency-Key`, client `request_id` and `external_id`. Upload-Post documents a
24-hour idempotency window; local duplicate records last beyond that window.
This prevents accidental repeats through this studio, not posts made separately
through YouTube, the provider dashboard or legacy automatic cross-posting.

Only a confirmed YouTube destination result counts as completion. A skipped
channel, generic provider success, no result, or an expired status record is not
reported as a published video. Provider-managed retryable results remain processing.

- **Draft / queued:** cancel locally before dispatch.
- **Blocked / rejected before acceptance:** fix credentials/connection, then retry
  the same immutable job and key, or cancel it and prepare corrected settings.
- **Confirmed failed YouTube result:** Retry uses the provider's retry endpoint
  and retained media, rather than uploading the file again.
- **Unknown:** refresh status and inspect the provider record. No resend button
  is offered because the previous upload might already exist.
- **Scheduled:** Cancel asks the provider to cancel. Failed or interrupted
  cancellation remains unknown; it is never presented as a confirmed cancellation.
- **Completed:** the original reviewed visibility is retained. A private/unlisted
  upload is not described as publicly available; its link may require authorization.

There is no automatic upload retry after an ambiguous network failure. Exactly-once
publishing cannot be guaranteed across independent third-party systems. Source
snapshots are checked again before upload; corrupted/missing bytes block delivery.
Storage limits: 512 MiB and one hour per video, 1000 durable job records, 32 queued
in-memory items (overflow remains durable and is drained as capacity returns).
This is an operator-trusted deployment, matching the existing WebUI account model.

## Compatibility and verification

The original optional cross-posting settings, service, API and generation pipeline
remain available. Their independently configured auto-upload behavior is not
silently rewritten. This YouTube-only studio always sends `platform[]=youtube`;
it cannot accidentally inherit legacy TikTok/Instagram destinations.

CPU tests mock provider transport and cover profile/link scoping, credentials,
channel identity, metadata validation, frozen-video review, duplicate approvals,
network uncertainty/restart, schedules, cancellation, retry, native WebM and stock
sources, and a real decoded FFmpeg video snapshot. Streamlit AppTest covers setup,
connections, draft review, reload recovery, unique widget keys and the actual Main
route. The focused regression run passed 78 tests and 10225 translation subtests.
No real Google sign-in, upload, scheduled publish, GPU inference or TTS call
is claimed. Those require the operator's connected account and explicit UI actions.

```sh
uv run --no-sync python -m pytest -q test/services/test_youtube_studio.py test/services/test_webui_youtube_studio.py test/services/test_upload_post.py test/services/test_youtube_audience.py test/services/test_webui_upload_post_settings.py
```

Provider contracts checked against official documentation on 27 October 2026:

- https://docs.upload-post.com/api/user-profiles/
- https://docs.upload-post.com/api/upload-video/
- https://docs.upload-post.com/api/upload-status/
- https://docs.upload-post.com/api/schedule-posts/
- https://docs.upload-post.com/api/retry-post
- https://docs.upload-post.com/api/upload-history
