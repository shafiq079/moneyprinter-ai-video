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
| In-product editor | Eventually provide a small, self-hosted, CapCut-like experience; do not copy or depend on CapCut. The initial release need not be a full multi-track NLE. | Existing Streamlit scene editor covers prompt/seed, preview, regenerate, variation, validated manual clip replacement, fixed-duration source trims, visual cut timing, visual playback reordering, version restore, render-only rerender, and saved narration ranges/audio previews with manual boundary adjustment, operator review, and saved replacement narration drafts for audition. The creative fixed-duration narration workflow includes text/TTS edits, uploaded recordings, optional tempo fitting, reviewed-range caption rebuilding, apply/export and restore-original. Automatic word alignment and independent timeline layers remain deferred. |
| Scene timing | Let scene count/length follow narration and content instead of forcing every scene to the same fixed length. | Current planner uses measured audio duration, beat weights and a maximum provider-supported scene duration. Visual cut timing rebalances adjacent scenes at fixed total duration. Automatic uses the existing narration-aware planner within model limits; natural-length narration retiming is implemented. Verified semantic/word alignment remains deferred. |
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

## Sixth editable-project extension: narration boundary review

Operators can adjust shared narration boundaries and explicitly mark ranges
reviewed after listening. Coverage stays contiguous, with fixed audio endpoints,
and remains separate from visual order/timing. Manual changes recut previews
without changing original audio, captions or final video. Moving a boundary
clears both adjacent reviews; changed source bindings clear all old reviews.
Revision checks and atomic publication protect newer edits and prior previews.
Operator review is a user assertion, with no claim of automatic speech alignment.
This prepares for later narration replacement without implementing TTS/text
editing, caption rebuilding or downstream retiming yet.

## Seventh editable-project extension: replacement narration drafts

Reviewed narration ranges now accept duration-matched audio uploads for saved
A/B audition. Original and replacement previews are separate, and drafts can be
removed to restore original-only playback. Drafts survive reopening, visual
edits and Resume without changing the master narration, captions or final video.
Source rebinding clears drafts; boundary edits require adjacent drafts to be
removed first. Atomic publication, hash/source checks and the existing queue
preserve prior assets on failure. See `docs/SCENE_EDITING.md` for limits.
Applying replacements to exports, narration text/TTS edits and caption/audio
retiming remain future milestones; no independent timeline format is selected.

## Eighth editable-project extension: reversible narration exports

Creative AI-video tasks can apply saved duration-matched recordings to exports,
using existing clips and music. The explicit apply action exports without
captions because replacement word timings are not rebuilt. Restore returns to
original narration and saved caption settings. Original media/script/scene
versions remain intact; later visual edits and Resume retain a validated active
mix. Source/range/scene checks, metadata publication and render rollback protect
prior assets. See `docs/SCENE_EDITING.md` for the transaction and crash limits.
Factual-task audio edits, caption rebuilding, text/TTS edits and variable-duration
retiming remain deferred. This extends Streamlit and the existing composer.

## Completed milestone: creative narration and captions at fixed duration

The complete fixed-timeline creative narration workflow now includes scene text
editing, explicit TTS generation with the saved voice, transcript-labelled
uploads, optional 0.5x–2x tempo fitting, previews, reviewed-range captions,
captioned apply/export, original restore, artifact downloads and reopening/Resume.
Existing narration/caption roots and visual generation assets remain unchanged.
Edited script, SRT and audio are separately bound and hash-validated. Version 1
caption-free mixes remain compatible; version 2 adds caption/script assets.
Automated acceptance covers real captioned MP4 and restore output, failure
rollback, fitting, immutable queue requests and restart/Resume persistence.

This completes the creative fixed-duration milestone, not the entire long-term
editable-project vision. Captions use operator-confirmed range timing and
transcripts, not automatic speech recognition or word alignment. Factual edits,
changes to total video length, independent timeline layers and portable project
archives remain outside this milestone. Manual operator acceptance is deferred
at the owner's request; automated CPU verification continues.

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
