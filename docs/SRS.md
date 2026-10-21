# Self-Hosted AI Video Extension for MoneyPrinterTurbo

Software Requirements Specification

Repository selection, product requirements, architecture, implementation roadmap, testing strategy, and final engineering decision

> Markdown transcription of the attached final SRS v1.1. Section 20.2–20.7 has been placed with Section 20; the closing version label has been corrected to 1.1. Product requirements and recommendations retain their source wording.

| **Document version**           | 1.1                                                             |
|--------------------------------|-----------------------------------------------------------------|
| **Status**                     | Final baseline SRS for implementation, migration and AI handoff |
| **Research snapshot**          | 26 September 2026                                               |
| **Recommended base**           | harry0703/MoneyPrinterTurbo (audited current-main snapshot)     |
| **Primary local video models** | Wan 2.2 TI2V-5B; LTX 2.5 Distilled / DFR                        |

*Prepared as a developer-ready product and engineering specification. Licensing observations are technical planning notes, not legal advice.*

# Executive Decision

> BASE PROJECT DECISION
> >
> > Use harry0703/MoneyPrinterTurbo as the base platform. Fork the current, audited upstream main snapshot (commit ad5496f1b729d1d7e361dd972015d26c08b0e052 as researched on 26 Sep 2026), tag that vendor baseline, and implement self-hosted local AI video as new material providers. Do not use MoneyPrinterV2 as the base for this product. MoneyPrinterTurbo already contains the exact extension seam we need: video_source -> material.download_videos() -> provider-specific on-demand generation -> existing narration/subtitle/music/editing/final-render pipeline. [R1-R7]

The most important research finding is that MoneyPrinterTurbo is no longer only a stock-footage generator. Its current code already supports multiple remote AI-video material sources (WaveSpeed, Volcano Engine Seedance, OFox, MuAPI, Metaso MiniMax, LoomLoom) alongside Pexels, Pixabay, Coverr, generated images, and local uploads. The proposed product is therefore not a rewrite of MoneyPrinterTurbo and not a replacement of its editing pipeline. It is a focused extension that adds local/self-hosted video-generation providers (Wan and LTX), improves script-to-scene prompt planning, and adds generation-safe caching/recovery around expensive GPU work. \[R1\]\[R3\]\[R6\]

MoneyPrinterV2 is useful as a reference for a simpler local/Ollama-driven workflow and AI-generated-image approach, but it is a substantially weaker base for this target: it is CLI-first, tightly couples content creation to Selenium publishing and broader money-automation workflows, currently renders AI images rather than AI video clips, has a much smaller test/CI surface, and is AGPL-3.0 rather than MIT. \[R8\]\[R9\]

| **Decision factor**          | **MoneyPrinterTurbo**                                                       | **MoneyPrinterV2**                                                            | **Engineering implication**                            |
|------------------------------|-----------------------------------------------------------------------------|-------------------------------------------------------------------------------|--------------------------------------------------------|
| Core short-video product fit | Direct: topic/script -\> materials -\> TTS -\> subtitles -\> BGM -\> render | YouTube Shorts is one workflow among Twitter, affiliate and outreach features | Turbo needs extension; V2 needs restructuring          |
| Video-material extensibility | Existing stock + AI video + AI image + local source dispatch                | Image generation is embedded inside YouTube class                             | Turbo already has the right seam                       |
| User/API surfaces            | Streamlit WebUI + FastAPI + CLI + agent workflow                            | Interactive CLI + Selenium automation                                         | Turbo reduces product-shell work                       |
| Testing and CI               | 71 Python test files; GitHub CI; coverage floor configured                  | 5 Python test files; no workflow observed in current tree                     | Turbo has materially lower integration risk            |
| License                      | MIT                                                                         | AGPL-3.0                                                                      | MIT provides greater deployment/commercial flexibility |
| Current activity             | Pushed 24 Sep 2026; v1.3.7 released 13 Sep 2026                             | Pushed 15 Sep 2026; no current GitHub release observed                        | Both active, Turbo substantially more mature           |

## Target Product in One Sentence

A self-hosted short-form video factory that keeps MoneyPrinterTurbo's proven script, TTS, caption, music, rendering, WebUI/API/CLI and optional publishing capabilities, but can generate each required visual scene locally with open/local text-to-video models instead of depending on stock-footage APIs or paid per-clip video-generation services.

## Non-negotiable Product Principles

- AI-generated video is a first-class material source, not a post-processing hack or a stock fallback.

- Local/self-hosted generation must work without a paid per-video API once models and compute are available.

- Every scene clip must be persisted and reusable so changing captions, BGM or rendering settings does not regenerate video.

- A failed later scene must not force completed scenes to be generated again.

- Wan and LTX must sit behind provider boundaries so future models can be added without rewriting the pipeline.

- GPU-dependent behavior must have CPU-safe contract tests; real visual quality claims require actual GPU validation.

- The first release should extend MoneyPrinterTurbo rather than build a new NLE/editor, account system or infrastructure stack.

- Upstream MoneyPrinterTurbo changes should remain mergeable; modifications to core upstream files should be intentionally small.

- The active repository must stay simple for human and AI contributors: preserve the old Content Factory separately as reference, and use only two long-lived branches in the new MoneyPrinterTurbo-based repository: main and development.

# Document Map

- 1\. Research Scope and Method

- 2\. Product Vision and Business Goals

- 3\. Repository Comparison and Base Selection

- 4\. Existing MoneyPrinterTurbo Architecture Analysis

- 5\. Target System Scope

- 6\. Stakeholders and User Journeys

- 7\. Functional Requirements

- 8\. Non-Functional Requirements

- 9\. Target Architecture

- 10\. Scene Planning and Prompt Engineering

- 11\. Local AI Video Provider Design

- 12\. GPU Runtime and Job Execution

- 13\. Data, Assets, Caching and Recovery

- 14\. Audio, Captions, Music and Rendering

- 15\. WebUI, API and CLI Changes

- 16\. Configuration and Deployment

- 17\. Security, Privacy and Licensing

- 18\. Testing and Quality Assurance

- 19\. Implementation Roadmap

- 20\. Migration from the Existing Content Factory Prototype

- 21\. Risk Register

- 22\. Acceptance and Release Criteria

- 23\. Final Architecture Re-analysis

- Appendix A. Requirement Traceability Summary

- Appendix B. Proposed Configuration

- Appendix C. References and Research Snapshot

- Appendix D. Fresh-Chat / AI Developer Handoff Checklist

# 1. Research Scope and Method

This specification is based on direct repository inspection rather than feature lists alone. The research reviewed the current source trees, repository metadata, recent commits/releases, licenses, dependency definitions, core material/video orchestration paths, task management, WebUI source selection, test/CI structure, and the official Wan 2.2 and LTX-2 model repositories. The user's existing Content Factory prototype was also reviewed as a source of reusable local-model adapter patterns. The snapshot date is 26 Sep 2026.

## 1.1 Repositories and snapshots reviewed

| **Reference** | **Repository / source**                     | **Snapshot / evidence used**                                                                                                |
|---------------|---------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------|
| R1            | harry0703/MoneyPrinterTurbo                 | Current main at ad5496f1b729d1d7e361dd972015d26c08b0e052; README-en.md and repository metadata                              |
| R2            | MoneyPrinterTurbo build/dependencies        | pyproject.toml v1.3.7; Python \>=3.11; MoviePy, Streamlit, FastAPI, faster-whisper, Redis, LiteLLM and related dependencies |
| R3            | MoneyPrinterTurbo material layer            | app/services/material.py, especially download_videos() and AI on-demand branches                                            |
| R4            | MoneyPrinterTurbo task/render orchestration | app/services/task.py and task managers/state services                                                                       |
| R5            | MoneyPrinterTurbo contracts                 | app/models/schema.py: VideoParams, MaterialInfo, VideoAspect, transitions                                                   |
| R6            | MoneyPrinterTurbo WebUI                     | webui/Main.py: grouped Stock Video / AI Video / AI Image / Local Material source selection                                  |
| R7            | MoneyPrinterTurbo release/quality           | v1.3.7 release; GitHub CI; current test tree                                                                                |
| R8            | FujiwaraChoki/MoneyPrinterV2                | Current main at a734fa924adb9ffe5ab8472aa5526e469e42a8b5; README, docs/YouTube.md, src/classes/YouTube.py, config           |
| R9            | MoneyPrinterV2 license/quality              | AGPL-3.0 LICENSE; current test/workflow tree                                                                                |
| R10           | Wan-Video/Wan2.2 + Wan-AI/TI2V-5B           | Official README and model card: 5B TI2V, 720p/24fps, consumer GPU target; model card Apache-2.0                             |
| R11           | Lightricks/LTX-2                            | Official README and LTX-2.x Community License dated 11 Aug 2026                                                             |
| R12           | shafiq079/content-factory                   | Current project context and local Wan/LTX adapters as reusable implementation reference                                     |

## 1.2 Repository health indicators

| **Indicator (26 Sep 2026)** | **MoneyPrinterTurbo** | **MoneyPrinterV2**        |
|-----------------------------|-----------------------|---------------------------|
| Stars                       | 126,013               | 31,989                    |
| Forks                       | 19,641                | 3,443                     |
| Open issues                 | 35                    | 93                        |
| Latest push observed        | 24 Sep 2026           | 15 Sep 2026               |
| License                     | MIT                   | AGPL-3.0                  |
| Python files in tree        | 121                   | 22                        |
| Python test files           | 71                    | 5                         |
| GitHub workflows observed   | CI + Docker GHCR      | None in .github/workflows |

> How to interpret these signals
> >
> > Stars and forks are not software-quality scores. They are used only as supporting evidence of adoption and ecosystem size. The base-project decision is driven primarily by architecture fit, license, tested extension points, and reduction of new code required.

# 2. Product Vision and Business Goals

## 2.1 Vision

The target system should let a creator provide a topic, niche, or complete script and receive a polished short-form video whose visuals are generated scene-by-scene by self-hosted AI models. The rest of the production stack - narration, captions, background music, transitions, formatting, final rendering, task history, API access and optional publishing - should remain based on MoneyPrinterTurbo wherever it is already adequate.

> Target end-to-end flow
> >
> > Topic / niche / custom script
> >
> > |
> >
> > v
> >
> > Script generation or user script
> >
> > |
> >
> > v
> >
> > TTS + measured narration duration
> >
> > |
> >
> > v
> >
> > Scene plan + cinematic prompts
> >
> > |
> >
> > v
> >
> > Local AI Video Provider
> >
> > | Wan 2.2 TI2V-5B
> >
> > | LTX 2.5 Distilled / DFR
> >
> > |
> >
> > v
> >
> > Persisted scene MP4 assets
> >
> > |
> >
> > v
> >
> > MoneyPrinterTurbo composition
> >
> > (captions + BGM + transitions + output format)
> >
> > |
> >
> > v
> >
> > Final MP4 + reusable project/task assets

## 2.2 Primary goals

- Replace dependence on stock-footage retrieval for the primary creative path with original generated visual clips.

- Avoid recurring per-video generation API charges by supporting local/self-hosted model inference.

- Preserve MoneyPrinterTurbo's existing user-facing workflow and media assembly rather than rebuilding solved components.

- Make local AI generation restart-safe and economical by persisting completed clips, model settings and seeds.

- Support at least Wan 2.2 TI2V-5B and LTX 2.5 through a model-provider abstraction.

- Provide a path to 30-120 second vertical short-form content, with 9:16 / 1080x1920 as the primary final output.

- Keep stock footage, local uploads and upstream remote AI sources available as optional/fallback material providers.

- Keep the fork maintainable against an actively changing MoneyPrinterTurbo upstream.

## 2.3 Success measures

| **Measure**                   | **MVP target**                                                                                                                            |
|-------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------|
| Local-generation independence | A complete local pipeline can run without Pexels/Pixabay/video-generation API credentials when local LLM/TTS/video models are configured. |
| Regeneration efficiency       | Changing subtitles, BGM, output aspect settings compatible with existing assets, or final rendering does not call the video model again.  |
| Scene recovery                | After a failure/restart, valid completed scene clips are reused and only missing/invalid scenes are generated.                            |
| Provider modularity           | A third local video model can be added without changing the final composer and with limited changes to source registration/configuration. |
| Quality observability         | Task history records provider, model/mode, prompt, seed, scene duration and output path for every generated clip.                         |
| Upstream maintainability      | The local-AI feature is concentrated in new modules plus small, tested registrations in existing dispatch/UI code.                        |

# 3. Repository Comparison and Base Selection

## 3.1 MoneyPrinterTurbo - engineering fit

MoneyPrinterTurbo is already an all-in-one short-video generator with multiple entry points. Its current README describes WebUI, API, CLI and agent workflows, multiple LLM and TTS providers, stock sources, local files, AI image generation, several remote text-to-video providers, 9:16/16:9/1:1 rendering, and optional social publishing. This breadth matters because the target product needs a working production shell more than it needs another general-purpose backend. \[R1\]

The strongest architectural evidence is in app/services/material.py. download_videos() already dispatches stock material and separately handles multiple on-demand AI-generation sources. The WaveSpeed generator deliberately follows a search/generation function signature compatible with the common material pipeline. Paid AI sources stop after enough material duration is generated and do not use the stock search cache. A local Wan/LTX provider can follow the same contract while replacing remote submission/poll/download with direct model inference and local file publication. \[R3\]

MoneyPrinterTurbo also exposes exactly the UI location needed for our extension. VIDEO_SOURCE_GROUPS currently separates Stock Video, AI Video, AI Image and Local Material. The initial integration can add Wan 2.2 Local and LTX 2.5 Local to the AI Video group with provider-specific settings while keeping all other sources untouched. \[R6\]

## 3.2 MoneyPrinterV2 - useful reference, weak base

MoneyPrinterV2 is a broader automation suite. Its README lists Twitter automation, YouTube Shorts, affiliate marketing and local-business outreach. Its YouTube workflow creates AI image prompts, generates images, converts the script to speech, assigns each image an equal share of narration duration, and composes a 1080x1920 slideshow with subtitles/music in MoviePy before Selenium-based upload. This is a coherent small system, but local text-to-video would require replacing its image-centric YouTube class, separating generation from Selenium/account logic, adding an API/WebUI, and building stronger task persistence and tests. \[R8\]

