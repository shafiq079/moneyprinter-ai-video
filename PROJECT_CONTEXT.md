# MoneyPrinter AI Video — Project Context

Read this file first in every new AI or developer session. `docs/SRS.md` is the full product specification; `docs/MIGRATION_MAP.md` is the file-level porting decision. `docs/PRODUCT_VISION.md` preserves the owner's longer-term editable-project and publishing goals separately from implemented scope and unapproved technical proposals. `docs/CHATGPT_PROJECT_SETUP.md` contains the reusable ChatGPT Project handoff. Update this handoff with every accepted milestone. Local desktop Codex setup and two-machine sync instructions are in `AGENTS.md` and `docs/LOCAL_CODEX_SETUP.md`.

## Direct Facebook authorization and Page publishing (28 October 2026)

The owner approved the direct Facebook milestone on `opencut-editor`. Social
Dashboard now switches between YouTube and Facebook; `?view=facebook` routes to
its direct Meta panels. The generator Facebook shortcut opens the same dashboard.
Meta app setup, browser-bound Facebook OAuth, permission/Page discovery and
explicit Page attachment replace Upload-Post in the default Facebook workflow.
YouTube and its encrypted grants remain independent.

Content loads Page videos/Reels, reviews title/description changes with fresh
ownership/revision checks and exact-ID permanent deletion. Create post freezes a
completed video or retained OpenCut export for separate public-post approval.
WebM converts locally to reviewed MP4, without TTS/GPU/generation. Page video
uploads use graph-video start/transfer/finish ranges; Reels use validated rupload
URLs and separate finish. Same-ID recovery and ambiguous-operation blocking
avoid silently creating replacement uploads. Calendar / Queue restores drafts,
tracks Meta state, reschedules and explicitly deletes confirmed unpublished
uploads when cancelling. Local projects are retained.

Application bounds: 512 MiB, one hour Page video, conservative Reels 4–60 sec,
9:16/minimum 540×960/24–60 fps, 1000 records, bounded dedicated queue and schedules
15 minutes–7 days ahead. These are application policy rather than claimed Meta
maximums. A late schedule blocks publication; only a matching actual Meta
schedule is reported accepted. No private-first Facebook semantics or exactly-once
network guarantee is promised. Interrupted Reel transfers/publication are never
blindly resent. Unknown initialization cannot be falsely cancelled.

Meta secrets/flows/jobs are encrypted in ignored storage/social/facebook using
the existing social encryption key. Account-wide disconnect blocks pending work,
revokes the grant, clears its Page connections/history, retains local media and
leaves YouTube alone. An expired token's local removal never claims confirmed
revocation. The existing gateway serves both callbacks without access-log secrets.
English/Chinese labels and secondary-locale English fallback are maintained.
Legacy Facebook is now ?view=facebook-legacy; legacy records and optional automatic
cross-posting remain separate and are never migrated/replayed automatically.

See docs/FACEBOOK_DIRECT.md for Meta app setup, permissions, API transports,
security, recovery and operator acceptance. No live Meta authorization/upload,
App Review approval, production eligibility or GPU validation is claimed.
TikTok/Instagram, analytics and unattended generation remain future scope.

Verification: 171 focused tests and 10225 translation subtests passed, including
YouTube, legacy publishing/settings and OpenCut regressions. After final malformed
start-response protection and actual Main-route checks, all 35 Facebook
service/dashboard tests passed again. Ruff, compileall, frozen dependency sync,
lock validation and whitespace checks passed. Real CPU MP4 decoding and WebM
conversion were verified against mocked Meta transports. No real social account
was authorized and no remote content was uploaded, edited, scheduled or deleted.

## Direct YouTube authorization and Social Dashboard (27 October 2026)

The owner clarified that social management must live inside MoneyPrinter, without
an Upload-Post account. After official API/product research, the owner approved
the complete direct YouTube milestone on `opencut-editor`. Development/main remain
unchanged. The later direct Facebook milestone is documented above; TikTok/Instagram remain later.

The generator opens Social Dashboard (`?view=social`; `?view=youtube` aliases it).
Accounts provides encrypted Google Web-client setup, Connect YouTube, hosted
Google consent and callback, verified channel identity, reconnect and revocation.
The existing same-origin gateway owns short-lived browser-bound OAuth state/PKCE
and callback routes. No Google password or Upload-Post key is required. One Google
Web application is configured by the operator; channel owners authorize it.

Content lists existing channel videos through the uploads playlist, edits
metadata/visibility with current ownership/ETag checks, preserves private schedules,
sets validated thumbnails and explicitly deletes videos only after exact-ID
confirmation. Create post freezes a completed final/native export before separate
review/approval. Calendar / Queue restores drafts and tracks resumable bytes,
processing, scheduled/public/private completion, pauses and unconfirmed outcomes.
Forms remain outside timed status fragments. English/Chinese labels are included.

All uploads start private. Resumable URLs/offsets and returned video IDs persist
before release changes. A restart reconciles Google's committed bytes; uncertain
initialization/expired sessions never silently start another video. Scheduled
public release uses YouTube's publishAt after upload; accepted schedules execute
at YouTube even while MoneyPrinter is stopped. Passed times stay private until
explicitly rescheduled. Remote cancellation rechecks removal of the schedule and
keeps the video private; permanent deletion is separate. Limits remain 512 MiB,
one hour, 1000 records and a bounded dedicated queue. Exactly-once publication is
not claimed across network failures or external platform actions.

Google settings, grants, OAuth transactions and jobs are encrypted in ignored
storage/social/youtube; the key is an operator secret or local 0600 key file.
No OAuth/session credentials enter task archives or logs. Disconnect revokes and
clears selected local API-derived history, retains user-created video/project
assets, invalidates pending callbacks and flags potentially shared Google grants
for reconnection. This remains a trusted single-operator WebUI, not multi-user SaaS.
Legacy Upload-Post records/interfaces remain separate at ?view=youtube-legacy and
?view=facebook-legacy; they are never migrated or resent through Google. Generator,
OpenCut, narration, scenes and old optional automatic cross-posting are preserved.

See docs/YOUTUBE_DIRECT.md for Google setup, exact callbacks/forwarded ports,
Testing-token lifetime, verification/audit uncertainty, quota and data boundaries.
The pinned OAuth library is new: run uv sync --frozen before launching. No OpenCut
rebuild is needed for this Python-only milestone. Real Google sign-in, private
upload and scheduled-public acceptance require the operator's Google app/channel;
CPU mocks do not establish project verification or live publishing eligibility.

Verification: **139 focused CPU tests and 10225 translation subtests passed**,
including old publishing/settings and OpenCut regressions. After the final storage
worker hardening, all **30 direct-account/service/dashboard tests passed again**.
The proof includes real OAuth URL/PKCE generation, real gateway cookie callbacks
with mocked token exchange, encrypted credential/session persistence, interrupted
byte ranges, missed schedules, lost publication responses, channel isolation,
revocation, ETag/field preservation and decoded real MP4 upload orchestration to
mocked Google transport. Actual Main routes and fresh-session review are covered
by Streamlit AppTest. Ruff, compileall, frozen dependency sync, lock validation
and whitespace checks passed. Live Google authorization/uploads/public schedules
remain operator acceptance; no GPU, TTS or paid publishing calls were made.

## Facebook Pages and Reels publishing (27 October 2026)

The owner approved Facebook as the next publishing platform on `opencut-editor`.
Facebook Studio (`?view=facebook`) adds Facebook-only hosted connection and
platform-specific disconnect, profile-scoped Page discovery, explicit Page
selection, Page video/Reel metadata and AI-label controls, frozen review,
approval, scheduling and reload-safe history. TikTok/Instagram remain later.

The existing YouTube durable delivery service now handles platform-tagged jobs;
legacy jobs without a platform remain YouTube. Each studio filters its history,
while one shared worker resumes approved deliveries for either platform.
Duplicate protection includes platform and destination, permitting deliberate
cross-platform publishing without same-Page duplicates. Uploads/results/history
reconciliation stay platform-specific; unknown outcomes never blindly reupload.
YouTube generation, editor and legacy optional cross-posting behavior remain.

Facebook Page ID and connected account identity are checked at prepare, approval,
dispatch and retry. The provider's Page pin overrides request Page ID: conflicting
pins block, available choices respect pins, and the app never clears pins.
External profile/pin changes during dispatch or after provider schedule acceptance
remain outside local locking; use dedicated profiles. Only Pages are supported,
not personal profiles/groups. Page posts are public and explicitly reviewed.
Reels have provider API format preflight; Page videos retain existing application
media limits. See `docs/FACEBOOK_PUBLISHING.md` for setup and exact boundaries.

Verification: all **97 focused test cases passed across the final runs**, plus
**10225 translation subtests**. The broad run had 95 passes and two existing
settings-test timeouts; a fresh diagnostic run passed all seven settings tests
without changes. Facebook coverage includes actual Main routing, separate
review/approval and recovery, profile-scoped pin checks, cross-platform history
and duplicate isolation, and a real 540×960/24 fps Reel frozen/decoded then
submitted through mocked multipart scheduling/cancellation. Ruff, compileall,
frozen dependency sync and whitespace checks passed. No live Meta sign-in,
Facebook post/scheduled execution, GPU inference or TTS was performed.

## YouTube-first connected accounts and reviewed publishing (27 October 2026)

The owner approved moving account attachment and publishing automation into
scope, then explicitly limited the first release to YouTube; TikTok/Instagram
remain later. Work continues on `opencut-editor`, preserving development/main.

Generator navigation now opens YouTube Studio (`?view=youtube`) outside the
editor. The existing Upload-Post provider supplies hosted YouTube-only OAuth
connection links, profile/channel lookup and reconnect/disconnect. Google tokens
stay with the provider; local cached identity is bound to an API-key fingerprint.

