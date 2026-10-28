# Automatic narration-driven scenes

## Approved implementation plan (29 October 2026)

Work on opencut-editor; development at 3a938c2 is the preserved baseline.
Improve Automatic only, retaining fixed-duration and historical saved-plan behavior.
No visual recognition, model downloads, new speech service or paid retries.

1. Persist a narration timeline from existing TTS cues or matching captions.
   Validate full script coverage and monotonic bounded times. Preserve original
   text; reject unrelated transcripts as timing evidence. Explicitly distinguish
   timestamped cues from text-proportional estimates (including No Voice).
2. Use sentence/clause and available word boundaries for variable-length shots,
   covering actual audio exactly within provider ceilings. Long coarse cues need
   estimated subdivision; report that limitation. Provider adapters keep ownership
   of minimum generation duration/frame quantization; playback can trim their tail.
3. Feed fixed narration spans into the existing AI director. Require the specific
   subject/action in each span, continuity without importing later actions, and
   no unsupported factual detail. Existing resume reuses the saved scene plan.
4. Offer Automatic for Pexels/Pixabay/Coverr too. Search each planned scene using
   its own narration, bounded query alternatives and enough decoded footage.
   Never substitute another scene's footage or loop short material to fill a gap.
   A stock no-result blocks at materials with its scene identified.
5. Render explicit ordered scene durations through the existing composer, keeping
   captions on their original speech clock. No independent random batch allocation
   for this mode. Store source/query records and timing quality for review.
6. Verify offline boundary cases, real CPU composition, fixed-mode regression,
   local resume, caption handling and UI restoration. Run lint and relevant suites.

Acceptance: each scene binds text and an interval; intervals cover measured audio
without gaps; no interval exceeds its ceiling; narration text is fully covered in
order; render does not shuffle/loop/stretch; old plans remain readable. Tests prove
structure/timing, not actual provider visual relevance. Operator live acceptance
remains necessary for real voices, stock search quality and generated visuals.

## Operator workflow and implemented bounds

In video settings select **Clip Duration → Automatic (recommended)**. It applies
for Wan/LTX/local-HF providers and Pexels/Pixabay/Coverr. Stock retains its previous
numeric default until Automatic is selected. Numeric choices retain the old
maximum-duration behavior; existing tasks retain their saved parameters.
The legacy API/CLI field remains `local_ai_duration_mode="auto"` for compatibility,
including stock. Other remote paid services retain existing fixed controls.
No OpenCut rebuild or new dependency is required.

Automatic uses actual measured audio length and existing TTS cues (Edge/Azure),
or matching caption timestamps when no TTS timings exist. Text-proportional TTS
fallbacks and No Voice are labeled `estimated_text`. Unusable/mismatched cue text
cannot be treated as actual alignment. Subdivisions inside a coarse cue are
interpolated and separately flagged. This is not forced alignment or speech
recognition; unavailable exact timing cannot be recovered without another service.
Sentence-ending shots are preferred; long sentences split on available word/clause
boundaries. Leading/trailing pauses stay covered. Playback is quantized by the
existing renderer to 30 fps; sample-accurate visual cuts are not claimed.

The recorded script is never rewritten to fit shots. Captions use their existing
TTS/Whisper timeline rather than shot duration weights. If captions are enabled
but no caption track was produced, Automatic stops before footage generation and
asks the operator to check the caption/voice settings. Caption styles are unchanged.

Local generation ceilings come from the registered capability and configured
provider limit. Adapters retain minimum-generation-length and frame quantization;
extra generated tails are trimmed for playback. Stock has a 10-second application
playback ceiling and a maximum of 100 scenes per search plan. Each scene gets
1–3 queries and examines at most five candidates per query. Short/corrupt media
and previously used remote URLs are rejected; no-result errors identify the scene.
The search planner is one bounded LLM request (180 seconds, no SDK retries).
No blind generic-topic fallback or additional paid generation is introduced.

Multiple Automatic stock outputs share the same ordered scene assets. A result
notice states this explicitly. Fixed mode retains independent batch allocation.
Stock query relevance is instruction-based, not a measured visual confidence score.
Queries and scene text are supplied to the operator's already configured model.

## Persistence and recovery

`narration_plan.json` stores exact script spans, planned start/end/duration,
script/audio hashes, timing source and interpolation status. Stock additionally
stores scene queries, selected assets and any failed scene ID. `script.json`
contains its timing summary and selected-source provenance. The artifact package
exposes the plan; portable local-AI archives retain it. Old archives need no new
sidecar. Local-AI manifests/scene plans continue to own versioning, regeneration,
resume and editor timing. OpenCut imports those existing saved scene durations.
Stock OpenCut import continues its existing rendered-video behavior.

Same-task local-AI Resume never rebuilds the narration plan or changes the saved
scene recipe; manual/historical plans remain supported. Stock does not acquire a
new automatic retry system: existing new-task regeneration is still explicit.
The renderer checks stock asset order, audio hash, intervals and footage coverage
before composing. Result warnings identify estimated timing and shared variants.

## Operator acceptance still required

- Generate one short with a voice returning word timestamps. Check a clear topic
  change against the voice, captions and saved scene cut.
- Repeat with the selected non-timestamped TTS provider; confirm the estimate notice.
- Use Pexels and Pixabay with several concrete subjects. Review saved per-scene
  searches and footage relevance. A failed scene must stop rather than borrow clips.
- Compare a numeric duration task to its previous behavior.
- Interrupt and resume one local-AI task, then open it in OpenCut. Confirm retained
  clips, narration and scene timing. GPU/provider calls are operator-controlled.

Offline tests validate timing, coverage and recovery contracts. They do not prove
real stock-search relevance, TTS accuracy or visual fidelity from video models.

## Verification record

Generation/material/voice/subtitle/archive run: **230 passed, 3 existing skips**.
Task/editor/OpenCut/campaign run: **180 passed, 3 existing skips, 10266 subtests**.
Final timing/UI/i18n run: **45 passed, 10225 subtests**. Final narration-plan
suite after coverage hardening: **20 passed**. Counts overlap between focused and
broad runs and are not a unique-test total. Lint, compilation, frozen dependency
sync, lock validation and whitespace checks passed. CPU render fixtures show the
first shot before, and the second shot after, the planned 1.1-second boundary.
Local-AI failure/resume and render-only recovery retain narration and valid assets.
No live provider/model/TTS/social call or GPU inference was used.
