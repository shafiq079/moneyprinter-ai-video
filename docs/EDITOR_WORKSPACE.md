# Dedicated video editor workspace

The owner requested a desktop video-editor layout rather than editing controls
inside Task Manager. **Task Manager → Edit** now opens a separate full-page
workspace (`?editor=<task-id>`). Back returns to the full-page task list; the
generator and its settings remain a separate screen. Editor deep links survive
refreshes. Missing/invalid tasks show an error and Back action, without creating
new projects or invoking models.

## Interface and operations

- Media library: searchable, paged saved scenes, cached CPU thumbnails, clip
  availability and selected-scene buttons.
- Preview: existing exported video, selected raw clip, or a validated rendered
  caption draft. Playback, seeking and 1/30-second stepping connect to the native
  Streamlit player. It keeps the existing task-media serving/proxy configuration.
- Timeline: zoom, ruler, playhead, ordered visual clips, narration ranges,
  caption cues and a music-settings track where music is configured. Clicking a
  block selects its inspector and seeks the preview. Playback advances the
  playhead entirely in the browser, without per-frame Python requests.
- Inspector: only the selected scene, narration range, caption cue, or Export
  settings. Existing trim/upload/prompt/seed/version/regeneration, narration
  draft/review/apply/restore and caption split/merge/add/remove operations remain
  available. Global narration/caption workflow actions are collapsible so the
  selected item's fields remain reachable.
- Export: render-only settings, existing music/narration gain, fit/transitions,
  caption font size, rerender queue and final MP4 downloads. This does not invoke
  a video model or publish the video. Selecting a new speech/scene generation
  action in its inspector retains the existing explicit provider semantics.

Dragging a visual clip changes visual playback order through the existing
reorder queue. Narration and captions keep their own timing. Visual duration
handles rebalance the following scene through the fixed-total timing service;
coverage and normal-speed rules still apply. Last-scene, legacy-layout and
active natural-narration timing changes use the inspector. Unavailable footage
is rejected, never stretched or generated automatically. Existing automatic
scene lengths and natural narration retiming remain authoritative.

Caption moves/resizes update the prepared caption draft through the existing
source/revision-validated caption queue. Preview or Apply in Caption actions
renders those changes. Original captions and an already applied track remain
unchanged until Apply. Narration and music bars select their settings; they are
not arbitrary movable audio layers. Music/SFX placement, multiple overlapping
video layers, browser rendering, undo/redo and portable project interchange
remain future work. This workspace covers the existing saved AI-scene projects;
it does not manufacture scene manifests for stock tasks or bypass factual gates.

Idle editing does not poll or remount the timeline. The v2 renderer reuses one
React root on each data update and cleans it up only on unmount; updates must
never append additional timelines. Active background jobs poll
progress and refresh the workspace after completion. Refresh also reloads
external changes. Busy/stale events are rejected before being submitted, with
existing worker validation and rollback still in force. Opening the editor,
selecting a scene, thumbnailing and transport controls perform no inference.

## Open-source selection and integration decision

Reviewed primary repositories:

| Candidate | Published license | Decision for this milestone |
| --- | --- | --- |
| [OpenCut](https://github.com/OpenCut-app/OpenCut) | MIT | Full application; keep as design/reference. Integrating it would require a separate adapter for our task assets, project state and exports. |
| [OpenReel Video](https://github.com/Augani/openreel-video) | MIT | Full application; keep as reference. Do not replace our saved projects and Python renderer with a second editor/runtime. |
| [React Timeline Editor](https://github.com/xzdarcy/react-timeline-editor) | MIT | Embed the reusable timeline component, with native Python inspectors and existing edit/export services. |

The owner approved using open-source editing code. The selected dependency is
`@xzdarcy/react-timeline-editor@1.0.0`, React/React DOM 18.3.1, bundled with pinned
esbuild and an npm lockfile. Its timeline-engine package declares ISC in package
metadata. Upstream and transitive notices accompany the offline bundle. No code
from OpenCut/OpenReel or the older Content Factory application was transplanted.
This is an embedded React component inside the existing Streamlit product,
not a new Next.js application, replacement renderer or canonical project schema.

`webui/editor_frontend/` owns source, build instructions, tests, lockfile,
licenses and checked-in `dist/`. Ordinary users need only the Python dependency
sync; Node is needed only to develop/rebuild the component. CI rebuilds the
bundle and checks for differences. There is no browser CDN dependency, account,
paid editor SDK or separate frontend dev server in the deployed application.

`app/services/editor_workspace.py` is a read/command adapter. Stable scene IDs,
scene snapshots, source-bound caption revisions and a hashed view revision
protect dispatch. Browser events cannot choose arbitrary filesystem assets or
write manifests directly; accepted edits call the existing queues. Scene plans,
scene versions, narration/caption sidecars and task state remain canonical.
Existing rollback, same-task Resume, Regenerate and publishing boundaries remain.
The caption queue also now infers completed status from saved final output after
an in-memory-state restart, rather than marking a successful draft edit failed.

## Frame seeking and caption appearance

Use **Exported video** to scrub the complete program. Ruler clicks and playhead
drags seek the paused native player; Next/Previous frame advance one 30 fps
output frame. Zoom supports 0.5x–30x, with frame subdivisions at high zoom.
Seeking at the end selects the last frame rather than the timestamp past it.
The selected raw-clip preview is limited to its own footage and uses its scene
start as the timeline offset. These controls do not submit Python requests per
frame. They do not play the video just to reach a chosen frame.

In **Captions → Caption Appearance**, choose All Captions or Selected Caption.
Font files include available font faces/styles. Controls include size, text
color, background on/off/color, rounded background, stroke color/width,
position/custom percentage and spring animation. Save Caption Style updates
the draft. A cue override inherits global style until saved; Reset Caption
Style removes its override. Preview Caption Draft or Apply Captions And Export
renders the saved appearance in the central preview/final video.

For a text-only highlight, select characters in the saved Caption Text field,
then click **Selected Text Color** in the timeline toolbar. The color section
opens with that exact range, including the correct occurrence of repeated
words. Pick a color and apply. Numeric range controls are also available;
start is zero-based and end is exclusive. Clear Text Colors removes the cue's
ranges. Unsaved text must be saved before its selection can be styled. Existing
ranges survive timing-only changes; changing text or splitting clears ranges,
and merging uses the first cue's style. Global/cue styles survive all these
operations. Caption timing/display grouping remains the saved editable cues;
this does not rerun word alignment or TTS.

The existing source-bound version-1 sidecars accept optional top-level `style`,
per-cue `style` and per-cue `spans` fields. Styles are bounded and font names
resolve only within shipped fonts. Ranges are ordered non-overlapping Unicode
code-point intervals with hex colors. Plain-text SRT is unchanged; sidecars
retain styling. Preview and final export use the same renderer, including
per-cue overrides and partial-text colors. Applied tracks remain independent of
later draft changes, and existing restoration/rollback rules still apply.

## Verification boundary

CPU tests cover read-only workspace loading/thumbnails, unsafe task IDs, stable
view revisions, stale/busy event rejection, queue payloads, caption state recovery,
full-page routing/selection/Back, native inspectors and translations. Automated
Chromium checks use synthetic local video and audio: real playback/playhead,
selection/seek, caption dragging, Export access, Task Manager Edit navigation,
responsive desktop layouts and visual dragging/rerendering. No live GPU, TTS,
paid music or publishing acceptance is claimed. Operator manual acceptance
remains deferred.