Compose selects a generated final or completed native MP4/WebM export and saves
an immutable video snapshot with title/description/tags, visibility (private by
default), explicit audience/content declarations and optional timezone-validated
schedule. Review and approval are separate. Drafts/history survive restart.
The bounded durable delivery queue uses cross-process locks, SHA/channel duplicate
checks, provider idempotency and stable request IDs. Uncertain/interrupted HTTP
operations reconcile status instead of re-uploading; provider-confirmed failures
retry retained remote media. Accepted schedules live at Upload-Post. Generation,
old optional auto-upload behavior, scene contracts and OpenCut are unchanged.
See `docs/YOUTUBE_PUBLISHING.md`, including the boundary around externally changed
provider profile destinations and the 24-hour provider idempotency window.

Verification: **78 CPU tests and 10225 translation subtests passed**, covering
the new provider/storage/UI contracts and existing publishing/audience/settings
behavior. A real FFmpeg MP4 was decoded and frozen, its source removed, and the
retained bytes submitted to a mocked scheduled-upload transport. The actual Main
route, connection controls, separate approval, fresh-session draft recovery,
unique review widgets and en/zh labels were exercised with Streamlit AppTest.
Ruff, compilation, frozen dependency sync and whitespace checks passed. Real
Google sign-in, live YouTube uploads/schedules, model inference and TTS were not
performed; operator setup and explicit live actions remain necessary.

## Combined OpenCut clip controls and font milestone (27 October 2026)

The owner approved both changes together on `opencut-editor`. The base native
OpenCut integration was previously promoted into development (`b1c9323`);
this new milestone stays on the OpenCut branch until explicitly promoted.

The native right inspector now includes AI Clip for linked generated footage:
prompt editing, Regenerate, New variation, Advanced seed, candidate review,
version history and uploaded replacement footage. Preview uses the upper monitor;
Use this version replaces only the selected occurrence through the native Undo
command system and preserves compatible timeline edits. Insufficient footage
blocks explicitly. Stable scene IDs survive split/duplicate and server reload;
old drafts link only unambiguous source hashes. Candidate generation is bounded,
cancellable at provider boundaries and recoverable after interruption. It does
not rewrite the original manifest/plan or recompose original final video.
Candidate versions/media travel in existing project archives. See
`docs/OPENCUT_EDITOR.md` for queue ownership, persistence and scope.

The native Font Family field is now a searchable local/system/OpenCut picker.
Installed MoneyPrinter fonts are loaded as actual browser FontFaces; TTC files
are converted to their first face with pinned FontTools. New caption imports
retain the saved font family. Existing drafts preserve their selected font.
No other caption controls are duplicated. Local font loading, native preview,
text edits, reload and export share the same family mapping.

Verification: 18 focused OpenCut/archive CPU tests passed. Real Chromium checked
local font loading/selection, candidate generation/preview/apply/Undo, selected
split-occurrence isolation, reload/fresh-browser restoration and native 1080x1920
WebM export with audible narration saved back to the task. There were no page
errors in the completed run. The CPU browser harness uses VP9 fixtures and native
WebGL fallback with CPU rasterization flags, avoiding software Dawn/external-image
copy and GPU-memory failures observed during initial runs. Production rendering
and provider dispatch remain unchanged. Ruff, pinned build, formatting and compile
checks passed. Live model inference/TTS/paid music/publishing were not exercised.

## Codespaces WebSocket/restart correction

The operator's forwarded HTTPS page stopped at Streamlit's initial skeleton and
reported a failed /_stcore/stream WebSocket. Gateway origin checks now accept
normalized actual Host or forwarded Host, with an exact current-port Codespaces
host derived from the documented environment variables. A forwarding header can
no longer override an already-correct Host. Foreign origins remain rejected.
Loopback WebSockets explicitly bypass environment proxies. Shutdown is bounded,
and POSIX port probes use listener-compatible SO_REUSEADDR so TIME_WAIT does not
force unnecessary public-port changes.

Eight focused tests passed. A real Streamlit session received binary new-session
and UI delta frames through an HTTPS Codespaces-style origin with localhost
forwarding headers. Stopping with the socket open took about one second in that
check, and the actual shell launcher immediately restarted on the same port.
The operator's remote Codespace still requires pulling this fix and restarting;
no claim is made that its actual browser session was remotely inspected.

## Owner-approved OpenCut experiment (26 October 2026)

The owner changed direction and explicitly requested a separate `opencut-editor`
branch. This is the authorized exception to the older two-branch rule. It starts
at development `df626edd3022863723382d7fedf58882ae688629`; do not modify or merge
into development/main during this experiment. AGENTS.md records this exception.

The real MIT OpenCut Classic editor is now integrated as a pinned source build,
not a recreated UI. Its native timeline/media/preview/properties/command system
and browser exporter run full-page on the same WebUI address via a local gateway.
MoneyPrinter generation, source scene history, Resume/Regenerate and the Python
composer remain intact. Task Manager Edit opens OpenCut. AI/original tools remain
available explicitly; native edits are independent of the generation manifest.

Native projects/media are saved under each task's opencut directory with bounded,
task-scoped capability access, SHA-addressed media, atomic writes and stale-tab
revision checks. Reload and fresh-browser restoration use server storage.
Native exports download and also save separately; Task Manager playback prefers
the newest completed native export. Project archives retain the native draft,
media and exports, and import copies use task-scoped browser IDs.

See docs/OPENCUT_EDITOR.md for setup, rollback, exact import/style boundaries and
CPU checks. The upstream main repository is a rewrite; its maintainers recommend
Classic for a working editor. The integration pins Classic cf5e79e919144200294fb9fed22a222592a0aeea.
Verification on this branch: 83 focused editor/archive/queue/i18n regressions,
93 composer/history/artifact checks (3 skipped), 11 native/archive checks and
20 gateway/history checks passed (counts overlap). The reproducible real
Chromium acceptance edited a caption, saved/reloaded it, restored media in a
fresh browser, exported 1080x1920 WebM with audible narration and saved it back
to the task. Source-only and full pinned npm build setup passed, as did Ruff,
compileall and shell syntax checks. No model GPU, TTS, paid music or publishing
calls were made. Full platform/browser CI is configured for this branch.

Initial support remains saved creative AI scene projects. Native beta limitations,
caption font/word-color/outline/animation mapping and non-mapped transitions are
explicitly documented. This does not claim full CapCut feature parity.

## Canonical product and repository state

- **Product base:** `harry0703/MoneyPrinterTurbo` `main`, commit `ad5496f1b729d1d7e361dd972015d26c08b0e052` (verified again on 26 September 2026). The local `upstream` remote points there. Vendor tag: `vendor/mpt-2026-09-26-ad5496f`.
- **Branches:** `main` is the stable accepted product branch and now includes the completed CPU-tested AI-video and first factual-mode implementation; `development` is the sole active development branch and was fast-forwarded to the promotion merge before further work. Create no other branches. Commit ordinary changes on `development`, promote accepted milestones to `main` with a normal merge commit, then fast-forward `development` to that merge.
- **Product remote:** `https://github.com/shafiq079/moneyprinter-ai-video`. This CPU hardening pass started at `development` commit `269d5c0202492608e2a1309c94afcf1650bea3fc`; the pinned original vendor commit remains `ad5496f1b729d1d7e361dd972015d26c08b0e052` and is preserved by the vendor tag. Use only the two product branches. `origin` points to this product repository and `upstream` points to `harry0703/MoneyPrinterTurbo`. Do not use the older `shafiq079/MoneyPrinterTurbo` fork for this product.
- **Old prototype:** `shafiq079/content-factory` `main` at `a1760488aae68b8c1c1076a26720a14f4368088f` is read-only reference. Its Next.js UI, FastAPI project API, SQLite queue, timeline v7 and renderer are **not** the new application.
- **Completed:** SRS conversion, upstream revalidation and migration decisions; M1 fake-provider foundation; M2/M3 Wan integration and operator surface; M4 Scene Director; LTX 2.5 Fast/DFR; Phase 5 scene iteration; render-only rerender, cancellation, cleanup, provenance/security hardening, true No-Voice local-AI rendering, portable local-AI output packages, per-GPU cross-process runtime serialization, persisted local-AI timing telemetry, local-AI final-output validation, structured local-AI observability, visual-only regeneration/audio-caption reuse regression coverage, final audio gain-control regression coverage, and recoverable final-validation failure classification. Real Wan/LTX inference and Phase 6 quality measurements require GPU hardware and remain deferred.

## Architecture to preserve

The owner confirmed that a final MP4 alone is not the full long-term product:
an editable project with independently adjustable scene clips, narration,
captions and audio is now implemented for saved creative AI projects through
the dedicated Streamlit editor, embedded offline timeline and portable archive
workflow. This remains a bounded editor rather than a full NLE. Archive format
version 1 wraps existing task sidecars; it does not replace their data contracts. See `docs/PRODUCT_VISION.md` before
scoping editor, variable-duration, publishing or channel-automation work.

Task Manager has a separate **Resume** action for failed local-AI tasks with
saved script/audio/scene plan/manifest. It queues work under the same task ID,
skips script/LLM/TTS/captions, revalidates and reuses completed scene versions,
generates missing/failed scenes, and composes the final video. **Regenerate**
still loads old settings to create a new task. Resume requires persisted inputs
and cannot recover a task that failed before those inputs existed. A changed
provider model fingerprint invalidates cached clips as designed.

`app/services/task.py` orchestrates script, search terms, narration/custom audio, captions, materials, final render and optional publishing. `app/services/material.py:download_videos()` handles stock and remote generated material; local AI bypasses it. The WebUI is `webui/Main.py`, requests are `app/models/schema.py:VideoParams`, API controllers live under `app/controllers/`, and CLI is `cli.py`. Keep upstream TTS, captions, BGM and MoviePy/FFmpeg composition. `wan22_local` and `ltx25_local` are distinct local AI video material sources implemented under `app/services/local_ai/`; the task-local scene plan and atomic generation manifest own persisted scene clips. Runtime management sits below the existing task manager.

## Current-upstream revalidation and SRS refinements

As of 21 October 2026, `upstream/main` is at
`6992380c5e82f07f3e1fc46b90927b6f1c655407` (v1.3.9), 252 commits beyond
the pinned vendor baseline. Forty-one changed paths overlap product changes,
including `task.py`, `video.py`, `voice.py`, `schema.py`, `cli.py`, and
`webui/Main.py`. That upstream history has not been merged into this product;
assess and integrate deliberately on `development` after this promotion.

