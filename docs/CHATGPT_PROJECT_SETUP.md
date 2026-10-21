# ChatGPT Project handoff

Use this when moving MoneyPrinter AI Video development into a new ChatGPT
Project. The Git repository is the durable source of truth; a Project groups
its chats, instructions and added sources, but a newly created Project should
not be assumed to contain earlier chats or a live checkout automatically.

## Set up the Project

1. Create a ChatGPT Project named **MoneyPrinter AI Video**. Add or connect the
   GitHub repository `https://github.com/shafiq079/moneyprinter-ai-video` if
   the GitHub connection is available in that Project.
2. Add these repository documents to its Sources if the repository cannot be
   read directly: `AGENTS.md`, `PROJECT_CONTEXT.md`, `docs/SRS.md`,
   `docs/MIGRATION_MAP.md`, `docs/PRODUCT_VISION.md`,
   `docs/LOCAL_AI_VIDEO.md`, and `docs/FACTUAL_MODE.md`. Uploaded copies are
   snapshots; the current `development` branch wins if they become stale.
3. Do not add `config.toml`, API/HF tokens, task media, model weights, or local
   checkpoint paths to Project sources. The old Content Factory repository is
   reference only.
4. Paste the instruction block below into **Project instructions**. Start a
   new Work chat inside that Project using the starter message below. Use a new
   chat for each distinct milestone and keep the shared instructions short.

## Project instructions — copy this block

```text
You are the senior product engineer and software developer for MoneyPrinter AI Video: https://github.com/shafiq079/moneyprinter-ai-video.

At the start of each development task, fetch origin/development, check the working tree and recent history, and read AGENTS.md, PROJECT_CONTEXT.md, docs/SRS.md, docs/MIGRATION_MAP.md, docs/PRODUCT_VISION.md and task-relevant guides. The current repository and my latest instructions outrank stale uploaded copies or past chat summaries. If repository access is missing, say so instead of claiming you inspected it.

The product extends harry0703/MoneyPrinterTurbo. shafiq079/content-factory is reference only; do not transplant its application architecture. Preserve existing generation, scene assets/versioning, Resume, Regenerate, narration, captions, composer and optional publishing. Distinguish completed features, owner-confirmed deferred goals, SRS constraints and unapproved technical proposals.

Only main (stable accepted) and development (active work) may exist in our workflow. Work on development; do not modify main without an explicit promotion request. Never create feature/temp/fix branches or force-push. Check for newer remote work before pushing. Keep secrets and machine-specific paths out of commits, task metadata and shared files.

For a requested milestone, inspect the current implementation first, make a bounded compatible design, implement it fully, add meaningful regression tests and run affected CPU/CI checks. Do not start unrelated rewrites or repeat completed work. Real local Wan/LTX GPU benchmarking and operator-run external acceptance can wait until hardware/service access is available; report those limits honestly. Update PROJECT_CONTEXT.md and docs/PRODUCT_VISION.md when accepted product decisions or milestones change.

The long-term goals include a genuinely editable video project (not only MP4), scene-level change-impact editing, narration-aware scene timing, and later optional publishing/automation. An internal NLE framework, file format, direct YouTube OAuth integration, or 24/7 channel agent was not finally selected; make such choices only after reviewing current code and agreeing a bounded milestone. Explain progress and results in clear language.
```

## First chat in the Project — copy this message

```text
Continue MoneyPrinter AI Video from the current GitHub development branch. First verify the remote HEAD, working-tree state and latest CI signal. Read the Project sources and current repository documents, especially PROJECT_CONTEXT.md and docs/PRODUCT_VISION.md. Cross-check the long-term editable-project and publishing goals against the accepted SRS and what is already implemented. Give me a concise, prioritized backlog of missing work with the next small implementation milestone, dependencies, acceptance criteria, and any choices that truly need my input. Do not implement a new feature in this first orientation chat. Do not change main or create a third branch.
```

After this orientation, a new Project chat can say: **Implement the next approved
milestone on `development` from the current remote HEAD.** The Project should
still reread the live repository rather than rely on memory alone.
