# Campaign content cards — implementation plan (1 November 2026)

Approved on opencut-editor only. Preserve development/main and the generation,
recovery, quote, input-retention and publishing approval contracts.

1. Compose content before campaign creation. Start with one stable-ID card; add,
   remove or adjust up to 20 cards. Removing nonempty content requires confirmation.
2. Each card owns subject, narration script and visual-search keywords. Keep the
   draft in non-widget session state across ordinary reruns and settings navigation.
   Creating a campaign saves the complete validated list atomically, without AI,
   speech/media calls, generation queue submission or publishing.
3. One explicit AI action fills missing fields for all/one selected card. Include
   existing content and writing defaults as context; preserve nonempty fields by
   default. Explicit replace confirmation authorizes regeneration. Validate exact
   IDs/count, lengths, keyword types and distinct subjects/scripts before applying
   any model result. Failure leaves all draft edits intact.
4. Shared production settings show reusable writing defaults and video/audio/
   caption controls only. Reuse the main generator's writing controls; hide the
   per-video subject/script/keyword tools. Clear keywords from new shared templates.
5. Save keywords per campaign item, expose them in individual editing, and freeze
   them with production approval. Keep old approved snapshots intact. For Automatic
   stock matching, keywords are hints subordinate to each scene's actual narration.
6. Show readable production summaries. Raw parameter JSON is optional advanced
   detail. Review content before create; separately approve actual production later.
7. Verify manual and AI flows, stable add/remove, protected edits, malformed AI
   rollback, settings round-trip, canonical keywords/quote invalidation, worker
   delivery and single-generator regression with CPU fixtures/mocked providers.

## Operator workflow

1. Pull opencut-editor and restart `sh webui.sh` (no OpenCut rebuild is needed).
2. Open Campaigns → New campaign. Enter the brief, language and intended accounts.
3. Set the count or use **+ Add video**; each card has its own subject, narration
   script and visual keywords. Empty keywords remain valid for automatic searches.
4. Configure shared production settings for writing rules, video source/timing,
   voice/music and captions. Returning preserves the cards in this browser session.
5. Use **Generate all scripts and keywords with AI**, or a card's **Generate with AI**.
   Existing nonempty fields are preserved. To replace content, use the explicit
   replacement controls. All generated content remains editable before creation.
6. Review and **Create campaign**. This persists the planned content; then separately
   review effective settings/quotes and **Approve campaign production** to render.
7. Review completed videos in Content Library; edit in OpenCut if needed. Publishing
   still requires its own approval.

Before creation, cards/settings are a browser-session draft, not a saved campaign.
A cold browser session can lose that unsaved draft. After creation, reviewed cards
are stored with the existing encrypted campaign record. No new scheduler or
unattended approval is introduced.

## Verification

182 tests passed across the final focused and regression runs, including 10225
translation subtests. Covered card add/remove/count protection, edit preservation,
scoped regeneration and malformed-model rollback; real Streamlit Main routing and
shared-settings round-trip; complete create without calls/queueing; independent
keywords and frozen approval; existing worker, library, OpenCut and narration
contracts. Ruff, compile, whitespace and frozen offline dependency checks passed.
Tests used mocked AI/providers and CPU fixtures. Actual live AI output quality,
provider rendering and social-account acceptance were not exercised.