1. Upstream `harry0703/MoneyPrinterTurbo` moved on 27 September 2026 from the pinned vendor baseline `ad5496f1b729d1d7e361dd972015d26c08b0e052` to `8e259e9f072c9e08464f040cd658d4eb046a57d0`. The one new upstream commit changes Redis task traversal/cross-post recovery in `app/services/state.py`, `app/services/task.py` and their tests. It is **not merged** into this product during M4; keep the vendor baseline pinned and reconcile upstream deliberately at a stabilization point.
2. Upstream already measures **written TTS audio** (with a duration ceiling) and probes custom audio in `task.py:generate_audio`; do not port Content Factory's narration measurement. Scene planning still needs to use that measured duration and maintain actual ordered scene-to-narration mapping.
3. API task manager already has `max_queued_tasks`, existing provider preflight, task state, and some remote task recovery. Local scene persistence and resumable local inference remain owned by the local-AI layer. `LocalAIRuntimeManager` now layers its in-process reentrant lock with an OS advisory file lock keyed by CUDA device under `storage/local_ai_locks/gpu-N.lock`, so independent MoneyPrinter worker processes serialize heavyweight local-AI work on the same configured GPU. This coordination contract is CPU-tested on Windows/POSIX paths, but real multi-process GPU behavior still needs hardware validation before throughput claims.
4. Existing `download_videos()` accepts `search_terms` and `audio_duration` and returns local paths. It does **not** carry SceneSpec, fingerprints, versions, or restart semantics. The local route may need its own ordered task-level orchestration and a small material-layer adapter, rather than blindly feeding prompts through the stock keyword interface.
5. Upstream still enters the shared audio stage for a full video, but FR-051 is now implemented explicitly: selecting the `no-voice` sentinel bypasses generated TTS, creates only a deterministic silent timing track for the existing composer, and uses the script timeline for captions instead of transcribing silence with Whisper. Custom uploaded audio still takes precedence. Do not treat an empty/invalid `voice_name` as No Voice; only the explicit sentinel enters this path.
6. Material records already use `script.json` and sanitized source metadata; reuse that practice. The local scene manifest is separate and must never leak model host paths or secrets. Upstream paid providers' remote task IDs do not substitute for local clip fingerprints.
7. Upstream test path is `test/` (singular). Baseline CI now runs on pushes to both `main` and `development`, and on PRs. The SRS example `test/services/test_local_ai_*.py` matches the actual test root.
8. The SRS is a requirements baseline, not an assertion that hardware or model APIs were validated. Wan/LTX inference, VRAM, visual quality and model licenses must be checked against installed revisions during their milestones. The SRS DOCX misplaced Sections 20.2–20.7 near its document map and ended with a v1.0 label; `docs/SRS.md` moves those subsections into Section 20 and fixes the closing label to v1.1.
9. M2 revalidated the current official `Wan-Video/Wan2.2` TI2V-5B code before adapting it. The inspected official source uses 24 fps, 121-frame TI2V sampling and 704×1280 / 1280×704 generation sizes. Its current requirements constrain NumPy to <2, while the MoneyPrinterTurbo lock resolves NumPy 2.x. To avoid destabilizing the product environment, Wan runs in a persistent **isolated local worker process** configured with its own Python environment; the MoneyPrinter process never imports the Wan/Torch GPU stack during normal startup or CPU CI. Reverify these assumptions before upgrading the official Wan checkout.

## M1 completed: local provider contract and fake end-to-end path

M1 is implemented on `development`. The local-AI foundation now includes a provider-neutral `SceneSpec` and generation protocol, deterministic scene fingerprints, an atomic task-local `generation_manifest.json`, versioned scene assets, restart-time media revalidation, retry reuse, a CPU-only fake provider, and ordered integration into the existing MoneyPrinter task/material/final-composer path. Local AI scenes bypass stock keyword generation and remote material download. The fake source is test-only and disabled unless `MPT_ENABLE_LOCAL_AI_FAKE_PROVIDER=1`, so it cannot accidentally appear as a production source.

The fake provider loads its runtime once for a multi-scene generation, writes temporary clips before atomic promotion, preserves completed scenes across later failures, regenerates corrupt cached scenes into a new version, and reuses valid clips without loading the runtime again. The scene planner uses measured narration duration and avoids repeating the complete script when the number of requested scenes exceeds sentence count. Generated clips are validated for decodability, positive duration and requested aspect before being recorded as active. No model paths, GPU imports or production Wan/LTX IDs are part of M1.

**M1 code head:** `ef007c85ffc64d18366861fe7eab6246d3889d78` on `development`. The final M1 CI run passed Windows smoke tests plus the Python 3.11 and 3.13 test/coverage jobs. An earlier first implementation run failed one scene-versioning assertion; that defect was fixed before the green M1 head.

## M2 completed: isolated Wan 2.2 local provider

M2 adds the stable backend source ID `wan22_local` on top of the M1 scene/manifest contract. `app/services/local_ai/wan22.py` owns operator configuration, checkpoint/shard validation, safe model fingerprinting, preflight, persistent worker reuse and provider output validation. `app/services/local_ai/wan22_worker.py` is a small standalone worker entry point intended to run with a dedicated Python environment created from the official Wan2.2 requirements. It loads the official TI2V-5B pipeline locally, never downloads weights during a task, generates 24 fps local video, normalizes to video-only H.264 MP4, and writes into M1's temporary/versioned scene publication flow.

The worker process remains persistent across compatible tasks. A model/code fingerprint is part of the runtime key so changing checkpoint/code inputs at the same paths evicts the old worker instead of silently reusing stale weights. `LocalAIRuntimeManager` holds a provider family across a scene batch to avoid Wan/LTX thrashing and supports family eviction. The later FR-031 hardening layer adds a reentrant, per-CUDA-device OS advisory file lock in addition to the in-process lock, so multiple MoneyPrinter worker processes coordinate on the same configured GPU. This cross-process contract is CPU-tested; actual multi-process CUDA behavior remains part of the deferred GPU validation pass.

Wan configuration is operator-owned through `[wan22_local]` / environment settings: repo path, checkpoint path, worker Python, CUDA device, seed and memory-related flags. These host paths are not added to public task payloads or manifests. The manifest stores safe provider/model metadata, deterministic per-scene seeds and input fingerprints. Scene failures expose provider, scene ID and a safe error code; completed scenes remain reusable. Task state now reports the active scene and total scene count while generation is running. The fake M1 provider remains test-only.

**M2 functional code head:** `e0a363bd82641c153f8485e48a09462b7c938bd5` on `development`. CPU CI exercises mocked Wan worker/runtime boundaries; no real Wan checkpoint was loaded and no GPU/VRAM/visual-quality claim has been validated.

## M3 completed: source registration and operator surface

M3 exposed `wan22_local` through WebUI, CLI and API using the same provider/preflight rules, added the readiness button and CLI/API preflight commands, documented operator setup in `docs/LOCAL_AI_VIDEO.md`, kept model/checkpoint paths out of public task requests, and left the fake provider internal. The M3 registration commit `09dbdae49cc8533c37f22560bf8c5a80bc3626a3` revealed two stale regression expectations; follow-up `7a6775bfb7e6fec73188f99b9daae6cb613c2927` aligned the Agent Skill exception and WebUI group test. CI run `36325467280` passed Windows smoke, Python 3.11, Python 3.13 and Ruff.

## Current development boundary

## Completed milestone: portable editable project archives

The owner approved a complete Save/Import Project milestone. Editor → Export
now prepares a `.mptproject.zip` snapshot; Task Manager imports it as a fresh
UUID task and opens the dedicated editor. Version-1 inventories retain existing
task-relative scene versions/order/timing, narration recordings/mixes, caption
styles/draft/applied tracks, music/SFX drafts/assets/applied arrangements,
original inputs and saved final videos. No new canonical timeline or renderer
was introduced. Combined caches and rendered previews are disposable.

Imports validate inventory hashes, bounded paths/files/media, existing layer
bindings and font availability in hidden staging before atomic publication.
Failures clean up staging and preserve existing projects. Custom narration
survives state loss/restart. Random/custom BGM is frozen locally for portable
rendering without a replacement song or provider call. Source configuration,
secrets and model weights are excluded. Creative AI scene projects only;
stock/factual expansion, undo/redo and publishing remain later work.

The previous reload/cache CI exposed a missing-manifest `AttributeError` in
optional composition-key calculation. Missing manifests now raise the existing
recoverable `ValueError`, allowing ordinary final-output validation to run; the
previously failing final-validation regression passes.

See `docs/PROJECT_ARCHIVES.md` for controls, limits, format and concurrency
boundaries. CPU round-trip tests delete the source task before import and render
using restored edited layers with generation providers blocked. No real GPU,
TTS, paid music or publishing requests are part of this milestone.

Verification: **112 editor/audio/narration/queue/artifact/i18n regressions**,
**73 archive/final-composer checks (3 skips)**, **169 core service smoke checks
(5 skips)** and **11 startup/history tests** passed. Counts overlap. Ruff,
compileall and whitespace checks passed. The previous CI failure was reproduced
from the Actions logs and its missing-manifest fallback is fixed; inspect the
new commit's CI run for the complete platform matrix.

## Editor reload consistency and audio-only render reuse

The owner observed an empty/collapsed program preview after browser reload
while an audio job was running. Render transactions temporarily removed the
exported MP4, and reload lost editor-only selection/playhead state. Shared render
backups now atomically preserve a decodable last-completed editor preview before
outputs are replaced. The program player uses that stable video while busy,
with compatible recognized-backup fallback for older interrupted transactions.
Missing first-time output retains the player height instead of collapsing.

Editor URLs retain scene, inspector, preview source and validated selected item.
Per-task/source/clip browser session storage retains the paused playhead, bounded
to the current duration; restore waits for player metadata. Job completion also
retains the chosen frame. Reload/Refresh are read-only and never submit edits.

