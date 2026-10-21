# Optional factual mode (first slice)

Factual mode is opt-in. Creative mode remains the default and does not request
evidence or run a claim review. The factual review occurs at the script stage,
before narration, local/remote materials, and final rendering. It works with
any existing video source. This phase needs no GPU.

## What the operator supplies

Add 1–6 distinct source URLs and supporting excerpts. Each URL must be HTTPS,
without embedded credentials, query parameters or fragments. You may paste an
excerpt yourself. In the WebUI, you may also enter a public HTTPS URL and click
**Import source excerpt**. This fetches a short suggestion once, fills the
existing source field and lets you edit it before generation. It rejects private
network addresses, redirects, non-HTML pages, oversized pages and slow reads.
Pages that require JavaScript or lack a readable paragraph need a manual excerpt.
The task itself never fetches a page, and CLI/API callers still supply their own
excerpts. The automated review checks whether script claims appear supported
by those excerpts. It cannot establish whether the page is authentic, whether
an excerpt was copied accurately, or whether the page is authoritative. Review
the source and final script yourself before publishing a factual video. Never
enter secrets in an excerpt.

In the WebUI, choose `factual` under **Content mode** and enter one line per
source:

```text
https://example.org/article | Article title | A copied supporting excerpt of at least twenty characters.
```

Then enter a subject or a complete script. If you provide a subject without a
script, the configured LLM drafts a script using those excerpts and a second
LLM call reviews its claims. If you provide a script, only the review call is
made. Factual mode ignores the custom system prompt for script generation;
custom script requirements are subject to the evidence constraint. A review
failure blocks the task before TTS/video calls. It does not silently replace a
user's narration. Creative mode follows the existing script path.

In the WebUI, **Review script only** queues the same factual script/review stage
and stops before narration, provider preflight, video generation or FFmpeg.
Task Manager shows the reviewed script and the review under **Artifacts**;
the approved script is saved in `script.json` so this result survives a WebUI
restart. You can load its settings with **Regenerate**, inspect or edit the
script, and start a separate full video task. The new task runs the review
again against its submitted script and excerpts. The script-only task is not a
same-task Resume and has no video to download.

CLI example (stop after the script for a zero-GPU check):

```bash
uv run python cli.py --video-subject "Moon surface" --content-mode factual \
  --factual-source "https://example.org/moon | Moon surface | The Moon has impact craters across its surface." \
  --stop-at script
```

The same fields work in API `VideoParams` requests and batch manifests:

```json
{
  "video_subject": "Moon surface",
  "content_mode": "factual",
  "factual_sources": [
    {
      "url": "https://example.org/moon",
      "title": "Moon surface",
      "excerpt": "The Moon has impact craters across its surface."
    }
  ]
}
```

When the reviewer returns a valid verdict, the task directory records
`factual_review.json` with source IDs (`S1`–`S6`), reviewed script hash,
individual claims/citations, verdict and limitations. Malformed or unavailable
LLM responses fail closed and can leave no review file.
The artifact package includes its task-relative path. Blocked tasks expose
`failed_stage=factual_review`; approved tasks continue through MoneyPrinter's
existing narration, planning, provider and composer. A same-task local-AI
resume reuses the approved saved script and media; Regenerate starts a new task
and runs the review for that new task. Resume rejects a factual task if the
approved review file is missing or its saved script hash or source excerpts no
longer match the task inputs. Keep the approved review with the task artifacts.

The WebUI Task Manager's **Artifacts** action is available for factual tasks
with a saved review, including blocked tasks that stopped before creating any
video. It displays the verdict, reason, claims with source IDs, and source
titles/URLs. The supporting excerpts remain in the task-local JSON but are not
repeated in this summary. The view makes the automated decision inspectable;
the operator still needs to check the underlying sources before publication.

The import button makes one server-side HTTPS request only after you click it.
The hostname is resolved and checked for public IP addresses, the connection
is pinned to a checked address with hostname-verified TLS, and redirects are not
followed. Imported text is a suggestion, not independently verified evidence.
The accepted URL/title/excerpt then follows exactly the same factual-mode task
path as a manually pasted source. This keeps saved approvals and same-task
Resume consistent and never causes a network fetch during retry.

**Deferred operator acceptance:** With the configured real LLM, run a
script-only factual task whose claims match a real copied source excerpt and a
second task with an unsupported claim. Confirm the first review approves and
the second blocks before media generation. This does not need video/GPU quota.
It is intentionally pending; CPU mock tests cannot measure the real model's
judgment or verify the source pages.
The optional import helper is covered by offline network-boundary tests; a
real public-page import in the operator's WebUI environment remains on the
same later acceptance list. It should be reviewed as a suggestion before use.

This is an optional Phase 7 workflow. Automatic source discovery, task-time
retrieval and source-authenticity checks are future work, and should be added
only after defining safe and dependable research inputs. The older Content
Factory research module remains reference only; its UI/API/job architecture is
not part of this application.
