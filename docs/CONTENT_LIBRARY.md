# Content Library and Batch Publishing Planner

Approved on 28 October 2026 on `opencut-editor`. This connects the existing
Python/Streamlit generation, OpenCut, AI preparation, Google and Meta publishing
services into one workflow. No new publishing subscription or frontend build is
needed. Work remains on this branch until the owner requests promotion.

## Start

```sh
git switch opencut-editor
git pull --ff-only origin opencut-editor
uv sync --frozen
sh webui.sh
```

The generator navigation now exposes **Content Library**, **Publishing**, and
**Accounts**. These pages share links to **Create**, **Content Library**,
**Publishing**, and **Accounts**. The original individual Social Dashboard
composers and queues remain available for advanced/manual publishing.

## Set up the accounts once

1. Open **Accounts** and connect a YouTube channel or Facebook account/Page.
   See YOUTUBE_DIRECT.md and FACEBOOK_DIRECT.md for the operator's OAuth app setup.
2. Open **Publishing → Posting schedules**. Select each account and save its
   timezone, weekday/time slots, language and reusable publishing defaults.
   Review the audience and content declarations explicitly before saving.
   New defaults affect future batches; existing plans keep their reviewed values
   until explicitly edited/rescheduled.
   YouTube includes category, immediate visibility, AI/paid disclosure and optional
   automatic video-frame thumbnails. Facebook includes VIDEO/REELS and disclosure.
3. Scheduled YouTube posts use public release, regardless of the immediate-upload
   visibility default. The actual options and UTC times are shown for batch review.
   Facebook posts are public. Saving defaults does not authorize publishing.
4. Optionally enable **Automatically prepare AI copy for completed videos
   (no publishing)**, then save preparation automation. This opt-in can prepare
   existing library videos as well as future completed videos, using the configured
   LLM and saved account languages. Provider usage/cost follows your existing LLM
   configuration. Disable it to stop starting further automatic requests; an
   already-running request can finish. No model is called just by opening a page
   unless this preparation automation was explicitly enabled or a requested batch
   still has authorized preparation work to finish.

## Five Shorts to YouTube and Facebook

1. Generate your videos using any existing provider. Completed finals appear
   automatically in **Content Library**. In-progress tasks are not offered as
   completed videos. Older completed outputs remain discoverable after reload.
2. Each generation task has **one library entry** with original final outputs
   and retained OpenCut exports in **Final video version**. Multiple outputs from
   one task are versions/alternatives; the library selects one final per task.
   The original `final-1.mp4` is initially selected when available. New exports
   never silently replace your chosen final.
3. Preview a video, check **I reviewed this final video**, and **Save final
   version**. Editing is optional. **Edit in OpenCut** uses the existing editor
   handoff, in a separate tab. Return to the library, choose the corrected export,
   preview it and save it as reviewed. If its story differs from the saved script,
   add **Video summary for AI (optional)** before saving. An unchecked save can
   select a version while leaving it unready.
4. Select the five **Ready videos** (or **Select all ready videos**) and your
   YouTube/Facebook destinations. Choose **Next available slots**, **Choose start
   time**, or **Publish after approval**, then **Prepare publishing batch**.
   Five videos and two accounts create **ten independent posts**.
5. Background preparation loads or generates script/summary-grounded AI copy for
   each platform/language and freezes a direct-service delivery draft for each
   destination. YouTube tags and optional actual frame/text thumbnails are kept
   with that draft. Facebook WebM conversion and Reel checks use the existing
   Meta service. Nothing is uploaded by preparation. If there are no prepared
   forms yet, the progress fragment refreshes the page when preparation finishes.
   Otherwise use **Refresh batch** to avoid interrupting edits in open forms.
6. In **Publishing → Batches and review**, the table exposes each post's title,
   description, tags, account, time and preparation issue. Select a post to preview
   its exact frozen video/thumbnail, inspect complete settings, and edit copy or
   time. YouTube thumbnails can be rebuilt from another frame/text/installed font
   or removed. A Facebook format change needs a new draft so media preflight is
   not bypassed. Exclude unwanted unapproved posts without affecting others.
7. Review the prepared count and the **Not included yet** count. Check the batch
   review statement and **Approve prepared posts**. Only the currently prepared
   rows are approved; blocked/unfinished/excluded rows do not gain approval.
   Each account/video has its own durable delivery ID and independent result.