The supplied logs showed an existing `_run_audio_layers` job rebuilding seven
saved scenes, not new AI inference. Audio preview/apply/restore now retain and
reuse valid combined visuals. Composition records bind video bytes to visual
settings, scene timing/order, source hashes and narration inputs; stale/corrupt
combinations rebuild. Legacy reuse requires inputs older than the completed
combined file plus media validation. Other render paths keep their existing
recomposition semantics. Logs now identify each audio action and success; the
UI distinguishes saving a draft, preview, applying/exporting and restoring.

CPU checks verify reload state without queue submission, stable preview during
missing/partial output, composition reuse/staleness and actual audio exports.
Chromium verified the paused frame, scene, panel, source and one timeline through
busy reload, job completion and completed reload, without page errors. No live
GPU, TTS, paid music or publishing requests were used.

Verification: **134 regression tests** passed, followed by **40 focused
workspace/audio/narration tests**, **46 queue/translation tests**, and **6 frontend
tests**. Chromium exercised busy reload, completion and completed reload at a
paused frame. Ruff, compileall and whitespace checks passed.

## Completed milestone: independent music and SFX editing

The owner approved the complete independent-audio milestone. The dedicated
editor now has a Music / SFX inspector and audio library for uploaded music and
sound effects, timeline placement, two-sided source trimming, gain/mute/fades,
duplicate/remove, overlapping lanes and saved draft/applied arrangements.
Existing saved BGM can be imported as an editable clip; legacy random/custom
music is frozen locally for consistent arrangement previews and exports.

Version-1 audio-layer sidecars and immutable task-local decoded WAV assets
extend the current task model; no replacement project format, frontend server
or audio-provider stack is introduced. Preview/apply/restore use the existing
composer and saved visuals/voice/captions/music with render backups/rollback.
Applied arrangements survive reopening, render-only/visual/caption edits and
same-task Resume. Artifact packages include safe sidecar/media references.
Limits are 50 MiB/ten minutes per import and 32 assets/32 placements per project.
Positions use absolute milliseconds. Natural narration shortening crops audio
at delivery time without changing stored placements; clips do not automatically
shift with narration. See `docs/AUDIO_EDITING.md` for the full contract.

The editor now polls only a small job-status fragment. Editable controls and
the timeline are outside timed fragments, preventing repeated stale-control
redraws while jobs complete. Workspace scene actions rerun the app, retaining
legacy fragment behavior outside the workspace. Frontend frame seeking and
singleton React-root ownership remain unchanged.

CPU acceptance covers real sample timing/trims/fades/gain/mute, MP4 preview and
export/restore, rollback, source/revision/busy checks, BGM freezing/import,
artifacts and partial Resume. Chromium checks cover upload, adding/trimming,
fade controls, timeline drag, duplicate overlapping lanes, rendered preview and
reopen with no JavaScript page errors. No live GPU/TTS/paid music/publishing
calls were made. Manual operator acceptance remains deferred.

Verification: **172 Python tests and 10302 subtests passed**, plus **5 frontend
tests** and automated Chromium acceptance. The final focused audio checks also
exercise frozen legacy music through the real shared composer. Ruff, compileall
and whitespace checks passed.

## Editor corrections: singleton timeline, frame seeking and caption styles

The owner reported accumulating timelines during Streamlit updates, a stale
preview while scrubbing/stepping, and missing caption appearance controls.
Streamlit invokes the v2 JavaScript renderer on data updates without unmounting
it. The component now reuses one React root per host and removes that root on
unmount; obsolete cleanup callbacks cannot remove a newer render. Playback
handlers read current source offsets and reconnect to replaced video elements.
Idle editing has no timer. Background-job inspector choices survive Streamlit
widget cleanup instead of reverting to Clips.

Paused ruler clicks, playhead dragging and frame buttons seek the native video
on the 30 fps delivery frame grid. Zoom reaches 30x, exposing frame subdivisions;
end seeks stop on the last decoded frame. The full exported-video preview is
the timeline reference; the selected-clip tab remains bounded by that clip.

Captions → Caption Appearance now includes font, size, foreground/background,
rounded background, outline, position/custom position and spring animation.
Styles can apply to the whole draft or only the selected cue. Highlight saved
caption text and use **Selected Text Color** on the timeline toolbar to open
its range/color controls. Color ranges use Unicode code-point offsets. Draft
styles and ranges survive preview, apply/export, reopening and render-only
rerender; they do not modify original captions or invoke speech/model services.
SRT downloads intentionally contain plain text/timing, with styles retained in
the existing version-1 caption sidecars. Timing edits preserve ranges; changing
text clears obsolete ranges. Split clears ranges; merge retains the first cue's
style. Word timing remains the saved editable cue timeline, not a new alignment.

Verification: **160 Python tests and 10302 subtests passed**, plus final focused
workspace/style checks and **4 frontend tests**, including repeated v2 data
updates and obsolete cleanup. Chromium verified one timeline across repeated
selections, refresh, queued style/color edits and idle time; paused seeking,
a decoded next frame, 30x zoom and highlighted-text color persistence. Real CPU
caption preview/export/reopen/rerender tests cover style persistence and rendered
colors. No live GPU, TTS, paid music or publishing calls were made.

## Completed milestone: dedicated video editor workspace

The owner rejected editing inside Task Manager and approved an editor-style
workspace plus reuse of open-source UI code. Task Manager's **Edit** action now
navigates to a separate full-page editor, with media library, large video
preview, interactive timeline and selected-item inspector. Back returns to the
task list; direct editor URLs can be reopened. Task Manager no longer renders
the scene/narration/caption editing panels.

The component uses MIT-licensed `@xzdarcy/react-timeline-editor@1.0.0` with React
18, shipped as a local prebuilt bundle. The selected timeline-engine package
lists ISC; notices/licenses are distributed. OpenCut and OpenReel were reviewed
as complete applications and retained as references. The current Streamlit
shell, Python renderer, saved task assets and edit/recovery contracts remain.
No new canonical timeline format or separate frontend server is introduced.

Browser playback and scrubbing drive the timeline playhead; clip/cue selection
opens the corresponding inspector. Visual drag/rebalance and caption drag/resize
use existing validated queues. All earlier inspector actions and render-only
exports remain available. Idle editing stays stable without polling; active
jobs refresh progress and results. Narration/music bars select existing settings;
arbitrary layers, audio placement, browser effects and undo/redo remain later.
See `docs/EDITOR_WORKSPACE.md` for the reviewed alternatives, scope and build/
license/verification contracts. Ordinary users do not need to install Node.

Verification: **126 Python tests and 10259 subtests passed**, plus **2 frontend
unit tests**. Real Chromium checks verified playback, seeking, caption drag
persistence, clip reorder/rerender, export controls and Task Manager navigation
with no JavaScript page errors. Checks used synthetic CPU media; no live GPU,
TTS, paid music or publishing services were invoked.


## Completed milestone: independent caption editing

Creative AI tasks now support independently editable caption drafts: text and
start/end changes, split/merge/add/remove, an ordered cue table, SRT download,
real video preview, apply/export and restore-base captions. Empty tracks can
explicitly export without captions. The editor lives below Scene Editor and
extends the existing Streamlit/task/composer architecture. It also supports
No Voice timing tracks; factual and stock-task editing remain outside scope.

Drafts and active captions are separate, source-bound snapshots. Applied
captions survive later draft edits, reopening, visual edits, render-only changes
and same-task Resume. Original script/audio/captions and generation assets remain
intact. Preview uses saved combined video and narration with caption styling;
it omits background music. Final exports retain saved music. Preview and export
make no video-generation, TTS, Whisper, publishing or new paid-music request.

The version-1 `caption_edits.json` and `caption_track.json` sidecars, UUID-owned
SRT/preview assets and optional artifact/API references preserve legacy tasks.
Cues use milliseconds, within the current audio duration, with no overlaps and
bounded cue/text/file counts. Source/revision/scene checks and output backups
protect queued edits and failed renders. Restore Original Narration removes
captions bound to its edited mix and rolls both layers back on failure. See
`docs/SCENE_EDITING.md` for the workflow, bounds, persistence and process-kill
limitation. No new project format or frontend stack is selected.

This completes independent caption editing; independently positioned music/SFX,
portable project archives and automatic word alignment remain later work.
Manual operator acceptance remains deferred; automated verification is CPU-only.

Independent-caption verification: **212 passed, 3 skipped and 10287 subtests
passed** across narration/automatic duration, editing, shared tasks, artifacts,
queue, history and translations. Final caption-focused acceptance after the
portable SRT byte-writing fix passed **12 tests**, including real preview and
export/restore MP4s, source/revision rejection, queue/status recovery, active SRT
downloads, failed-preview preservation, empty tracks, No Voice/factual bounds,
partial restart/Resume with natural narration, and coupled original-restore
rollback even with damaged mix metadata. Ruff, compileall and whitespace checks
passed. No real GPU inference, live TTS, publishing or manual acceptance is
claimed. Check GitHub CI at the published development head.


## Automatic AI clip duration

The owner clarified that flexible clip length should also be an option when
starting a video, where the numeric clip-length selector lives. **Automatic
(recommended)** is now available for Wan Local, LTX Local and LTX Hugging Face.
Fresh WebUI AI-source selections default to Automatic; selecting a number keeps
the existing manual maximum. Automatic/manual is remembered and restored with
task settings. Older saved tasks and API requests without the new field retain
manual behavior. Stock/paid-provider selectors retain their existing behavior.

Automatic uses the existing Scene Director and deterministic fallback unchanged:
measured narration duration, script segmentation and beat weighting choose the
scene count and individual target lengths. The planning ceiling is the smaller
of the public model limit and the provider's configured limit (Wan 5s, local
LTX 8s, HF LTX at most 5s). Longer narration is split into multiple clips.
The total video still follows narration; this does not promise arbitrary single
model clip lengths or verified word/sentence alignment. Provider frame rounding
and minimum request lengths remain owned by the existing adapters. No extra
LLM, TTS or alignment-model call was introduced.

