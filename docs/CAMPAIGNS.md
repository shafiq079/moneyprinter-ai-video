# Content Campaigns and Automated Production

Approved 29 October 2026 on opencut-editor. Extend the existing Python/WebUI;
keep generation, library and direct publishing as separate services.

## Implementation plan and acceptance contract

1. Create an encrypted campaign brief, language, 1–20 video count, generation
   template and intended destination accounts. No credentials or account tokens
   are embedded. Capture templates from existing tasks or normal video settings.
2. Request AI topic/script planning explicitly. Return distinct, editable items
   grounded in the brief, not claimed live research. No media calls during planning.
3. Review all topics/scripts and template before separately approving production.
   Item/template changes increment a revision; stale approvals fail.
4. Queue one item at a time through the existing serialized WebUI task manager.
   Save the task ID and execution intent before submission. Disable the legacy
   auto-publishing path for every campaign generation, regardless of global setting.
5. Preserve completed siblings and original attempts on failure. Resume local AI
   with existing saved context; stock or explicit full restarts create a new
   attempt ID, without deleting earlier artifacts. Never automatically restart
   an interrupted provider request with an unknown outcome.
6. Pause blocks new starts; cancellation requests the existing cooperative task
   cancellation for the active item. Completed media is retained.
7. Completed items appear in Content Library for visual review and optional
   OpenCut edits. Campaign view groups its projects and reads current final selection.
8. Build a publishing batch from ready campaign items, using existing AI copy,
   account defaults and slots. Bind the resulting batch ID to the campaign.
   Publishing still requires the existing, separate batch approval.
9. Show per-item planning, production, attention, review and per-account delivery
   states. Recovery reconciles retained finals and queued/running task intents;
   refresh does not call AI or authorize generation/publishing.
10. Verify with mocked AI/providers and CPU fixtures, existing service/UI suites,
    and an operator checklist for live acceptance. Never publish test content to
    a real account automatically.

## Scope choices

Creative campaigns initially support Pexels, Pixabay and registered local AI
providers. Factual scripts retain the individual evidence-review workflow; paid
quote/confirmation providers, uploaded/reference audio and task-local material
paths are not silently reused in a campaign template. Local AI still needs the
operator's real compute; CPU tests do not validate model inference or quality.
This milestone adds no recurring unattended campaign creation, trend scraper,
analytics, ranking guarantee or automatic public-post approval.

## Operator workflow

Open Campaigns from navigation. Enter a brief and count; choose a generation
source/voice/language or load a completed task's supported template. Plan with AI,
edit the resulting topics/scripts and review production settings. Approve
production once. Monitor progress, pause between items, cancel the active task,
or explicitly retry a failed attempt. Open Content Library to review the actual
videos and choose any edited exports as finals. Return to Campaigns and prepare
publishing for ready items, then review/approve in Publishing.

The application must run during planning, production and media transfer. Native
Google/Meta schedules already accepted still follow the existing contracts.

## Recovery and persistence

Campaigns are encrypted under ignored `storage/social/campaigns`, using the
existing social key. Up to 100 campaigns, 20 items per campaign and ten intended
accounts are retained. Scripts/templates and generation task IDs are durable;
credentials remain in the existing operator configuration. Production settings
are frozen before approval; current configured provider credentials are resolved
by the existing generation wrapper under its runtime configuration lock.

A completion receipt records a successful pipeline result plus a decodable final,
not merely the existence of an MP4. If a final-validation failure left a file,
the item stays in attention. After a crash, an unconfirmed provider operation
is not automatically repeated. Inspect the retained task; resume supported local
AI context, explicitly start a new attempt, or accept an existing final after
review. Earlier attempts remain available and completed siblings are unchanged.
Stock retries are new attempts, not a promise of narration/scene-level resume.
Campaign pause does not cancel already-approved native social schedules.

Only one campaign item at a time enters the existing shared WebUI task manager.
An item lease and persisted intent prevent duplicate execution; queued approved
work is recovered on startup. Planning/production errors never approve a post.
Publishing can be prepared for successful, visually reviewed items even while
other campaign items need attention. Missing account/video pairs are prepared
without repeating existing delivery plans, splitting batches at the existing
fifty-post boundary when necessary. Batch links and per-account results are
visible in the campaign. Destination accounts can be updated explicitly; existing
batches retain their approved targets/settings.

## Live acceptance checklist (operator-run)

Automated tests use mocked AI/providers; they do not establish live provider or
account eligibility. For acceptance, first configure a stock provider and voice
and create a small campaign on a test niche. Check the following in order:

- Planning produces the requested distinct editable scripts, without media calls.
- Production approval starts generation; pause/resume and one intentional failure
  preserve completed items and task IDs. Inspect actual narration, captions,
  duration and footage before marking originals/edited exports ready.
- AI publishing copy matches the actual video, including any summary override.
- Prepare destination-specific drafts and inspect exact times/settings. Use a
  private YouTube test upload and an appropriate Facebook test Page only after
  explicitly reviewing and approving those real deliveries.
- Verify actual platform processing/publication, reconnect/recovery and schedule
  confirmation. Do not infer live success from mocked transport tests.

No GPU benchmark, paid model call, actual OAuth authorization or social post is
performed automatically as part of implementation verification.

## Automated verification

The broad run passed 274 tests, 3 existing skips and 10243 subtests across
campaigns, library/publishing, OpenCut, task generation, archives and UI labels.
After final ownership/status hardening, all 20 dedicated campaign/service/UI
checks passed again. This includes the real task pipeline's no-auto-publish
flag even when the global legacy setting is enabled. Ruff, compileall, frozen
dependency sync, lock validation and whitespace checks passed. The live
acceptance checklist above is not claimed completed by those mocked tests.
