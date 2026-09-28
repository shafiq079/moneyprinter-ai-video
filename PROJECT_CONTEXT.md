# MoneyPrinter AI Video — Project Context

Read this file first in every new AI or developer session. `docs/SRS.md` is the full product specification; `docs/MIGRATION_MAP.md` is the file-level porting decision. Update this handoff with every accepted milestone.

## Canonical product and repository state

- **Product base:** `harry0703/MoneyPrinterTurbo` `main`, commit `ad5496f1b729d1d7e361dd972015d26c08b0e052` (verified again on 26 September 2026). The local `upstream` remote points there. Vendor tag: `vendor/mpt-2026-09-26-ad5496f`.
- **Branches:** `main` is the untouched, stable vendor baseline; `development` is the sole active branch and contains the accepted local-AI implementation work in progress. Create no other branches. Changes go directly onto `development`; after an accepted stabilization point, merge `development` into `main` with a normal merge commit and keep the two-branch policy.
- **Product remote:** `https://github.com/shafiq079/moneyprinter-ai-video`. This CPU hardening pass started at `development` commit `269d5c0202492608e2a1309c94afcf1650bea3fc`; `main` remains the pinned vendor baseline `ad5496f1b729d1d7e361dd972015d26c08b0e052`. Use only these two branches. `origin` points to this product repository and `upstream` points to `harry0703/MoneyPrinterTurbo`. Do not use the older `shafiq079/MoneyPrinterTurbo` fork for this product.
- **Old prototype:** `shafiq079/content-factory` `main` at `a1760488aae68b8c1c1076a26720a14f4368088f` is read-only reference. Its Next.js UI, FastAPI project API, SQLite queue, timeline v7 and renderer are **not** the new application.
- **Completed:** SRS conversion, upstream revalidation and migration decisions; M1 fake-provider foundation; M2/M3 Wan integration and operator surface; M4 Scene Director; LTX 2.5 Fast/DFR; Phase 5 scene iteration; render-only rerender, cancellation, cleanup, provenance and security hardening. All are on `development`. Real Wan/LTX inference and Phase 6 quality measurements require GPU hardware and remain deferred.

## Architecture to preserve

`app/services/task.py` orchestrates script, search terms, narration/custom audio, captions, materials, final render and optional publishing. `app/services/material.py:download_videos()` handles stock and remote generated material; local AI bypasses it. The WebUI is `webui/Main.py`, requests are `app/models/schema.py:VideoParams`, API controllers live under `app/controllers/`, and CLI is `cli.py`. Keep upstream TTS, captions, BGM and MoviePy/FFmpeg composition. `wan22_local` and `ltx25_local` are distinct local AI video material sources implemented under `app/services/local_ai/`; the task-local scene plan and atomic generation manifest own persisted scene clips. Runtime management sits below the existing task manager.

## Current-upstream revalidation and SRS refinements

1. Upstream `harry0703/MoneyPrinterTurbo` moved on 27 September 2026 from the pinned vendor baseline `ad5496f1b729d1d7e361dd972015d26c08b0e052` to `8e259e9f072c9e08464f040cd658d4eb046a57d0`. The one new upstream commit changes Redis task traversal/cross-post recovery in `app/services/state.py`, `app/services/task.py` and their tests. It is **not merged** into this product during M4; keep the vendor baseline pinned and reconcile upstream deliberately at a stabilization point.
2. Upstream already measures **written TTS audio** (with a duration ceiling) and probes custom audio in `task.py:generate_audio`; do not port Content Factory's narration measurement. Scene planning still needs to use that measured duration and maintain actual ordered scene-to-narration mapping.
3. API task manager already has `max_queued_tasks`, existing provider preflight, task state, and some remote task recovery. Reuse these, but they do **not** provide local scene persistence, GPU serialization, or a resumable local inference workflow. An in-process GPU lock alone will not coordinate multiple API worker processes; either constrain the first deployment to one inference process or design a cross-process guard before claiming multi-process safety.
4. Existing `download_videos()` accepts `search_terms` and `audio_duration` and returns local paths. It does **not** carry SceneSpec, fingerprints, versions, or restart semantics. The local route may need its own ordered task-level orchestration and a small material-layer adapter, rather than blindly feeding prompts through the stock keyword interface.
5. `task.py:_run_pipeline` currently generates search terms **before** narration and enters `generate_audio()` for every full video. A genuinely no-voice mode (FR-051), scene plan after measured narration, and render-only/retry paths are **not already solved** by upstream. Custom audio is supported; a silent/no-voice path needs explicit design and tests. Avoid promising no-voice support based only on an empty `voice_name`.
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