Automatic exports use the saved scene target durations with cumulative frame
rounding, sequential footage and normal playback speed. They do not reapply a
hidden numeric cap or loop excess footage into a different scene. Insufficient
footage fails explicitly. Saved visual timing overrides and active natural-length
narration retiming take precedence. The original generation plan remains the
source of truth for Resume, scene regeneration and render-only rerender.
The UI fixes speed at 1x in Automatic; an API/CLI request for another speed is
rejected before provider preparation or TTS.

The additive `VideoParams.local_ai_duration_mode` field accepts `auto` or
`manual`, defaulting to `manual` for backward compatibility. `video_clip_duration`
remains a positive integer and is the manual maximum. API and batch JSON can
set `"local_ai_duration_mode": "auto"`; CLI can use
`--local-ai-duration-mode auto`. Duration mode is a generation/planning choice,
not a render-only settings override. Resume retains the saved mode and plan;
Regenerate restores the mode into the ordinary new-task controls.

CPU checks cover provider/configured bounds, backward-compatible request and CLI
serialization, the WebUI default/manual switch and legacy task restore, real
variable-scene MP4 export, process-state restart/partial Resume and render-only
reuse without new speech or model work. Manual operator and real-GPU acceptance
remain deferred.

Automatic-duration verification: **378 passed, 3 skipped and 10372 subtests
passed** across planning/providers, shared rendering/audio, scene/narration
editing, Resume, API schema/CLI and WebUI regressions. After the source-specific
selector adjustment, fresh UI/history/default/translation checks passed with
**37 passed and 10225 subtests passed**. Ruff, compileall and whitespace checks
passed. The prior natural-duration milestone also has green full CI on
`a9e839fbdd5613f0c811e24eb96a87f62a18f68a`. Check current GitHub CI for the new
published head; no live GPU/speech acceptance is claimed.


### Completed creative narration/caption milestone (fixed timeline)

The owner explicitly requested finishing the milestone end to end rather than
shipping another partial slice. Scene Editor now supports replacement text,
explicit scene TTS through the existing saved-voice dispatch, transcript-labelled
recording uploads, optional pitch-preserving 0.5x–2x tempo fitting, previews,
reviewed-range caption rebuilding, captioned apply/export, original restore,
artifact downloads and persistence across visual edits/rerender/Resume.
Total video/audio duration stays fixed. No video inference is needed.

New replacement metadata optionally records text, origin and tempo ratio.
Captioned mixes use sidecar schema version 2 with separate hashed audio, SRT
and edited script. Version 1 caption-free mixes remain compatible. Caption
rebuilding requires every original range reviewed and every replacement given
a transcript, plus explicit operator confirmation. Captions are scene-range
cues using supplied text, not automatic transcription/word alignment. Original
root audio/script/captions and scene assets remain unchanged. Edited script/SRT
are exposed separately through output-package/API fields and Artifact downloads.

TTS writes into an automatically cleaned temporary task directory. Queue and
publication recheck source/range revisions; failed TTS/fitting/caption work or
render restores prior drafts/outputs. Every future local-AI render validates
active audio/script/caption hashes. Restore recovers original narration and
caption settings. The existing documented multi-file process-kill limitation
remains. See `docs/SCENE_EDITING.md` for the complete workflow/data contract.

Verification: final focused acceptance passed **77 tests and 10246 subtests**,
including a real captioned MP4, tempo/pitch checks, real original restore,
Artifact downloads, failure rollback and TTS/transcript UI/queue actions.
The full CPU sweep passed **1575 tests**, with **19 skipped**. Its only failures
were 120 translation subtests after final download labels were added during
that run (the test module had cached the older fallback-key set). A fresh
translation run against the finished files passed **16 tests and 10225
subtests**; no other test failures occurred. Do not describe the initial full
sweep as entirely green; check GitHub CI on the published frozen commit.
Ruff, compilation and whitespace checks passed. No live TTS or GPU acceptance
is claimed from the offline test response.

Creative AI tasks are the supported editing scope. Factual audio edits, stock
scene editing, variable-duration retiming, independent caption timelines and
automatic speech alignment are separate work. Scene TTS uses the configured
speech provider only on an explicit Generate action; automated tests use an
offline response. Manual/GPU acceptance remains deferred as the owner requested.

The eighth editor extension applies saved replacement narration to creative
AI-video exports. Apply explicitly requires caption omission because matching
audio duration does not establish matching word timings. Restore rerenders
original narration with saved caption settings. The original audio, captions,
script, scene plan, visual versions and timing remain untouched. Factual-task
apply is blocked; edited-content review and caption rebuilding are future work.

`narration_mix.json` binds the active 16 kHz mono PCM track to source hashes
and range/draft inputs. The shared local-AI final composer validates and uses
it on later renders, scene edits and Resume. Master-audio state stays original;
optional artifact/API fields expose `edited_audio`, `narration_mix` and
`captions_omitted` separately. Restore before changing drafts/boundaries. Apply
and restore use the existing serialized queue, stale scene/range checks and
render backups; failed processing restores prior mix metadata and outputs.
The active sidecar is atomic, but a process kill between sidecar publication
and rendering is not a multi-file atomic transaction; saved assets permit
rerender/restore recovery. See `docs/SCENE_EDITING.md` for the exact contract.
No GPU/video generation, TTS, LLM, caption generation or publishing is invoked.

Verification: **72 narration/UI/translation/artifact/queue tests**, all **9
scene timing/visual-edit/Resume tests**, and **67 task tests** passed (3 optional
integrations skipped). A real CPU-composed MP4 contains the replacement tone
and unchanged later audio; original files remain unchanged. Tests cover restore,
failed render/publication rollback, stale source rejection, unsafe references,
queue snapshots, UI apply/restore, and active-mix persistence through restart/
Resume. Ruff, compilation and whitespace checks passed. No GPU inference or
manual acceptance was requested; check current GitHub CI after publication.

The operator has now confirmed successful voice sampling and complete Pexels
and Pixabay videos after upgrading Edge TTS to 7.3.1. This is operator-environment
acceptance of the shared stock/audio paths; it is not local-GPU acceptance.
The operator requests continued implementation and defers further manual
walkthrough/acceptance testing until the end. Continue automated CPU checks.

### Edge TTS audio regression investigation

Verification: **196 affected voice, WebUI preview, task and queue tests passed**,
with 6 optional integration tests skipped. The added offline integration uses
real dispatch, MP3 decoding, SubMaker and WebUI sample/full preview cleanup for
both stock sources; only the external TTS transport is replaced. Idle timeout,
cancellation/closure, immediate upstream errors, legacy compatibility and safe
failure logs are covered. Frozen dependency sync, lock validation, Ruff,
compilation and whitespace checks passed. This is not live speech acceptance.

The operator's Pexels task and both short/full voice previews failed with
three exact 30-second Edge TTS timeouts. These share `voice.azure_tts_v1` and
fail before stock-material retrieval. Recent scene/narration editor work did
not change that provider. The application was pinned to `edge-tts==7.2.7`.
Upstream 7.3.0 adds the updated service token protocol and 7.3.1 fixes
locale-dependent server-date parsing. Both install manifests and the focused
`uv.lock` entry now pin 7.3.1; unrelated dependencies are unchanged.

The official synchronous wrapper can hide async-worker exceptions while
waiting on a queue. Our adapter now consumes the async stream directly,
propagates errors and cancels/closes stalled requests. `edge_tts_timeout`
(default 30 seconds) limits waiting for the next event, including the first,
rather than cutting off a healthy long response at 30 seconds total. Sync-only
legacy adapters retain their bounded fallback. Failure logs include version,
error class and safe status/TLS guidance without raw request URLs/tokens.

A live short Microsoft request from this development environment failed with
`ClientConnectorCertificateError`. This is not proof of the operator's network
failure or successful live synthesis. Keep certificate verification enabled;
verify the real voice sample/full narration in the operator's Codespace after
`git pull --ff-only origin development` and `uv sync --frozen`, then restart
`sh webui.sh`. That launcher reuses the existing `.venv` and does not update
installed dependencies merely because code was pulled.


The seventh editor extension adds saved replacement narration drafts for
operator-reviewed ranges. WAV/MP3/M4A uploads (20 MiB maximum) must match the
decoded range duration within 2 ms and are normalized to task-local PCM WAV.
Original and draft previews remain separately available; remove restores
original-only playback. Drafts are explicitly audition-only: master narration,
script, captions, visual generation and final exports remain unchanged.

An optional per-range `replacement` reference/hash in `narration_ranges.json`
binds each draft to the existing sources/ranges. Queued requests are snapshotted;
source/revision checks and atomic publication preserve prior assets on failure.
Only active draft directories remain after successful cleanup. Reopening,
preview repair, visual edits and Resume retain drafts. Source rebinding clears
them. Remove adjacent drafts before moving a narration boundary. No TTS,
transcription, video inference, final composition or publishing is introduced.
Applying drafts to final narration/captions and downstream retiming remain
future work. See `docs/SCENE_EDITING.md` for the complete contract.

Verification: **69 affected narration/UI/translation/queue/artifact tests**
passed, followed by all **9 scene timing/visual-edit/Resume tests** with saved
drafts. The media checks cover original-vs-draft content, stereo normalization,
invalid uploads/paths, fixed durations, stale publication, rollback, source
rebinding, cleanup and restore-original. Streamlit tests cover draft upload,
preview and remove controls. Ruff, compilation and whitespace checks passed.
Check the published development head for full Python/Windows CI. No real GPU,
speech-alignment or publishing acceptance is claimed.

The preceding boundary-review milestone's full Python/Windows CI passed on
`9415c1b0ba1d842ff0d1529bdca14de452f83e39` (run `40125307648`).

The sixth editor extension adds manual narration boundary adjustment and
operator review. A range's end moves the next narration range's start in
original narration order; total audio coverage and endpoints remain fixed.
Changes are sample-rounded and cannot empty either adjacent range. They rebuild
previews from existing audio, set `basis=operator_adjusted`, retain initial
estimation weights and keep `speech_aligned=false`. Explicit user review is
saved in `operator_reviewed_scene_ids`; moving a boundary clears both affected
reviews. Source changes re-estimate and clear reviews. Visual edits and Resume
preserve valid manual ranges/reviews.

