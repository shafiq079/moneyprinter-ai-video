# Legacy Facebook Studio: Page videos and Reels

The default Facebook dashboard now uses direct Meta authorization. See
[FACEBOOK_DIRECT.md](FACEBOOK_DIRECT.md). This document describes only the retained
Upload-Post implementation at `?view=facebook-legacy`.

Approved on 27 October 2026 on `opencut-editor`. Facebook joins YouTube through
the existing Upload-Post integration. TikTok/Instagram, Stories, analytics and
unattended content generation remain outside this milestone.

## Operator workflow

1. Pull `opencut-editor`, run `uv sync --frozen`, and start `sh webui.sh`.
   This milestone does not change the OpenCut bundle or require rebuilding it.
2. Enable Upload-Post and configure its existing key in Settings → Auto-Publish,
   or set `UPLOAD_POST_API_KEY` in the server environment. Provider plan and
   account permissions apply. Legacy automatic cross-posting is independent;
   leave it disabled if every delivery should use explicit review.
3. Open **Social Dashboard → Legacy publishing → Legacy Facebook publishing**, or `?view=facebook-legacy`.
   **Pages** can refresh existing profiles, create a profile, and open a
   Facebook-only provider-hosted connection link. Complete Meta authorization
   yourself, return, and refresh. MoneyPrinter never requests your Facebook
   password or stores Meta OAuth tokens.
4. Choose **Compose & review**, a completed generated video or native OpenCut
   MP4/WebM export, and an explicit **destination Facebook Page**. Selection
   starts empty; account names never substitute for a Page ID. This provider
   publishes to Pages, not personal profiles or groups.
5. Choose **Page video** (default, any aspect within the application's one-hour
   limit) or **Reel**. Review title and description. Reels expose the provider's
   AI-generated label, enabled by default; Page videos can put needed disclosure
   in the description because the provider label is Reels-only. Stories and
   unpublished Facebook drafts are not exposed. Local review drafts are not
   Facebook drafts: approval publishes publicly to the reviewed Page.
6. Choose delivery after approval, or a date/time/IANA timezone. For example,
   `Asia/Karachi` noon converts to 07:00 UTC. Review displays the UTC instant.
   The shared service rejects ambiguous/nonexistent DST times and requires
   two minutes to 365 days of notice.
7. **Prepare for review** freezes the selected bytes. Review the frozen video,
   Page name/ID, format, metadata and schedule; check the confirmation and
   explicitly approve. Rendering, page reload and preparation never approve.
8. **Delivery history** restores review drafts in fresh sessions and tracks
   processing, confirmed completion, schedules, failures and uncertain outcomes.
   Supported controls include draft/queued cancellation, remote scheduled
   cancellation and safe failed-delivery retry. Status uses the existing small
   polling fragment; the video and editable controls do not repeatedly redraw.

Reel preflight follows Upload-Post's current API requirements: 3–90 seconds,
9:16 (small rounding tolerance), at least 540×960 and 24–60 fps. Incompatible
videos fail before uploading; choose Page video or re-export in OpenCut.
There is no automatic crop, transcode or new generation request. The UI does not
promise that these API bounds describe all uploads made in Facebook's own app.

## Destination identity and pinned Pages

Facebook connection and Page selection are distinct. The provider's read-only
`GET /api/uploadposts/users/facebook-page?profile_username=...` returns available
Pages and the current pin. Only normalized IDs/names are cached; provider tokens,
images and raw responses are discarded. Caches are isolated by API-key fingerprint.

A pinned Page overrides `facebook_page_id`. The picker therefore offers only that
Page when a pin exists. The service re-reads the account and available Pages/pin
at preparation, approval, dispatch and explicit failed retry. A changed account,
missing Page or conflicting pin blocks the action. It never changes or clears a
pin on the operator's behalf. Use a dedicated profile per Page when scheduling.
Connection changes in this UI are blocked while the same platform/profile has
pending deliveries; Facebook disconnect removes only Facebook, preserving YouTube.

This is not an atomic provider-side destination lock. Do not change the profile
connection or pin through Upload-Post or an old OAuth link while it has pending
posts. Changes between the final read and remote upload, or after acceptance of
a future schedule, are outside MoneyPrinter's local approval/locking boundary.
Accepted schedules are owned by Upload-Post and can execute while MoneyPrinter
is stopped. Local queued jobs still require the app running until accepted.

## Shared delivery contracts and compatibility

Facebook reuses the existing durable publishing catalogue, immutable SHA-256
snapshots, per-job leases, catalogue approval lock, bounded single worker,
provider idempotency and stable request/external IDs. Each new job records
`platform`; historical records without it remain YouTube. Default YouTube
history filters out Facebook; Facebook history rejects other-platform IDs.
Duplicate prevention is SHA-256 + platform + destination ID: intentionally
approving the same bytes to YouTube and Facebook is possible, but another title,
profile or task cannot bypass the same-Page guard.

Every upload sends only `platform[]=facebook`, the reviewed Page ID and explicit
`facebook_media_type`/`video_state=PUBLISHED`. No YouTube visibility/audience/tags
fields or legacy cross-post destination list leak into Facebook uploads. Only a
confirmed Facebook result marks completion; a YouTube-only/generic response does
not. Expired status reconciles exact external ID + profile + Facebook history.
Known failures retry the provider's retained media, never upload again blindly.
Timeouts/interrupted submissions/retries/cancellations become unknown and require
status reconciliation. Provider idempotency has a finite window (documented as
24 hours); local durable duplicate guards continue beyond it. No exactly-once
claim is made for third-party systems or external posts.

Storage remains ignored `storage/publishing/`, separate from project archives;
importing a video never imports publishing approval. Limits remain 512 MiB,
one hour, 1000 jobs and 32 in-memory queue entries with durable overflow.
Generator, narration, captions, editor, original task artifacts and legacy
optional auto-upload behavior are unchanged. No new dependency is introduced.

## Verification

CPU tests replace external transport. They cover platform/history isolation,
legacy YouTube compatibility, Facebook-only hosted links/disconnect/uploads,
profile-scoped Pages and pin precedence, changed account/key/Page rejection,
Reel bounds, duplicate approvals, immutable review, explicit scheduling,
uncertain transport/recovery, provider cancellation and retained-media retry.
A real 540×960/24 fps MP4 Reel is decoded and frozen, its original deleted,
then the retained bytes pass through actual multipart upload dispatch to a
mocked provider and confirmed remote schedule cancellation.
Streamlit AppTest covers the actual Main route, no-connect/publish on reload,
explicit Page selection, separate approval, fresh-session draft recovery,
unique compose/history widget keys, pin-filtered picker, timezone schedule and
English/Chinese labels. Live Meta authorization, real Facebook posts and real
scheduled execution remain operator acceptance; tests do not claim those passed.

Final verification covered 97 distinct test cases and 10225 translation
subtests. The combined run passed 95 cases but timed out in two existing settings
tests; a fresh diagnostic run of all seven settings tests passed without code
changes. Ruff, compilation, frozen dependency sync and whitespace checks passed.

Official provider contracts checked on 27 October 2026:

- https://docs.upload-post.com/api/user-profiles/
- https://docs.upload-post.com/api/facebook-page/
- https://docs.upload-post.com/api/get-facebook-pages/
- https://docs.upload-post.com/api/upload-video/
- https://docs.upload-post.com/api/video-requirements/
- https://docs.upload-post.com/api/upload-status/
- https://docs.upload-post.com/api/schedule-posts/
- https://docs.upload-post.com/api/retry-post
- https://docs.upload-post.com/api/upload-history
