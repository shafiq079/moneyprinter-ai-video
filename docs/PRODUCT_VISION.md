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
| In-product editor | Eventually provide a small, self-hosted, CapCut-like experience; do not copy or depend on CapCut. The initial release need not be a full multi-track NLE. | Existing Streamlit scene editor covers prompt/seed, preview, regenerate, variation, version restore, and render-only rerender. More detailed editing is deferred, not rejected. |
| Scene timing | Let scene count/length follow narration and content instead of forcing every scene to the same fixed length. | Current planner uses measured audio duration, beat weights and a maximum provider-supported scene duration. Semantic timing, editing boundaries and retiming after narration changes need further design and implementation. |
| Publishing | Complete video generation without an upload dependency. Initially defer upload automation and channel-growth tooling. | Existing optional Upload-Post integration offers YouTube, TikTok and Instagram; operator end-to-end publishing was not established in this development effort. Direct platform OAuth is not an approved replacement. |
| Factual content | Optional evidence/review mode must not burden creative generation. | User-supplied excerpts, safe one-page import, review-only workflow and structural claim checks exist. Automatic discovery/source authentication and real-model acceptance remain deferred. |
| Deployment | Start with a working single-product workflow; add multi-user infrastructure or new frontend only when real needs justify it. | No decision to add accounts, billing, distributed GPU scheduling, or a React editor now. |

## Deferred editor requirements to design incrementally

These are recovered **user goals**, not permission to replace the current
frontend or renderer in one step:

1. Reopen a completed task as an editable project. Preserve original/generated
   media and the active scene-version references. Keep final MP4 export.
2. Preview, replace and reorder individual scene clips. A manually supplied
   replacement must be validated and stored within the project; it should
   rerender without calling the AI video provider.
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

The first candidate editor milestone is an audit and specification of the
editable-project asset contract and change-impact rules, followed by the
smallest useful edit using existing task artifacts (for example validated
single-scene clip replacement). That is a **candidate**, not a locked design or
authorization for a frontend rewrite. Check the latest user request first.