Its AGPL-3.0 license is also a strategic constraint for a future hosted product. The license is designed so users interacting with modified network software can obtain corresponding source under the AGPL terms. That may be acceptable for an intentionally AGPL product, but it is unnecessary friction when an MIT-licensed base already fits the architecture better. This is an engineering planning observation, not legal advice. \[R9\]

## 3.3 Weighted engineering fit matrix

| **Criterion**                             | **Weight** | **MoneyPrinterTurbo** | **MoneyPrinterV2** |
|-------------------------------------------|------------|-----------------------|--------------------|
| Existing short-video pipeline             | 18%        | 5.0/5                 | 3.0/5              |
| AI-video material extension seam          | 18%        | 5.0/5                 | 2.0/5              |
| WebUI/API/CLI readiness                   | 12%        | 5.0/5                 | 1.5/5              |
| Testing and CI maturity                   | 10%        | 5.0/5                 | 2.0/5              |
| License flexibility for fork              | 10%        | 5.0/5                 | 2.0/5              |
| Upstream activity/ecosystem               | 8%         | 5.0/5                 | 3.0/5              |
| TTS/caption/music/render breadth          | 8%         | 5.0/5                 | 3.0/5              |
| Task history/queue/recovery foundation    | 6%         | 4.5/5                 | 2.0/5              |
| Ease of local GPU provider integration    | 7%         | 4.5/5                 | 2.5/5              |
| Scope alignment / low irrelevant coupling | 3%         | 5.0/5                 | 2.0/5              |
| Weighted fit score                        | 100%       | 98.7/100              | 46.3/100           |

> Decision record
> >
> > MoneyPrinterTurbo is the selected base. MoneyPrinterV2 should not be merged into the codebase. Specific ideas - local Ollama-first operation, AI prompt generation, and simpler CLI flows - may be used as conceptual references only.

## 3.4 Recommended fork baseline and upstream strategy

- Create the product fork from MoneyPrinterTurbo current main at audited SHA ad5496f1b729d1d7e361dd972015d26c08b0e052 (26 Sep 2026 snapshot).

- Immediately tag that commit in the fork, for example vendor/mpt-2026-09-26-ad5496f, so every later change has a deterministic origin.

- Keep an upstream remote pointing to harry0703/MoneyPrinterTurbo and schedule controlled upstream merges rather than copying individual files ad hoc.

- Prefer new local-AI modules and registries over large modifications to app/services/material.py or webui/Main.py.

- Every upstream merge must run the complete CPU test suite plus local-provider contract tests before acceptance.

- Model weights are never committed to the fork; paths and runtime settings belong in local/deployment configuration.

# 4. Existing MoneyPrinterTurbo Architecture Analysis

## 4.1 Current architectural assets to preserve

| **Area**    | **Existing capability**                                                            | **Decision**                                                         |
|-------------|------------------------------------------------------------------------------------|----------------------------------------------------------------------|
| Inputs      | Topic, custom script, language, aspect, video source, clip duration, video count   | Preserve; add local AI settings without breaking old request schema  |
| Script/LLM  | Large provider registry including Ollama/local-compatible routes                   | Reuse; extend prompt generation for scene-grade visual prompts       |
| Materials   | Stock, remote AI video, AI image, local files through MaterialInfo/download_videos | Primary integration seam                                             |
| Narration   | Multiple TTS options including Kokoro and Edge TTS                                 | Reuse for MVP narration                                              |
| Captions    | Subtitle generation/styling, faster-whisper options, word-by-word modes            | Reuse                                                                |
| Music       | Background music selection/generation/preview and volume handling                  | Reuse                                                                |
| Composition | MoviePy/FFmpeg based concatenation, fit/aspect, transitions, subtitles and audio   | Reuse initially; optimize only if profiling proves necessary         |
| Tasks       | WebUI background tasks; API memory/Redis task manager and state                    | Reuse, but add GPU serialization and per-scene manifest              |
| Interfaces  | Streamlit WebUI, FastAPI, CLI, agent tooling                                       | Reuse; local provider should work through all supported entry points |
| Publishing  | TikTok/Instagram/YouTube paths already exist                                       | Keep optional; not part of local-AI MVP critical path                |

## 4.2 Current material provider flow

> Current upstream seam
> >
> > VideoParams.video_source
> >
> > |
> >
> > v
> >
> > app/services/task.py
> >
> > _prepare / download materials
> >
> > |
> >
> > v
> >
> > material.download_videos(...)
> >
> > |
> >
> > +-----+-------------------------------+
> >
> > | stock search |
> >
> > | pexels / pixabay / coverr |
> >
> > +---------------------------------------+
> >
> > | remote AI on-demand |
> >
> > | wavespeed / seedance / ofox / muapi |
> >
> > | metaso / loomloom |
> >
> > +---------------------------------------+
> >
> > | AI image / local files |
> >
> > +---------------------------------------+
> >
> > |
> >
> > v
> >
> > List[local material paths]
> >
> > |
> >
> > v
> >
> > preprocess / combine / final render

The target local providers should terminate at the same boundary: they must return validated local MP4 paths to the existing compositor. The final renderer should not know or care whether a clip came from Pexels, an API, Wan or LTX. This keeps the integration small and testable.

## 4.3 Current task concurrency implication

The WebUI task manager is intentionally serialized at max_concurrent_tasks=1 because Streamlit runtime configuration is process-global. The API task manager can be configured for higher concurrency and optionally backed by Redis. Local AI video therefore needs its own GPU semaphore/lock regardless of the outer task manager. Without that guard, concurrent API tasks could each try to load or execute a heavyweight model and trigger GPU OOM. \[R4\]

## 4.4 Gaps between upstream and target system

- Upstream AI-video sources are primarily remote services; there is no first-class in-process local Wan/LTX provider.

- video_terms are optimized for material search and are not guaranteed to be cinematic scene prompts with camera/action/continuity instructions.

- Remote provider recovery tracks provider task IDs, while local inference needs scene-level checkpoints, model fingerprints and local clip validation.

- Upstream material selection is duration-oriented; high-quality local generation needs stronger mapping between narration segments and generated scenes.

- Upstream concurrency does not enforce a global GPU resource policy across multiple local video model families.

- A full scene regeneration/review experience is not the first-class center of the current UI, although task history and material controls provide a foundation.

# 5. Target System Scope

## 5.1 MVP in scope

- Fork MoneyPrinterTurbo and preserve upstream stock, local-file, AI-image, TTS, caption, BGM, render, API, CLI and optional publishing behavior.

- Add self-hosted Wan 2.2 TI2V-5B as a local AI Video source.

- Add self-hosted LTX 2.5 as a second local AI Video source, with Fast/Distilled and Quality/DFR modes subject to license and GPU validation.

- Generate scene-grade visual prompts from the script/narration, not only stock-search keywords.

- Persist a scene plan and local generation manifest inside each task directory.

- Generate clips sequentially or under a configurable GPU concurrency limit, reuse the loaded model runtime across scenes, and safely evict another model family when switching.

- Validate every generated clip before publishing it to the rest of the pipeline.

- Reuse complete valid clips on retry/restart and regenerate only missing/invalid scenes.

- Expose provider configuration, preflight status, generation mode, scene progress and useful errors in the existing WebUI/API/CLI.

- Keep final video creation through MoneyPrinterTurbo's existing narration/caption/music/render pipeline.

## 5.2 Deferred / explicitly out of MVP

- A Premiere/CapCut/DaVinci-style full multi-track non-linear editor.

- Multi-user accounts, cloud collaboration, permissions and billing.

- Distributed multi-node GPU scheduling or Kubernetes orchestration.

- Training or fine-tuning Wan/LTX models.

- Automatic model downloading during a generation job.

- Using LTX native synchronized audio in the initial integration; MoneyPrinter narration remains authoritative in MVP.

- Advanced SFX timeline editing beyond what upstream currently provides.

- Replacing MoviePy/FFmpeg solely for architectural preference without measured bottlenecks.

- Social analytics/scheduling improvements; existing publication features may remain but are not an MVP dependency.

## 5.3 Later strategic scope

- Factual-content research/evidence mode and automated claim review, ported selectively from the existing Content Factory prototype.

- Scene review/regeneration UI with thumbnail strip, prompt editing, seed variation and asset version selection.

- Optional native/hybrid LTX audio modes after visual-generation quality is proven.

- Dedicated GPU worker process/service and multi-GPU resource scheduling.

- A separate React/Next.js editing frontend using the MoneyPrinterTurbo API if Streamlit becomes the UX bottleneck.

# 6. Stakeholders and User Journeys

## 6.1 Primary stakeholders

| **Stakeholder**    | **Needs**                                                                                                       |
|--------------------|-----------------------------------------------------------------------------------------------------------------|
| Creator / operator | Enter topic/script, choose local model and style, see progress, get final video without managing provider APIs. |
| Power user         | Control model, mode, clip duration, aspect, seed behavior, prompts, TTS/captions/BGM and retry/regeneration.    |
| Developer          | Clear provider contracts, CPU-testable integrations, minimal upstream conflicts, reproducible task artifacts.   |
| System operator    | Predictable GPU memory use, model preflight, logs, disk cleanup, queue limits and recoverable failures.         |
| Product owner      | Low recurring generation cost, model portability, high-quality original footage, future commercial flexibility. |

## 6.2 Core user journey - local AI short

1. User opens MoneyPrinterTurbo WebUI and enters a topic or supplies a full script.

1. User chooses aspect (normally 9:16), narration voice, captions/BGM and Local AI Video -\> Wan 2.2 or LTX 2.5.

1. System performs provider preflight before starting expensive work: model/checkpoint paths, required packages, CUDA/device availability, writable task directory and FFmpeg.

1. System produces/accepts the script, generates narration and measures its actual duration.

1. Scene planner segments narration into practical visual beats and generates a detailed prompt for each scene.

1. Local provider loads the selected model once and generates scene clips one by one, persisting each completed validated clip immediately.

1. System reuses MoneyPrinterTurbo to normalize/assemble clips, add narration, captions, BGM/transitions and encode the final MP4.

1. User receives final video and task assets. A retry only regenerates failed/missing scenes.

## 6.3 Core user journey - scene retry/regeneration

1. User or system identifies Scene N as failed or visually unacceptable.

1. User changes only Scene N prompt/seed/mode, or selects Regenerate variation.

1. System retains all other scene clips and all source assets.

1. Provider generates a new versioned Scene N clip; the previous version remains available until cleanup policy removes old versions.

1. System reruns only composition/final render after successful replacement.

# 7. Functional Requirements

> Requirement notation
> >
> > "Must" items define the MVP release gate. "Should" items are expected in the first production-quality iteration unless a documented trade-off defers them. "Could" items are intentionally non-blocking. Requirement IDs are stable references for implementation issues, tests and acceptance evidence.

## 7.1 Workflow and project inputs

**FR-001 - Topic and script input**

**Requirement:** The system shall accept a topic/niche and shall also accept a complete user-supplied script that bypasses script generation.

**Rationale:** Supports both automatic and controlled creation.

**Acceptance (Must):** A task can be created from either input path and both reach the same downstream scene/video workflow.

**FR-002 - Output aspect selection**

**Requirement:** The system shall preserve MoneyPrinterTurbo aspect options 9:16, 16:9 and 1:1 and use the chosen aspect when requesting/generating local AI clips.

**Rationale:** Avoids a separate local-provider format model.

**Acceptance (Must):** A generated task uses the requested aspect and final output dimensions remain consistent with upstream behavior.

**FR-003 - Video source selection**

**Requirement:** The WebUI/API/CLI shall expose local Wan and local LTX as AI Video sources without removing existing stock/remote/local sources.

**Rationale:** Keeps upstream capabilities and enables gradual adoption.

**Acceptance (Must):** Existing sources still work; new sources appear in the AI Video group and serialize in task params.

**FR-004 - No paid-video API dependency**

**Requirement:** When a local AI source is selected, the material generation stage shall not call Pexels/Pixabay or any paid video-generation API.

**Rationale:** Core product cost/privacy goal.

**Acceptance (Must):** Network inspection or mocks show no stock/remote video provider call during local AI generation.

**FR-005 - Task artifact ownership**

**Requirement:** All locally generated scene clips and manifests shall be stored under the MoneyPrinterTurbo task/project directory or a configured safe material directory.

**Rationale:** Required for recovery and portability.

**Acceptance (Must):** Completed task contains scene assets and manifests using safe task-scoped paths.

**FR-006 - Existing pipeline compatibility**

**Requirement:** Local AI clips shall enter the same downstream preprocess/composition path used by other MoneyPrinterTurbo materials.

**Rationale:** Minimizes fork and rendering risk.

**Acceptance (Must):** Final video is produced without a local-provider-specific final renderer.

**FR-007 - Existing source fallback**

**Requirement:** The system shall retain stock footage and local uploads as optional material sources.

**Rationale:** Operational fallback and upstream compatibility.

**Acceptance (Must):** User can choose upstream sources independently of local model setup.

**FR-008 - Optional existing publishing**

**Requirement:** Existing MoneyPrinterTurbo publishing integrations shall remain available but shall not be required to create or export a final MP4.

**Rationale:** Separates generation from distribution.

**Acceptance (Must):** Local AI task completes with publishing disabled.

## 7.2 Script and scene planning

**FR-010 - Measured narration timing**

**Requirement:** The system shall base required visual duration on actual narration audio duration when narration is enabled.

**Rationale:** Prevents large timing drift.

**Acceptance (Must):** Scene durations sum to cover the measured narration duration within the configured tolerance.

**FR-011 - Scene segmentation**

**Requirement:** The system shall split the script/narration into ordered visual scenes instead of treating all video_terms as interchangeable search keywords.

**Rationale:** AI video quality depends on coherent prompts and order.

**Acceptance (Must):** scene_plan.json contains ordered scene IDs, narration/text segment, prompt and target duration.

**FR-012 - Scene duration policy**

**Requirement:** The planner shall constrain scene target duration to provider-supported practical bounds and shall prefer splitting scenes over strongly slowing a short generated clip.

**Rationale:** Avoids slow-motion artifacts and invalid model requests.

**Acceptance (Must):** Wan plan normally targets approximately 4-5 second clips; requests outside provider bounds are split or explicitly normalized.

**FR-013 - Cinematic prompt generation**

