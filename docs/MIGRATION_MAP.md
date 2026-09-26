# Content Factory to MoneyPrinterTurbo Migration Map

Source: `shafiq079/content-factory` `main` at `a1760488aae68b8c1c1076a26720a14f4368088f`. Target: clean MoneyPrinterTurbo baseline `ad5496f1b729d1d7e361dd972015d26c08b0e052`. These are decisions, not completed ports. `docs/SRS.md` Section 20 defines the controlling migration policy.

| Old source | Decision | Target in MoneyPrinterTurbo | Specific treatment and timing |
| --- | --- | --- | --- |
| `backend/app/wan_video.py` (`Wan22Video`) | **ADAPT** | `app/services/local_ai/wan22.py` | Carry checkpoint/shard preflight, lazy official pipeline load, runtime reuse, seed/frame logic and local output handling. Replace `core.Request`, `scene: dict` and prototype path assumptions with SceneSpec/task paths. Normalize and validate MP4; do not stretch short clips just to fit long beats. Wan milestone after M1. |
| `backend/app/core.py` (`LTX25Video`, lines around 615–791) | **ADAPT** | `app/services/local_ai/ltx25.py` | Extract only Distilled/DFR path validation, pipeline creation/inference and single-runtime mode switching. Ignore native audio for MVP. Verify official model API and installed model revision before adapting. LTX milestone. Do not copy all of `core.py`. |
| `backend/app/core.py` (`GPU_VIDEO_LOCK`) and provider release methods | **ADAPT** | `app/services/local_ai/runtime.py` | Reuse family eviction/one-runtime-at-a-time intent. Scope ownership and locks to actual worker topology; a thread lock alone is not multi-process safe. M1 contract first; GPU integration later. |
| `backend/app/media.py` (`inspect`, `validate_clip`, `validate_final`) | **PORT** selectively | Local AI clip probe/normalization helper, preferably adjacent to `app/services/local_ai/` | Use ffprobe duration/stream/dimension checks where upstream lacks equivalents; compare upstream `app/services/video.py` before porting. No separate general media stack. M1. |
| `backend/app/contracts.py` (`Scene`, `Timeline`) | **REFERENCE ONLY** | `SceneSpec` and manifest schemas | Take validation ideas for ordered IDs, duration, prompt and safe asset references. Prototype timeline v7 is not canonical. M1. |
| `backend/app/scene_assets.py` | **ADAPT** concepts | `app/services/generation_manifest.py` and task-local `generated_ai/scene-*/v*.mp4` | Keep immutable versioned asset/atomic-publish idea; tailor task paths to `utils.task_dir(task_id)` and only mark a validated clip ready. M1/retry milestone. |
| `backend/app/core.py` (`ensure_scene_media`, `process`, `regenerate_work`, `render_work`) | **REFERENCE ONLY** | Task-local orchestration in `app/services/task.py` plus manifest | Use recovery and independence of render-only edits as behavior specifications. Do not transplant prototype project pipeline. M1 and recovery milestone. |
| `backend/app/jobs.py` | **REFERENCE ONLY** | `app/controllers/manager/`, task state and local runtime guard | Borrow cancellation/retry/idempotency test cases; no SQLite queue. Existing API queue is bounded but local scene restart needs new manifest logic. |
| `backend/app/core.py` (`TemplatePlanner`, `OllamaPlanner`, narrative beats/visual bible) | **ADAPT** later | `app/services/scene_planner.py` | Create prompts from upstream script and measured audio with ordered visual beats. Keep factual claims separate. Implement scene director after basic fake/Wan path. |
| `backend/app/providers.py` | **REFERENCE ONLY** | Existing `video_source` dispatch plus narrow local provider protocol | Do not import wholesale registry or prototype preflight table. Wire `wan22_local` and `ltx25_local` at upstream registration points in their milestone. |
| `backend/app/research.py` and `backend/app/core.py` (`ensure_claim_review`) | **REFERENCE ONLY** | Optional later factual mode | Defer entirely from local-video MVP; if needed, isolate before visual inference. |
| `backend/app/audio.py` and Kokoro/SFX code in `backend/app/core.py` | **DO NOT PORT** | `app/services/voice.py`, existing subtitle/BGM and composer | Existing MoneyPrinter audio path is authoritative. Revisit one verified missing behavior only with a test and explicit reason. |
| `backend/app/main.py` | **DO NOT PORT** | `app/controllers/v1/` and existing FastAPI app | No duplicate API/routes/CORS/project model. Add narrow local AI status or scene endpoints only when needed. |
| `frontend/` | **DO NOT PORT** | `webui/Main.py` | No Next.js editor in MVP. Add source controls and progress through Streamlit once provider contract works. |
| `backend/app/core.py` (`render`, FFmpeg timeline) and `timeline.json` schema v7 | **DO NOT PORT** | `app/services/video.py`, `task.py`, task state + local scene manifest | Retain upstream final render. Import an isolated FFmpeg fix only if profiling or regression demonstrates a gap. |
| `backend/tests/` | **ADAPT** test intent | `test/services/test_local_ai_*.py` and task integration tests | Rewrite fake-runtime, preflight, scene retry, version preservation and render-only assertions against MoneyPrinter interfaces. No direct fixture copy. |
| Old `PROJECT_CONTEXT.md` | **REFERENCE ONLY** | Root `PROJECT_CONTEXT.md` | Carry only current product choices and proven observations; old product instructions do not govern this repository. |

## New component boundaries

- `app/services/local_ai/base.py`: scene and generation contracts, provider interface and fingerprints. The provider owns inference; orchestration owns planning, manifest, progress and composition.
- `app/services/local_ai/runtime.py`: GPU occupancy, family switching and runtime reuse. Define scope before supporting concurrent API processes.
- `app/services/scene_planner.py`: ordered scenes from upstream script/audio and later cinematic prompt direction.
- `app/services/generation_manifest.py`: atomic scene state, fingerprint comparison, validated versioned files and retry reuse under `utils.task_dir(task_id)`.
- Small upstream integrations: `app/services/task.py` to place planning after audio and before material generation; `app/services/material.py` only for provider/source bridging; additive `app/models/schema.py`, `webui/Main.py`, `cli.py` and API controllers at later milestones. The final composer remains provider-agnostic.

No source from Content Factory has been copied into the new baseline. Review the old file at the commit above and the current upstream equivalent before each individual adaptation.
