# MoneyPrinterTurbo Local AI Video — Project Context

Read this file first in every new AI or developer session. `docs/SRS.md` is the full product specification; `docs/MIGRATION_MAP.md` is the file-level porting decision. Update this handoff with every accepted milestone.

## Canonical product and repository state

- **Product base:** `harry0703/MoneyPrinterTurbo` `main`, commit `ad5496f1b729d1d7e361dd972015d26c08b0e052` (verified again on 26 September 2026). The local `upstream` remote points there. Vendor tag: `vendor/mpt-2026-09-26-ad5496f`.
- **Branches:** `main` is the untouched, stable vendor baseline; `development` is the sole active branch and contains this documentation. Create no other branches. Changes go directly onto `development`; after milestone acceptance merge `development` into `main` with a normal merge commit, then fast-forward `development` to `main`.
- **Product remote:** **not connected yet**. This local checkout must be published to a new, clean repository before a future AI session can fetch it from GitHub. Do not push it to the older `shafiq079/MoneyPrinterTurbo` fork: that fork's `main` is `238bcd2bdb4f3cc48e504bd505a2d3db1f63a3af` (10 August 2026) and has numerous unrelated branches. Do not reset or delete that fork to enforce this project's branch rule.
- **Old prototype:** `shafiq079/content-factory` `main` at `a1760488aae68b8c1c1076a26720a14f4368088f` is read-only reference. Its Next.js UI, FastAPI project API, SQLite queue, timeline v7 and renderer are **not** the new application.
- **Completed:** SRS read and converted to Markdown; upstream and selected prototype files inspected; architecture and migration decisions recorded. No product feature has been implemented or ported.

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

## Exact next milestone: M1 local provider contract and fake end-to-end path

**Start on `development`; do not begin M1 as part of this documentation baseline.** Deliver a provider-neutral `SceneSpec`, generation result/protocol, task-local scene plan and atomic manifest with fingerprints, versioned assets and media validation. Implement CPU-only fake provider and ordered local-material orchestration integrated into the current task path. Wire a **test-only** source so a fake multi-scene task reaches the existing final composer without a paid video provider. Cover multiple scenes with one runtime load, failure/retry preserving valid clips, corrupt-clip invalidation, render-only reuse and no remote material calls. Keep model paths and GPU imports out of CPU tests. The first production Wan and LTX IDs/UI are added after this contract proves itself; no real model integration in M1.

**M1 exit:** fake provider creates a playable video through the existing composer on CPU; relevant `test/` tests and Ruff pass; no upstream stock/local task regression; documentation updated. Then proceed to Wan provider, scene-director prompt quality and LTX as sequenced in SRS Section 19. No real GPU performance claim until dedicated hardware validation.

## Verification and working protocol

Baseline verified here with Python 3.11 after `uv sync --frozen --python 3.11`: `uv run --no-sync python -X utf8 -m pytest -q test` returned **1314 passed, 19 skipped, 10622 subtests passed** (12 dependency/serializer warnings); `uv run --no-sync ruff check app cli.py main.py webui test docs/skill` passed; `uv run --no-sync python -m compileall -q app cli.py main.py webui test docs/skill` passed. There was no GPU run or model benchmark. The baseline documentation and CI trigger are the only local changes.

On the next session: `git fetch upstream`, `git switch development`, inspect `git status`, check that `development` contains `main`, read this file, `docs/SRS.md` Sections 3/9/19/20, then `docs/MIGRATION_MAP.md`. Recheck `upstream/main` for changes before implementing; do not silently merge upstream into the product. Preserve upstream MIT `LICENSE`, do not commit model weights, and use the existing `uv.lock` / CI commands for baseline and later regression runs.