The worker process remains persistent across compatible tasks. A model/code fingerprint is part of the runtime key so changing checkpoint/code inputs at the same paths evicts the old worker instead of silently reusing stale weights. `LocalAIRuntimeManager` serializes heavyweight local generation inside one MoneyPrinter process, holds a provider family across a scene batch to avoid Wan/LTX thrashing, and supports family eviction. This is deliberately **process-local**; do not claim multi-process GPU safety until a cross-process guard or dedicated single GPU worker topology is implemented.

Wan configuration is operator-owned through `[wan22_local]` / environment settings: repo path, checkpoint path, worker Python, CUDA device, seed and memory-related flags. These host paths are not added to public task payloads or manifests. The manifest stores safe provider/model metadata, deterministic per-scene seeds and input fingerprints. Scene failures expose provider, scene ID and a safe error code; completed scenes remain reusable. Task state now reports the active scene and total scene count while generation is running. The fake M1 provider remains test-only.

**M2 functional code head:** `e0a363bd82641c153f8485e48a09462b7c938bd5` on `development`. CPU CI exercises mocked Wan worker/runtime boundaries; no real Wan checkpoint was loaded and no GPU/VRAM/visual-quality claim has been validated.

## M3 completed: source registration and operator surface

M3 exposed `wan22_local` through WebUI, CLI and API using the same provider/preflight rules, added the readiness button and CLI/API preflight commands, documented operator setup in `docs/LOCAL_AI_VIDEO.md`, kept model/checkpoint paths out of public task requests, and left the fake provider internal. The M3 registration commit `09dbdae49cc8533c37f22560bf8c5a80bc3626a3` revealed two stale regression expectations; follow-up `7a6775bfb7e6fec73188f99b9daae6cb613c2927` aligned the Agent Skill exception and WebUI group test. CI run `36325467280` passed Windows smoke, Python 3.11, Python 3.13 and Ruff.

## Current development boundary

Phase 5 single-scene regeneration was CI verified on
`ce5f299564cf3c7b4945f93e0c83bfe576191406`. Subsequent commits added
version restore, render-only rerender, cooperative cancellation, safe cleanup,
provenance and metadata redaction through the starting SHA above. The next
hardware-dependent milestone is real Wan/LTX GPU validation and quality tuning;
do not claim model quality or GPU performance from CPU fake-provider tests.

Development may continue without blocking on hardware. Phase 6 tooling provides
`scripts/local_ai_benchmark.py`, which will later run identical prompts across
Wan 2.2, LTX Fast and LTX Quality and record timing/media/GPU telemetry. Do not
invent default-quality conclusions before those real measurements exist.
Optional factual workflow and a larger editor remain non-blocking and should
only be started for an explicit product need.

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

## Verification and working protocol

Baseline verification before M1 used Python 3.11 after `uv sync --frozen --python 3.11`: `uv run --no-sync python -X utf8 -m pytest -q test` returned **1314 passed, 19 skipped, 10622 subtests passed**; Ruff and compileall passed.

M1 is verified by GitHub Actions on commit `ef007c85ffc64d18366861fe7eab6246d3889d78`: Windows smoke tests passed, Python 3.11 tests/coverage passed, Python 3.13 tests/coverage passed, and Ruff passed in the Python 3.11 job.

M2's production-provider implementation and subsequent hardening commits are CPU-tested only. Commit `258323657245be1b680a11f49d406fc40aefd40f` passed Windows smoke, Python 3.11 and Python 3.13 jobs with **1340 passed, 16 skipped, 10622 subtests passed** and about **80% total coverage**. The final code-only follow-up `e0a363bd82641c153f8485e48a09462b7c938bd5` adds only import-package metadata for the isolated Wan worker; its Python 3.11 full suite, Ruff and Windows smoke checks passed before this documentation update. There was no real GPU run, Wan inference, LTX inference or model benchmark.

On the next session: fetch `origin/development`, inspect `git status`, read this file, `docs/SRS.md`, `docs/MIGRATION_MAP.md` and `docs/LOCAL_AI_VIDEO.md`. Recheck `upstream/main` before any deliberate upstream integration; do not silently merge it. Preserve upstream MIT `LICENSE`, do not commit model weights, keep the fake provider test-only, keep provider host paths out of persisted metadata, and use the existing `uv.lock` / CI commands for regression runs.