**Requirement:** Each AI scene shall have a generation prompt that includes subject/action, environment, composition/camera, motion, visual style, continuity and no-text/logo guidance where appropriate.

**Rationale:** Search keywords are insufficient for T2V.

**Acceptance (Must):** Prompt examples meet the structured prompt contract and are not only 1-3 keyword terms.

**FR-014 - Prompt continuity**

**Requirement:** The planner should provide recurring-subject/visual continuity guidance between scenes.

**Rationale:** Reduces obvious multi-scene identity/style drift.

**Acceptance (Should):** Consecutive prompts include shared subject/style constraints when the script requires continuity.

**FR-015 - User instructions**

**Requirement:** User-provided style/direction shall be incorporated into scene prompts without overriding safety/system constraints.

**Rationale:** Creative control.

**Acceptance (Must):** Prompt output visibly reflects style instructions.

**FR-016 - Prompt preview**

**Requirement:** The WebUI should let the user inspect generated scene prompts before or after generation.

**Rationale:** Provides control over expensive GPU work.

**Acceptance (Should):** Scene prompts are readable in task UI/history or exported manifest.

**FR-017 - Prompt edit/regenerate**

**Requirement:** The system should support editing one scene prompt and regenerating only that scene.

**Rationale:** Key iterative workflow.

**Acceptance (Should):** A scene change produces one new video clip and reuses other scene assets.

**FR-018 - Deterministic metadata**

**Requirement:** Every scene shall persist provider, model/mode, prompt, target duration, actual duration, seed and output asset path.

**Rationale:** Reproducibility and debugging.

**Acceptance (Must):** generation_manifest.json contains these fields for every completed scene.

## 7.3 Local AI video providers

**FR-020 - Wan local provider**

**Requirement:** The system shall provide a Wan 2.2 TI2V-5B local provider using official/local model assets supplied by the operator.

**Rationale:** Primary practical local T2V path.

**Acceptance (Must):** A GPU integration test generates a valid local MP4 without a remote generation API.

**FR-021 - LTX local provider**

**Requirement:** The system shall provide an LTX 2.5 local provider behind the same material contract.

**Rationale:** Second model choice and quality/speed trade-off.

**Acceptance (Must):** A configured GPU integration test generates a valid local MP4 and downstream render succeeds.

**FR-022 - LTX Fast mode**

**Requirement:** LTX provider shall support the official Distilled/Fast path.

**Rationale:** Iteration speed.

**Acceptance (Must):** User/config can select Fast and manifest records the mode.

**FR-023 - LTX Quality mode**

**Requirement:** LTX provider should support DFR production-quality mode including required detailing resources.

**Rationale:** Higher final quality where hardware/license permit.

**Acceptance (Should):** Preflight validates DFR-specific assets and generates through DFR when selected.

**FR-024 - Provider preflight**

**Requirement:** Before queueing expensive work, each local provider shall validate model paths, critical checkpoint files, Python dependencies, CUDA/device availability and writable output.

**Rationale:** Fail early rather than after script/TTS/GPU cost.

**Acceptance (Must):** Missing setup returns a provider-specific actionable error without starting video inference.

**FR-025 - No model download in task**

**Requirement:** Generation jobs shall not silently download heavyweight video checkpoints.

**Rationale:** Predictable operations/security/disk.

**Acceptance (Must):** Missing weights fail preflight with setup instructions.

**FR-026 - Video-only Wan output**

**Requirement:** Wan TI2V output shall be treated as video-only for MVP; narration remains the authoritative audio track.

**Rationale:** Avoids false native-audio semantics.

**Acceptance (Must):** Wan clip normalization strips/ignores model audio and final audio comes from selected narration/BGM pipeline.

**FR-027 - LTX audio policy**

**Requirement:** LTX native synchronized audio shall be ignored/disabled in MVP unless an explicit future audio mode is enabled.

**Rationale:** Keeps one consistent audio model initially.

**Acceptance (Must):** Final MVP audio matches MoneyPrinter narration/BGM regardless of raw LTX audio capability.

**FR-028 - Provider registry direction**

**Requirement:** Local AI providers should implement a common provider protocol/registry rather than adding unlimited special cases to core code.

**Rationale:** Long-term extensibility.

**Acceptance (Should):** A third fake provider can be registered in tests without changing composer code.

**FR-029 - Media validation**

**Requirement:** Every generated clip shall be validated for decodable video, non-zero duration and usable dimensions before being marked complete.

**Rationale:** Stops corrupt assets from reaching render.

**Acceptance (Must):** Invalid/empty clip never becomes active material and scene is marked failed.

## 7.4 GPU/runtime management

**FR-030 - Persistent model runtime**

**Requirement:** A local provider shall load its heavyweight runtime once per worker/process and reuse it across scenes in the same provider family.

**Rationale:** Model load cost is too high per scene.

**Acceptance (Must):** Instrumentation shows one model build/load for multiple scene generations.

**FR-031 - GPU serialization**

**Requirement:** A global GPU lock/semaphore shall prevent incompatible heavyweight local video generations from running concurrently on one configured GPU by default.

**Rationale:** Avoids OOM and nondeterministic crashes.

**Acceptance (Must):** Concurrent API tasks queue at GPU boundary rather than loading two runtimes simultaneously.

**FR-032 - Model family switching**

**Requirement:** Switching between Wan and LTX shall unload/evict the previous heavyweight runtime before loading the next family, unless an operator explicitly configures enough GPU capacity for coexistence.

**Rationale:** VRAM safety.

**Acceptance (Must):** Provider-switch test calls eviction and next provider can initialize.

**FR-033 - Configurable device**

**Requirement:** The operator shall be able to select CUDA device/index using configuration/environment settings.

**Rationale:** Supports workstation and rental GPU setups.

**Acceptance (Must):** Provider reports and uses configured device.

**FR-034 - Seed handling**

**Requirement:** Scene generation shall support deterministic base seed plus scene-specific offset and user variation.

**Rationale:** Reproducibility and regeneration.

**Acceptance (Must):** Same provider/settings/seed can be re-requested; variation produces a new recorded seed.

**FR-035 - Progress by scene**

**Requirement:** Task status/logs shall report local generation progress at scene granularity (for example Scene 3/12).

**Rationale:** Long inference needs observability.

**Acceptance (Must):** WebUI/API task status shows current scene and total scene count.

**FR-036 - Cancellation boundary**

**Requirement:** Cancellation shall be honored between scenes and before final composition; mid-inference interruption may be provider-dependent.

**Rationale:** Safe cancellation without corrupting runtime.

**Acceptance (Must):** Cancel request prevents the next scene from starting and task reaches cancelled/failed terminal state.

**FR-037 - OOM handling**

**Requirement:** GPU OOM shall be caught, reported with provider/model/mode context, and shall not mark incomplete output as valid.

**Rationale:** Operational safety.

**Acceptance (Must):** Synthetic/real OOM produces actionable failure and preserves completed scenes.

**FR-038 - GPU telemetry**

**Requirement:** The system should log provider/model load time, scene generation duration and, where available, GPU memory usage.

**Rationale:** Required for later cost/performance tuning.

**Acceptance (Should):** Metrics appear in task logs/manifest without leaking secrets.

## 7.5 Assets, caching and recovery

**FR-040 - Scene manifest**

**Requirement:** Each local AI task shall write a machine-readable generation_manifest.json (or equivalent) before/while generating scenes.

**Rationale:** Crash-safe progress record.

**Acceptance (Must):** Manifest updates atomically as each scene becomes complete.

**FR-041 - Atomic scene publication**

**Requirement:** A generated scene shall be written to a temporary/versioned path, validated, then atomically promoted/recorded as active.

**Rationale:** Avoids half-written clips after crashes.

**Acceptance (Must):** Interrupted generation never leaves a partial file referenced as complete.

**FR-042 - Retry reuse**

**Requirement:** Retrying a task shall reuse all valid scene clips whose generation inputs still match.

**Rationale:** Avoids wasting GPU time.

**Acceptance (Must):** Failed Scene 7 of 12 causes retry to resume at Scene 7, not Scene 1.

**FR-043 - Input fingerprint**

**Requirement:** The system shall compute a generation fingerprint from provider/model version or model fingerprint, prompt, seed, duration, aspect and important generation settings.

**Rationale:** Safe cache invalidation.

**Acceptance (Must):** Changing prompt or mode invalidates that scene; changing subtitle style does not.

**FR-044 - Versioned regeneration**

**Requirement:** Regenerating a scene shall not immediately destroy its previous valid clip.

**Rationale:** Allows comparison/recovery.

**Acceptance (Should):** At least the current and previous scene version remain until cleanup policy runs.

**FR-045 - Project-local default cache**

**Requirement:** Generated clips shall be reused within the same task/project by default; cross-project cache reuse shall be optional.

**Rationale:** Avoids unwanted repeated visuals across videos.

**Acceptance (Must):** Default does not substitute another task's clip solely because prompt hash matches.

**FR-046 - Disk cleanup**

**Requirement:** The operator shall have a policy for temporary raw generations, old scene versions and completed task retention.

**Rationale:** Model/video assets can consume large disk space.

**Acceptance (Must):** Configurable cleanup removes only unreferenced/expired assets and never deletes active final/task files.

**FR-047 - Asset source metadata**

**Requirement:** MoneyPrinter task artifacts should identify local AI provider and generation settings rather than presenting generated footage as public-stock material.

**Rationale:** Provenance and debugging.

**Acceptance (Must):** Material source records label provider as wan22_local/ltx25_local and include safe metadata.

**FR-048 - Restart validation**

**Requirement:** On process restart/retry, previously completed scene files shall be re-probed before reuse.

**Rationale:** Protects against corruption/manual deletion.

**Acceptance (Must):** Missing/corrupt clip is regenerated; valid clip is reused.

## 7.6 Audio and captions

**FR-050 - Narration provider reuse**

**Requirement:** The system shall reuse MoneyPrinterTurbo TTS providers, including self-hosted/local choices such as configured Kokoro, rather than implementing a separate mandatory narration stack.

**Rationale:** Avoids duplicate functionality.

**Acceptance (Must):** Local AI video can be combined with any upstream-compatible narration provider.

**FR-051 - No-voice mode**

**Requirement:** Existing no-voice/custom-audio modes shall remain compatible with local AI video.

**Rationale:** Preserve upstream use cases.

**Acceptance (Must):** Local AI task can render with no generated TTS when configured.

**FR-052 - Caption reuse**

**Requirement:** Existing MoneyPrinterTurbo subtitle generation and styling shall remain the default caption system.

**Rationale:** Mature upstream feature.

**Acceptance (Must):** Local AI video task produces captions with upstream settings.

**FR-053 - Whisper compatibility**

**Requirement:** faster-whisper based caption timing shall remain usable with local AI video.

**Rationale:** Local timing option.

**Acceptance (Must):** Configured Whisper captions are generated from narration audio, independent of material provider.

**FR-054 - BGM reuse**

**Requirement:** Existing background-music selection/generation/mixing shall work unchanged with local AI footage.

**Rationale:** Avoids reimplementing audio composition.

**Acceptance (Must):** Local AI final render includes configured BGM at expected level.

**FR-055 - Audio/video duration reconciliation**

**Requirement:** The final composer shall trim/loop/sequence visual material so the final video covers narration duration without unexpected black frames.

**Rationale:** Core output integrity.

**Acceptance (Must):** Final duration is within configured tolerance of narration/output target.

**FR-056 - Future native audio gate**

**Requirement:** Any future LTX native/hybrid audio mode shall be an explicit user setting, never an implicit side effect of selecting LTX.

**Rationale:** Avoids accidental mixed/doubled audio.

**Acceptance (Must):** MVP exposes no ambiguous native-audio behavior.

**FR-057 - Audio clipping control**

**Requirement:** Final audio mixing should preserve existing limiter/volume safeguards or equivalent behavior.

**Rationale:** Prevents distorted output.

**Acceptance (Should):** Regression media test detects no gross clipping introduced by local provider integration.

**FR-058 - Subtitle/content sync after scene retry**

**Requirement:** Replacing/regenerating visual clips shall not change narration/caption timing unless narration itself changes.

**Rationale:** Scene visuals should be independently replaceable.

**Acceptance (Should):** Visual-only regeneration triggers composition only, not TTS/caption regeneration.

## 7.7 Rendering and outputs

**FR-060 - Final format compatibility**

**Requirement:** Final output shall preserve MoneyPrinterTurbo supported aspect/output codec behavior and produce a broadly playable MP4.

**Rationale:** User-facing compatibility.

**Acceptance (Must):** ffprobe verifies final video and expected audio streams/dimensions.

**FR-061 - Existing transitions**

**Requirement:** Existing MoneyPrinterTurbo transition modes shall remain applicable to local AI clips.

**Rationale:** Reuse editor capabilities.

**Acceptance (Must):** A local AI task renders with configured fade/slide/zoom transition mode without provider-specific code.

**FR-062 - Fit mode**

**Requirement:** Generated clips shall pass through existing cover/contain normalization where necessary.

**Rationale:** Provider output sizes may differ from final canvas.

**Acceptance (Must):** 720p provider clip can be composed to 1080x1920 final output correctly.

**FR-063 - Final rerender without inference**

**Requirement:** A completed local AI task shall be rerenderable from stored material for changes that do not alter AI-video generation inputs.

**Rationale:** Major cost/time requirement.

**Acceptance (Must):** Render-only test verifies no local video provider generate() call.

**FR-064 - Output package**

**Requirement:** The task shall expose final MP4 plus script, captions, scene plan, generation manifest and generated scene material paths.

**Rationale:** Developer/user auditability.

**Acceptance (Must):** Artifacts are discoverable from task directory/history.

**FR-065 - Task history**

**Requirement:** Local AI task status, warnings/errors and output paths shall appear in existing task history surfaces.

**Rationale:** Operational consistency.

**Acceptance (Must):** Completed/failed local task behaves like other MoneyPrinter tasks in history.

**FR-066 - Multiple output variants**

**Requirement:** Upstream video_count behavior may be retained, but local AI generation shall avoid unintentionally multiplying expensive unique clips unless requested.

**Rationale:** Cost/control.

**Acceptance (Should):** UI/API clearly communicates whether variants share or regenerate materials.

**FR-067 - Render isolation**

**Requirement:** Final composition failure shall not invalidate or delete already generated local scene clips.

