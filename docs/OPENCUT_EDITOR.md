# OpenCut editor integration branch

The owner explicitly approved the additional `opencut-editor` branch on
26 October 2026. It starts at `development` commit
`df626edd3022863723382d7fedf58882ae688629`. The former editor and generation
pipeline remain unchanged on `development`; this experiment is not merged there
or into `main`.

## What is integrated

This is the real **OpenCut Classic** editor, not an imitation of its layout.
OpenCut's main repository currently describes a rewrite and recommends Classic
for the working editor. `webui/opencut_frontend/upstream.json` pins the reviewed
MIT-licensed Classic source at `cf5e79e919144200294fb9fed22a222592a0aeea`.

The build imports the upstream editor page, panels, timeline, command/undo
system, media handling, preview, properties and native WebCodecs exporter.
A small Vite host replaces Next routing/image/link wrappers and site-only
feedback/changelog components. The public-site Next layout, analytics, accounts,
Postgres, billing and hosted-service backend are not part of this integration.
No OpenCut source files are patched. Source is fetched at setup and dependencies
are locked in this repository. MIT and dependency notices accompany the build.

MoneyPrinter continues to generate scenes, voice, captions and music with its
existing Python pipeline. Task Manager → **Edit** opens the native full-page
OpenCut editor, outside Streamlit's rerender cycle. Both apps use the same
WebUI address through a local HTTP/WebSocket gateway, so Codespaces needs only
its ordinary WebUI port forwarded. No models or paid providers are called by
opening/editing/exporting an existing project.

## Run in Codespaces or locally

Install Node.js **22 or newer**, npm, Git and the project's usual Python/uv
requirements. Then stop the running WebUI and run:

```sh
git fetch origin
git switch opencut-editor
uv sync --frozen
uv run python scripts/setup_opencut.py
sh webui.sh
```

On Windows use `webui.bat` for the final command. Windows launcher changes are
provided; the full native browser acceptance was exercised on Linux.

Setup fetches the pinned source into ignored `webui/opencut_frontend/upstream`,
runs `npm ci --ignore-scripts`, and builds local static assets. Do not commit
that checkout, `node_modules`, compiled binaries or task media. Rerun setup after
pulling integration updates. Initial setup needs internet; ordinary local edits
and local-file exports do not require OpenCut's hosted application. Optional
upstream font/sticker/transcription tools can require their own downloads
or external services. The hosted sound-search panel is replaced by a clear
local-audio import shortcut; no Freesound credentials/backend are configured.
These are not new MoneyPrinter generation integrations.

To return to the previous implementation:

```sh
# Stop this WebUI first.
git switch development
uv sync --frozen
sh webui.sh
```

Configuration and task assets are retained. OpenCut drafts/exports are separate
from original generated files, so the old editor does not consume arbitrary
OpenCut timeline changes. Returning to `opencut-editor` reopens its saved draft.

## Import and persistence contract

This first integration opens the same saved **creative AI scene projects** as
the previous editor. Stock/factual editor expansion remains later work.

| Source | Initial native OpenCut representation |
| --- | --- |
| Active scene clips and visual order/durations | Separate video elements on the main track; source audio disabled to avoid duplicate narration. |
| Original or applied narration mix | Independent narration audio track with the saved voice gain. |
| Applied captions, otherwise existing SRT | Editable text cues with timing, color, size, basic background and position. |
| Music/SFX arrangements | Independent audio placements with source trims, gain and mute. Existing fades are retained in prepared audio clips; original recordings remain intact. |
| Legacy random/custom or saved generated BGM | Saved song imported locally and repeated as needed; no replacement provider request. |

Caption fonts initially use Arial. Selected-word colors, outlines, animations,
font metrics and custom compositor transitions do not have complete one-to-one
mappings in this OpenCut revision. Review styling in OpenCut before exporting;
original caption/style data is preserved. OpenCut itself is beta and its native
Transitions/Adjustment panels still contain upstream "coming soon" sections.
Using its source does not make those upstream features complete.

**AI / original tools** opens the preserved generation/version controls.
OpenCut's arbitrary cuts, overlays, effects and text are saved in its own native
project; they are not silently rewritten into MoneyPrinter's simpler scene
manifest. Later AI regeneration does not overwrite an existing OpenCut draft.
Use the native media import controls to incorporate replacement footage.

OpenCut autosave and **Save project** persist the native project plus immutable
media blobs under `storage/tasks/<id>/opencut/`. Browser IndexedDB/OPFS are working
caches; a fresh browser can rebuild the editable project from server storage.
Browser project IDs are scoped to the MoneyPrinter task, including imported
copies. Concurrent-tab revision checks reject stale overwrites, and unsaved or
failed server saves retain an unload warning. Reopen from Task Manager if a
session expires (12 hours).

The normal OpenCut **Export** renders in the browser and downloads MP4 or WebM
according to browser codec support. A successful export is also validated and
saved under `opencut/exports/`, separately from the original generated final.
Task Manager Play/download prefers the newest completed native export;
Artifacts exposes the native project/export references and downloads. MP4
encoding depends on the browser/platform. The automated native rendering check
uses WebM in Chromium and validates a video stream plus audio.

**Project backup** saves first, then downloads the existing `.mptproject.zip`
archive including the native OpenCut draft, media and exports. Task Manager's
existing project import restores these alongside the original editable assets.
Archive limits remain 512 MiB; native project metadata allows up to 8 MiB.
Individual OpenCut media/export uploads are bounded to 512 MiB. Temporary uploads
are not treated as completed exports.

Session capabilities are task-scoped and signed with an operator-local key.
Their fragment tokens are removed from the address bar and sent as authorization
headers, not media URLs. Source files resolve only within the task. Upload
hashes, bounded metadata, immutable asset names, atomic project writes and stale
revision checks protect the handoff. The gateway is for the existing trusted
operator deployment; it does not add a multi-user account system.

## Verification

```sh
uv run --no-sync python -m pytest -q test/services/test_opencut.py
# Optional reproducible CPU browser acceptance:
cd webui/opencut_frontend
npx playwright-core install chromium
cd ../..
uv run --no-sync python scripts/verify_opencut.py
```

The acceptance command creates and removes its own fake-provider fixture. It
checks native caption editing, server save, reload, a fresh browser, independent
tracks, native 1080×1920 export with audio, saving the export to the task, and
Streamlit Task Manager through the gateway. Output evidence is under ignored
`storage/opencut-browser-check`. No live GPU model, TTS, paid music or publishing
calls are made. CI builds the pinned source and runs this browser acceptance in
addition to the existing Python/platform checks and legacy frontend build.


## Forwarded page stays on the loading skeleton

The static Streamlit page can load while its live WebSocket fails. The gateway
checks actual and forwarded hosts without discarding a correct actual Host,
normalizes HTTPS authorities and recognizes the exact Codespaces hostname for
its selected public port. Internal WebSocket requests bypass environment
proxies. Origin checks remain enabled; arbitrary foreign domains are rejected.
The gateway reports origin rejections in terminal logs without printing cookies
or session protocols. Codespaces host construction uses GitHub's documented
`CODESPACE_NAME` and `GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN` variables:
https://docs.github.com/en/codespaces/developing-in-a-codespace/default-environment-variables-for-your-codespace

After pulling Python/gateway fixes, restart the WebUI; rebuilding the OpenCut
bundle is unnecessary. Stop old MoneyPrinter gateway and Streamlit child
processes if a prior shutdown remained running. Open the public port printed by
the launcher, not the random internal Streamlit port. POSIX port probing now
handles recently closed sockets, and gateway shutdown has a bounded grace time.
