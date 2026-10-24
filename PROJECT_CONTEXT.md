# MoneyPrinter AI Video — Project Context

Read this file first in every new AI or developer session. `docs/SRS.md` is the full product specification; `docs/MIGRATION_MAP.md` is the file-level porting decision. `docs/PRODUCT_VISION.md` preserves the owner's longer-term editable-project and publishing goals separately from implemented scope and unapproved technical proposals. `docs/CHATGPT_PROJECT_SETUP.md` contains the reusable ChatGPT Project handoff. Update this handoff with every accepted milestone. Local desktop Codex setup and two-machine sync instructions are in `AGENTS.md` and `docs/LOCAL_CODEX_SETUP.md`.

## Canonical product and repository state

- **Product base:** `harry0703/MoneyPrinterTurbo` `main`, commit `ad5496f1b729d1d7e361dd972015d26c08b0e052` (verified again on 26 September 2026). The local `upstream` remote points there. Vendor tag: `vendor/mpt-2026-09-26-ad5496f`.
- **Branches:** `main` is the stable accepted product branch and now includes the completed CPU-tested AI-video and first factual-mode implementation; `development` is the sole active development branch and was fast-forwarded to the promotion merge before further work. Create no other branches. Commit ordinary changes on `development`, promote accepted milestones to `main` with a normal merge commit, then fast-forward `development` to that merge.
- **Product remote:** `https://github.com/shafiq079/moneyprinter-ai-video`. This CPU hardening pass started at `development` commit `269d5c0202492608e2a1309c94afcf1650bea3fc`; the pinned original vendor commit remains `ad5496f1b729d1d7e361dd972015d26c08b0e052` and is preserved by the vendor tag. Use only the two product branches. `origin` points to this product repository and `upstream` points to `harry0703/MoneyPrinterTurbo`. Do not use the older `shafiq079/MoneyPrinterTurbo` fork for this product.
- **Old prototype:** `shafiq079/content-factory` `main` at `a1760488aae68b8c1c1076a26720a14f4368088f` is read-only reference. Its Next.js UI, FastAPI project API, SQLite queue, timeline v7 and renderer are **not** the new application.
- **Completed:** SRS conversion, upstream revalidation and migration decisions; M1 fake-provider foundation; M2/M3 Wan integration and operator surface; M4 Scene Director; LTX 2.5 Fast/DFR; Phase 5 scene iteration; render-only rerender, cancellation, cleanup, provenance/security hardening, true No-Voice local-AI rendering, portable local-AI output packages, per-GPU cross-process runtime serialization, persisted local-AI timing telemetry, local-AI final-output validation, structured local-AI observability, visual-only regeneration/audio-caption reuse regression coverage, final audio gain-control regression coverage, and recoverable final-validation failure classification. Real Wan/LTX inference and Phase 6 quality measurements require GPU hardware and remain deferred.

## Architecture to preserve

The owner confirmed that a final MP4 alone is not the full long-term product:
an editable project with independently adjustable scene clips, narration,
captions and audio remains a deferred goal. The existing Streamlit scene editor
is the first slice, not a complete multi-track timeline. Earlier proposals
for a specific editor framework, project-file extension or interchange format
were not accepted architecture decisions. See `docs/PRODUCT_VISION.md` before
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

## Verification and working protocol

Baseline verification before M1 used Python 3.11 after `uv sync --frozen --python 3.11`: `uv run --no-sync python -X utf8 -m pytest -q test` returned **1314 passed, 19 skipped, 10622 subtests passed**; Ruff and compileall passed.

M1 is verified by GitHub Actions on commit `ef007c85ffc64d18366861fe7eab6246d3889d78`: Windows smoke tests passed, Python 3.11 tests/coverage passed, Python 3.13 tests/coverage passed, and Ruff passed in the Python 3.11 job.

M2's production-provider implementation and subsequent hardening commits are CPU-tested only. Commit `258323657245be1b680a11f49d406fc40aefd40f` passed Windows smoke, Python 3.11 and Python 3.13 jobs with **1340 passed, 16 skipped, 10622 subtests passed** and about **80% total coverage**. The final code-only follow-up `e0a363bd82641c153f8485e48a09462b7c938bd5` adds only import-package metadata for the isolated Wan worker; its Python 3.11 full suite, Ruff and Windows smoke checks passed before this documentation update. Later CPU hardening CI runs also passed for final-media duration handling (`3a8337f02ecbf869f3d5a5ba2434cb7f114a37bc`, run `36464742520`), local-AI observability (`cda8ff7143c9f7660f0f1d7f3e11c63b218b699c`, run `36469373973`), visual-only scene regeneration (`bcb0771ad91c74c4d8a13663dd150c3b615da979`, run `36471448658`), audio gain controls (`1c4b921aefd8c811588f819e39915b64e07001e9`, run `36474601945`), and structured final-validation failures (`9845dfb1ffaaff2e1e178c4e0059c42e80a955a6`, run `36476314141`). There was no real GPU run, Wan inference, LTX inference or model benchmark.

On the next session: fetch `origin/development`, inspect `git status`, read this file, `docs/SRS.md`, `docs/MIGRATION_MAP.md` and `docs/LOCAL_AI_VIDEO.md`. Recheck `upstream/main` before any deliberate upstream integration; do not silently merge it. Preserve upstream MIT `LICENSE`, do not commit model weights, keep the fake provider test-only, keep provider host paths out of persisted metadata, and use the existing `uv.lock` / CI commands for regression runs.