8. Use **Calendar / Queue** for a UTC week view or list, with account/state filters.
   Open a batch for full delivery controls: refresh, reviewed same-ID resume,
   supported rescheduling and actual remote cancellation. The library also shows
   per-destination status and a **Manage publishing** link for each project.

## Scheduling rules

Posting slots are per account and timezone. Each next-slot allocation skips
occupied times and local clock-change gaps/folds. Batch creation and schedule
edits share a catalogue lock, preventing competing batches from reserving the
same account/time. Exact-start mode spaces each account's videos by the chosen
minute interval. Immediate mode does not assign a schedule. Duplicate final-file
plans for the same account are blocked; direct-service duplicate protections also
remain in force.

Slot planning stays within **20 minutes to seven days ahead**, a conservative
shared application window. This is not a claim of every platform's maximum.
If there are not enough slots, add times or choose another mode; the planner does
not silently assign invalid dates. Approval and upload revalidate platform time
requirements, so a stale schedule blocks until explicitly changed. User-chosen
slots are not claimed to be engagement-optimized recommendations.

Schedules already accepted by YouTube/Meta can execute while MoneyPrinter is
stopped. Preparation, transfers and handing a schedule to the platform require
MoneyPrinter to be running. The existing gateway resumes persisted preparation
and approved deliveries at startup; ambiguous direct-service operations retain
their existing safety boundaries rather than starting replacement uploads.
The calendar requests bounded status refreshes while open, and manual refresh
remains available. A displayed state is the last confirmed result, not a promise
of real-time platform visibility.

## Review, versions and recovery

Readiness is tied to the selected source hash, file stamp and final-selection
revision. Changed/missing video files, a new selection or updated summary require
review again. Unapproved batches pointing at an earlier selection cannot be
approved as if they described the new final. Metadata/thumbnail edits change the
batch revision; an approval submitted against an older revision is rejected.

Already-approved posts retain their reviewed frozen media and settings. Changing
a library final does **not** replace or silently cancel them. Manage/cancel those
existing deliveries before planning a replacement. A YouTube cancellation keeps
its uploaded video private and removes a confirmed schedule; Facebook cancellation
deletes only a confirmed unpublished upload. Removing a local batch row is not a
substitute for cancelling an approved remote delivery.

Preparation failures are individual rows. Retry missing preparation explicitly;
known prepared children are recovered by a stable batch/item reference, including
a crash after child creation but before saving the parent link. Approval checks
child state before repeating any action, so a lost parent write does not approve
or upload a second copy. Source changes and unrelated approval failures do not
stop valid rows from proceeding. The existing direct APIs keep their own
same-session/same-ID reconciliation and ambiguous-outcome protections.

A serial bounded preparation worker reads persisted work, with at most 32 in-memory
queue entries, 50 posts per batch, 250 retained batches, and 1000 automatic
preparation records. Existing direct services impose their own limits too.
Automatic AI errors are retained and not retried forever on every page refresh.
Batch preparation can explicitly retry missing copy; an accurate summary can be
provided in the library. Preparation captures the operator LLM configuration after
the existing runtime configuration lock is released and never persists that
credential snapshot.

Catalogue, presets, source selections, preparation records and batches are
encrypted under ignored `storage/social/library`, using the existing social
credential key. Frozen media/thumbnails remain in the existing ignored publishing
assets directory. No account tokens are copied into batches or project archives.
This remains a trusted single-operator application, not a multi-user approval
system. No new GPU, speech generation, unattended publishing policy, analytics,
recurring reposting or third-party scheduling service is introduced.

## Verification boundaries

CPU tests exercise five videos/two accounts, exact versions, encrypted reload,
slot conflicts/concurrency/DST, explicit declarations, stale review rejection,
partial failures, same-child recovery, optional AI preparation, per-platform
cancellation and actual Main routes. Streamlit tests cover final selection, batch
creation, editing, reload, approval and posting defaults. A real decoded MP4 and
JPEG prove the library-to-two-platform pipeline against mocked AI/social transport.
Existing publishing, settings, generation and OpenCut regressions are checked.
No live LLM, Google/Meta authorization/upload or GPU inference is claimed.

Validation results: 224 publishing/OpenCut tests plus 10225 translation subtests
passed; 110 generation/task/artifact/archive tests plus 18 subtests passed, with
3 existing skips. The final dedicated library/planner run passed 29 tests. Ruff,
compileall, frozen sync, lock validation and whitespace checks passed.
