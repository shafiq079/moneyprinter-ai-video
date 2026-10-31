# Campaign production settings — implementation plan

Approved 31 October 2026, opencut-editor only. Preserve development/main.

- Reuse the four existing generator panels in a full-page campaign settings
  route. Do not duplicate source/voice/font lists or build another editor.
- New campaigns use saved shared production settings; planned videos may inherit
  them or save a complete override. Settings are editable only before production.
- Reuse the existing upload and provider validation/submission preparation with
  a narrow save callback. Saving settings never queues generation. One output
  per campaign item is enforced; campaign count remains the number of outputs.
- Persist approved upload/reference inputs with checksums and copy task-local
  narration into each real task. No browser UploadedFile object enters the queue.
- Keep all generator sources visible. Shared quote-based settings can be selected,
  but every quoted video needs its own current script-bound quote before approval.
  Ordinary paid providers retain per-video charge confirmations. Factual items
  retain the existing task-time evidence gate.
- Freeze per-video effective parameters and input bindings at revision-bound
  production approval. Model/voice options stored in task parameters stay distinct;
  credentials/endpoints remain operator configuration. Do not persist secrets.
- Plan AI scripts using shared language, paragraph count and script instructions;
  preserve explicit per-video script edits and language overrides.
- Validate reload/restore, shared vs override/reset, stale approvals, immutable
  approved settings, worker parameter delivery, missing/tampered uploads, quote
  binding, and existing single-video generation. Use CPU mocks, not paid calls.

## Where to find it

1. Campaigns → New campaign → **Configure shared production settings**.
2. The full-page screen has **Script**, **Video**, **Audio**, and **Subtitle** tabs
   using the same controls as Create. Voice selection is the real provider/voice
   dropdown; source, fonts, colors, timing, matching, music and preview controls
   follow the normal generator. Configure shared operator credentials through
   the existing settings dialog if needed.
3. Click **Save campaign production settings** to return. This only saves inputs;
   it does not plan scripts, call video providers or queue production. Voice
   previews and explicit script/quote/readiness actions remain deliberate actions.
4. Create the campaign and plan scripts. Existing campaigns have **Edit shared
   production settings** while every item is still unapproved.
5. Select a planned video → **Edit this video production settings**. Saving creates
   an independent override and saves its topic/script edits together. **Reset to
   shared settings** restores inheritance. Shared changes do not replace overrides.
6. Review all effective video parameters. Approve paid provider charges where
   applicable, then separately approve production against the current revision.
   Per-video settings lock after approval. Review/publishing remain separate.

One campaign item creates one video. The generator's output-count control is
fixed to one here; choose campaign count on the campaign page. Shared topic/script
fields are examples; planning uses language, paragraph count and script instructions
for distinct scripts. Use item settings to edit the actual script. Individual
language selections override the campaign fallback language.

## Inputs and provider requirements

All main-generator sources are offered, with the same upload/provider checks.
Custom narration, local footage, uploaded/preset music and reference voices are
supported. Shared uploaded narration/media is reused by every inherited item;
use overrides to supply different recordings or footage. Reopening settings retains
saved inputs. Switching away from uploaded narration or local media removes that
mode's input from the new settings snapshot rather than silently reusing it.

Retained inputs live under ignored `storage/social/campaign-inputs/<id>/`.
Files are copied with private permissions and bound by SHA-256; media inputs are
bounded to 200 MiB per file and reference audio to 64 MiB. Existing upload type/
provider validation remains in the generator. Metadata stays in encrypted campaign
records. Task-owned narration is copied into the final task before generation;
server-file permissions are not relaxed. Missing/tampered inputs block work.
Music continues to resolve through the existing allowed music directories.
Do not remove retained input directories while campaigns still reference them;
there is no automatic campaign-input garbage collector in this change.

LoomLoom can be selected in shared settings without a quote, because scripts do
not exist yet. Before production, open **each video's** settings, obtain its quote,
confirm and save. Script/settings changes invalidate its bound quote. Each item
needs a different request ID. Credential values are never stored with the quote;
settings are rebuilt at execution from current operator configuration. An endpoint
or listing change blocks the old quote. Quoted failures use existing individual
request recovery; a new campaign is required for another quoted new attempt.
Other paid video sources retain their item-level confirmation controls; campaign
production additionally requires a review of all listed paid outputs.

Factual campaigns must include excerpts and still pass the existing evidence
review for each script before media generation. Selecting factual mode does not
constitute factual approval. Automatic duration remains limited to its supported
stock/local-AI sources and provider bounds, exactly as on Create.

## Configuration and compatibility

Generation styles/voice/subtitle choices do not overwrite generator defaults.
Supported non-secret model/encoder options are snapshotted and applied under the
existing worker runtime lock, then restored. Provider endpoints, credentials,
model/checkpoint locations and operator infrastructure remain shared configuration.
New credentials can be configured in the existing dialog; they are not copied into
campaign records. CPU/GPU requirements and remote charges are unchanged.

Legacy campaigns without overrides/input packages retain their prior behavior.
Approved settings cannot be edited while queued/running or after completion.
Failures retain prior task IDs/assets; generation never grants publishing approval.
Settings for a not-yet-created campaign are a browser-session draft; create the
campaign to make them durable across a cold browser session.

## Live acceptance checklist

- Configure a voice using the dropdown, several caption controls and Automatic;
  create two videos and verify both receive the settings.
- Override one video's source/voice/captions; confirm the other still inherits.
- Upload narration or reference audio; reload after saving and verify reuse.
- Check one paid-source charge review and each quoted video's individual setup
  using the operator's own account. No live charge/provider test was run here.
- Confirm a completed output can still open in OpenCut and enter Content Library
  without editing; publication remains separately reviewed.

Campaign topic planning continues through the configured LLM. Alternate script
creation helpers in the shared screen act on its example script; on an individual
video they act on that video's script. Saved language/paragraph/instruction fields
feed campaign planning. Replacing an AI campaign plan is blocked while independent
video overrides exist, so settings and quotes cannot disappear silently; reset
those overrides first or create another campaign.

Campaign metadata is bounded below the existing encrypted-record limit. If an
expanded approval snapshot is too large, the previous readable campaign is kept
and no generation is queued. Split unusually large campaigns rather than deleting
input history. The quote's displayed currency/task count/estimated amount is saved
for final review; it is an estimate, not a guarantee of total provider costs.

## Verification record

Final generator/campaign/voice-preview/worker/library/OpenCut regression:
**216 passed, 3 existing skips, 10243 subtests**. After final quote-summary and
replanning protection, focused campaign/settings/worker/i18n regression:
**82 passed, 10225 subtests**, including **16 dedicated settings tests**. Counts
overlap and are not a unique-test total. Ruff, compilation, frozen dependency sync,
lock validation and whitespace checks passed. Existing source-specific controls,
charge/quote checks, narration, preset restoration and music were exercised with
CPU mocks. No live model, TTS, paid source, stock API, GPU or social call was made.

Real Main AppTest checks cover shared controls, no-generation saves, independent
item overrides, cold restoration, retained narration and switching back to TTS.
AppTest sometimes retains old widget nodes after a mid-render route change; the
generator-default return check uses a fresh render with preserved session backup.
This is not a claim of completed browser layout/navigation or live provider
acceptance. Use the operator checklist above for those checks.