**Rationale:** Allows cheap retry.

**Acceptance (Must):** Fixing renderer environment and retrying reuses scene clips.

## 7.8 WebUI experience

**FR-070 - AI Video group UI**

**Requirement:** Local Wan and LTX options shall appear under the existing AI Video group in WebUI.

**Rationale:** Fits upstream navigation.

**Acceptance (Must):** Source picker displays named local providers without breaking other groups.

**FR-071 - Provider settings UI**

**Requirement:** WebUI should provide local provider status/config guidance (paths/device/mode) without exposing secrets unnecessarily.

**Rationale:** Operator usability.

**Acceptance (Should):** User can identify missing checkpoint/CUDA setup from UI before generation.

**FR-072 - Preflight status**

**Requirement:** WebUI shall show actionable preflight errors rather than a generic generation failure.

**Rationale:** Reduces setup friction.

**Acceptance (Must):** Missing WAN22_CHECKPOINT error identifies the exact setting/file class.

**FR-073 - Scene progress UI**

**Requirement:** WebUI shall display current scene/total and stage while local generation runs.

**Rationale:** Long jobs need feedback.

**Acceptance (Must):** Status updates at least between scene completions.

**FR-074 - Prompt/scene view**

**Requirement:** WebUI should expose the scene plan and prompts for inspection.

**Rationale:** Expensive inference warrants transparency.

**Acceptance (Should):** User can read the prompt associated with each generated clip.

**FR-075 - Scene regeneration control**

**Requirement:** WebUI should expose single-scene regenerate/variation without rerunning the whole task.

**Rationale:** Core iterative value.

**Acceptance (Should):** One scene can be regenerated and final composition updated.

**FR-076 - No full NLE requirement**

**Requirement:** MVP WebUI shall not require a multi-track visual timeline editor to ship.

**Rationale:** Avoids scope explosion.

**Acceptance (Must):** All Must requirements can be completed through existing Streamlit patterns.

**FR-077 - Cost/runtime warning**

**Requirement:** UI should indicate that local AI generation is GPU-intensive and provider/mode affects runtime/memory.

**Rationale:** Expectation management.

**Acceptance (Should):** Provider help text is visible before run.

**FR-078 - Model/license notice**

**Requirement:** UI or documentation shall make model-specific license terms discoverable, particularly LTX commercial thresholds.

**Rationale:** Compliance awareness.

**Acceptance (Must):** Docs link to relevant model licenses and recorded model choice.

## 7.9 API, CLI and configuration

**FR-080 - API compatibility**

**Requirement:** Existing video generation API shall accept local video_source values with additive optional settings.

**Rationale:** Automation support.

**Acceptance (Must):** API task can select local provider and existing clients remain valid.

**FR-081 - CLI compatibility**

**Requirement:** CLI shall support the local sources and relevant mode/seed options.

**Rationale:** Headless/rental GPU operation.

**Acceptance (Must):** Documented CLI command completes preflight and task submission.

**FR-082 - Config separation**

**Requirement:** Checkpoint/repository paths and device settings shall be server/operator configuration, not embedded in public task payloads.

**Rationale:** Security/portability.

**Acceptance (Must):** Task history does not expose arbitrary host filesystem paths beyond safe diagnostic identifiers.

**FR-083 - Stable provider identifiers**

**Requirement:** Provider IDs shall be stable strings, recommended wan22_local and ltx25_local, and shall be preserved in task history/manifests.

**Rationale:** Compatibility.

**Acceptance (Must):** Historical task can be interpreted after UI label changes.

**FR-084 - Backward compatibility**

**Requirement:** Tasks/presets using existing video_source values shall continue to validate.

**Rationale:** Fork upgrade safety.

**Acceptance (Must):** Upstream test suite passes without migrations for old providers.

**FR-085 - Health/preflight API**

**Requirement:** A provider-preflight endpoint or equivalent callable should report readiness without creating a generation task.

**Rationale:** Deployment verification.

**Acceptance (Should):** Operator can check model readiness independently.

**FR-086 - Structured local provider errors**

**Requirement:** API errors shall identify failed stage, provider, scene where applicable, and recoverability.

**Rationale:** Automation/debugging.

**Acceptance (Must):** Failed scene response/state includes provider and scene ID without secrets.

**FR-087 - No secret persistence**

**Requirement:** API keys, access tokens or private credentials shall not be written into generation manifests/logs.

**Rationale:** Security.

**Acceptance (Must):** Secret-scanning tests/log review show redaction; local model paths are handled according to configured visibility.

## 7.10 Optional factual-content evolution

**FR-090 - Factual mode - optional research**

**Requirement:** A later factual-content mode may obtain an evidence pack before scripting; creative mode shall not require research.

**Rationale:** Reuses valuable Content Factory work without blocking MVP.

**Acceptance (Could):** Feature flag/mode can be added without changing local video provider contract.

**FR-091 - Factual claim review**

**Requirement:** A later evidence-review gate may validate/rewrite factual narration before expensive video generation.

**Rationale:** Avoids generating footage for unsupported claims.

**Acceptance (Could):** When enabled, review occurs before local video inference.

**FR-092 - Research independence**

**Requirement:** Research/claim-review features shall be independent of visual provider selection.

**Rationale:** Avoids coupling.

**Acceptance (Could):** Wan/LTX/stock all receive the same approved script/scene plan.

# 8. Non-Functional Requirements

| **ID**  | **Quality attribute** | **Requirement**                                                                                                                    | **Priority** |
|---------|-----------------------|------------------------------------------------------------------------------------------------------------------------------------|--------------|
| NFR-001 | Reliability           | A failed scene or renderer stage must not destroy completed valid scene assets.                                                    | Must         |
| NFR-002 | Recoverability        | Retry/restart must reconstruct progress from persisted task/scene state, not only process memory.                                  | Must         |
| NFR-003 | GPU safety            | Default local video inference concurrency per GPU is 1 unless explicitly overridden after validation.                              | Must         |
| NFR-004 | Performance           | Heavy model runtime is cached across scenes; model initialization must not occur per clip.                                         | Must         |
| NFR-005 | Responsiveness        | WebUI request submission must return promptly and not block the browser for the full generation duration.                          | Must         |
| NFR-006 | Observability         | Logs identify task, provider, scene, stage and elapsed time; secrets are redacted.                                                 | Must         |
| NFR-007 | Portability           | Local model paths/device/settings are configurable for workstation, Codespace-like dev (CPU tests only), and rental GPU hosts.     | Must         |
| NFR-008 | Maintainability       | Core upstream modifications are minimized and protected by regression tests.                                                       | Must         |
| NFR-009 | Extensibility         | Provider-specific inference does not leak into final rendering/composition APIs.                                                   | Must         |
| NFR-010 | Compatibility         | Existing MoneyPrinterTurbo providers and saved parameters remain valid where upstream supports them.                               | Must         |
| NFR-011 | Testability           | All provider orchestration/cache/state logic has CPU-safe fake-provider tests; GPU tests are separate.                             | Must         |
| NFR-012 | Media integrity       | Generated and final media are ffprobe/decoder validated before completion status.                                                  | Must         |
| NFR-013 | Security              | Untrusted upload/material paths remain restricted to safe directories; no new arbitrary-path HTTP exposure is introduced.          | Must         |
| NFR-014 | Privacy               | Fully local mode can operate without sending script/prompts/video to a remote video-generation service.                            | Must         |
| NFR-015 | License traceability  | Task manifest records model/provider choice; documentation preserves third-party notices and license links.                        | Must         |
| NFR-016 | Disk control          | Temporary and versioned assets follow bounded retention/cleanup rules.                                                             | Must         |
| NFR-017 | Graceful degradation  | A missing local GPU/model affects only local AI sources; stock/local-upload sources remain usable.                                 | Must         |
| NFR-018 | Error quality         | Setup errors are actionable and mention the failing configuration/dependency without exposing credentials.                         | Must         |
| NFR-019 | Determinism           | Seed and generation settings are persisted sufficiently to attempt reproduction on the same model version.                         | Should       |
| NFR-020 | Accessibility         | New WebUI controls use labels/help text and do not rely only on color for status.                                                  | Should       |
| NFR-021 | Internationalization  | New user-facing strings should follow MoneyPrinterTurbo translation patterns rather than English-only hardcoding.                  | Should       |
| NFR-022 | Scalability path      | Architecture allows later extraction of local inference into a GPU worker without rewriting scene/manifests/composer.              | Should       |
| NFR-023 | Throughput safety     | API queue bounds prevent unbounded accumulation of GPU-heavy jobs.                                                                 | Must         |
| NFR-024 | Deployment security   | Public API deployment should use existing x-api-key/auth controls and should not expose model file directories.                    | Must         |
| NFR-025 | Code quality          | New Python code follows upstream Ruff/typing/test conventions and does not reduce configured coverage below the project threshold. | Must         |

# 9. Target Architecture

## 9.1 Recommended architecture - extend, do not replace

**Recommended logical architecture**

```text
+--------------------------------------------------------------+

| MoneyPrinterTurbo |

| WebUI (Streamlit) | FastAPI | CLI | Agent |

+-----------------------------+--------------------------------+

| VideoParams

v

+--------------------------------------------------------------+

| Task Orchestrator |

| script -> TTS -> measured duration -> scene planning |

+-----------------------------+--------------------------------+

| ScenePlan[]

v

+--------------------------------------------------------------+

| Material Provider Registry / Adapter Boundary |

| |

| Stock: Pexels / Pixabay / Coverr |

| Remote AI: existing upstream providers |

| Local: local files |

| NEW Local AI: |

| - wan22_local -> WanLocalProvider |

| - ltx25_local -> LTXLocalProvider |

+-----------------------------+--------------------------------+

| validated local MP4 paths

v

+--------------------------------------------------------------+

| Existing MPT media pipeline |

| preprocess -> concat -> transitions -> narration -> captions |

| -> BGM -> final encode |

+-----------------------------+--------------------------------+

|

v

final.mp4 + task assets + manifests
```

## 9.2 New modules - proposed

| **Module**                          | **Responsibility**                                                                   |
|-------------------------------------|--------------------------------------------------------------------------------------|
| app/services/local_ai/base.py       | Provider protocol, shared scene/generation result types, fingerprint utilities.      |
| app/services/local_ai/wan22.py      | Wan configuration validation, persistent runtime, generation, output normalization.  |
| app/services/local_ai/ltx25.py      | LTX Fast/DFR validation, runtime, generation, audio stripping policy, normalization. |
| app/services/local_ai/runtime.py    | GPU semaphore/lock, active runtime family, eviction, optional telemetry.             |
| app/services/scene_planner.py       | Convert narration/script into ordered SceneSpec objects and cinematic prompts.       |
| app/services/generation_manifest.py | Atomic manifest load/save, asset fingerprints, scene status/version/recovery.        |
| test/services/test_local_ai\_\*.py  | CPU contract tests with fake runtimes/providers.                                     |

## 9.3 Minimal upstream touch points

- app/models/schema.py - add only additive request fields if needed (generation mode, base seed, prompt mode) and preserve defaults.

- app/services/material.py - register/dispatch local providers; avoid placing model inference implementation in this large file.

- app/services/task.py - invoke ScenePlan-aware path for local AI sources and publish progress; preserve other source behavior.

- webui/Main.py - add source labels/group entries and local-provider settings/help; follow existing translation/group patterns.

- config.example.toml - add local provider paths/device/mode defaults with no secrets/model weights.

- CLI/API validation - add the new stable source IDs and optional parameters.

- README/docs - local GPU setup, model licenses, minimum validated hardware, troubleshooting.

## 9.4 Provider contract (conceptual)

**Provider boundary (conceptual)**

```python
class LocalVideoProvider(Protocol):
    provider_id: str

    def preflight(self, config) -> ProviderStatus: ...
    def load_runtime(self) -> None: ...
    def generate(self, scene: SceneSpec, output: Path) -> GenerationResult: ...
    def validate_output(self, output: Path, scene: SceneSpec) -> None: ...
    def unload(self) -> None: ...

# Orchestration owns:
# - scene planning
# - cache/fingerprint decisions
# - task status/cancellation
# - final composition
# Provider owns model-specific inference only.
```

# 10. Scene Planning and Prompt Engineering

This is the main product-quality difference between simply wiring a model into download_videos() and building the intended system. Stock-video search terms such as "black hole space" are acceptable retrieval queries but weak generative prompts. The local-AI path must create a scene plan that aligns narration beats with provider-friendly duration and visual direction.

## 10.1 SceneSpec contract

| **Field**         | **Meaning / rule**                                                                      |
|-------------------|-----------------------------------------------------------------------------------------|
| scene_id          | Stable ordered integer/string within task.                                              |
| narration_segment | Exact or bounded script segment represented by this scene.                              |
| beat              | Hook/setup/build/reveal/payoff/ending or equivalent narrative purpose.                  |
| prompt            | Full visual generation prompt; model-neutral intent, with provider adaptation allowed.  |
| negative_prompt   | Optional provider-supported exclusions; otherwise absorbed into positive prompt policy. |
| target_duration   | Desired clip duration based on provider bounds and narration coverage.                  |
| aspect            | 9:16 / 16:9 / 1:1 from VideoParams.                                                     |
| continuity        | Subject/style/camera continuity notes inherited from project visual bible.              |
| seed              | Resolved deterministic scene seed.                                                      |
| provider_settings | Mode/steps/resolution/quality settings that materially affect output.                   |

## 10.2 Prompt construction rules

- State the visible subject and what it is doing; avoid abstract script restatement when a concrete visual can be generated.

- Specify environment/time/lighting only when it improves the intended shot.

- Specify shot scale and camera motion (for example close-up, tracking, slow push-in) without stacking contradictory camera commands.

- Use a project-level visual bible to keep recurring subject identity, palette and realism/stylization consistent.

- Do not ask the video model to render titles, captions, logos or on-screen explanatory text; captions remain a compositor responsibility.

- Avoid prompt inflation: provider adapters may truncate/reshape prompts, but the canonical SceneSpec should remain readable and auditable.

- Factual narration and visual prompts are separate: the image/video prompt may be illustrative but must not silently alter narration claims.

- For local providers, prompt expansion should prefer the already configured LLM/Ollama path rather than a paid external prompt-extension service by default.

## 10.3 Duration planning

