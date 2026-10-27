# Direct YouTube in MoneyPrinter

The owner approved replacing the default YouTube publishing surface with direct
Google authorization on 27 October 2026. This milestone stays on `opencut-editor`.
It uses Google's official APIs and OAuth libraries; no Upload-Post account, key,
profile or service is required for direct YouTube.

## Start and configure once

```sh
git switch opencut-editor
git pull --ff-only origin opencut-editor
uv sync --frozen
sh webui.sh
```

The existing OpenCut build is unaffected. Do not skip dependency sync: the pinned
Google OAuth library is new. No GPU, model, speech or paid publishing service is
needed to start this dashboard.

1. In Google Cloud, create/select the development project. Enable **YouTube Data
   API v3**. Configure Google Auth Platform branding, audience and data access.
   For an external app in Testing, add the operator's Google account as a test
   user. Configure the application name accurately (for example MoneyPrinter).
2. Create an **OAuth client ID → Web application**. This is a client ID and
   client secret, not a Google API key and not a Google password.
3. Open MoneyPrinter **Social Dashboard → Accounts → Google application setup**.
   The callback suggestion uses the current public Codespaces port/hostname or
   local loopback address. Register that exact URL in Google's authorized
   redirect URIs, then save the client ID, client secret and callback in
   MoneyPrinter. Example path: `/social/youtube/oauth/callback`.
4. Google matches the complete callback including scheme, hostname, port and
   path. Use the browser-visible public gateway, never the random internal
   Streamlit port printed in backend logs. If the launcher changes the public
   port, update the callback in Google and MoneyPrinter together. Keep Codespaces
   forwarding access private to the operator. If Google rejects a shared preview
   hostname, use local loopback development or an owned HTTPS development domain.
5. Alternatively set server environment values `MPT_YOUTUBE_CLIENT_ID`,
   `MPT_YOUTUBE_CLIENT_SECRET` and `MPT_YOUTUBE_REDIRECT_URI`. These override
   encrypted saved settings; conflicting UI changes are rejected explicitly.
6. Click **Connect YouTube**, then **Continue with Google**. Google handles
   account/channel selection and permission consent in a new tab. Return to
   MoneyPrinter and refresh accounts. Check the actual channel name and stable
   channel ID. Connect additional channels separately; channel IDs never repoint
   an existing connection. Brand-account behavior must be checked with the
   operator's actual Google role; an email address alone is not a channel ID.

The requested `youtube.force-ssl` permission covers the implemented read, upload,
metadata, thumbnail and deliberate deletion actions. The consent wording is
broader than upload-only permission because this dashboard manages existing
videos. Analytics and comments are not implemented in this milestone.

Google external Testing refresh tokens generally expire after seven days. A
refresh token is not a permanent login guarantee: revocation, permission changes
and Google policy can require reconnection. Production OAuth verification and
YouTube API quota/compliance review are separate processes. Google's current
video-resource reference and Help documentation conflict about unverified
project private-only uploads; do not promise unrestricted public publishing
before validating the actual project or obtaining clarification/required review.
No app verification/audit or quota extension is claimed by this code milestone.

## Dashboard workflow

- **Accounts** configures the Google app, connects/checks channels and revokes
  access. Credentials are never sent to the frontend after storage.
- **Content** loads 25 existing channel videos at a time with Load more. It uses
  the authenticated channel's uploads playlist, then fetches those videos; no
  scraping, video download or unnecessary search API is involved. Reload before
  editing. Metadata editing verifies fresh ownership and the reviewed ETag,
  preserves supported fields, and retains an existing private video schedule
  unless visibility/scheduling is intentionally changed. Pending direct jobs
  must be managed in Queue before remote metadata editing.
- **Create post** selects a completed generated final or native OpenCut MP4/WebM
  export, channel, title, description, tags, category ID, visibility, audience
  and content declarations. Review and approval are separate. Private is the
  default; audience is an explicit choice. The video is decoded and frozen
  before review. Later rendering or deleting its source cannot change approval.
