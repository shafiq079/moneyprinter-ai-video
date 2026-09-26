# MoneyPrinterTurbo Local AI Video — Project Context

Read this file first in every new AI or developer session. `docs/SRS.md` is the full product specification; `docs/MIGRATION_MAP.md` is the file-level porting decision. Update this handoff with every accepted milestone.

## Canonical product and repository state

- **Product base:** `harry0703/MoneyPrinterTurbo` `main`, commit `ad5496f1b729d1d7e361dd972015d26c08b0e052` (verified again on 26 September 2026). The local `upstream` remote points there. Vendor tag: `vendor/mpt-2026-09-26-ad5496f`.
- **Branches:** `main` is the untouched, stable vendor baseline; `development` is the sole active branch and contains this documentation. Create no other branches. Changes go directly onto `development`; after milestone acceptance merge `development` into `main` with a normal merge commit, then fast-forward `development` to `main`.
- **Product remote:** `https://github.com/shafiq079/moneyprinter-ai-video`. Published baseline verified on 27 September 2026: `main` = `ad5496f1b729d1d7e361dd972015d26c08b0e052`, `development` = `7d6980f117126e42c6102e1f8ffe2d83b6079377` before this documentation update. The remote contains only `main` and `development`. `origin` points to this product repository and `upstream` points to `harry0703/MoneyPrinterTurbo`. Do not use the older `shafiq079/MoneyPrinterTurbo` fork for this product.
- **Old prototype:** `shafiq079/content-factory` `main` at `a1760488aae68b8c1c1076a26720a14f4368088f` is read-only reference. Its Next.js UI, FastAPI project API, SQLite queue, timeline v7 and renderer are **not** the new application.
- **Completed:** SRS read and converted to Markdown; upstream and selected prototype files inspected; architecture and migration decisions recorded; **M1 local provider contract/fake CPU path completed on `development`**. No Wan/LTX production model has been integrated or GPU-validated yet.

## Architecture to preserve

Existing `app/services/task.py` orchestrates script, search terms, narration/custom audio, captions, materials, final render and optional publishing. `app/services/material.py:download_videos()` handles stock and remote generated material. The WebUI is `webui/Main.py`, requests are `app/models/schema.py:VideoParams`, API controllers live under `app/controllers/`, and CLI is `cli.py`. Keep upstream TTS, captions, BGM and MoviePy/FFmpeg composition. Add `wan22_local` and `ltx25_local` as distinct AI video material sources through small integrations and new `app/services/local_ai/` modules. A local scene plan and atomic generation manifest will own persisted scene clips; runtime/GPU management will sit below the existing task manager.

## Current-upstream revalidation and SRS refinements

1. The upstream SHA in the SRS is still the latest `main`; no rebase or new vendor commit is necessary. The stock/remote AI dispatch and WebUI AI Video group described in the SRS exist.
2. Upstream already measures **written TTS audio** (with a duration ceiling) and probes custom audio in `task.py:generate_audio`; do not port Content Factory's narration measurement. Scene planning still needs to use that measured duration and maintain actual ordered scene-to-narration mapping.
3. API task manager already has `max_queued_tasks`, existing provider preflight, task state, and some remote task recovery. Reuse these, but they do **not** provide local scene persistence, GPU serialization, or a resumable local inference workflow. An in-process GPU lock alone will not coordinate multiple API worker processes; either constrain the first deployment to one inference process or design a cross-process guard before claiming multi-process safety.
4. Existing `download_videos()` accepts `search_terms` and `audio_duration` and returns local paths. It does **not** carry SceneSpec, fingerprints, versions, or restart semantics. The local route may need its own ordered task-level orchestration and a small material-layer adapter, rather than blindly feeding prompts through the stock keyword interface.
5. `task.py:_run_pipeline` currently generates search terms **before** narration and enters `generate_audio()` for every full video. A genuinely no-voice mode (FR-051), scene plan after measured narration, and render-only/retry paths are **not already solved** by upstream. Custom audio is supported; a silent/no-voice path needs explicit design and tests. Avoid promising no-voice support based only on an empty `voice_name`.
6. Material records already use `script.json` and sanitized source metadata; reuse that practice. The local scene manifest is separate and must never leak model host paths or secrets. Upstream paid providers' remote task IDs do not substitute for local clip fingerprints.
7. Upstream test path is `test/` (singular). Baseline CI now runs on pushes to both `main` and `development`, and on PRs. The SRS example `test/services/test_local_ai_*.py` matches the actual test root.
8. The SRS is a requirements baseline, not an assertion that hardware or model APIs were validated. Wan/LTX inference, VRAM, visual quality and model licenses must be checked against installed revisions during their milestones. The SRS DOCX misplaced Sections 20.2–20.7 near its document map and ended with a v1.0 label; `docs/SRS.md` moves those subsections into Section 20 and fixes the closing label to v1.1.