For Wan TI2V-5B, the official model supports 720p at 24 fps and the current Content Factory adapter uses the standard 121-frame ceiling, approximately five seconds. The MVP should therefore design Wan scenes around roughly 4-5 seconds rather than routinely stretching a five-second motion clip to eight seconds. Longer narrative beats should be split into two related prompts/scenes. LTX may support different timing strategies, but the canonical planner should still prefer short, editable scenes.

| **Narration length** | **Preferred planning behavior**                                                                                      |
|----------------------|----------------------------------------------------------------------------------------------------------------------|
| \<= 20 s             | 4-5 scenes, strong hook, no filler.                                                                                  |
| 20-45 s              | 5-9 scenes, 4-7 s beats depending on provider.                                                                       |
| 45-90 s              | 9-18 scenes; GPU cost/runtime warning should be explicit.                                                            |
| 90-120 s             | High-cost local generation; scene density may be configurable, but quality mode should not silently reduce coverage. |

# 11. Local AI Video Provider Design

## 11.1 Wan 2.2 TI2V-5B

Wan2.2 is the recommended first implementation. The official repository describes the TI2V-5B model as a 5B high-compression text/image-to-video model supporting 720p at 24 fps and consumer-grade graphics cards such as the RTX 4090. The official run instructions/model ecosystem make it a practical single-GPU starting point compared with the much larger A14B path. The Wan-AI/Wan2.2-TI2V-5B model card identifies the license as Apache-2.0. \[R10\]

| **Wan design item** | **Requirement**                                                                                                                             |
|---------------------|---------------------------------------------------------------------------------------------------------------------------------------------|
| Configuration       | WAN22_REPO, WAN22_CHECKPOINT, optional CUDA device, seed, offload policy. Prefer server config/env, not task payload.                       |
| Preflight           | Validate official checkout, checkpoint index/shards, T5 encoder/tokenizer/VAE, packages and CUDA.                                           |
| Runtime             | Cache one Wan pipeline per worker/device/model fingerprint.                                                                                 |
| Generation          | Use SceneSpec.prompt, provider-supported 720p portrait/landscape size, scene seed, practical frame count.                                   |
| Output              | Write raw temporary clip, validate, normalize to H.264/yuv420p or a MoneyPrinter-compatible input, remove raw temporary file after success. |
| Audio               | Treat clip as video-only in MVP. MoneyPrinter TTS/BGM remains authoritative.                                                                |
| Recovery            | Manifest marks scene complete only after validation and atomic publication.                                                                 |

## 11.2 LTX 2.5

LTX 2.5 is recommended as the second provider, not the first integration milestone. The official LTX repository provides a Distilled pipeline for fast inference and DFR for production-quality refinement. LTX also supports synchronized audio/video, but the MVP should intentionally ignore model-native audio to keep the MoneyPrinter narration pipeline stable. \[R11\]

> LTX licensing gate
> >
> > LTX 2.5 releases since 11 Aug 2026 are governed by the LTX-2.x Community License. The license grants broad use subject to restrictions but states that entities with annual revenue of at least USD 10,000,000 require a paid license for commercial use (except the defined non-commercial cases). Product launch/commercial deployment must include a license review. This specification is not legal advice. [R11]

| **LTX mode**          | **Use case**                                  | **Implementation expectation**                                                              |
|-----------------------|-----------------------------------------------|---------------------------------------------------------------------------------------------|
| Fast / Distilled      | Drafts, iteration, faster scene regeneration  | Persistent DistilledPipeline; recorded mode/seed/settings.                                  |
| Quality / DFR         | Final-quality production after GPU validation | Same base components plus required detailing IC-LoRA/refinement assets; stricter preflight. |
| Native audio (future) | Character dialogue / environmental audio      | Deferred until explicit audio routing exists; not automatic in MVP.                         |

## 11.3 Provider selection rule

The product should not claim one model is universally superior before real GPU output is evaluated. Wan is selected first for integration practicality and licensing simplicity; LTX provides a second quality/speed family. A later GPU benchmark should compare identical scene prompts, record generation time/VRAM/artifacts, and tune the default based on measured output rather than model marketing.

# 12. GPU Runtime and Job Execution

## 12.1 Single-host MVP topology

**MVP deployment topology**

```text
Browser / API Client

|

v

MoneyPrinterTurbo process

- WebUI / FastAPI / CLI

- task manager + task state

- script/TTS/captions

- final MoviePy/FFmpeg render

|

v

Global Local-AI GPU Runtime Manager

[GPU semaphore = 1 by default]

|

+---+---+

| |

Wan LTX

(runtime family cached; incompatible family evicted)

|

v

Task-scoped generated scene MP4s
```

## 12.2 Why a separate GPU lock is required

MoneyPrinterTurbo WebUI is currently serialized, but its API can run multiple tasks according to max_concurrent_tasks and may use Redis. Local AI inference must therefore enforce resource safety below the outer task manager. The provider runtime manager is the authority for GPU occupancy. This is also the clean seam for a later dedicated GPU-worker service.

## 12.3 Runtime lifecycle

1. Preflight resolves selected provider/model/device before video generation.

1. Acquire GPU generation semaphore before loading/switching heavyweight runtime.

1. If active runtime family matches and fingerprint is valid, reuse it.

1. If provider family changes, unload old runtime, release references, request CUDA cache cleanup where appropriate, then load new runtime.

1. Generate one scene, write/validate/publish asset, update manifest, then continue while retaining runtime.

1. Release generation semaphore when task leaves local inference stage; keep runtime resident if policy allows for future tasks.

1. On fatal CUDA/runtime corruption, mark runtime unhealthy and force unload/rebuild on next attempt.

## 12.4 Future split-worker topology

If multiple users or GPUs become a requirement, local inference can move behind an internal worker API or durable queue. SceneSpec and GenerationResult contracts should be designed now so this extraction does not change MoneyPrinter's script/composition layers. The MVP should not introduce distributed infrastructure before a real throughput requirement exists.

# 13. Data, Assets, Caching and Recovery

## 13.1 Proposed task asset layout

**Conceptual task layout - adapt to exact upstream task paths**

```text
task/<task_id>/

script.json # existing/upstream task content

scene_plan.json # NEW canonical scene plan

generation_manifest.json # NEW local AI state/fingerprints

generated_ai/

scene-001/

v001.mp4

v002.mp4 # regeneration versions

scene-002/v001.mp4

audio/... # upstream behavior

subtitles/... # upstream behavior

final-1.mp4 # upstream task output naming as applicable

logs / task history state
```

## 13.2 Manifest state machine

| **State**  | **Meaning**                                                 | **Allowed next states**                     |
|------------|-------------------------------------------------------------|---------------------------------------------|
| planned    | Scene has prompt/duration/seed but no valid clip.           | generating, cancelled                       |
| generating | Provider is actively producing a temporary asset.           | ready, failed, cancelled                    |
| ready      | Validated active clip exists and input fingerprint matches. | generating (explicit regeneration), invalid |
| failed     | Scene attempt failed; prior ready version may still exist.  | generating, cancelled                       |
| invalid    | Referenced file failed validation or disappeared.           | generating                                  |
| cancelled  | Task stopped before next scene.                             | generating on explicit retry                |

## 13.3 Fingerprint policy

The generation fingerprint must include every value that can materially change the generated visual: provider ID, model/checkpoint fingerprint or configured model version, mode, canonical prompt, negative prompt if used, seed, requested duration/frame count, aspect/resolution and provider-specific sampling settings. It must exclude unrelated rendering choices such as subtitle font or BGM volume. This is the key rule that lets render-only changes reuse expensive video assets safely.

## 13.4 Atomic writes and recovery

- Write manifest changes to a temporary file and replace atomically where the filesystem supports it.

- Generate into \*.partial or a versioned temporary file, validate, then rename/publish.

- Never set scene status=ready before media validation succeeds.

- On retry, inspect file existence and media validity even if manifest says ready.

- Do not delete previous ready version until the new version is validated and active.

- A final-render failure must not trigger video regeneration when scene fingerprints remain valid.

# 14. Audio, Captions, Music and Rendering

The architecture deliberately treats MoneyPrinterTurbo as the media-production shell. Local T2V providers supply visual material; they do not own narration, captions, BGM, transitions or final encoding. This separation is the main reason the integration remains manageable.

## 14.1 MVP audio policy

- Narration is generated through the existing MoneyPrinter TTS provider selected by the user.

- Wan generated clips contribute no audio to the final mix.

- LTX model-native audio is ignored/stripped in MVP unless a later explicit audio-mode design is implemented.

- Custom uploaded audio/no-voice upstream modes remain valid.

- Background music remains an upstream setting and is mixed during final composition.

- Captions are generated from script/TTS/Whisper through upstream logic and are not baked into generated scene clips.

## 14.2 Final composition invariants

| **Invariant**                                                | **Reason**                             |
|--------------------------------------------------------------|----------------------------------------|
| Visual clips are reusable independently of captions/BGM.     | Allows cheap rerenders.                |
| Final duration matches narration/target within tolerance.    | Prevents ending gaps/cutoffs.          |
| All final clips are normalized to composer-compatible media. | Avoids codec/pixel-format surprises.   |
| Transitions are applied by MoneyPrinter, not the T2V model.  | Keeps edit semantics provider-neutral. |
| Final MP4 validation runs before success state.              | Ensures download is playable.          |

## 14.3 When to consider renderer changes

Do not replace MoviePy because another renderer is theoretically faster. Profile real local-AI projects first. If final composition becomes a material bottleneck relative to multi-minute GPU generation, a later FFmpeg-first renderer can be introduced behind the same task/asset contracts. The MVP should spend engineering effort on generation quality, persistence and recovery.

# 15. WebUI, API and CLI Changes

## 15.1 WebUI changes

| **UI area**              | **Required change**                                                                                         |
|--------------------------|-------------------------------------------------------------------------------------------------------------|
| Video Source group       | Add Wan 2.2 Local and LTX 2.5 Local under AI Video.                                                         |
| Provider settings        | Show configured checkpoint/repo/device and a readiness check; never upload model weights through Streamlit. |
| LTX controls             | Mode: Fast/Distilled or Quality/DFR; disable Quality when required assets are missing.                      |
| Local AI common controls | Scene target duration/density (advanced), seed policy, optional prompt preview.                             |
| Task progress            | Stage + scene index/total + provider/model.                                                                 |
| Task details             | Scene prompts, seeds, generated clip paths/preview when practical, failure reason.                          |
| Regeneration (P1)        | Regenerate selected scene / seed variation, preserving old version.                                         |

## 15.2 API request additions - recommended minimal contract

**Illustrative additive request fields**

```text
{
"video_source": "wan22_local" | "ltx25_local",
"video_clip_duration": 5,
"local_ai_generation_mode": "fast" | "quality",
"local_ai_seed": 42,
"local_ai_prompt_mode": "scene_director"
}
# Host/model filesystem paths remain in server config, not request JSON.
```

## 15.3 API response/task state additions

- current_stage: planning \| local_ai_video \| composing \| complete \| failed

- scene_progress: {current, total, scene_id}

- local_ai_provider and generation_mode

- failed_scene_id where applicable

- recoverable flag / retry guidance where determinable

- artifact references for scene_plan and generation_manifest (subject to existing API-key/file protections).

## 15.4 CLI

CLI source validation must include wan22_local and ltx25_local. CLI should expose only portable generation controls; model paths/device remain config/environment. A headless GPU host should be able to run the entire generation workflow without WebUI.

# 16. Configuration and Deployment

## 16.1 Proposed configuration

**Illustrative configuration**

```toml
[app]

video_source = "wan22_local"

max_concurrent_tasks = 5

max_queued_tasks = 100



[local_ai]

gpu_device = 0

gpu_max_concurrent_generations = 1

keep_runtime_loaded = true

scene_target_seconds = 5

retain_scene_versions = 2



[wan22_local]

repo_path = "/opt/models/Wan2.2"

checkpoint_path = "/opt/models/Wan2.2-TI2V-5B"

seed = 42

offload_model = true



[ltx25_local]

config_path = "/opt/models/ltx-models.json"

default_mode = "fast"

seed = 42
```

## 16.2 Deployment profiles

| **Profile**                     | **Purpose**                                         | **Notes**                                                                       |
|---------------------------------|-----------------------------------------------------|---------------------------------------------------------------------------------|
| Developer CPU                   | Run WebUI/API and fake provider tests without CUDA. | Local real providers fail preflight cleanly; no model download.                 |
| Single GPU workstation          | Primary MVP development/validation.                 | WebUI/API + model runtimes on one host; generation semaphore 1.                 |
| Rental GPU host                 | Production-like generation without buying hardware. | Mount model cache and task output volume; use CLI/API; secure public ports.     |
| Split CPU + GPU worker (future) | Scale multiple users/tasks.                         | Requires internal authenticated worker protocol/queue; same SceneSpec contract. |

## 16.3 Hardware validation policy

The SRS must not claim real generation speed or exact VRAM consumption until measured on the target GPU. Official Wan documentation presents TI2V-5B as a 720p/24fps model suitable for consumer-grade cards such as 4090, while larger A14B examples require much more memory. The first production hardware recommendation should be based on an internal benchmark matrix using the exact fork/model versions. \[R10\]

# 17. Security, Privacy and Licensing

## 17.1 Security requirements

- Do not expose arbitrary host filesystem model paths through HTTP file endpoints.

- Reuse MoneyPrinterTurbo path-safety patterns for uploads/material/font files; local provider output must stay under approved directories.

- Do not log API keys, access tokens or provider secrets; local model paths may be logged only if operator accepts that visibility.

- Public FastAPI deployment should enable x-api-key or an equivalent authentication layer and rate/queue limits.

- Model repositories/checkpoints are operator-installed artifacts and should be verified for expected file structure; avoid executing untrusted arbitrary Python from user-supplied model directories.

- Keep TLS verification enabled for any remaining remote APIs unless an operator explicitly configures a trusted local exception.

- Generated-content use remains subject to applicable platform/law/policy requirements; the system should preserve model/provider provenance.

## 17.2 License summary