- **Calendar / Queue** lists planned UTC times and durable drafts/deliveries.
  Fresh browser sessions restore draft approval controls. Live status is a small
  polling fragment; forms and review videos are outside timed fragments.
  Details include a bounded event log without credentials or upload session URLs.
- **Legacy publishing** links to the old Upload-Post YouTube/Facebook interfaces.
  Default `?view=youtube` now opens direct Social Dashboard; legacy YouTube is
  `?view=youtube-legacy`. Existing jobs never change transport, get silently
  imported or resend through Google. The generator navigation opens Social
  Dashboard. Facebook still uses the old provider until its direct milestone.

Category defaults to 22 (People & Blogs). The UI accepts an explicit numeric
YouTube category ID; invalid/unavailable categories can be rejected by Google.
Thumbnail changes accept decoded JPG/PNG up to 10 MiB and 4096 pixels per side;
Google/channel eligibility still applies. Thumbnail upload is explicit and does
not reupload the video. Permanent video deletion requires typing its exact ID,
verifies ownership again and leaves the local project/video intact.

## Upload and publication contract

A new direct upload always starts **private**, irrespective of final reviewed
visibility. The upload uses bounded 8 MiB resumable chunks. The encrypted session
URL and committed offset survive restart. Before sending any further bytes, the
worker queries Google's received range; it never assumes a timed-out chunk was
lost. No-progress responses are bounded. Lost initialization results or expired
sessions become unknown rather than starting a second video automatically.

The returned remote video ID is saved before a separate metadata operation sets
reviewed visibility or schedule. A lost publication response reconciles that ID;
it never resends video bytes. Processing, scheduled, published, private/unlisted
completion, paused and unconfirmed publication are distinct. Only Google's
current response is treated as confirmation; API acceptance is not proof that
processing, copyright checks or public availability succeeded.

Scheduling means **public release**, not delaying the first upload. MoneyPrinter
uploads privately now, then sends `status.publishAt` with private visibility.
Once Google accepts the schedule, YouTube owns its execution even while
MoneyPrinter is stopped. A locally queued/unaccepted upload still needs the app
running. Processing/account restrictions can delay publication. If the chosen
instant passes before acceptance, the video stays private and requires explicit
rescheduling; it is never accidentally published immediately with a past time.

Queue controls can reschedule a pending private publication or cancel it while
keeping the uploaded video private. Cancellation is confirmed with a fresh read;
uncertain cancellation is not reported as completed. A video already public must
be managed through Content. Active transfers own a job lease; wait for completion
or pause before cancelling. Cancelling without a returned video ID abandons local
publication but cannot guarantee Google retained no partial/private resource.
Inspect Content when an outcome is unknown. Deletion is a separate explicit action.

A bounded single worker and per-job OS leases preserve responsiveness and serialize
updates. Approved queued work resumes on reopening the dashboard; interrupted
transfers pause for reconciliation and explicit resume. Duplicate approval checks
use video SHA-256 plus channel, independent of task/title. Known legacy deliveries
are checked before preparation and approval. Upload-Post's independently scheduled
posts and legacy automatic cross-posting remain outside Google's idempotency
boundary; do not approve the same video through both paths. Existing automatic
cross-posting, if enabled, produces a warning rather than being silently modified.

Limits remain one hour, 512 MiB per video, 1000 direct jobs and 32 in-memory entries
with durable queue overflow. No exactly-once guarantee is made across Google,
external dashboard actions and network failures.

## Credentials, data and deployment boundary

Google client settings, access/refresh tokens, OAuth transactions and direct jobs
(including upload URLs) are encrypted under ignored `storage/social/youtube/`.
The application uses Fernet with an operator environment key
`MPT_SOCIAL_ENCRYPTION_KEY`, or an automatically generated local 0600
`encryption.key`. Back up that key securely with encrypted records; losing it
requires restoring the original key or reconnecting. It is not written to task
manifests, exports or project archives. Legacy immutable media snapshots remain
under `storage/publishing/assets/` and carry no Google secrets.