The existing serialized narration queue preserves task status and checks saved
sidecar revisions at submission, execution and publication. Failures preserve
the prior map/previews. Source audio, captions, script, generation versions,
visual timing and final exports remain unchanged. No TTS, automatic alignment,
video generation or publishing is added. Narration replacement and downstream
retiming remain deferred. See `docs/SCENE_EDITING.md` for the contract.

Verification: **73 affected CPU tests** passed, with **27 final range/UI/
translation checks** and both manual-range visual-edit/Resume integration
checks passing. Ruff, compilation and whitespace checks passed. Check the
published development head for full Python/Windows CI. Operator review is
not automatic speech-alignment or real-model acceptance.

The fifth editor extension saves estimated narration ranges and offline audio
previews. **Prepare narration previews** in Scene Editor creates a separate
`narration_ranges.json`, binding stable scene IDs and narration text to exact
source audio/script hashes. Ascending scene-ID order and the original target
weights estimate ranges across the decoded audio duration. Initial weights are
saved for traceability. The UI explicitly says estimated, not speech-aligned.
**Preview narration** serves a validated cut WAV without new speech, video,
caption generation or final composition. No Voice timing audio is excluded;
custom recorded audio takes precedence. Inputs stay task-local.

Visual order/timing/prompt/version changes and Resume preserve the sidecar.
Source changes require explicit preparation before previews can load. Corrupt
previews recover from the existing saved ranges. The background queue preserves
the prior completed/failed task state; extraction or publication failure keeps
the old map and previews. Temporary decoded audio avoids MP3 padding errors,
and only the active preview set is retained. The optional output-package/API
`narration_ranges` reference makes the sidecar discoverable. See
`docs/SCENE_EDITING.md` for bounds and validation. Actual narration edits,
verified speech alignment and audio/caption retiming remain deferred.

Verification: **115 affected CPU tests** passed, covering API/artifact
serialization, task management, timing, UI and translations. Final acceptance
passed **10 tests** for preview content, source binding, visual-edit persistence
and full Resume. All 8 narration tests passed again after adding interrupted
preview cleanup. Ruff, compilation and whitespace checks passed. Full Python
3.11/3.13 and Windows results must be checked at the published development head;
no speech-alignment, real GPU or publishing acceptance is claimed.

The fourth editor extension adds visual screen-duration controls. Changing one
scene's duration balances the following scene in playback order; narration,
caption timestamps and the total planned visual duration remain fixed. Additive
`playback_durations` metadata is separate from generation targets/fingerprints
and version history. Existing tasks keep their original composition behavior
until edited. Reset removes the override. Timing edits require normal speed,
positive durations and enough saved footage, use cumulative frame rounding,
and fail explicitly rather than stretching or looping visuals. The transaction
preserves previous manifest and final/combined outputs on failure. Queued work
rechecks an immutable snapshot of order, timings and active clips.

Reopening/Resume, reordering and other scene edits retain timing. New uploads
and trims retain enough footage for extended playback slots. Generation recipes
remain unchanged; if later regeneration cannot cover a slot, restore a longer
version or reset timing before rerendering. See `docs/SCENE_EDITING.md` for the
bounded contract. Whole narrated-scene moves, narration editing and changes to
total video length remain deferred. No new inference or publishing request is
made by a timing edit.

Verification: **192 existing affected regression tests** passed. A fresh final
run passed all **9 timing tests** plus 5 composer checks; 18 UI/translation
checks and the final no-op UI check also passed. The initial broad run exposed
a fake-provider fixture issue in the new Resume test; it was corrected and the
full timing acceptance rerun passed. Ruff, compilation and whitespace checks
passed. Check full Python 3.11/3.13 and Windows CI at the published head; no real
GPU or external publishing acceptance is claimed.

The third editor extension adds fixed-duration clip start controls. A new
upload can start later in its source; a saved active clip can be trimmed when
it contains enough remaining footage. Each successful cut is a restorable,
hash-validated version, with `scene_trim` provenance for saved-clip edits.
The existing replacement transaction preserves narration/captions, playback
order and unrelated versions and rolls back manifest and final/combined
outputs on failure. Submission and the worker reject stale active versions.
No new model or publishing request is made. Old imports contain only their
normalized footage; excess raw footage was never retained. Upload the original
again to choose a later section. Changes to total duration and audio retiming remain deferred; visual cut
timing controls are described above. See `docs/SCENE_EDITING.md` for the additive metadata contract.

Verification for this extension: **124 affected editing/recovery/task tests**
passed. A fresh final acceptance run passed **24 tests and 10231 subtests**,
including the new trim, upload-start, UI and translation checks after the
translation additions. Ruff, compilation and whitespace checks passed. The
full Python/Windows CI result must be checked at the published development
head. No GPU inference or live publishing acceptance is claimed.

The second editor extension adds visual-only playback reordering through
**Move earlier / Move later** in the existing Scene Editor. The additive
manifest `playback_order` lists each stable scene ID exactly once; older
manifests keep ascending ID order without migration. Scene-plan narration
segments, fingerprints, active clips and version histories stay attached to
their original IDs. The editor displays playback position separately.
Narration and caption timestamps stay fixed; moving visuals can change which
words they accompany. Clip timing continues to use the existing composer
settings, with no audio retiming; fixed-duration source trims are described above.

The background worker rejects busy/publishing tasks and stale order requests.
Reordering reuses saved clips/audio/captions/generated BGM without inference or
publishing. Invalid media or failed rendering restores the previous manifest
and all final/combined outputs. Resume, regeneration, replacement, restore,
rerender, provenance and artifact-index scene materials use the saved order.
Invalid saved orders fail before inference rather than silently resetting.
See `docs/SCENE_EDITING.md` for the contract and acceptance checks.

Playback-order verification on Python 3.11 passed **136 tests and 10235
subtests**, covering the new export/Resume/queue/UI cases plus existing local-AI,
replacement, cleanup, task/artifact and history regressions. Ruff, compileall
and diff whitespace checks passed. Check CI at the current development head
for the full Python 3.11/3.13 suites and actual Windows runner result; this
milestone uses CPU fake media and makes no new GPU or publishing claim.

The first post-orientation editor extension adds validated single-scene MP4
replacement in the existing Streamlit Scene Editor. See `docs/SCENE_EDITING.md`
for the additive manifest metadata, asset ownership and change-impact contract.
Uploads (maximum 100 MiB) are trimmed to the existing scene duration, normalized
to video-only H.264 and published as task-local versions. Narration/captions and
other scene versions are reused; existing generated BGM is reused without a paid
request. Invalid uploads or render failures preserve the prior active manifest
and final/combined outputs. Successful edits refresh manual-upload provenance.
Generated and imported versions can both be restored. Explicit regeneration
switches provenance back to the selected AI provider.

Resume revalidates imported clips with their saved content hash independently of
the provider/model fingerprint. Missing, damaged or timing-incompatible imports
block with `replace_imported_clip_or_restore_version` guidance rather than
silently generating substitute footage. Existing generated-scene fingerprint
invalidation remains unchanged. Queued edit workers now recognize their own
reservation while rejecting unrelated busy/cross-posting tasks. Scene version
labels bind their own scene's metadata rather than the last loop iteration.
No editor framework, project interchange format, narration retiming or new
publishing behavior is introduced by this milestone.

CPU verification: the Python 3.11 full run passed with **1520 passed, 19
skipped, 10748 subtests passed** and **78%** branch-measured coverage. Final
caption/history and active-preview guards also passed focused checks after that
run began. Ruff, compileall and diff whitespace checks passed. Check GitHub CI
at the current development head for Python 3.13 and actual Windows results;
these CPU fixtures do not validate Wan/LTX hardware or operator publishing.

Phase 5 single-scene regeneration was CI verified on
`ce5f299564cf3c7b4945f93e0c83bfe576191406`. Subsequent development added
version restore, render-only rerender, cooperative cancellation, safe cleanup,
provenance and metadata redaction. The CPU integration/hardening pass then
stabilized those flows through `b875a5f83986b643f267393e8d241e23530cf591`.

Post-hardening CPU work completed FR-051 No Voice and FR-064 Output Package.
`df2defccb65406c46b518e6606b84eceff5060fd` is a green CI head covering the
No-Voice timing fixture plus the output-package/composer/OOM contract tests.
FR-031 was then strengthened by
`13d09945da416c72eb917baa65c1373e1112c644`: local GPU work now uses a
reentrant per-CUDA-device OS advisory lock in addition to the in-process lock,
so separate application worker processes coordinate through
`storage/local_ai_locks/gpu-N.lock`. FR-038 timing telemetry is implemented on
`aca48814e89880978b9d153e182adbca12147d08`: runtime-load/reuse time and
per-scene generation/validation time are persisted in the generation manifest
and logs, with an optional sanitized provider telemetry hook for later GPU
memory metrics.

The later CPU integrity/observability pass is green through
`9845dfb1ffaaff2e1e178c4e0059c42e80a955a6`. Local-AI final MP4s are now
decoder-probed before task completion for non-empty media, expected dimensions,
measured narration duration tolerance and an audio stream. Validation uses the
actual written narration duration rather than the rounded planning duration.
Invalid final files are rejected before completion and are classified in task
state as recoverable `video` failures with `rerender_final_video` guidance
and the selected local provider. Local-AI runtime/scene logs also include safe
task/provider/scene/stage/timing context. Regression coverage locks visual-only
scene regeneration to reuse existing narration/captions and preserves the
existing narration/BGM gain controls in the shared final composer.

Real Kaggle GPU validation has now proved LTX-2.5 distilled can generate valid
MP4 output on a Tesla T4 with disk offload, but that configuration is too slow
for practical scene production (a roughly two-second test took more than
15 minutes). A temporary Kaggle FastAPI + Cloudflare path also proved the remote
request/download shape end to end. These measurements apply only to that tested
T4/offload setup.

