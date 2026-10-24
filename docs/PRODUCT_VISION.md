# MoneyPrinter AI Video: long-term product vision and deferred work

Read `PROJECT_CONTEXT.md` for current implementation, `docs/SRS.md` for the
accepted v1.1 scope, and this document for product goals recovered from the
owner's earlier planning chats. This is a roadmap and handoff, not a claim that
every idea below is implemented or that a particular editor stack was approved.
The owner's latest explicit instruction and observed repository state take
precedence. Update this document when a product decision is made.

## Original product goal

Create original, high-quality, mostly free/open-source AI video for a chosen
topic, niche, or script. The intended flow is script and scene direction,
multiple short generated video clips, voice and other audio, captions, editing,
and a final downloadable video. The user also wants an **editable project**
containing the underlying assets, not only a flattened MP4. Longer assembled
vertical videos (roughly 30–120 seconds, often 60–120 seconds) are an eventual
goal; provider clip limits and compute costs still apply.

The active implementation extends MoneyPrinterTurbo. The older Content Factory
is reference only. Do not transplant its Next.js/FastAPI/SQLite/timeline-v7
application. Existing MoneyPrinterTurbo narration, captions, music, task
management, publishing integration, and MoviePy/FFmpeg composition remain the
starting point. Wan/LTX providers generate video scenes behind local-AI
contracts, with no mandatory paid video-generation API.

## Decisions and current boundary

| Area | Owner's intent and scope decision | Current state / remaining boundary |
| --- | --- | --- |
| AI scene generation | Original clips, scene prompts, continuity, selective retries, reusable assets. | Implemented through local Wan/LTX and remote HF LTX paths; one real seven-scene HF LTX task completed. Real **local** Wan/LTX checkpoint validation and comparative GPU tuning remain deferred. |
| Editable project | Keep independently editable scene clips, narration/audio, captions, prompts and metadata alongside the final MP4. A bad scene or a render-only change must not invalidate unrelated generated assets. | Scene plan, scene versions, final output and portable artifact references exist. A full editable timeline/project with independent audio/text layers does not. |
| In-product editor | Eventually provide a small, self-hosted, CapCut-like experience; do not copy or depend on CapCut. The initial release need not be a full multi-track NLE. | Existing Streamlit scene editor covers prompt/seed, preview, regenerate, variation, validated manual clip replacement, fixed-duration source trims, visual cut timing, visual playback reordering, version restore, render-only rerender, and saved estimated narration ranges/audio previews. Narration edits and independent timeline layers remain deferred. |
| Scene timing | Let scene count/length follow narration and content instead of forcing every scene to the same fixed length. | Current planner uses measured audio duration, beat weights and a maximum provider-supported scene duration. Visual cut timing rebalances adjacent scenes at fixed total duration. Semantic audio alignment and retiming after narration changes remain deferred. |
| Publishing | Complete video generation without an upload dependency. Initially defer upload automation and channel-growth tooling. | Existing optional Upload-Post integration offers YouTube, TikTok and Instagram; operator end-to-end publishing was not established in this development effort. Direct platform OAuth is not an approved replacement. |
| Factual content | Optional evidence/review mode must not burden creative generation. | User-supplied excerpts, safe one-page import, review-only workflow and structural claim checks exist. Automatic discovery/source authentication and real-model acceptance remain deferred. |
| Deployment | Start with a working single-product workflow; add multi-user infrastructure or new frontend only when real needs justify it. | No decision to add accounts, billing, distributed GPU scheduling, or a React editor now. |

## Deferred editor requirements to design incrementally

These are recovered **user goals**, not permission to replace the current
frontend or renderer in one step:

1. Reopen a completed task as an editable project. Preserve original/generated
   media and the active scene-version references. Keep final MP4 export.
2. Preview, replace and reorder individual scene clips. Validated single-scene
   MP4 replacement is implemented using task-local versions, unchanged scene
   timing and existing narration/captions. Visual-only reordering is also
   implemented; narration and captions keep their existing timestamps.
3. Edit narration text or audio for a selected scene. Rebuild only affected
   narration and captions; recalculate duration and shift later scenes and
   audio cues as required. Define precisely how changes to a voice track relate
   to any video clip that contains model-native speech.
4. Edit captions and basic transitions, plus music/SFX placement and level,
   without needlessly regenerating AI visuals. Keep layers independently
   adjustable until final composition.
5. Distinguish **render-only**, **voice/caption**, and **video-generation** edits
   in one change-impact contract. Preserve completed good clips on every
   failure. Maintain same-task Resume and version history semantics.
6. Make durations narration-aware and provider-capability-aware. Decide
   generation duration, timeline duration, trimming and continuity explicitly;
   never promise an arbitrary length from a single model invocation.

An internal project/timeline representation, OTIO interchange, `.mptproj`/
`.mptz`, an OpenReel-based UI, and XML/AAF/EDL export were **suggestions** in
earlier discussions, not accepted format or framework decisions. Content
Factory's `timeline.json` v7 is not the canonical schema here. Choose a format
only after auditing the existing task artifacts and defining migration,
validation and render behavior. Native LTX audio/hybrid audio and advanced SFX
remain later optional scope under `docs/SRS.md`.

