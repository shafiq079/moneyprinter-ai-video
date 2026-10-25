# Independent music and sound-effects editing

## Workflow

Open a saved creative AI project through **Task Manager → Edit → Music / SFX**.
This extends the current Streamlit editor and MoneyPrinter composer; it does not
replace narration, the generation manifest or the renderer.

1. Expand **Audio Library**, upload a WAV, MP3, M4A, OGG or FLAC, and choose
   **Import Audio**. Imports are limited to 50 MiB and ten minutes. They are
   decoded locally to immutable stereo 48 kHz PCM WAV assets. No model, TTS or
   external audio service is called. A project supports 32 assets and 32 clips.
2. Audition the uploaded asset, choose music or SFX and a timeline start, then
   **Add Audio To Timeline**. The clip initially uses as much of the source as
   fits the video. Imported music defaults to 25% gain; SFX defaults to 100%.
3. Select a clip in the timeline or inspector. Change timeline start, source
   in/out, type, volume, mute, fade-in and fade-out, then **Save Audio Clip**.
   Volume is a 0–2 gain multiplier. Overlapping clips are summed without automatic
   gain normalization; adjust their levels as needed. Source audio and narration
   remain separate. Source trims do not stretch or loop the recording.
4. Drag a clip to move it. Drag either edge to trim it: the left edge changes
   both timeline start and source in; the right edge changes source out. Trims
   must stay within the uploaded recording and fit the current video. Duplicate
   creates an independent clip at the same position; move that copy to its new
   location. Overlapping clips get separate visible lanes. Remove deletes a
   placement, retaining its source in the library for reuse.
5. Under **Audio Preview And Export**, choose whether to keep the pre-existing
   background music and save that choice. Narration always follows its existing
   gain/mix settings. **Preview Audio Arrangement** renders a preview using the
   saved visuals, narration and applied captions; it opens in the central player.
   Draft edits do not change the last exported MP4 or an applied arrangement.
6. **Apply Audio And Export** commits the current arrangement and rerenders the
   final video. Later visual/caption edits, render-only export and same-task
   Resume retain the applied audio arrangement. Reopening retains the draft too.
   **Reset Audio Draft** returns to the applied arrangement, or an empty timeline
   if none is applied. **Restore Original Audio Arrangement** removes the applied
   layer and renders with original BGM settings; it retains the draft/library.

For existing music, **Edit saved background music** imports the saved provider
BGM or resolved built-in/custom song as an editable music clip. It switches off
legacy BGM in the draft to avoid doubling it. Missing provider music is reported;
this button never requests a new paid/generated track. Random/custom legacy BGM
is snapshotted once while an arrangement is used so preview and export use the
same song. Existing provider BGM is reused through the normal renderer.

Preview is an explicit background render, not a live browser audio mixer. It
uses the same composition path as export and can take time on CPU. It includes
applied caption styling; unapplied caption drafts have their own caption preview.
The editor polls only a small job-status region; timers do not redraw editing
controls. A completed job refreshes the workspace once. Idle controls stay stable.

## Timing and compatibility

Audio placements use integer milliseconds, independently of visual cuts. Voice
and the current project length remain authoritative. If natural narration edits
shorten the project, rendering crops audio at the new end and skips placements
entirely beyond it. Persisted positions and source trims remain unchanged, so
lengthening the project can reveal them again. Audio does not automatically shift
with narration edits. A new or manually adjusted clip must fit the current video.

Legacy tasks without an applied arrangement use their existing audio/BGM behavior
unchanged. Creative saved AI projects, including No Voice projects, are supported.
Stock projects, factual projects, project archives, live waveforms, automatic
music ducking, looping controls and undo/redo are outside this milestone.

## Saved data and change-impact contract

- `audio_layers.json`: version-1 draft with original-audio SHA binding, assets,
  independent clip IDs and the legacy-BGM choice.
- `audio_layers_active.json`: independently applied snapshot. Draft changes do
  not mutate it. Active assets are hash-checked before composition.
- `audio_assets/<uuid>/audio.wav`: immutable validated uploaded media. Original
  temporary uploads are removed after decoding. File/protocol and format limits
  prevent uploaded playlist files from retrieving external sources.
- `audio_layer_mixes/<hash>.wav`: reproducible CPU overlay mix, bounded to the
  current narration duration. The mixer pads/trims by sample count and checks
  output duration. Output duration, bytes and subprocess runtime are bounded.
- `audio_base_music.json` and `audio_base_music/`: frozen legacy song reference
  and task-local copy. Host paths are not stored in these references.
- `audio_layers_preview.json` and `audio_previews/<uuid>/preview.mp4`: source,
  draft-revision, render-settings and scene-snapshot-bound preview.

All mutations use the existing bounded WebUI queue, same-task busy/cross-post
reservation and configuration lock. Stale drafts/sources/scenes are rejected.
Preview temporarily uses the draft on the existing composition path, backs up
and restores final/combined videos and the previous active arrangement, and
publishes the preview only after validation. Apply/restore also back up outputs;
failed renders restore the previous arrangement and videos. As with existing
caption/narration edits, multiple media files and sidecars are not a single
filesystem-wide atomic transaction across process termination.

Upload/placement/trim/gain/mute/fade changes are metadata/audio operations.
Preview/apply/restore are render-only operations using saved scene clips,
narration, captions and provider music. They make no new video-generation, TTS,
Whisper, paid-music or publishing request. Explicit existing scene regeneration
and narration generation retain their own separate semantics.

Output packages expose optional `audio_layers_draft`, `audio_layers_active`,
`audio_base_music` and safe `audio_layer_assets` references. Original scripts,
voice tracks, captions, scene plan, clips and scene versions remain authoritative.

## Verification

CPU tests cover actual decoded uploads, sample placement, source trims, fades,
gain/mute/silence, duplicate/remove, bounds, stale/busy rejection, active/draft
separation, real MP4 preview/apply/restore, rollback, cached-music reuse/import,
artifacts, reopening and partial same-task Resume without new narration or
captions. Browser checks use synthetic audio/video and exercise upload, editing,
timeline dragging, overlapping lanes, preview, reopen and singleton controls.
No real GPU, live TTS, paid music or publishing acceptance is claimed.

## Audio-only rendering and diagnostics

Preview/apply/restore reuse the saved combined visuals when their composition
record, source/settings signature and video bytes match and media validation
passes. Legacy files are reusable only if the saved inputs predate them. Missing,
corrupt or stale combinations rebuild through the existing composer. Normal
visual edits still recompose. Audio/caption mixing and final MP4 encoding remain
CPU render work; this does not create new AI clips, speech or paid music.

Audio-job start/finish logs include the action (`preview`, `apply`, `restore`,
etc.). The UI names that action rather than showing every job as a generic edit.
Reload reconnects to the current job and keeps the last completed video visible.
It never starts a new job. See the editor guide for selection/playhead retention.
