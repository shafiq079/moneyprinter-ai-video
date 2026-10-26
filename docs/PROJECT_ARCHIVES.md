# Portable editable projects

Saved **creative AI scene projects** can be backed up and moved to another
MoneyPrinter installation running a compatible version. Stock/factual projects
are outside this first archive milestone.

## Save and restore

1. Open Task Manager → Edit → Export.
2. Choose **Prepare Project Download**, then **Download Editable Project**.
   Preparation requires an idle task. The download is a snapshot; prepare it
   again after further edits.
3. On the receiving installation, open Task Manager → **Import Editable Project**,
   upload the `.mptproject.zip`, and choose **Import and Open Project**.
4. Import validates the files and opens a new task in the full-page editor.
   Edit and render through the ordinary controls. Existing tasks are preserved.

Import does not call an LLM, voice generator, video provider or music service.
Rendering uses saved scenes, narration, captions and music. Explicit scene/voice
regeneration still requires the receiving operator's provider configuration.

The archive includes all retained scene versions, playback order/timing,
scene prompts/settings, original narration/script/captions, narration recordings
and active mixes, caption drafts/applied tracks/styles, audio assets and
music/SFX draft/applied arrangements. Saved final MP4s and generated BGM are
included. Narration-range audition files required by the existing range contract
are retained. Rendered editor previews, combined-video caches, logs, transient
backups, credentials, application configuration and model weights are excluded.

Legacy random/custom BGM is frozen into a task-local asset during preparation.
On restore its settings reference that saved song, so another machine does not
choose a new random song. Fonts are referenced by name rather than bundled;
the receiving installation must have the referenced fonts. A missing font is
reported during validation instead of silently changing caption appearance.

## Version-1 format and limits

The ZIP contains `project.json` with format `moneyprinter-editable-project`,
`schema_version: 1`, a task-relative original-audio reference, and an inventory
of every payload file's byte size and SHA-256. Payloads retain the existing task
layout and sidecar schemas; this is a transport envelope, not a replacement
canonical timeline. Unsupported versions are rejected explicitly.

Limits: 512 MiB archive, 2 GiB expanded content, 4096 payload files, 2 MiB per
JSON, 512 scenes, one hour of narration, at most 16 final outputs and 16 render
threads. Existing narrower narration/upload/caption/audio-layer limits still
apply. ZIP paths must be relative and unique (including case); links, directories,
unsupported entries, encrypted files, traversal and private host configuration
are rejected. Media is checked with restricted demuxers/protocols before normal
media validation. Inventory checks detect damaged files; this is not a signed
archive or proof of authorship.

Import extracts into a hidden staging directory, validates scene/range/layer
contracts and media, then atomically renames it to a new UUID task. Errors remove
staging and do not replace any existing project. The task remains discoverable
from disk after application restart; original narration references remain
relative. An interrupted process can leave a hidden staging directory, which
can be removed when no import is running. This does not add cross-process
transactions for edits to the source task: export checks the task is idle and
unchanged while copying, and serializes ordinary WebUI submissions in-process.

CPU regression tests remove the source task, restore independent edited layers,
reopen after state loss, render a real MP4 with provider calls blocked, and
re-export/re-import custom narration and frozen music. Negative checks cover
checksums, versions, references, missing files, links, traversal, playlist media
and size/count limits. Streamlit tests verify explicit preparation/download and
that ordinary reruns never submit an import.


On the owner-approved `opencut-editor` branch, archives additionally transport
`opencut/project.json`, SHA-addressed native media and completed native exports.
Native project metadata has an 8 MiB bound; the archive remains at most 512 MiB.
This adds a payload to the version-1 envelope and keeps the original layer
contracts. Reopen imported OpenCut drafts through Task Manager Edit. Installations
on older development code do not understand this additional native payload;
restore such archives with the OpenCut branch. See OPENCUT_EDITOR.md.