## Publishing and broader automation

The owner explicitly deferred automated uploads, tool integrations, schedules
and analytics while the free/open-source generation path was being established.
The existing Upload-Post integration is an optional preserved capability and
does not prove account-level publishing. Before adding to it, separately define
the user-facing approval, platform account/configuration, result/retry, and
privacy behavior and exercise the actual flow in an authorized environment.

Earlier discussions about a 24/7 channel agent also mentioned trend research,
thumbnails, titles/SEO, multi-platform posts, scheduling, analytics feedback
and monetization. Those discussions included an AgentTube direction. They are
**possible future product ideas**, not an agreed MoneyPrinter AI Video backlog
or evidence that all such features should be built. Ask the owner to approve
the specific scope before implementing one of them.

## Working sequence for future sessions

1. Fetch the latest `development` and read `AGENTS.md`, `PROJECT_CONTEXT.md`,
   `docs/SRS.md`, `docs/MIGRATION_MAP.md`, this document and the relevant
   operator guide. Inspect current code and tests; do not redo completed work.
2. Reconcile one deferred user goal with the v1.1 MVP boundary. Write a bounded
   milestone with its asset/data contract, change-impact policy, acceptance
   evidence and compatibility requirements before implementing it.
3. Implement on `development` only, with focused CPU-safe regression checks.
   Defer real local-GPU measurements and owner-operated external service tests
   until that environment is available; do not claim those passed from mocks.
4. Preserve `main` as accepted stable code. Use only `main` and `development`;
   never create a third branch or force-push. Update `PROJECT_CONTEXT.md` and
   this roadmap when a milestone is accepted or a deferred choice is settled.

## First editable-project extension: manual clip replacement

The owner approved the next small editor extension after orientation.
`docs/SCENE_EDITING.md` defines its asset and change-impact contract. A scene can
now receive a validated MP4 upload, trimmed to its existing duration with native
audio removed. It becomes a task-local version with imported provenance; final
composition reuses narration, captions and existing generated BGM. Failed
replacement/rendering preserves the prior active version and outputs.
Resume retains imports across model revisions and fails explicitly for missing
or changed uploads instead of silently generating substitute footage.

This extends the existing Streamlit workflow. It does not select an NLE
framework, new project-file extension or interchange format.

## Second editable-project extension: visual playback order

The owner approved visual-only reordering as the next bounded milestone.
**Move earlier / Move later** changes a saved playback-order list independently
of stable scene IDs, active versions and generation fingerprints. Narration
and captions stay fixed; the editor explains that moving footage can change
which words it accompanies. Existing clip durations and composition settings
remain in effect. Resume and subsequent scene edits retain the saved order.
Invalid/stale requests are rejected, and failed rendering rolls back order and
prior outputs. No generation or publishing request is made by a reorder.

Fixed-duration source trims are now implemented as the third bounded extension.
Visual cut timing is now implemented while keeping total planned duration fixed.
Overall-duration changes remain a later milestone with an explicit relationship
to fixed narration and provider limits. Moving whole narrated scenes requires
audio/caption segmentation and retiming, which this milestone does not provide.
Self-contained project export, scene-level narration edits and independent
audio/text layers remain future work.

## Third editable-project extension: fixed-duration source trims

The owner approved clip start controls. New uploads can select a later section,
and existing active clips can be cut where enough saved footage remains. Cuts
create restorable, video-only versions using the existing replacement/rollback
path. Scene durations, playback order, narration and captions stay unchanged.
Saved trims carry source-version provenance and hash validation through Resume;
no inference or publishing occurs. Earlier imports discarded excess footage,
so the original must be uploaded again to select a section no longer present.
This does not choose a new project format or add timeline/audio retiming.

## Fourth editable-project extension: visual cut timing

The next incremental editor step adds a saved screen-duration map independently
of generation settings. Changing one duration balances the next scene in saved
playback order. Narration/captions and total planned visual duration stay fixed.
The composer uses existing footage at normal speed, rounds cumulative cuts to
frames and rejects insufficient footage. Reset restores legacy timing behavior.
The saved map survives reopening, Resume and scene edits, with snapshot checks
and rollback of timing and prior outputs on failure. New uploads/trims retain
enough footage for extended slots. Later regeneration keeps its original recipe
and may require restoring longer footage or resetting timing. No automatic model
duration increase, audio segmentation, narration editing or project-format
selection is introduced. See `docs/SCENE_EDITING.md` for the contract.

## Fifth editable-project extension: narration range foundation

Saved estimated narration ranges and cut-audio previews now exist separately
from visual order and screen durations. Ranges use stable scene IDs, measured
decoded audio and initial generation-duration weights. Exact audio/script and
scene-text bindings prevent stale preview reuse. They survive reopening,
Resume and visual edits. Labels explicitly distinguish estimates from verified
speech alignment. Preparation uses existing audio only and preserves task
status and prior artifacts on failure. This does not implement narration text
editing, TTS rebuilding, verified alignment or audio/caption retiming. Those
remain the next narration milestones after validating this foundation.