| **Component**             | **License/status observed**               | **Product implication**                                                                                                                      |
|---------------------------|-------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------|
| MoneyPrinterTurbo         | MIT                                       | Recommended base; retain MIT copyright/license notice in copies/substantial portions.                                                        |
| MoneyPrinterV2            | AGPL-3.0                                  | Not selected; network-use source obligations are an unnecessary constraint for this target.                                                  |
| Wan2.2 TI2V-5B            | Official model card identifies Apache-2.0 | Generally permissive; preserve notices and verify the exact downloaded checkpoint/model card at deployment.                                  |
| LTX 2.5                   | LTX-2.x Community License (11 Aug 2026+)  | Commercial entities with \>= USD 10M annual revenue require a paid license for commercial use per current license; review before production. |
| FFmpeg / system codecs    | Depends on build/options                  | Distribution must respect the licenses of the shipped FFmpeg build/codecs.                                                                   |
| MoneyPrinter dependencies | Mixed open-source/service terms           | Maintain a THIRD_PARTY_NOTICES / dependency review for distributable builds.                                                                 |

> License governance rule
> >
> > Record the exact model repository/checkpoint revision and applicable license text used for every production deployment. Model licenses can change independently from our application code. A legal review is recommended before commercial distribution or SaaS launch, especially for LTX.

## 17.3 Privacy modes

| **Mode**           | **Remote data exposure**                                                                                             |
|--------------------|----------------------------------------------------------------------------------------------------------------------|
| Fully local        | Ollama/local LLM + local TTS + Wan/LTX: topic/script/prompts/media need not be sent to a remote generation provider. |
| Hybrid             | Cloud LLM or TTS may receive script/narration; local video remains private.                                          |
| Upstream remote AI | Existing remote material provider receives prompts and may host generated assets according to that provider's terms. |

# 18. Testing and Quality Assurance

## 18.1 Test pyramid

| **Layer**                                               | **Runs on CPU CI?**                     | **Purpose**                                                                                               |
|---------------------------------------------------------|-----------------------------------------|-----------------------------------------------------------------------------------------------------------|
| Unit tests                                              | Yes                                     | Scene planner normalization, fingerprint, manifests, config parsing, provider registry, error mapping.    |
| Provider contract tests with fake runtime               | Yes                                     | Preflight/generate lifecycle, one runtime load across scenes, asset publication, cancellation boundaries. |
| MoneyPrinter integration tests with fake local provider | Yes                                     | Task pipeline, duration coverage, final rendering, no video-model call on rerender, task history.         |
| Media tests                                             | Yes                                     | FFmpeg-generated fixtures, ffprobe validation, aspect/duration/audio behavior.                            |
| GPU smoke tests                                         | No - dedicated GPU job/manual initially | One Wan clip, one LTX Fast clip, one LTX DFR clip when licensed/configured.                               |
| GPU end-to-end acceptance                               | No - GPU environment                    | 30-60 s local short with multiple scenes and final MP4.                                                   |
| Visual quality review                                   | Human + benchmark rubric                | Prompt adherence, motion, subject consistency, artifacts, pacing; not automatable by unit tests alone.    |

## 18.2 Mandatory regression cases

- Existing Pexels/Pixabay/Coverr/local-file task remains valid after adding local providers.

- Unknown/misconfigured local provider fails before TTS/video inference as designed.

- Fake provider generates N scene files and final MoneyPrinter render succeeds.

- Provider runtime constructor is called once for N scenes.

- Second concurrent local-AI task waits on GPU semaphore rather than loading a second runtime.

- Failure on scene N preserves scenes 1..N-1; retry reuses them.

- Changing caption style/BGM causes no local video generation calls.

- Changing one scene prompt invalidates only that scene fingerprint.

- Corrupt referenced scene clip is detected and regenerated.

- Provider switch Wan -\> LTX triggers runtime eviction policy.

- Cancellation after a scene completes stops before next scene.

- No secrets appear in task manifest/log snapshots.

- Final media passes existing MoneyPrinter output/media tests.

## 18.3 GPU benchmark matrix

| **Measure**    | **Record for each provider/mode**                                                            |
|----------------|----------------------------------------------------------------------------------------------|
| Hardware       | GPU model, VRAM, driver, CUDA/Torch versions.                                                |
| Model          | Exact checkpoint/revision and quantization/offload settings.                                 |
| Prompt set     | Same representative prompts across providers where semantically valid.                       |
| Load time      | Cold model/runtime initialization.                                                           |
| Scene time     | Per clip and distribution across multiple scenes.                                            |
| Peak VRAM      | Measured maximum where tooling allows.                                                       |
| Output         | Raw resolution/fps/duration/audio streams.                                                   |
| Quality rubric | Prompt adherence, motion coherence, visual artifacts, subject consistency, text/logo errors. |
| Recovery       | Behavior after OOM/cancel/retry.                                                             |

# 19. Implementation Roadmap

## 19.1 Phase plan

| **Milestone**                            | **Work**                                                                                                                  | **Exit criterion**                                                           |
|------------------------------------------|---------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------|
| Phase 0 - Fork and freeze baseline       | Create fork from audited MoneyPrinterTurbo SHA, tag vendor baseline, run upstream test suite, document upstream remote.   | No feature changes; clean CI baseline.                                       |
| Phase 1 - Provider scaffolding           | Add local_ai provider protocol/runtime manager, SceneSpec/manifest, fake provider, source IDs/UI registration, CPU tests. | End-to-end fake local provider works through WebUI/API/CLI and final render. |
| Phase 2 - Wan 2.2 Local                  | Port/adapt validated Wan setup logic, persistent runtime, 720p generation, scene cache/retry, GPU preflight.              | Multi-scene Wan task generates final short on real GPU.                      |
| Phase 3 - Scene Director quality         | Upgrade script segmentation and cinematic prompt generation; continuity/visual bible; prompt preview.                     | Prompts are scene-grade and mapped to narration beats.                       |
| Phase 4 - LTX 2.5 Local                  | Implement Fast/Distilled and then DFR Quality, licensing/setup docs, runtime eviction.                                    | LTX multi-scene E2E and same downstream composer.                            |
| Phase 5 - Scene iteration UX             | Single-scene regenerate/variation, previous asset retention, task detail improvements.                                    | User can fix one bad scene without whole-task generation.                    |
| Phase 6 - GPU quality tuning             | Benchmark Wan vs LTX modes, tune prompts/scene duration/defaults, profile renderer.                                       | Measured default settings and hardware guidance.                             |
| Phase 7 - Optional factual workflow      | Port bounded research/evidence and claim-review concepts only if needed by product content.                               | Factual mode blocks unsupported narration before video generation.           |
| Phase 8 - Scale/editor only if justified | Dedicated GPU worker and/or richer React editor if multi-user/editor demand is proven.                                    | Architecture evolves from measured need, not speculation.                    |

## 19.2 Suggested milestone/merge decomposition (two-branch workflow)

1. Milestone 1: vendor baseline + CI confirmation + architecture ADR (no functional change).

1. Milestone 2: SceneSpec, generation manifest and fake local provider; CPU tests.

1. Milestone 3: WebUI/API/CLI registration and local provider configuration/preflight surface.

1. Milestone 4: Wan 2.2 runtime/generation + fake tests; keep real GPU tests separate.

1. Milestone 5: restart/retry/cache/versioned scene assets.

1. Milestone 6: scene-director prompt upgrade and prompt preview.

1. Milestone 7: LTX Fast provider.

1. Milestone 8: LTX DFR Quality + license/documentation gate.

1. Milestone 9: scene regeneration UI and task artifact browser.

1. Milestone 10: measured GPU tuning/defaults and release documentation.

## 19.3 Development rule

> Do not rewrite the product shell
> >
> > The local-AI feature should prove value inside MoneyPrinterTurbo before any new frontend or renderer rewrite. If Streamlit/editor limits become a real product blocker, a separate frontend can later consume the existing FastAPI/task artifacts. This sequence preserves optionality and prevents repeating work MoneyPrinterTurbo already solved.

# 20. Migration from the Existing Content Factory Prototype

The existing shafiq079/content-factory prototype contains substantial useful engineering work, but it should not become the active base application. Preserve that repository as a read-only/reference implementation and start the active product from the audited harry0703/MoneyPrinterTurbo baseline. The migration goal is to preserve proven local-model knowledge while avoiding a mixed architecture containing two frontends, two APIs, two job systems and two project schemas.

| **Prototype asset**              | **Reuse decision**                          | **How to reuse**                                                                                                                    |
|----------------------------------|---------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------|
| Wan 2.2 adapter/preflight        | High value                                  | Port checkpoint validation, persistent runtime pattern, frame/output normalization and GPU checks into MoneyPrinter local provider. |
| LTX Fast/DFR adapter             | High value                                  | Port official pipeline/model-path handling and runtime caching into MoneyPrinter local provider.                                    |
| Shared GPU lock/runtime eviction | High value                                  | Adapt as LocalAIRuntimeManager below MoneyPrinter task manager.                                                                     |
| Scene-level asset versioning     | High value                                  | Implement through generation_manifest + versioned generated_ai scene files.                                                         |
| AI Director scene planning       | High value after basic provider integration | Port narrative beat/continuity/prompt concepts into scene_planner; adapt to MoneyPrinter script/TTS flow.                           |
| Research v2 + claim review       | Optional later                              | Keep isolated factual-content module; do not block local video MVP.                                                                 |
| Next.js editor/UI                | Do not port now                             | MoneyPrinter Streamlit WebUI is the product shell for MVP.                                                                          |
| SQLite job queue                 | Do not port wholesale                       | Use MoneyPrinter task manager/state; add GPU lock and local manifest rather than a second queue.                                    |
| Custom FFmpeg timeline renderer  | Do not port wholesale                       | Reuse MoneyPrinter composition first; port only specific fixes if a measured gap exists.                                            |

## 20.1 Porting rule

No file should be copied from Content Factory simply because it exists. For each reuse candidate, port the smallest behavior or model-specific unit into MoneyPrinterTurbo interfaces, rewrite imports/configuration around the MoneyPrinter architecture, and add MoneyPrinter-native tests. The old repository remains the source reference; the active repository must not carry a second application shell merely to preserve history.

## 20.2 Repository preservation and active-base decision

> DECISION - KEEP THE OLD CODE, BUT KEEP IT OUT OF THE ACTIVE PRODUCT
> >
> > Do not delete the existing Content Factory repository. Freeze it as a reference/archive. Do not merge its complete source tree into the new product. The active product repository should be a clean fork of MoneyPrinterTurbo. This gives future AI sessions one canonical architecture while retaining every old implementation detail for selective reuse.

- The old shafiq079/content-factory repository is reference-only after migration. Its main branch should remain readable so model adapters, tests and past design decisions can be inspected when a specific port is justified.

- The active product repository is a separate fork/clone of harry0703/MoneyPrinterTurbo pinned to the audited vendor baseline stated in this SRS. This repository becomes the only place where new product development occurs.

- Do not create a legacy/content-factory branch inside the active MoneyPrinter repository. Git history in the old repository already preserves the prototype, so duplicating it into the new repository only increases AI confusion and merge cost.

- If an exact archival marker is desired, use a Git tag in the old repository (for example content-factory-v1-final). A tag is not a working branch and does not violate the two-branch policy for the active repository.

## 20.3 File-level migration matrix

| **Current Content Factory source**              | **Decision**              | **Target in MoneyPrinter-based product**               | **Developer instruction**                                                                                                                                                                            |
|-------------------------------------------------|---------------------------|--------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| backend/app/wan_video.py                        | PORT / ADAPT              | New local Wan provider module                          | Reuse checkpoint/preflight validation, persistent runtime, generation call and output normalization. Replace Content Factory Request/scene contracts with MoneyPrinter SceneSpec/provider contracts. |
| LTX25Video code in backend/app/core.py          | PORT / EXTRACT ONLY       | New local LTX provider module                          | Extract Distilled/DFR model-path loading, runtime caching and inference behavior. Do not copy the monolithic core.py file or Content Factory project pipeline.                                       |
| backend/app/media.py                            | SELECTIVE PORT            | Shared local-AI media validation helpers               | Reuse only helpers that MoneyPrinter lacks, such as robust stream/duration validation. Prefer upstream MoneyPrinter utilities when equivalent.                                                       |
| backend/app/providers.py                        | DESIGN REFERENCE          | MoneyPrinter material-provider registration            | Do not transplant the registry wholesale. MoneyPrinter already has video_source dispatch and AI material providers; register wan22_local/ltx25_local using its architecture.                         |
| backend/app/contracts.py                        | SELECTIVE PORT            | scene_planner / SceneSpec validation                   | Reuse plan-validation ideas and strict scene contracts, adapted to MoneyPrinter script/TTS/material flow. Old timeline schema is not canonical.                                                      |
| backend/app/scene_assets.py                     | PORT CONCEPTS             | generation_manifest + versioned scene assets           | Reuse non-destructive asset replacement/versioning and fingerprint ideas. Use MoneyPrinter task directories and naming.                                                                              |
| backend/app/jobs.py                             | CONCEPTS ONLY             | Existing MoneyPrinter task manager + GPU runtime guard | Do not port the SQLite queue. Reuse restart/retry/idempotency lessons; keep MoneyPrinter task/state architecture and add local-AI GPU serialization beneath it.                                      |
| AI Director logic in backend/app/core.py        | PORT AFTER PROVIDER MVP   | scene_planner / prompt director                        | Reuse narrative beats, variable scene lengths, continuity and visual-bible concepts after basic local generation is working.                                                                         |
| backend/app/research.py + claim-review logic    | DEFER / OPTIONAL          | Future factual-content module                          | Keep as later reference. Do not make research/evidence review a dependency of the first local-video MVP.                                                                                             |
| backend/app/audio.py and custom BGM/SFX layer   | DO NOT PORT WHOLESALE     | Use MoneyPrinter audio/TTS/BGM pipeline first          | Port only a proven missing behavior after measuring an upstream gap. Avoid duplicate audio stacks.                                                                                                   |
| frontend/ (Next.js editor/workspace)            | DO NOT PORT               | MoneyPrinter Streamlit WebUI                           | The unfinished visual editor is not part of the new MVP. Extend the existing MoneyPrinter UI instead of maintaining a second frontend.                                                               |
| backend/app/main.py (FastAPI project API)       | DO NOT PORT               | MoneyPrinter existing FastAPI/controllers              | Do not bring the Content Factory project API, routes or CORS model into the new architecture. Add only required fields/endpoints to MoneyPrinter.                                                    |
| Content Factory SQLite DB/project schema v7     | DO NOT PORT AS SYSTEM     | MoneyPrinter task state + local generation manifest    | Use only useful field ideas. Do not make v7 timeline.json the canonical MoneyPrinter data model.                                                                                                     |
| Content Factory FFmpeg timeline/editor renderer | DO NOT PORT WHOLESALE     | MoneyPrinter existing composition pipeline             | Reuse upstream composition. Port a specific FFmpeg fix only when a measurable requirement cannot be met upstream.                                                                                    |
| Content Factory tests                           | PORT TEST INTENT          | MoneyPrinter-native tests                              | Rewrite high-value behavior tests (runtime reused, failed scene preserved, no regeneration on rerender) against MoneyPrinter interfaces instead of copying fixtures blindly.                         |
| PROJECT_CONTEXT.md                              | REWRITE / CARRY DECISIONS | New repo PROJECT_CONTEXT.md                            | Carry only active decisions, current milestone, validated state and links to this SRS. Do not preserve obsolete Next.js/FastAPI instructions as current architecture.                                |

