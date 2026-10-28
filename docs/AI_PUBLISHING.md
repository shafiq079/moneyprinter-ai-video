# AI publishing preparation

Approved on 28 October 2026 on `opencut-editor`, for the direct YouTube and
Facebook dashboards. This extends the existing Python/Streamlit workflow and
configured MoneyPrinter LLM, without another publishing subscription or editor.

## Use it

1. Update the branch, run `uv sync --frozen`, then `sh webui.sh`. No OpenCut
   rebuild or new dependency is required.
2. Open **Social Dashboard → YouTube or Facebook → Create post**, choose an
   attached destination and a completed video/native OpenCut export.
3. Expand **AI publishing preparation**. Leave language as `auto` to follow the
   script, or enter the desired language. The saved task script supplies the
   content; no audio transcription or video generation is required. For an
   export whose edits changed the story, enter an accurate summary override.
4. Click **Generate AI publishing package**. One configured LLM request produces
   up to three title choices, a platform-specific description, relevant hashtags,
   a topic/focus, and thumbnail text/visual suggestions. YouTube additionally
   receives keyword tags; Facebook has no YouTube tag field. Hashtags are
   appended once to the description, not sent as a nonexistent API field.
   The generated copy fills the existing editable composer. Choose another title
   and **Use selected title and AI copy** if desired. Language/provider usage can
   have costs under the operator's configured LLM plan; no new paid service is
   mandated and local LLM configurations remain available.
5. For YouTube, click **Build thumbnail from video**. It extracts the selected
   frame (default zero seconds), fits it without cropping to a 1280×720 canvas,
   and draws the suggested/editable text. Select an installed MoneyPrinter font
   supporting your language and inspect the actual preview. A font that lacks
   glyphs can render missing characters; preview matters. Empty overlay text is
   allowed. This is a CPU frame/text layout, not an AI image-generation model.
   Include the thumbnail checkbox to attach it to delivery approval. Facebook's
   thumbnail idea is advisory: its current uploader does not set a cover image.
6. Review the filled metadata and choose audience, disclosures, category,
   visibility and timing yourself. AI never changes these account/compliance
   settings or approves publishing. Click **Prepare for review**, inspect the
   exact frozen video, publishing information and optional thumbnail, then
   separately approve the delivery. The delivered job's options are the final
   reviewed values, including any manual edits to the AI suggestions.

## Reloads, failures and recovery

Generated packages are encrypted under ignored `storage/social/publishing-seo`,
using the existing social credential encryption key. A package is isolated by
platform, task and export. It records source/script fingerprints, generation
ID/time, language, optional summary and validated metadata; it contains no
social OAuth tokens or LLM credentials. It is a publishing draft, not a public
endpoint or portable task-archive file. Regeneration replaces the current copy
only on success. Previously prepared delivery jobs retain their frozen metadata
and thumbnail independently of later regeneration.

A fresh dashboard restores saved AI copy without calling the model. Ordinary
reruns preserve edits already in the composer. Unsaved manual field changes
follow the existing session behavior; prepare a delivery draft for durable
reviewed values. Reload never invokes generation or authorizes a post. Changing
the source video or saved script invalidates the package; regenerate after
editing finishes. Script changes during generation and source changes before
snapshotting are checked. The optional summary is the operator's description of
the final edit; the model does not watch or fact-check the video itself.

Malformed/empty/overlong model output is rejected. Provider failure is explicit,
retains the previous draft and current edits, and never substitutes heuristic
copy labelled as AI success. The request passes a 90-second timeout and zero SDK
retries to the existing JSON helper; timeout enforcement varies with the selected
provider adapter. There is no unbounded new background generation queue, automatic
provider switch, social API call or scene/TTS regeneration during SEO preparation.

YouTube thumbnails are validated, content-addressed JPEG files under the existing
ignored publishing assets directory (under 2 MiB). Approval rechecks their hash.
The transport sends raw image bytes to Google's dedicated
`/upload/youtube/v3/thumbnails/set` endpoint with the image content type.
Delivery saves the remote video ID, applies the thumbnail to that same private
upload and only then applies public visibility or the schedule. A failed thumbnail
keeps the delivery pending, including when the requested visibility is private;
refresh cannot falsely mark it complete. Resume retries the same-video thumbnail
operation, without creating another upload. A lost response may repeat the same
thumbnail replacement safely. Channel restrictions still apply; this code cannot
grant YouTube custom-thumbnail eligibility. No Facebook thumbnail is uploaded.

Existing direct manual composition and legacy Upload-Post behavior remain
available. This milestone does not automatically generate SEO from the old
legacy auto-upload path. It does not authorize unattended publishing or eliminate
the existing approval gate. It automates the writing and thumbnail layout after
an explicit preparation request.

## Metadata quality and boundaries

The prompt treats supplied script/summary text as content, asks for factual
alignment, and disallows invented numbers, links, trend/search-volume claims,
misleading promises or irrelevant keyword stuffing. Application validation limits
titles to 100 characters, description body to 4500, hashtags to five and YouTube
tags to twenty within a conservative 450-character budget (including separators
and quotation allowance for phrases). The combined description stays below
5000 characters. Generated URLs/contact details are rejected. Thumbnail text is
at most 60 characters. These are application policies, not ranking scores.

Title, thumbnail and description should accurately describe the video. No
algorithm/ranking guarantee, measured search-volume research, competitor analysis,
A/B test, live trends, analytics feedback, captions translation or automatic
chapters are claimed. The AI can still make mistakes, which is why copy and the
actual thumbnail remain editable and part of explicit review.

Primary references checked during implementation:

- [YouTube thumbnail media-upload endpoint](https://developers.google.com/youtube/data/reference/rest/v3/thumbnails/set)
- [YouTube video resource and metadata fields](https://developers.google.com/youtube/data/reference/rest/v3/videos)
- [YouTube hashtag guidance](https://support.google.com/youtube/answer/6390658)
- [YouTube thumbnail and title guidance](https://support.google.com/youtube/answer/12340300)
- [YouTube discovery/performance guidance](https://support.google.com/youtube/answer/141805)

CPU verification covers structured response validation, prompt grounding,
platform isolation, encrypted reload, stale-source checks, explicit failures,
real frame-to-JPEG layout, thumbnail-before-release ordering and private-delivery
recovery. Streamlit AppTest covers both composers, alternate titles, saved copy,
manual-edit preservation and separate review. Regression suites cover direct and
legacy social publishing, translations and OpenCut. No live LLM, OAuth/social
upload, GPU or speech provider call is required or claimed by these tests.

Final validation: **199 focused tests and 10225 translation subtests passed**;
25 checks specifically cover AI preparation and its UI. An earlier broad run
had an intermittent WebSocket TestClient cleanup CancelledError. The baseline
comparison and final full rerun passed without gateway/test changes. Ruff,
compileall, frozen dependency sync, lock and whitespace checks passed.

## Library and batch workflow

Content Library and Publishing now connect final-version review to per-account
AI preparation, posting defaults/slots and explicit batch approval. See
[CONTENT_LIBRARY.md](CONTENT_LIBRARY.md). Individual composers remain available.
