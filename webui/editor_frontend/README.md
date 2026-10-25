# MoneyPrinter editor component

An offline React timeline embedded in the existing Streamlit application through
Streamlit Components v2. Uses `@xzdarcy/react-timeline-editor@1.0.0` and React 18.
The existing Python scene plan, narration and caption sidecars remain canonical;
this component does not introduce a browser renderer or new project format.

```sh
cd webui/editor_frontend
npm ci
npm test
npm run build
```

`dist/` is committed so ordinary Python/Codespaces users do not need Node or a
frontend dev server. CI rebuilds it and rejects source/bundle differences. All
runtime assets are local; no browser CDN or third-party account is needed.
Third-party notices are distributed in `dist/THIRD_PARTY_NOTICES.txt`, with the
upstream editor's MIT notice retained under `licenses/`. Package-declared
licenses, including the timeline engine's ISC declaration, are recorded there.

The component connects to the native Streamlit video in the explicitly keyed
`editor_program` container. It observes replacement players, synchronises the
playhead, and releases event listeners/animation frames when unmounted. This
keeps Streamlit's existing local-media delivery and server/proxy configuration.
It uses ordinary DOM mounting because the timeline library's pointer/drag
handling needs document-level events. Component CSS selectors are scoped to the
workspace/timeline; no remote media URLs are accepted from timeline events.

Events contain stable scene/cue identifiers and a view revision. Python rejects
stale, busy, malformed or unsupported changes, then submits through the existing
validated task queues. Dragging visuals changes playback order; narration and
captions stay on their own clocks. Caption drags save a draft; Preview/Apply in
the caption inspector renders it. Visual duration handles rebalance the next
scene through the existing fixed-total timing contract. Last-scene, legacy and
active natural-narration duration changes use the inspector instead.

The music track and narration timing bars are selection targets, not generic
movable audio layers. Music gain lives in Export; narration edits remain in the
Narration inspector. Independent music/SFX placement, arbitrary video layers,
undo/redo and browser-side effects rendering remain future work.

The Streamlit v2 renderer is invoked again for each data update. A host-keyed
WeakMap reuses its React root, and cleanup removes the root/container only if
it belongs to that render. Do not append a root on every invocation. The
lifecycle regression test compiles the production renderer against a minimal
DOM/root harness and checks repeated updates and obsolete cleanup callbacks.
Frame seeks use the 30 fps delivery grid, including the final valid frame.
The browser bridge captures Unicode text selections only on explicit color
actions; playback/scrubbing remain browser-local.
