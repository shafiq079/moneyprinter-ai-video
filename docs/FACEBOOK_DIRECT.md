# Direct Facebook Pages in MoneyPrinter

Approved on 28 October 2026 on `opencut-editor`. Facebook now uses Meta directly
in **Social Dashboard → Facebook** (`?view=social&platform=facebook`, with
`?view=facebook` as an alias). No Upload-Post account or dashboard is required.
This milestone manages Facebook **Pages**, not personal profiles, groups,
Instagram, Stories, analytics, comments or unattended content generation.

## Start and configure once

```sh
git switch opencut-editor
git pull --ff-only origin opencut-editor
uv sync --frozen
sh webui.sh
```

The OpenCut bundle does not need rebuilding. No GPU, generation service or voice
provider is involved in account setup or uploading an existing video.

1. Create/select an application in [Meta for Developers](https://developers.facebook.com/apps/).
   Enable Facebook Login with access to the Page management/publishing use case.
   Meta's dashboard and available products depend on the chosen app/use case.
   The permissions requested by MoneyPrinter are `pages_show_list`,
   `pages_read_engagement` and `pages_manage_posts`.
2. In **Social Dashboard → Facebook → Accounts → Meta application setup**, enter
   the app ID, app secret and the exact Facebook callback URL. Register the same
   URL in Meta's valid OAuth redirect URIs. Its path is
   `/social/facebook/oauth/callback`. Use the browser-visible public gateway,
   including its current hostname/port, rather than the random internal
   Streamlit port. HTTPS is required except for local loopback development.
   Codespaces preview domains must also be accepted by your Meta app; otherwise
   use an owned HTTPS development domain. Do not expose an unauthenticated
   MoneyPrinter installation publicly: this is a trusted operator application.
3. The default Graph API version is `v26.0`, matching the official Business SDK
   inspected for this implementation. Configure an API version supported by your
   app; a version setting does not guarantee access to every feature.
   If the app requires **Facebook Login for Business**, optionally enter its
   configuration ID. Use a **user access token** configuration that grants the
   Page permissions above. System-user-token configurations are not supported
   by this interactive account workflow.
4. Save the application, click **Connect Facebook → Continue with Facebook**,
   and authorize the intended Facebook account and Pages on Meta's website.
   MoneyPrinter never asks for a Facebook password. Return to MoneyPrinter and
   refresh available Pages. Select the intended Page and click **Attach selected
   Facebook Page**. Authorization alone neither attaches every Page nor
   approves publishing. Check the displayed Page name and stable Page ID.
5. The authorizing user must have content creation/full control tasks for that
   Page. Permission consent and Page tasks are checked again before delivery.
   Limited asset selection can hide a Page even when the user manages it.
   Reconnect to revise permissions or selected assets. App-role/test users can
   exercise development access; use by other people can require App Review,
   advanced access and business verification. This milestone does not certify
   those approvals, your app configuration, quota or Page publishing eligibility.
6. Optional server overrides: `MPT_FACEBOOK_APP_ID`, `MPT_FACEBOOK_APP_SECRET`,
   `MPT_FACEBOOK_REDIRECT_URI`, `MPT_FACEBOOK_GRAPH_VERSION`, and
   `MPT_FACEBOOK_LOGIN_CONFIG_ID`. Nonempty environment values override saved
   settings; conflicting changes from the UI are rejected. Disconnect grants
   before changing the app credentials or API version.

## Dashboard workflow

- **Accounts:** application setup, Meta authorization, available Page refresh,
  explicit attachment, Page identity checks and account-wide revocation. An
  account can authorize several Pages; disconnecting that grant removes all
  its attached Page connections and local API delivery history. Finish/cancel
  pending deliveries first. Local videos/projects and YouTube connections are
  retained. If a token has already expired, local removal does not claim Meta
  revocation; remove the app in Facebook Business Integrations yourself.
- **Content:** explicitly load Page videos or Reels, 25 at a time. Review edits
  to title/description, then save; fresh ownership and `updated_time` checks
  prevent silently overwriting a changed video. Meta may restrict edits to some
  published media. Permanent deletion requires typing the exact video ID and
  rechecking Page ownership. Pending uploads are managed in Queue first.
- **Create post:** select a completed generated final or retained OpenCut export,
  attached Page, Page video/Reel, title, description and timing. Page videos
  become public after approval and accepted publication. Reels support the
  provider's AI-generated declaration; for Page video add any needed disclosure
  to the description. There is no claim of private-first Facebook publication.
  Preparing freezes the exact delivered MP4 before a separate review/approval.
- **Calendar / Queue:** restores drafts after reload, shows upload progress,
  confirms Meta processing/publication/scheduling, and provides reviewed resume,
  reschedule and cancellation. The stored video ID always identifies the same
  remote upload. Cancellation explicitly deletes a **confirmed unpublished**
  remote video; it does not merely remove a local job. Public videos require
  permanent deletion in Content. Ambiguous initialization cannot be declared
  cancelled without knowing whether a remote resource exists.
- **Legacy publishing:** existing Upload-Post records stay at
  `?view=facebook-legacy` and `?view=youtube-legacy`. They are never converted or
  resent automatically. The old optional generator auto-publishing setting is
  independent; turn it off in Settings if all posting should require review.

## Media and scheduling boundaries

Application limits are 512 MiB, one hour for Page videos, 1000 local delivery
records, and a dedicated bounded worker. Reels have a deliberately conservative
application acceptance range: **4–60 seconds, 9:16, at least 540×960, 24–60 fps**.
These are application limits, not a claim about every current Meta format limit.
MP4 is retained as reviewed. WebM is converted locally to H.264/AAC MP4 with
FFmpeg, bounded to five minutes and 512 MiB; the converted MP4 is reviewed before
approval. Conversion requires CPU and can take time; it does not rerender scenes,
call TTS or generate new media. A source hash and delivered-file hash are retained
separately so conversion cannot bypass same-source duplicate protection.

The application accepts schedules **15 minutes to seven days ahead**. Enter local
time and an IANA timezone (default Asia/Karachi); review the resulting UTC time.
These bounds are application policy, not asserted platform-wide maxima. Meta
owns the accepted schedule and can publish while MoneyPrinter is stopped. Only
an actual matching `scheduled_publish_time` and confirmed unpublished state mark
a delivery scheduled. Processing, permissions and Page restrictions can still
delay/prevent release. If less than ten minutes remain before finishing upload,
publication is blocked until an explicit new schedule is approved.

## Transport, recovery and credentials

Page video uploads use the documented start/transfer/finish protocol on
`graph-video.facebook.com`, saving the returned video/session IDs before sending
bytes. Server byte ranges are bounded to 32 MiB and reconciled using returned
ranges, including offset conflict responses. Reels use the returned, strictly
validated `rupload.facebook.com/video-upload/<version>/<video_id>` URL and a
separate finish request. API pagination follows opaque cursors on fixed hosts,
never arbitrary `paging.next` URLs. Redirects are disabled for token/media calls.

Jobs, token grants, app secrets and OAuth flows are encrypted under ignored
`storage/social/facebook`. Encryption reuses the existing social credential key
(`MPT_SOCIAL_ENCRYPTION_KEY` or the existing 0600 local key under
`storage/social/youtube/encryption.key`); protect and back up that key. A missing
key never silently replaces encrypted records. User/Page tokens and upload
session endpoints are omitted from UI records and task archives. OAuth start
links are short lived and single use, with browser-bound state cookies,
HttpOnly/SameSite and HTTPS Secure protection. Account/configuration changes
invalidate pending callbacks. Callback/token values are not reflected in errors
or gateway access logs. Meta's interactive code flow uses OAuth state; this
implementation does not claim Meta PKCE support.

Permission loss, access expiry, network errors and transient responses surface
as actionable states rather than an infinite retry loop. Recovering an interrupted
operation preserves its ID. Reel byte transfers and publication requests are not
blindly repeated after uncertain acceptance. Unknown initialization is blocked
from automatic replacement; inspect the Page in Meta before manual resolution.
The application cannot promise exactly-once publication across external actions
or ambiguous network failures. UI refreshes only reconcile known pending IDs;
there is no background continuous generation or social scheduling agent.

## Verification and live acceptance

Tests cover OAuth state/cookie/replay/expiry, permission denial, explicit Page
attachment, encryption, identity, duplicate approval, Page upload byte ranges,
Reel ambiguity, schedules, cancellation/deletion, metadata freshness, recovery,
fixed transport hosts and frontend reloads. CPU-only MP4 and WebM fixtures verify
actual decoding/conversion with mocked Meta transport. YouTube and legacy
publishing regression suites remain in scope.

No real Meta account was authorized and no live post was created in automated
verification. Operator acceptance must validate the actual app's permissions,
selected Page roles, Meta processing, scheduling and editing behavior. Keep
publication review enabled and use a suitable test Page.

Primary implementation references:

- [Meta Reels publishing examples](https://github.com/fbsamples/Facebook-Reels-Publishing-API-Postman-Collection)
- [Official Meta Python Business SDK](https://github.com/facebook/facebook-python-business-sdk):
  `facebook_business/adobjects/page.py`, `advideo.py`, `video_uploader.py`,
  `apiconfig.py` and `session.py` for Page methods, fields, transfer protocol,
  API version and app-secret proof. Meta documentation pages were rate limited
  during implementation; no claim is made that those blocked pages were read.

## AI preparation

Create post now includes AI publishing copy, title alternatives and relevant
hashtags using the configured LLM. See [AI_PUBLISHING.md](AI_PUBLISHING.md) for
the exact workflow, platform-specific thumbnail support and review boundaries.

## Library and batch workflow

Content Library and Publishing now connect final-version review to per-account
AI preparation, posting defaults/slots and explicit batch approval. See
[CONTENT_LIBRARY.md](CONTENT_LIBRARY.md). Individual composers remain available.