## 20.4 Mandatory two-branch Git strategy

The active repository uses exactly two long-lived branches. This rule exists specifically to make fresh AI sessions predictable and to prevent abandoned feature branches from becoming competing sources of truth.

| **Branch**  | **Purpose**                   | **Allowed activity**                                                                   | **Rules**                                                                                                                                                   |
|-------------|-------------------------------|----------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------|
| main        | Stable accepted product state | Milestone merges, release tags and explicitly approved hotfixes                        | AI must not start ordinary development directly on main. main should always be runnable/tested at the last accepted milestone.                              |
| development | Only active working branch    | All implementation, refactoring, tests, docs and experiments for the current milestone | Every fresh AI session checks out development and continues from its current head. No feature/\*, fix/\*, experiment/\* or AI-generated temporary branches. |

### Required merge cycle

1.  Start each milestone from development after fetching both branches and confirming development contains the latest accepted main.

1.  Make small, reviewable commits directly on development. Commit messages should identify the subsystem and behavior changed.

1.  Run the relevant CPU test suite and static checks before asking for milestone acceptance. GPU-dependent changes must also have fake/contract tests even when a GPU is unavailable.

1.  When the milestone is accepted, open one pull request from development to main. Prefer a normal merge commit for this long-lived branch model; avoid squash/rebase merges that make development diverge from main.

1.  After the merge, fast-forward development to the new main before starting the next milestone. Keep the development branch; delete no branch because no temporary branch should have been created.

1.  At any point, the expected branch list in the active repository is only main and development. If a tool or AI creates another branch accidentally, stop and remove it after confirming no unique accepted work would be lost.

## 20.5 One-time migration/bootstrap sequence

1.  Freeze the current Content Factory repository as reference. Do not delete its main history. Optionally create an archival tag before the pivot.

1.  Create the active repository from the audited MoneyPrinterTurbo vendor baseline. Preserve upstream license/copyright notices and record the exact base commit.

1.  Create development from that baseline. The active repository should then contain only main and development.

1. Commit this SRS (preferably also as Markdown under docs/) and a concise PROJECT_CONTEXT.md that states the current milestone, branch policy, baseline commit and migration rule.

1. Run upstream MoneyPrinterTurbo tests before feature work. Record failures separately so local-AI changes are not blamed for pre-existing issues.

1. Implement the local provider contract/fake provider first, then Wan, recovery/cache, scene planning and LTX according to Section 19. Port old code only when the current milestone reaches the relevant component.

1. Do not bulk-copy Content Factory into a legacy directory. When a component is ported and tested, note its origin/decision in PROJECT_CONTEXT.md and continue using the MoneyPrinter-native version as canonical.

## 20.6 Fresh-chat AI operating protocol

> FRESH AI STARTUP RULE
> >
> > A new AI session must treat the active MoneyPrinter-based repository as canonical. The old Content Factory repository is a reference library, not an alternative implementation path. The AI must continue on development and must not create a third branch.

At the beginning of every fresh development session, the AI/developer must:

- Fetch the repository, check out development, fetch main, and inspect git status/log before editing. If development is behind main, fast-forward/sync it first.

- Read PROJECT_CONTEXT.md completely, then read this SRS - especially Sections 3, 9, 19 and 20 - before proposing architecture changes.

- Identify the next unfinished milestone from PROJECT_CONTEXT.md. Do not repeat completed work and do not restart from an older handoff message when repository state is newer.

- Inspect the relevant current MoneyPrinterTurbo code path before editing. Existing upstream provider/task/WebUI patterns take precedence over assumptions from the old Content Factory.

- If reuse from Content Factory is required, inspect only the specific source files listed in Section 20.3, port the smallest useful unit, and rewrite it against MoneyPrinter interfaces.

- Preserve CPU-testability. A missing GPU is not a reason to block architecture, provider contracts, fake-provider tests, caching/recovery logic or UI/config wiring.

- Update PROJECT_CONTEXT.md in the same milestone whenever architecture, provider contracts, configuration, migration decisions or validated project state changes.

The AI/developer must not:

- Create a new feature/fix/experiment branch as part of normal work.

- Replace MoneyPrinterTurbo with the old Next.js + FastAPI application shell.

- Copy the old SQLite queue, project API, timeline schema or editor simply to save implementation time.

- Delete the old Content Factory repository after porting one component; it remains useful as historical/test reference.

- Assume Content Factory code is automatically superior to upstream MoneyPrinter behavior. Prefer the upstream implementation whenever it already satisfies the requirement.

- Claim real Wan/LTX performance, VRAM or visual-quality results without an actual GPU validation record.

## 20.7 Cleanup and "done migrating" criteria

| **Area**        | **Active repository end state**                                                                                                               |
|-----------------|-----------------------------------------------------------------------------------------------------------------------------------------------|
| Frontend        | MoneyPrinter Streamlit WebUI only for MVP; no copied Content Factory Next.js app.                                                             |
| API             | MoneyPrinter FastAPI/controllers with additive local-AI fields/endpoints only; no second Content Factory FastAPI project API.                 |
| Task execution  | MoneyPrinter task manager/state remains authoritative; local GPU serialization/recovery is integrated beneath it.                             |
| Data model      | MoneyPrinter task artifacts plus scene/generation manifest; no requirement to carry timeline schema v7.                                       |
| Rendering/audio | MoneyPrinter composition/TTS/subtitle/BGM path remains default unless a specific tested gap justifies a selective port.                       |
| Local AI        | Wan and LTX are MoneyPrinter-native providers with reusable runtime management and scene-level persisted assets.                              |
| Git             | Only main and development exist in the active repository; no stale feature branches.                                                          |
| Documentation   | PROJECT_CONTEXT.md points to this SRS and records current milestone/validated state. Old Content Factory is explicitly marked reference-only. |


# 21. Risk Register

| **ID**  | **Risk**                                                 | **Impact** | **Likelihood** | **Mitigation**                                                                                                                             |
|---------|----------------------------------------------------------|------------|----------------|--------------------------------------------------------------------------------------------------------------------------------------------|
| RISK-01 | GPU OOM / model contention                               | High       | High           | Global GPU semaphore=1, provider preflight, runtime eviction, validated hardware presets.                                                  |
| RISK-02 | Generation time makes 60-120 s videos slow               | High       | High           | Persist every scene, clear progress, scene density controls later, draft modes, benchmark before promises.                                 |
| RISK-03 | Poor prompt-to-video consistency across scenes           | High       | Medium         | Scene Director, visual bible/continuity, short scenes, seed control, human scene regeneration.                                             |
| RISK-04 | Upstream MoneyPrinter merges become painful              | Medium     | High           | Small core diff, new modules, vendor baseline tag, regular upstream sync, regression CI.                                                   |
| RISK-05 | LTX licensing changes/threshold issue                    | High       | Medium         | License gate in docs/deployment; Wan first; record exact LTX license/revision; legal review before commercial use.                         |
| RISK-06 | Disk growth from model/raw/versioned video               | Medium     | High           | Configurable retention, project-local cache, remove raw temp after validated normalized output.                                            |
| RISK-07 | Local model output codecs break MoviePy                  | Medium     | Medium         | Normalize every provider output to known compatible MP4 and validate before composer.                                                      |
| RISK-08 | Task retry accidentally regenerates everything           | High       | Medium         | Scene manifest + fingerprint + media revalidation; tests proving reuse.                                                                    |
| RISK-09 | Streamlit becomes editor bottleneck                      | Medium     | Medium         | Keep API/artifacts clean; defer React editor until proven need.                                                                            |
| RISK-10 | User expects cloud-grade quality on unvalidated hardware | High       | Medium         | Explicit GPU validation milestone; no unsupported quality/performance claims.                                                              |
| RISK-11 | Paid upstream providers accidentally invoked             | High       | Low            | Local source branch has no remote-generation fallback; fail closed when local setup missing.                                               |
| RISK-12 | Model/plugin Python dependency conflicts                 | Medium     | High           | Lazy imports, optional AI dependency group/environment; consider isolated GPU worker if conflicts become material.                         |
| RISK-13 | AGPL contamination by copying V2 code                    | High       | Low            | Do not copy MoneyPrinterV2 implementation code into the MIT fork; use only conceptual observations unless legal compatibility is reviewed. |
| RISK-14 | Security regression via filesystem paths                 | High       | Medium         | Restrict config-only model paths, safe task output roots, preserve upstream path validation.                                               |

# 22. Acceptance and Release Criteria

## 22.1 MVP release acceptance

1. Fork baseline is documented and upstream MoneyPrinterTurbo tests pass.

1. wan22_local and ltx25_local are represented through a shared local-provider contract; fake providers exercise both paths on CPU CI.

1. A real GPU Wan task produces at least one multi-scene 9:16 final video from topic/script without any stock or paid video-generation API.

1. A real GPU LTX Fast task produces a multi-scene final video; DFR is either validated or clearly marked unavailable until required assets/hardware/license are ready.

1. Local model runtime loads once and is reused across multiple scenes.

1. Task manifest records every scene prompt/seed/duration/provider/mode/asset and survives restart/retry.

1. A forced failure on a later scene preserves earlier clips and retry resumes without regenerating them.

1. Changing subtitle/BGM/final render settings does not call local video generation.

1. Existing upstream Pexels/local-file path still passes regression tests.

1. WebUI shows local source, preflight error/help, task stage and scene progress.

1. Final MP4 is media-validated and task exposes required artifacts.

1. README/setup contains exact local model install/config steps and third-party license notices.

1. No real performance/quality claim is published without benchmark evidence from the target GPU.

1. The active repository contains only main and development branches under the documented two-branch policy.

1. The old Content Factory remains available as a separate reference/archive and has not been bulk-copied into the active product.

1. PROJECT_CONTEXT.md identifies the MoneyPrinter vendor baseline, current development branch, current milestone and links developers to Section 20 for reuse/retire rules.

## 22.2 Definition of production-ready (after MVP)

- At least one validated deployment profile with documented GPU/driver/Torch/model versions.

- GPU benchmark data for selected defaults, including generation time and peak VRAM.

- Scene regeneration/versioning usable from UI or documented API.

- Recovery tested across process restart and at least one deliberate render failure.

- License review completed for all shipped/default model choices.

- Security review completed for public API exposure, task artifact access and filesystem configuration.

- Operational cleanup/retention policy tested with multiple large tasks.

# 23. Final Architecture Re-analysis

After building the first-pass requirements and architecture, the design was re-evaluated against the original product objective, the current upstream code, operational GPU realities, licensing and maintainability. The following questions were used as a second-pass architecture review.

| **Review question**                                           | **Conclusion / improvement**                                                                                                                                         |
|---------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Are we rebuilding capabilities MoneyPrinterTurbo already has? | No. The plan explicitly reuses TTS, captions, BGM, transitions, final rendering, WebUI/API/CLI, task history and existing providers.                                 |
| Is the integration located at a real upstream extension seam? | Yes. download_videos()/MaterialInfo and the AI Video source group already support multiple generated-video providers.                                                |
| Does local inference create a new failure/cost model?         | Yes, and the plan adds scene manifests, atomic publication, cached runtimes, GPU locking and resume behavior rather than pretending it is identical to stock search. |
| Are search keywords good enough as T2V prompts?               | No. A separate SceneSpec/scene-director layer is required.                                                                                                           |
| Should Wan/LTX own narration?                                 | Not initially. MoneyPrinter narration is the stable authority; model-native audio is deferred.                                                                       |
| Should we build a visual timeline editor now?                 | No. Scene review/regeneration is valuable, but a full NLE does not determine whether the local generation product works.                                             |
| Should we use MoneyPrinterV2 because it is simpler/local?     | No. Simplicity comes with missing product surfaces and image-centric coupling; it would create more net work and AGPL obligations.                                   |
| Should we replace MoviePy now?                                | No. GPU video generation is the dominant unknown. Renderer replacement is justified only by profiling.                                                               |
| Can the design scale later?                                   | Yes. SceneSpec/provider/manifest boundaries let the GPU runtime move into a worker service without changing final composition.                                       |
| Is model licensing treated as a deployment property?          | Yes. Wan/LTX model licenses are recorded separately from the MIT application fork, with an explicit LTX commercial-license gate.                                     |

## 23.1 Improvements made after re-analysis

- Changed the recommended integration from "replace stock search" to "add first-class local AI material providers" because current MoneyPrinterTurbo already has multiple AI Video providers.

- Made scene planning a separate requirement instead of reusing raw video_terms blindly.

- Moved full timeline-editor work out of MVP and prioritized scene-level regeneration/recovery.

- Added a dedicated GPU resource boundary beneath MoneyPrinter task concurrency.

- Made project-local caching the default to avoid repetitive visuals across unrelated tasks.

- Made Wan the first local provider and LTX the second due to implementation practicality and the need for explicit LTX license governance.

- Recommended pinning an audited upstream commit rather than loosely saying "fork latest".

- Added a deliberate upstream-sync strategy and minimal-core-diff rule because MoneyPrinterTurbo is actively changing.

- Kept factual research/claim review as a later orthogonal module, preserving the valuable Content Factory work without blocking the core product.

- Added an explicit repository migration matrix, separate archival strategy and two-branch main/development workflow so a fresh AI session sees one canonical product architecture and does not recreate abandoned Content Factory subsystems.