A capability-driven local-AI UX layer now keeps user choices inside supported
model/backend domains. Public local-AI sources declare model/backend identity,
allowed modes, aspect ratios, derived generation dimensions, clip-duration
choices, seed bounds and prompt-guidance limits. The WebUI uses that contract to
show only valid choices, and task preflight validates the same contract so API
or CLI callers cannot bypass it. Users choose an aspect ratio rather than raw
width/height; model-specific generation dimensions are derived automatically.

The `ltx25_hf` deployment path is now integration-validated against the
operator-owned Hugging Face ZeroGPU Space using the optimized LTX-2.5 distilled
Gradio implementation. On 30 September 2026 MoneyPrinter preflight reported the
named `generate_scene` endpoint ready, then an authenticated provider smoke run
completed a requested 2.0-second landscape scene and returned a 768x512 MP4
through remote generation, download, FFmpeg normalization and media validation.
That smoke run proved the real remote execution path but exposed an early aspect
mapping defect: 768x512 is 3:2 rather than 16:9, and the old validator checked
orientation only. The HF adapter now uses the official LTX-2.5 ZeroGPU demo's higher-resolution
/64-grid generation profile: 1472x832 for landscape and 832x1472 for portrait.
These are near-16:9 / near-9:16 model working canvases; the shared MoneyPrinter
composer produces the exact 1920x1080 / 1080x1920 delivery canvas. The adapter
fingerprint is bumped so older lower-resolution cached clips are not silently
reused, and ratio-aware media validation rejects materially wrong outputs. The smoke run does **not** establish standardized latency, visual-quality
or quota-efficiency measurements because it did not capture benchmark timing.
Phase 6 tooling now accepts `ltx25_hf:fast`
as an explicit opt-in target in addition to the local Wan/LTX targets. Remote
benchmarks never sample the caller machine's `nvidia-smi`, and the HF target is
not added to defaults so a benchmark cannot spend ZeroGPU quota accidentally.

For the first full WebUI garden test on 1 October, a 90-second optional Scene
Director LLM timeout correctly fell back to a deterministic seven-scene plan;
the remote Space generated and persisted scenes 1–3, then returned a Gradio
error event for scene 4. The Space's shared container logs did not identify
that request's cause. The Gradio client now classifies known error events into
safe quota, memory, timeout and unavailability reason codes and logs only the
reason and payload shape; unknown or empty events stay `generation_failed`.
The WebUI Task Manager's Regenerate control still loads settings for a new
task ID; it is not a same-task resume action. Do not claim the scene-4 failure
was a quota event without a subsequent specific diagnostic.
The HF provider settings are read from the `[ltx25_hf]` section of the local,
Git-ignored `config.toml`. A preflight failure exposed that this section was
documented but not registered in `app/config/config.py`; the config loader and
save path are now wired, with regression coverage. Authentication continues to
read only the `token_env` environment variable (normally `HF_TOKEN`), supplied
by an operator secret; do not add a token value to `config.toml`.

The 30 September 2026 CI checkpoint `79aa148107c92e6f09d8f62590af98475f11d93d`
passed Windows smoke and both Python 3.11/3.13 jobs after the capability and
high-resolution HF changes. An offline integration test now sends a scripted
20-second task with simulated narration through the actual `ltx25_hf` adapter,
replacing only the external Space with a CPU synthetic-video backend. It verifies
five ordered scenes, subtitles/BGM, task artifacts and a validated 1080×1920
final MP4. MP3 padding
made the measured audio slightly longer than 20 seconds, so the five-scene
plan is expected. This proves the application path without using HF quota; it
does not prove that the current Space can successfully generate at the new
832×1472 / 1472×832 working resolution. Before a 20–30-second real task,
perform one deliberate two-second high-resolution scene smoke with the current
Space revision and operator token, then assess its runtime/quota and output.
Do not repeatedly retry or start a multi-scene task if that smoke fails.

On 30 September the operator subsequently generated valid 832×1472 portrait
clips through that Space: 2 seconds in 23.35 seconds and 3 seconds in 30.92
seconds (single-run benchmarks, not quality or quota measurements). The first
real WebUI task spent 12 minutes on the configured OpenAI-compatible Scene
Director LLM and then failed its first Space submission at the 60-second HTTP
request timeout; the 3-second benchmark later succeeded, so that Space failure
is not yet reproducible. A second WebUI task waited 30 minutes for the LLM
SDK's default timeout and two retries, then honored the user's cancellation.
For this optional Scene Director call the OpenAI-compatible adapter initially
used a 90-second timeout with no SDK retry and persisted the existing
deterministic fallback plan if it failed. Investigate another Space submission
failure only if it recurs.

After NVIDIA Nemotron 3 Super returned a valid seven-scene plan in 82.1 seconds
with reasoning off but the provider-default request timed out at 90 seconds,
the Scene Director request timeout was raised to 180 seconds without changing
the configured model's reasoning defaults. On NVIDIA's hosted
`integrate.api.nvidia.com` endpoint, only the Scene Director opts into streamed
chat completions. Final-answer tokens are assembled into the usual JSON; any
reasoning deltas count as activity but are never logged or persisted. An
inactivity gap of 180 seconds (including the initial queue wait) or a total
stream duration of 15 minutes triggers the existing deterministic fallback.
Other OpenAI-compatible hosts retain the previous non-streaming request shape
with the new 180-second client timeout. Stream activity means only that tokens
arrived; it cannot prove that a silent/queued remote model is making progress.
Resume keeps the saved plan and does not call the Scene Director again.

On 4 October 2026 UTC, the operator completed the first real seven-scene
`ltx25_hf` WebUI garden task (`06853305-0932-4149-a3e2-0598eeab4a83`) across
quota-limited resumes. The initial run saved scenes 1–3; the next resume reused
them and generated scenes 4–6; the final resume reused scenes 1–6, generated
scene 7, and composed a validated 20.270-second, 1080×1920 MP4 with narration
and subtitles. The operator shared the finished video for visual review. The
butterfly and sunlit water droplets are present but small in the wide portrait
frame. This validates the remote HF LTX Fast path and same-task recovery on the
operator's Space; it does not validate local Wan/LTX checkpoints or establish
comparative quality, throughput, VRAM or quota requirements. This resumed task
used its saved deterministic visual plan; the separately tested NVIDIA Nemotron
seven-scene response was not substituted into it.

The successful resume initially left the main WebUI result panel pointed at the
earlier task selection, so the final file existed but was not displayed there.
The Task Manager Resume action now selects the resumed ID for the existing
generation-result player after queueing succeeds; completed history tasks also
offer a download alongside their headless browser preview. CPU Streamlit tests
cover both paths without remote inference. Task generation/recovery contracts
and Regenerate semantics are unchanged.

## Phase 7 first slice: optional factual mode

This CPU-only first slice is implemented on `development` in commit
`889fdd5fcdd7bf1b22925b6c7e1a48232082bbcd` (following the resumed-video
WebUI fix `093e9ec`). The reported local verification for the slice was
Python 3.11 full-suite **1474 passed, 19 skipped, 10744 subtests passed** plus
Ruff. Check GitHub Actions for the current commit; do not treat that prior
local result as a claim about any later changes. The operator chose to defer
the real-model acceptance test and continue CPU-safe development. Automatic
research ingestion remains unimplemented and is not assumed authorized.

Phase 6 local Wan/LTX hardware benchmarking remains deferred because no local
GPU is available. The operator's seven-scene HF ZeroGPU result validates the
remote LTX Fast task and resume path, but does not establish local GPU defaults.
This CPU-safe feature slice added an opt-in `content_mode=factual` with 1–6
operator-supplied HTTPS source excerpts. Factual scripting uses those excerpts;
the configured LLM then reviews the supplied/generated script before narration
or video materials. Unsupported/uncertain claims block the task at
`factual_review` rather than spending video quota. A task-local
`factual_review.json` records the decision and citations; the output package
points to it. Creative mode retains its old path. WebUI, CLI, API and batch
parameters share the same `VideoParams` contract. Task generation does not fetch or
authenticate source pages; automated evidence alignment is not independent
fact-checking. See `docs/FACTUAL_MODE.md`. Content Factory research remains
reference only. Automatic discovery/retrieval is a separate future slice.

The following CPU integration check runs an approved factual script through
the fake local-AI provider, narration, captions, BGM and final MP4 composition.
It verifies the persisted review, script, scene plan and generation manifest
without stock-material downloads. Same-task Resume for a factual task now
requires its saved approved review to match the persisted script hash and exact
source excerpts. Missing or changed approval data blocks Resume before scene
generation; creative task recovery is unchanged. This checks task-local
consistency, not the authenticity or truth of user-supplied evidence.

A manual one-command GPU acceptance pack is also implemented through
`scripts/local_ai_gpu_validate.py` and
`app/services/local_ai/gpu_validation.py`. It uses an offline supplied script,
deterministic no-voice timing audio and the real local-provider/composer paths.
For each target it checks provider preflight and safe worker Python/Torch/CUDA/
NumPy versions, real multi-scene generation, one runtime load/reuse call for the
initial scene batch, final validated MP4 output, one-scene versioned
regeneration, render-only rerender with an unchanged generation manifest, GPU
telemetry and the portable output package. Wan and LTX Fast are required by
default. LTX Quality may be reported as `skipped` only when its preflight is
unavailable; once preflight succeeds, a later failure is a validation failure.
The pack has CPU-safe orchestration tests but has **not** been run against real
Wan/LTX weights yet.

Do not invent model-quality, performance or recommended-GPU conclusions before
those real measurements exist. The factual first slice remains optional;
automatic discovery and a larger editor are not required for creative videos.

The factual review is now visible through the existing WebUI Task Manager
**Artifacts** action, even if an unsupported script was blocked before a video
or local-AI output package existed. The read-only summary shows the decision,
reason, claim-to-source IDs and citation titles/URLs without reprinting source
excerpts. The original task-local review remains available as JSON. Real LLM
acceptance with one supported and one unsupported script is deliberately
deferred at the operator's request; keep it on the later verification list,
along with real local-GPU validation. Do not claim the CPU fixtures measure
real-world factual accuracy.

