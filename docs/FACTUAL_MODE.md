# Optional factual mode (first slice)

Factual mode is opt-in. Creative mode remains the default and does not request
evidence or run a claim review. The factual review occurs at the script stage,
before narration, local/remote materials, and final rendering. It works with
any existing video source. This phase needs no GPU.

## What the operator supplies

Add 1–6 distinct source URLs and supporting excerpts. Each URL must be HTTPS,
without embedded credentials, query parameters or fragments. The app **does not
fetch the page**: the excerpts are supplied by the operator. The automated
review checks whether script claims appear supported by those excerpts. It
cannot establish whether the page is authentic, whether an excerpt was copied
accurately, or whether the page is authoritative. Review the source and final
script yourself before publishing a factual video. Never enter secrets in an
excerpt.

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

This is the first Phase 7 slice. Automatic source discovery, independent page
retrieval and source-authenticity checks are future work, and should be added
only after defining safe and dependable research inputs. The older Content
Factory research module remains reference only; its UI/API/job architecture is
not part of this application.