OAuth uses a ten-minute, single-use start capability followed by authorization
code + PKCE, a single-use state, and an HttpOnly SameSite=Lax browser binding
cookie. HTTPS callbacks use Secure cookies; loopback development is the only
HTTP exception. Epoch checks invalidate in-flight callbacks after configuration
or disconnection changes. The gateway handles callbacks before Streamlit proxying,
uses no-store/no-referrer responses, strips callback parameters from return links
and disables its access logging. Reverse proxies must also avoid logging OAuth
query strings. Redirects are disabled for API/token revocation/upload requests;
resumable URLs are restricted to Google's exact upload endpoint hosts/path.

Disconnect revokes Google access, removes the selected local credentials and its
direct API-derived delivery history, and invalidates pending connection links.
Original user-created local media/projects are retained. Because Google revocation
can affect a shared grant, other cached channel connections are marked as needing
reconnection; all pending direct deliveries must finish/cancel before revocation.
Revocation is not presented as deletion of uploaded videos or accepted schedules.

This retains the existing **single trusted operator** WebUI deployment model.
Use private Codespaces forwarding or an authenticated reverse proxy. This is not
multi-user SaaS authorization: do not expose the setup/dashboard to anonymous
users. A public release needs owned-domain verification, accurate privacy/data
lifecycle policies, authentication/account isolation and Google review as applicable.
Per-session content cache is not a permanent analytics database. No Google Analytics,
revenue ingestion, monetization setup, copyright dispute or full YouTube Studio
feature parity is claimed.

## Verification and acceptance

Automated tests use official OAuth library URL/PKCE generation and a real gateway
cookie/callback flow with mocked token exchange. They cover expired/replayed/
foreign-browser callbacks, encrypted files/key mismatch, exact channel identity,
frozen snapshots, duplicate approvals and legacy boundaries, resumable offsets,
no-progress/expired sessions, missed schedule times, lost publication responses,
refresh/revocation, metadata field preservation and deletion/thumbnail bounds.
A real CPU MP4 is decoded and frozen, its source deleted, and its bytes pass through
actual direct resumable request orchestration into mocked Google scheduling.
Streamlit AppTest checks setup without Upload-Post, connection links, review versus
approval, fresh-session draft restoration, content editing and actual Main routes.

The final regression run passed **139 tests and 10225 translation subtests**;
the final direct-only run after storage worker hardening passed all **30 tests**.
Ruff, compilation, frozen dependency sync, lock validation and whitespace checks
passed. TestClient emits an upstream deprecation warning about its HTTPX adapter;
there were no test failures in those completed verification runs.

Live acceptance still requires the operator's Google Web client and own channel:
authorize, upload privately, verify the returned channel/video, edit metadata,
explicitly schedule a test publication, check cancellation, and revoke/reconnect.
No live Google login, upload, public release, GPU inference or TTS is performed by
the automated tests. Those are not represented as passed from mocks.

Official contracts checked 27 October 2026:

- https://developers.google.com/identity/protocols/oauth2/web-server
- https://developers.google.com/identity/protocols/oauth2
- https://developers.google.com/youtube/data/reference/rest/v3/channels/list
- https://developers.google.com/youtube/data/guides/using_resumable_upload_protocol
- https://developers.google.com/youtube/data/reference/rest/v3/videos
- https://developers.google.com/youtube/data/reference/rest/v3/videos/update
- https://developers.google.com/youtube/data/reference/rest/v3/videos/delete
- https://developers.google.com/youtube/data/reference/rest/v3/thumbnails/set
- https://developers.google.com/youtube/data/guides/quota_and_compliance_audits

## Facebook alongside YouTube

Social Dashboard now has a platform selector. Facebook uses direct Meta app
setup and Page management, described in [FACEBOOK_DIRECT.md](FACEBOOK_DIRECT.md).
Google grants and uploads are unchanged. Upload-Post remains legacy only.

## AI preparation

Create post now includes AI publishing copy, title alternatives and relevant
hashtags using the configured LLM. See [AI_PUBLISHING.md](AI_PUBLISHING.md) for
the exact workflow, platform-specific thumbnail support and review boundaries.