## M1 completed: local provider contract and fake end-to-end path

M1 is implemented on `development`. The local-AI foundation now includes a provider-neutral `SceneSpec` and generation protocol, deterministic scene fingerprints, an atomic task-local `generation_manifest.json`, versioned scene assets, restart-time media revalidation, retry reuse, a CPU-only fake provider, and ordered integration into the existing MoneyPrinter task/material/final-composer path. Local AI scenes bypass stock keyword generation and remote material download. The fake source is test-only and disabled unless `MPT_ENABLE_LOCAL_AI_FAKE_PROVIDER=1`, so it cannot accidentally appear as a production source.

The fake provider loads its runtime once for a multi-scene generation, writes temporary clips before atomic promotion, preserves completed scenes across later failures, regenerates corrupt cached scenes into a new version, and reuses valid clips without loading the runtime again. The scene planner uses measured narration duration and avoids repeating the complete script when the number of requested scenes exceeds sentence count. Generated clips are validated for decodability, positive duration and requested aspect before being recorded as active. No model paths, GPU imports or production Wan/LTX IDs are part of M1.

**M1 code head:** `ef007c85ffc64d18366861fe7eab6246d3889d78` on `development`. The final M1 CI run passed Windows smoke tests plus the Python 3.11 and 3.13 test/coverage jobs. An earlier first implementation run failed one scene-versioning assertion; that defect was fixed before the green M1 head.

## Exact next milestone: M2 Wan 2.2 local provider

Implement the first production source ID `wan22_local` on top of the M1 contract. Port only the validated Wan 2.2 concepts from `shafiq079/content-factory`: explicit local repo/checkpoint configuration, dependency/CUDA/checkpoint preflight, persistent runtime reuse, safe serialized GPU access, deterministic seed handling, generation into the M1 temporary/versioned asset flow, media validation, retry/restart reuse and structured provider errors. Keep the existing MoneyPrinter script/TTS/caption/BGM/final composition path. Do not expose arbitrary model paths in task payloads and do not auto-download model weights during a generation task.

M2 CPU CI must use mocked/fake runtime boundaries and remain GPU-independent. Real Wan inference, VRAM claims and quality/performance acceptance remain unverified until a dedicated GPU environment is available.

## Verification and working protocol

Baseline verification before M1 used Python 3.11 after `uv sync --frozen --python 3.11`: `uv run --no-sync python -X utf8 -m pytest -q test` returned **1314 passed, 19 skipped, 10622 subtests passed**; Ruff and compileall passed.

M1 is verified by GitHub Actions on commit `ef007c85ffc64d18366861fe7eab6246d3889d78`: Windows smoke tests passed, Python 3.11 tests/coverage passed, Python 3.13 tests/coverage passed, and Ruff passed in the Python 3.11 job. The preceding fixed code commit also reported about **81% total coverage** in CI. There was no real GPU run, Wan inference, LTX inference or model benchmark, so do not turn CPU fake-provider results into hardware/performance claims.

On the next session: `git fetch upstream`, `git switch development`, inspect `git status`, check that `development` contains `main`, read this file, `docs/SRS.md` Sections 3/9/19/20, then `docs/MIGRATION_MAP.md`. Recheck `upstream/main` for changes before M2; do not silently merge upstream into the product. Preserve upstream MIT `LICENSE`, do not commit model weights, keep the fake provider test-only, and use the existing `uv.lock` / CI commands for regression runs.
