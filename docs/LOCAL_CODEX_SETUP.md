# Local Codex setup and project handoff

This guide is for a Windows computer with the ChatGPT desktop app already
installed. Codex edits a local Git checkout; the existing GitHub Codespace
continues running the application and holds its ignored configuration and
generated videos. No local GPU or model weights are needed for this setup.

## 1. Clone `development` on Windows

Install Git for Windows if `git --version` is unavailable. In PowerShell, choose
your preferred parent folder and run:

```powershell
git --version
New-Item -ItemType Directory -Force -Path "$HOME\Projects" | Out-Null
Set-Location "$HOME\Projects"
git clone --branch development https://github.com/shafiq079/moneyprinter-ai-video.git
Set-Location .\moneyprinter-ai-video
git remote add upstream https://github.com/harry0703/MoneyPrinterTurbo.git
git fetch origin development
git status --short --branch
git rev-parse HEAD
git ls-remote --heads origin
```

The clone URL becomes `origin`. `upstream` is for deliberate comparison with
the original MoneyPrinterTurbo and must not be merged casually. If `upstream`
already exists, skip `git remote add upstream`. Expect exactly `main` and
`development` from the final command. Do not check out `main` for active work.
GitHub authentication may prompt when you first push; sign in through Git's
normal credential flow instead of storing a token in a project file.

## 2. Open the repository in Codex

Sign in to the ChatGPT desktop app with the account used for this Work chat.
Choose **Codex** from the app selector, add a **local project** rooted at
`$HOME\Projects\moneyprinter-ai-video` (or your chosen clone folder), and
start a **Local / This computer** chat on `development`. Keep the repository
root as the primary folder so `AGENTS.md` is discovered. Do not select
Worktree or Cloud for this two-branch workflow.

Paste this as the first Codex message:

> This is the MoneyPrinter AI Video project. Read AGENTS.md and
> PROJECT_CONTEXT.md completely; then read docs/SRS.md,
> docs/MIGRATION_MAP.md, docs/LOCAL_AI_VIDEO.md and docs/FACTUAL_MODE.md.
> Fetch origin/development and inspect Git status and recent commits. Confirm
> the current project state, branch policy, completed milestones, deferred
> hardware checks and the next proposed task. Do not change code yet. I edit
> locally and run the WebUI in my existing GitHub Codespace. Work directly on
> development and never create another branch.

Once Codex reports the actual current state, give it one specific next task.
The old Work transcript is not part of a new Codex chat by default. The
checked-in handoff documents and Git history carry the durable decisions.
You can view the old Work conversation in the ChatGPT side of the desktop app
with the same account, and attach it to a Codex chat if the app offers that
action. Do not depend on transcript transfer for repository instructions.

## 3. Sync code to the running Codespace

After reviewing local edits and tests, in the Windows checkout:

```powershell
git status --short --branch
git fetch origin development
git status --short --branch
git push origin development
```

Codex can make focused commits on `development` after checking that remote
`development` has not advanced. If it has, integrate the newer work without
resetting or force pushing. In the existing Codespace:

```bash
git switch development
git pull --ff-only origin development
sh webui.sh
```

Before starting the next local Codex task, pull any Codespace commits into
the Windows checkout:

```powershell
git pull --ff-only origin development
```

The Codespace's ignored `config.toml`, environment secrets, model setup, and
`storage/tasks/` media stay there; Git does not transfer them. Keep the HF
token in Codespaces secrets. If you want Codex to inspect a generated video or
task artifact, explicitly provide it or access the Codespace separately.

Optional local CPU verification needs the repository's pinned Python/`uv`
setup; use `uv sync --frozen --python 3.11` and the commands in
`.github/workflows/ci.yml` if you install those tools. Running the app locally
is not required for this handoff.
