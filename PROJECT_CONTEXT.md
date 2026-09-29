# MoneyPrinter AI Video — Project Context

Read this file first in every new AI or developer session. `docs/SRS.md` is the full product specification; `docs/MIGRATION_MAP.md` is the file-level porting decision. Update this handoff with every accepted milestone.

## Canonical product and repository state

- **Product base:** `harry0703/MoneyPrinterTurbo` `main`, commit `ad5496f1b729d1d7e361dd972015d26c08b0e052` (verified again on 26 September 2026). The local `upstream` remote points there. Vendor tag: `vendor/mpt-2026-09-26-ad5496f`.
- **Branches:** `main` is the untouched, stable vendor baseline; `development` is the sole active branch and contains the accepted local-AI implementation work in progress. Create no other branches. Changes go directly onto `development`; after an accepted stabilization point, merge `development` into `main` with a normal merge commit and keep the two-branch policy.
- **Product remote:** `https://github.com/shafiq079/moneyprinter-ai-video`. This CPU hardening pass started at `development` commit `269d5c0202492608e2a1309c94afcf1650bea3fc`; `main` remains the pinned vendor baseline `ad5496f1b729d1d7e361dd972015d26c08b0e052`. Use only these two branches. `origin` points to this product repository and `upstream` points to `harry0703/MoneyPrinterTurbo`. Do not use the older `shafiq079/MoneyPrinterTurbo` fork for this product.
- **Old prototype:** `shafiq079/content-factory` `main` at `a1760488aae68b8c1c1076a26720a14f4368088f` is read-only reference. Its Next.js UI, FastAPI project API, SQLite queue, timeline v7 and renderer are **not** the new application.
- **Completed:** SRS conversion, upstream revalidation and migration decisions; M1 fake-provider foundation; M2/M3 Wan integration and operator surface; M4 Scene Director; LTX 2.5 Fast/DFR; Phase 5 scene iteration; render-only rerender, cancellation, cleanup, provenance/security hardening, true No-Voice local-AI rendering, portable local-AI output packages, per-GPU cross-process runtime serialization, persisted local-AI timing telemetry, local-AI final-output validation, structured local-AI observability, visual-only regeneration/audio-caption reuse regression coverage, final audio gain-control regression coverage, and recoverable final-validation failure classification. All are on `development`. Real Wan/LTX inference and Phase 6 quality measurements require GPU hardware and remain deferred.

## Architecture to preserve

`app/services/task.py` orchestrates script, search terms, narration/custom audio, captions, materials, final render and optional publishing. `app/services/material.py:download_videos()` handles stock and remote generated material; local AI bypasses it. The WebUI is `webui/Main.py`, requests are `app/models/schema.py:VideoParams`, API controllers live under `app/controllers/`, and CLI is `cli.py`. Keep upstream TTS, captions, BGM and MoviePy/FFmpeg composition. `wan22_local` and `ltx25_local` are distinct local AI video material sources implemented under `app/services/local_ai/`; the task-local scene plan and atomic generation manifest own persisted scene clips. Runtime management sits below the existing task manager.

## Current-upstream revalidation and SRS refinements

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

The next deployment path is `ltx25_hf`: an operator-owned Hugging Face ZeroGPU
Space using the official optimized LTX-2.5 distilled Gradio implementation.
MoneyPrinter accesses it through the provider-neutral scene contract and an
isolated Hugging Face transport adapter. CPU tests may validate the adapter and
task integration before GPU quota is available, but real ZeroGPU latency,
quality and quota behavior remain unvalidated until an authenticated generation
is run after quota reset. Phase 6 tooling provides
`scripts/local_ai_benchmark.py`, which will later run identical prompts across
Wan 2.2, LTX Fast and LTX Quality and record timing/media/GPU telemetry.

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
those real measurements exist. Optional factual workflow and a larger editor
remain non-blocking and should only be started for an explicit product need.

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
