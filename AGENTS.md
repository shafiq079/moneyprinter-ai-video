# MoneyPrinter AI Video: Codex handoff

Before changing this repository, fetch `origin/development`, check the working
tree and recent commits, and read `PROJECT_CONTEXT.md` completely. Then read
`docs/SRS.md`, `docs/MIGRATION_MAP.md`, `docs/PRODUCT_VISION.md`, and the
documentation relevant to the task (`docs/LOCAL_AI_VIDEO.md` or
`docs/FACTUAL_MODE.md`). Treat the repository
and current remote history as the source of truth if a previous chat differs.

## OpenCut branch exception (owner approved 26 October 2026)

The owner explicitly requested a third branch, `opencut-editor`, to integrate
real OpenCut while keeping `development` as the previous-editor fallback.
The base integration was later promoted to `development` at the owner's request.
The combined native clip-controls/font milestone is authorized on `opencut-editor`
(27 October 2026). The owner subsequently approved the YouTube-first connected
accounts/reviewed publishing milestone on this working line, followed by the
Facebook Page/Reel publishing extension. The owner then approved replacing the
default YouTube integration with direct Google OAuth and in-product account/
content management on the same branch. On 28 October 2026 the owner approved
the equivalent direct Meta Facebook Page/Reel integration on this branch.
The owner then approved AI publishing copy and thumbnail preparation for both
direct platforms on this same working line (28 October 2026). The owner also
approved the Content Library and Batch Publishing Planner on this branch,
including optional automatic AI preparation and explicit batch approval. On
29 October 2026 the owner approved Content Campaigns and Automated Production
on this working branch, with separate production and publishing approval.
On 29 October 2026 the owner promoted the completed work to `development`
at 3a938c2 and approved narration-driven Automatic scene timing and tighter
scene-specific visual instructions on `opencut-editor`. Visual recognition and
automatic inspection of generated footage are explicitly outside this milestone.
On 31 October 2026 the owner approved reuse of the full generator settings
for campaigns, including shared defaults, per-video overrides and retained
provider-specific upload/charge/quote requirements, on opencut-editor.
Do not promote new changes to `development`/`main` without a
later instruction. This overrides the historical
two-branch restriction below for this experiment only.

## Project rules

- This product extends the original MoneyPrinterTurbo Python/WebUI architecture.
  `shafiq079/content-factory` is reference only; never replace the application
  with its Next.js/FastAPI/editor architecture.
- `main` is the stable baseline. Work directly on `development`. Do not create
  feature, fix, temporary, backup or experimental branches, and do not force
  push or overwrite newer remote work. Fetch before starting and before push.
- Preserve the existing local-AI scene manifest, versioning, same-task Resume,
  separate Regenerate, cancellation, render-only rerender, and upstream
  narration/composition pipeline. Use the fake provider for CPU tests. Do not
  claim local Wan/LTX hardware validation without a real GPU run.
- Creative mode is the default. The first optional factual-mode slice requires
  operator-approved excerpts and reviews claims before media generation. The
  WebUI has an explicit bounded HTTPS import helper, but tasks do not fetch or
  authenticate cited pages. See `docs/FACTUAL_MODE.md`.
- Never commit `config.toml`, credentials, checkpoint/model weights, generated
  task media, or machine-specific paths. HF authentication comes from the
  operator's environment (normally `HF_TOKEN`).
- Keep implementation focused on the user's requested outcome; update
  `PROJECT_CONTEXT.md` when an accepted milestone or architectural decision
  changes. Do not start a new feature merely to complete a setup/handoff task.

## Local computer and Codespaces

The local checkout is where Codex edits and reviews code. GitHub Codespaces
remains the place where the operator runs the WebUI and remote HF video tests.
The local checkout will not contain the Codespace's ignored configuration,
secrets, model files or `storage/tasks/` artifacts. Sync committed code with
`git push origin development` on the computer and
`git pull --ff-only origin development` in Codespaces; pull the latest
`development` locally before more edits. Follow `docs/LOCAL_CODEX_SETUP.md`.

The former ChatGPT Work conversation is separate from a new Codex chat. These
checked-in documents provide the durable technical handoff; inspect actual
Git history for the latest state rather than assuming the chat transcript is
automatically included.