> Final architecture conclusion
> >
> > The lowest-risk, highest-leverage implementation is: MoneyPrinterTurbo current main as the product shell + new local Wan/LTX material providers + scene-grade prompt planning + scene-level persistent recovery. This satisfies the desired product with materially less code and less duplicated infrastructure than continuing a standalone Content Factory application or basing the product on MoneyPrinterV2.

# Appendix A. Requirement Traceability Summary

| **ID** | **Requirement**                         | **Priority** | **Planned delivery** |
|--------|-----------------------------------------|--------------|----------------------|
| FR-001 | Topic and script input                  | Must         | Phase 1-5            |
| FR-002 | Output aspect selection                 | Must         | Phase 1-5            |
| FR-003 | Video source selection                  | Must         | Phase 1-5            |
| FR-004 | No paid-video API dependency            | Must         | Phase 1-5            |
| FR-005 | Task artifact ownership                 | Must         | Phase 1-5            |
| FR-006 | Existing pipeline compatibility         | Must         | Phase 1-5            |
| FR-007 | Existing source fallback                | Must         | Phase 1-5            |
| FR-008 | Optional existing publishing            | Must         | Phase 1-5            |
| FR-010 | Measured narration timing               | Must         | Phase 1-5            |
| FR-011 | Scene segmentation                      | Must         | Phase 1-5            |
| FR-012 | Scene duration policy                   | Must         | Phase 1-5            |
| FR-013 | Cinematic prompt generation             | Must         | Phase 1-5            |
| FR-014 | Prompt continuity                       | Should       | Phase 1-5            |
| FR-015 | User instructions                       | Must         | Phase 1-5            |
| FR-016 | Prompt preview                          | Should       | Phase 1-5            |
| FR-017 | Prompt edit/regenerate                  | Should       | Phase 1-5            |
| FR-018 | Deterministic metadata                  | Must         | Phase 1-5            |
| FR-020 | Wan local provider                      | Must         | Phase 1-5            |
| FR-021 | LTX local provider                      | Must         | Phase 1-5            |
| FR-022 | LTX Fast mode                           | Must         | Phase 1-5            |
| FR-023 | LTX Quality mode                        | Should       | Phase 1-5            |
| FR-024 | Provider preflight                      | Must         | Phase 1-5            |
| FR-025 | No model download in task               | Must         | Phase 1-5            |
| FR-026 | Video-only Wan output                   | Must         | Phase 1-5            |
| FR-027 | LTX audio policy                        | Must         | Phase 1-5            |
| FR-028 | Provider registry direction             | Should       | Phase 1-5            |
| FR-029 | Media validation                        | Must         | Phase 1-5            |
| FR-030 | Persistent model runtime                | Must         | Phase 1-5            |
| FR-031 | GPU serialization                       | Must         | Phase 1-5            |
| FR-032 | Model family switching                  | Must         | Phase 1-5            |
| FR-033 | Configurable device                     | Must         | Phase 1-5            |
| FR-034 | Seed handling                           | Must         | Phase 1-5            |
| FR-035 | Progress by scene                       | Must         | Phase 1-5            |
| FR-036 | Cancellation boundary                   | Must         | Phase 1-5            |
| FR-037 | OOM handling                            | Must         | Phase 1-5            |
| FR-038 | GPU telemetry                           | Should       | Phase 1-5            |
| FR-040 | Scene manifest                          | Must         | Phase 1-5            |
| FR-041 | Atomic scene publication                | Must         | Phase 1-5            |
| FR-042 | Retry reuse                             | Must         | Phase 1-5            |
| FR-043 | Input fingerprint                       | Must         | Phase 1-5            |
| FR-044 | Versioned regeneration                  | Should       | Phase 1-5            |
| FR-045 | Project-local default cache             | Must         | Phase 1-5            |
| FR-046 | Disk cleanup                            | Must         | Phase 1-5            |
| FR-047 | Asset source metadata                   | Must         | Phase 1-5            |
| FR-048 | Restart validation                      | Must         | Phase 1-5            |
| FR-050 | Narration provider reuse                | Must         | Phase 1-5            |
| FR-051 | No-voice mode                           | Must         | Phase 1-5            |
| FR-052 | Caption reuse                           | Must         | Phase 1-5            |
| FR-053 | Whisper compatibility                   | Must         | Phase 1-5            |
| FR-054 | BGM reuse                               | Must         | Phase 1-5            |
| FR-055 | Audio/video duration reconciliation     | Must         | Phase 1-5            |
| FR-056 | Future native audio gate                | Must         | Phase 1-5            |
| FR-057 | Audio clipping control                  | Should       | Phase 1-5            |
| FR-058 | Subtitle/content sync after scene retry | Should       | Phase 1-5            |
| FR-060 | Final format compatibility              | Must         | Phase 1-5            |
| FR-061 | Existing transitions                    | Must         | Phase 1-5            |
| FR-062 | Fit mode                                | Must         | Phase 1-5            |
| FR-063 | Final rerender without inference        | Must         | Phase 1-5            |
| FR-064 | Output package                          | Must         | Phase 1-5            |
| FR-065 | Task history                            | Must         | Phase 1-5            |
| FR-066 | Multiple output variants                | Should       | Phase 1-5            |
| FR-067 | Render isolation                        | Must         | Phase 1-5            |
| FR-070 | AI Video group UI                       | Must         | Phase 1-5            |
| FR-071 | Provider settings UI                    | Should       | Phase 1-5            |
| FR-072 | Preflight status                        | Must         | Phase 1-5            |
| FR-073 | Scene progress UI                       | Must         | Phase 1-5            |
| FR-074 | Prompt/scene view                       | Should       | Phase 1-5            |
| FR-075 | Scene regeneration control              | Should       | Phase 1-5            |
| FR-076 | No full NLE requirement                 | Must         | Phase 1-5            |
| FR-077 | Cost/runtime warning                    | Should       | Phase 1-5            |
| FR-078 | Model/license notice                    | Must         | Phase 1-5            |
| FR-080 | API compatibility                       | Must         | Phase 1-5            |
| FR-081 | CLI compatibility                       | Must         | Phase 1-5            |
| FR-082 | Config separation                       | Must         | Phase 1-5            |
| FR-083 | Stable provider identifiers             | Must         | Phase 1-5            |
| FR-084 | Backward compatibility                  | Must         | Phase 1-5            |
| FR-085 | Health/preflight API                    | Should       | Phase 1-5            |
| FR-086 | Structured local provider errors        | Must         | Phase 1-5            |
| FR-087 | No secret persistence                   | Must         | Phase 1-5            |
| FR-090 | Factual mode - optional research        | Could        | Phase 7              |
| FR-091 | Factual claim review                    | Could        | Phase 7              |
| FR-092 | Research independence                   | Could        | Phase 7              |

# Appendix B. Proposed Configuration and Naming

## B.1 Stable provider IDs

| **ID**                   | **UI label**          | **Notes**                                                        |
|--------------------------|-----------------------|------------------------------------------------------------------|
| wan22_local              | Wan 2.2 Local GPU     | Primary MVP local text-to-video provider.                        |
| ltx25_local              | LTX 2.5 Local GPU     | Mode setting selects Fast/Distilled or Quality/DFR.              |
| preview/fake (test only) | Local AI Fake/Preview | Not exposed as a production content source; CPU CI/testing only. |

## B.2 Naming and compatibility rules

- Provider IDs are machine-stable; UI labels may be localized.

- Do not overload existing "local" source; it means user-supplied local material, not local AI generation.

- Do not call a local source "Wan API" or "LTX API" when inference is in-process/self-hosted.

- Model path/config names should be explicit and provider-prefixed.

- Generation mode is provider-specific but stored in a general manifest field for auditing.

- Model/checkpoint version or fingerprint should be recorded in manifest even when the UI displays a friendly model name.

## B.3 Example generation manifest

**Illustrative manifest schema**

```json
{

"schema_version": 1,

"task_id": "...",

"video_source": "wan22_local",

"model_fingerprint": "wan2.2-ti2v-5b:<checkpoint-id>",

"scenes": [

{

"scene_id": 1,

"status": "ready",

"narration_segment": "...",

"prompt": "...",

"target_duration": 5.0,

"actual_duration": 5.0,

"aspect": "9:16",

"seed": 42,

"fingerprint": "sha256:...",

"active_asset": "generated_ai/scene-001/v001.mp4",

"versions": ["generated_ai/scene-001/v001.mp4"]

}

]

}
```

# Appendix C. References and Research Snapshot

| **Ref** | **Source**                                                  | **URL**                                                                                         | **Use in this SRS**                                                                                         |
|---------|-------------------------------------------------------------|-------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------|
| R1      | MoneyPrinterTurbo repository and README                     | https://github.com/harry0703/MoneyPrinterTurbo                                                  | Snapshot inspected at main commit ad5496f1b729d1d7e361dd972015d26c08b0e052; 26 Sep 2026.                    |
| R2      | MoneyPrinterTurbo pyproject.toml / dependency configuration | https://github.com/harry0703/MoneyPrinterTurbo/blob/main/pyproject.toml                         | Version declared 1.3.7; Python \>=3.11; CI/coverage/dependency context.                                     |
| R3      | MoneyPrinterTurbo material service                          | https://github.com/harry0703/MoneyPrinterTurbo/blob/main/app/services/material.py               | download_videos(), stock search and on-demand AI video provider branches.                                   |
| R4      | MoneyPrinterTurbo task manager/state/task pipeline          | https://github.com/harry0703/MoneyPrinterTurbo/tree/main/app                                    | Task orchestration, in-memory/Redis managers, task state and final rendering.                               |
| R5      | MoneyPrinterTurbo schemas                                   | https://github.com/harry0703/MoneyPrinterTurbo/blob/main/app/models/schema.py                   | MaterialInfo, VideoParams, VideoAspect and transition contracts.                                            |
| R6      | MoneyPrinterTurbo WebUI                                     | https://github.com/harry0703/MoneyPrinterTurbo/blob/main/webui/Main.py                          | Video source groups, labels and generation controls.                                                        |
| R7      | MoneyPrinterTurbo v1.3.7 release                            | https://github.com/harry0703/MoneyPrinterTurbo/releases/tag/v1.3.7                              | Published 13 Sep 2026; release notes reviewed.                                                              |
| R8      | MoneyPrinterV2 repository, YouTube docs and implementation  | https://github.com/FujiwaraChoki/MoneyPrinterV2                                                 | Snapshot inspected at main commit a734fa924adb9ffe5ab8472aa5526e469e42a8b5; 26 Sep 2026.                    |
| R9      | MoneyPrinterV2 AGPL-3.0 license                             | https://github.com/FujiwaraChoki/MoneyPrinterV2/blob/main/LICENSE                               | License text reviewed; technical planning notes only, not legal advice.                                     |
| R10     | Wan2.2 official repository and TI2V-5B model card           | https://github.com/Wan-Video/Wan2.2 ; https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B              | Official architecture/run guidance; model card marks Apache-2.0; 720p/24fps TI2V-5B.                        |
| R11     | LTX-2 official repository and LTX-2.x license               | https://github.com/Lightricks/LTX-2 ; https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x | LTX 2.5 pipeline guidance and Community License dated 11 Aug 2026.                                          |
| R12     | Existing Content Factory prototype                          | https://github.com/shafiq079/content-factory                                                    | Used only to identify reusable local Wan/LTX/runtime/scene-recovery patterns; not selected as product base. |

## C.1 Repository comparison snapshot notes

MoneyPrinterTurbo repository metadata observed on 26 Sep 2026: 126,013 stars, 19,641 forks, 35 open issues, MIT license, current push 24 Sep 2026. Tree inspection found 121 Python files, 71 Python test files, and GitHub workflows for CI and Docker/GHCR. MoneyPrinterV2 metadata: 31,989 stars, 3,443 forks, 93 open issues, AGPL-3.0 license, current push 15 Sep 2026; tree inspection found 22 Python files, 5 Python test files and no .github/workflows entries. These are time-bound research signals, not permanent product properties.

## C.2 Research limitations

- No real Wan/LTX GPU generation was run as part of this document. Model output quality, throughput and actual VRAM requirements for the target deployment remain validation tasks.

- Repository activity and feature sets can change after the snapshot date; implementation should rebase/compare upstream before the first coding milestone.

- Third-party model/service licenses and platform terms can change. Re-check the exact versions used for production.

- The weighted repository matrix expresses engineering fit for this specific product, not a general quality ranking of the projects.

# Appendix D. Fresh-Chat / AI Developer Handoff Checklist

This appendix is intentionally operational. It can be copied into a fresh ChatGPT/Work/Codex session together with the repository URL. Repository state always overrides stale chat summaries.

| **Check**            | **Fresh session action**                                                                                                           |
|----------------------|------------------------------------------------------------------------------------------------------------------------------------|
| Canonical repository | Use the active MoneyPrinterTurbo-based repository, not shafiq079/content-factory.                                                  |
| Branch               | Work on development. Fetch main. Do not create another branch.                                                                     |
| Read first           | PROJECT_CONTEXT.md, then SRS Sections 3, 9, 19 and 20, then the relevant current source files.                                     |
| Old code             | Use Content Factory only as a reference for the explicit port candidates in Section 20.3.                                          |
| Architecture         | Preserve MoneyPrinter WebUI/API/task/rendering shell; add local-AI providers and scene-safe persistence.                           |
| No GPU               | Continue CPU-safe contracts/fake providers/tests; defer only real inference/benchmark validation.                                  |
| Before coding        | Confirm next unfinished milestone and run/inspect relevant baseline tests.                                                         |
| Before merge         | Run tests, update PROJECT_CONTEXT.md, summarize changed files/behavior/known limitations.                                          |
| Merge                | One PR from development to main after milestone acceptance; regular merge commit preferred; then fast-forward development to main. |

## Recommended fresh-chat opening instruction

| Continue development of my MoneyPrinterTurbo local-AI-video project. First fetch the latest repository state and check out development. Do not create a new branch. Read PROJECT_CONTEXT.md completely, then read the SRS, especially Sections 3, 9, 19 and 20. The old shafiq079/content-factory repository is reference-only; port only the components explicitly marked for reuse. Identify the next unfinished milestone from the repository state, implement it using MoneyPrinterTurbo's existing architecture, run the relevant tests, and update PROJECT_CONTEXT.md when the project state or architecture changes. |
|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

**END OF BASELINE SRS v1.1**