The next optional factual-mode slice adds an explicit WebUI **Import source
excerpt** action. It fetches one public HTTPS HTML page into the existing
editable source field, with DNS/public-address checks, TLS hostname validation
against a pinned address, no redirects, bounded bytes and a short read deadline.
The operator accepts or edits the excerpt before task submission. CLI/API
inputs and the task pipeline still require ordinary excerpts and never fetch
sources during generation or same-task Resume. No Content Factory research
module was ported. Automatic discovery, source authentication and a real-LLM
acceptance run remain deferred.
The import helper has CPU tests for rejected private/mixed DNS answers,
redirects, oversized/non-HTML pages, timeouts, pinned TLS hostname and the
WebUI click-to-edit flow. A live public-page import in the operator environment
has not yet been exercised; add it to later acceptance without spending GPU
quota.

The WebUI now also offers **Review script only** in factual mode. It queues
the existing `stop_at="script"` task stage, saves an approved `script.json`
alongside `factual_review.json`, and shows the reviewed script in the current
result and Task Manager Artifacts. It does not preflight a video provider,
generate narration, or use GPU quota. Regenerate loads the review-only task's
settings for a new full video task; the new task reviews the script again.
Same-task local-AI Resume and the creative workflow are unchanged. Real LLM
acceptance remains deferred.

The factual review gate now requires an approved model response to account for
every ordered narration sentence with its exact text and a cited source ID.
This closes the gap where an incomplete claim list could approve an unreviewed
sentence. It is a structural coverage check, not independent verification of
the cited source or model judgment. HTTP task detail/list responses now retain
the task-relative `factual_review.json` path in the artifact package; a real
ASGI response test covers it. The operator deferred manual real-LLM and live
public-page testing until the development phase is complete. CPU regression
tests continue; do not claim real-model acceptance from them.

New factual approvals also require a short, verbatim passage from each cited
operator-supplied excerpt for each reviewed narration unit. The gate rejects
missing or invented passages before any audio/video work, and stores accepted
passages only in the task-local review JSON; WebUI summaries still omit excerpt
text. Earlier saved approvals remain readable and resumable. A matching passage
does not prove that a claim is supported or that its source is authentic. Real
LLM approval/blocking behavior and imported-page acceptance remain on the
deferred manual verification list.

## CPU integration and hardening pass

Starting from `269d5c0202492608e2a1309c94afcf1650bea3fc`, the locked
Python 3.11 and 3.13 environments were installed with `uv sync --frozen`.
The CPU fake provider completed the real task pipeline from supplied script
through offline narration, scene planning, three versioned scenes, subtitles,
stock BGM mixing, final MP4 and persisted state/artifacts. The stock/remote
material downloader was excluded. CLI source/mode/seed/style and stop-at
checks, FastAPI preflight/submission/state/cancellation/error routes, Streamlit
AppTest source controls and live HTTP health were exercised. Existing tests
cover scene edit/restore, corrupt cache reuse, render-only rerender, cancellation
boundaries, cleanup dry-run/apply, and provider metadata redaction. New tests
also verify generated BGM reuse without paid requests or new narration/AI,
failed final-rerender rollback and a full fake-provider task.

The pass found that `MemoryState.update_task` replaced the whole record at
every progress step, silently dropping cancellation requests made during a
stage and discarding local-AI provenance from later task state. It now merges
fields atomically like `RedisState`; failure return snapshots include retained
fields. A missing `SceneSpec` import in a security test was also fixed.
No model weights, CUDA setup or actual Wan/LTX inference were run. Browser
automation could not reach this container's localhost; Streamlit AppTest and
same-process HTTP health provided the practical UI/startup checks.
The final Python 3.11 full suite passed with **1407 passed, 19 skipped and
10624 subtests passed**; overall coverage with branch measurement was
**77%**, above the configured
70% CI floor. The sequential Python 3.13 full suite also passed with
**1407 passed, 19 skipped and 10624 subtests passed**, and **77%** coverage.
Linux execution of the Windows smoke subset passed with
**187 passed, 5 skipped and 70 subtests passed**. Check GitHub Actions at the
latest `development` commit for the actual Windows runner result.

After that pass, true No-Voice local-AI generation was completed using the
existing explicit `no-voice` sentinel: generated TTS is skipped, a task-local
silent timing track drives the existing composer, custom audio keeps precedence,
and No-Voice captions use the deterministic script timeline rather than sending
silence to Whisper. FR-064 output packaging now exposes discoverable,
task-relative references for final/combined MP4s, script, captions, audio,
`scene_plan.json`, `generation_manifest.json`, and active generated scene
materials through existing task/history/API surfaces.


## Completed milestone: variable-duration creative narration

Creative local-AI tasks now support natural-length uploaded or explicitly
synthesized narration. In the Scene Editor, enable **Keep Natural Narration
Duration**, save a recording, then use **Preview Revised Timeline**. The preview
shows original and revised narration ranges, the revised total duration, and
required versus available footage for every visual scene. Applying requires a
current preview, sufficient footage and confirmed transcripts. Fixed-duration
fitting remains available as a separate choice; natural duration and fitting
cannot be combined.

Later narration and reviewed-range captions shift automatically. Visual cuts
are mapped monotonically through the changed narration clock and quantized to
output frames, preserving the saved visual playback order. The starting visual
timeline uses saved playback durations, or the original planned scene durations
when no overrides exist; it does not infer a new timeline from clip lengths.
Any original visual tail beyond narration shifts by the total audio delta.
Narration remains sample-accurate at 16 kHz. Coverage permits rounded container
durations only when the final output frame timestamp remains inside the clip.
No visual looping, stretching, automatic model requests or GPU inference are
performed by retiming. Normal visual playback speed is required, and edited
audio is limited to one hour.

When footage is too short, supply a longer clip with the existing scene upload
or version restore controls, then refresh the preview. Uploads retain enough
footage for the pending revised slot instead of trimming to the original slot.
Explicit Regenerate still uses the original provider recipe and can therefore
remain too short. Narration uploads retain their existing 20 MiB limit and
video uploads their existing 100 MiB limit.

Original narration, root script/captions, source duration and generation recipe
remain unchanged. Optional natural recording metadata lives in the compatible
version-1 narration-ranges sidecar; active version-3 mixes bind the revised
audio timeline, edited audio, script and optional captions. The artifact package
exposes edited_audio_duration separately from original audio_duration. Legacy
version-1/2 mixes remain supported. Active natural mixes are honored by later
renders, visual edits and same-task Resume; Restore Original Narration returns
to the original timing and captions.

Preview requests run through the existing task queue and persist in
narration_timeline_preview.json. Revision, source, playback settings and scene
snapshot checks reject stale previews; Apply also recomputes coverage and hashes
the saved footage before accepting the preview signature. In-process render
failures roll back published output. The existing limitation remains: sidecar
publication and multiple render files are not one filesystem-wide atomic
transaction across process termination.

CPU acceptance covers longer/shorter recordings, shifted captions and audio,
footage-gap blocking, longer clip import, real MP4 apply/restore, reordered
visuals, stale footage, queued preview, failed-render rollback, Scene Editor
controls and restart/Resume. Provider calls are mocked or use the test-only CPU
provider. Real GPU generation and manual operator acceptance remain deferred.
This completes variable-duration creative narration; factual narration edits,
independent timeline layers, automatic word alignment and portable project
archives remain future work.

Variable-duration milestone verification: the focused compositor, narration,
scene timing/import/reorder, task/artifact, queue and i18n regression run passed
with **244 passed, 3 skipped and 10333 subtests passed**. Two additional focused
checks passed for the natural-duration Scene Editor and a real export extending
the original 3-second video to 4 seconds (including tampered-preview rejection).
Ruff, compileall and whitespace checks passed. These are CPU checks, with no
live provider or GPU acceptance claim.

## Verification and working protocol

Baseline verification before M1 used Python 3.11 after `uv sync --frozen --python 3.11`: `uv run --no-sync python -X utf8 -m pytest -q test` returned **1314 passed, 19 skipped, 10622 subtests passed**; Ruff and compileall passed.

M1 is verified by GitHub Actions on commit `ef007c85ffc64d18366861fe7eab6246d3889d78`: Windows smoke tests passed, Python 3.11 tests/coverage passed, Python 3.13 tests/coverage passed, and Ruff passed in the Python 3.11 job.

M2's production-provider implementation and subsequent hardening commits are CPU-tested only. Commit `258323657245be1b680a11f49d406fc40aefd40f` passed Windows smoke, Python 3.11 and Python 3.13 jobs with **1340 passed, 16 skipped, 10622 subtests passed** and about **80% total coverage**. The final code-only follow-up `e0a363bd82641c153f8485e48a09462b7c938bd5` adds only import-package metadata for the isolated Wan worker; its Python 3.11 full suite, Ruff and Windows smoke checks passed before this documentation update. Later CPU hardening CI runs also passed for final-media duration handling (`3a8337f02ecbf869f3d5a5ba2434cb7f114a37bc`, run `36464742520`), local-AI observability (`cda8ff7143c9f7660f0f1d7f3e11c63b218b699c`, run `36469373973`), visual-only scene regeneration (`bcb0771ad91c74c4d8a13663dd150c3b615da979`, run `36471448658`), audio gain controls (`1c4b921aefd8c811588f819e39915b64e07001e9`, run `36474601945`), and structured final-validation failures (`9845dfb1ffaaff2e1e178c4e0059c42e80a955a6`, run `36476314141`). There was no real GPU run, Wan inference, LTX inference or model benchmark.

On the next session: fetch `origin/development`, inspect `git status`, read this file, `docs/SRS.md`, `docs/MIGRATION_MAP.md` and `docs/LOCAL_AI_VIDEO.md`. Recheck `upstream/main` before any deliberate upstream integration; do not silently merge it. Preserve upstream MIT `LICENSE`, do not commit model weights, keep the fake provider test-only, keep provider host paths out of persisted metadata, and use the existing `uv.lock` / CI commands for regression runs.
