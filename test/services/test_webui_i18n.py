import ast
import json
import re
import unittest
from pathlib import Path

from app.models.llm_provider import get_llm_provider
from app.utils import utils


ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"
I18N_DIR = ROOT_DIR / "webui" / "i18n"
LLM_PROVIDER_TIPS_PREFIX = "llm_provider_tips."
TTS_PROVIDER_TIPS_PREFIX = "tts_provider_tips."
SECONDARY_LOCALES = ("az", "ca", "de", "es", "fr", "id", "it", "ko", "pt", "ru", "tr", "vi")
PROVIDER_TIPS_PREFIXES = (
    LLM_PROVIDER_TIPS_PREFIX,
    TTS_PROVIDER_TIPS_PREFIX,
)
# 合作 Provider 的品牌名和长说明只维护中英文。次要 locale 统一回退英文，
# 避免把完全相同的品牌名复制十份，也避免长说明后续只更新部分语言。
ENGLISH_FALLBACK_KEYS = frozenset(
    {
        'Back to campaign',
        'Campaign production settings',
        'Campaign video is unavailable.',
        'Configure shared production settings',
        'Edit shared production settings',
        'Edit this video production settings',
        'Effective video production settings',
        'I approve paid provider charges for all listed campaign videos',
        'Inherits shared settings',
        'Per-video override',
        'Production settings are locked after approval.',
        'Re-upload task inputs in shared production settings.',
        'Reset to shared settings',
        'Review all video settings',
        'Save campaign production settings',
        'Saved uploads are retained. Upload a replacement to change them.',
        'Shared settings apply to inherited videos. Per-video overrides remain independent. Campaign count controls the number of outputs.',
        'Shared topic and script fields are examples only. Campaign planning creates the individual scripts using your language and script instructions.',
        'These are the same controls as the single-video generator. Saving settings does not generate videos.',

        'Earlier generation attempts',
        'Accept retained final after review',
        # Campaign labels use English fallback in secondary locales.
        'Approve campaign production',
        'Campaign',
        'Campaign brief',
        'Campaign dashboard',
        'Campaign destination accounts',
        'Campaign is busy. Refresh shortly.',
        'Campaign language',
        'Campaign publishing timing',
        'Campaign video',
        'Campaign video source',
        'Campaigns',
        'Cancel active generation and pause',
        'Choose video settings below',
        'Create a campaign to begin.',
        'Create campaign',
        'Enable captions',
        'Generation settings template',
        'Generation task',
        'I reviewed every topic, script and generation setting and approve production',
        'I reviewed this failed task and approve this recovery attempt',
        'Include the niche, audience, target video length, tone and topics to include or avoid.',
        'Inspect generation tasks',
        'Intended publishing accounts',
        'Mark final videos ready in Content Library first. Publishing preparation creates drafts and does not approve uploading.',
        'Match video clips to narration automatically',
        'Narration voice name',
        'New campaign',
        'Number of campaign videos',
        'Open campaign publishing batch',
        'Pause new campaign items',
        'Plan several videos, approve their scripts, then review the finished videos before publishing.',
        'Plan topics and scripts with AI',
        'Planning campaign scripts...',
        'Planning never starts video generation. Source credentials and local AI compute must be configured before production.',
        'Prepare publishing for ready campaign videos',
        'Production settings',
        'Recovery method',
        'Refresh campaign',
        'Resume queued campaign items',
        'Resume saved local AI task',
        'Retry campaign item',
        'Review campaign videos in Content Library',
        'Save campaign accounts',
        'Save campaign script',
        'Start a new attempt; keep earlier files',
        'Status refreshes automatically. Refresh the campaign to load updated controls.',
        'Video narration script',
        'Video topic',
        'Select all ready videos',
        # Library and batch publishing maintain English/Chinese with fallback elsewhere.
        'AI copy and frozen delivery drafts are being prepared. Refresh this batch to see progress.',
        'Account posting defaults',
        'Account to configure',
        'After approval',
        'All videos',
        'Approve prepared posts',
        'Automatic preparation uses your configured LLM and saved account languages. It never marks videos ready, approves posts, or uploads them.',
        'Automatically prepare AI copy for completed videos (no publishing)',
        'Batch timing',
        'Batches and review',
        'Build video-frame thumbnails automatically',
        'Calendar',
        'Cancel existing delivery',
        'Change this thumbnail',
        'Changing Facebook format requires a new batch after excluding this post.',
        'Changing the final version does not replace already-approved posts. Manage or cancel those deliveries in Publishing.',
        'Choose a new time',
        'Choose start time',
        'Complete a video to add it to your library.',
        'Connect YouTube or Facebook in Accounts first.',
        'Connect accounts, then save their posting defaults in Publishing before preparing a batch.',
        'Content Library',
        'Create',
        'Delivery state',
        'Edit in OpenCut',
        'Edit this publishing draft',
        'Exclude this unapproved post',
        'Filter by account',
        'Filter by delivery state',
        'Final video version',
        'Find a video',
        'Friday',
        'I reviewed the final videos, destination accounts, metadata, thumbnails and exact publishing times',
        'I reviewed these reusable publishing defaults',
        'I reviewed this existing delivery and the action below',
        'I reviewed this final video',
        'Keep planned time',
        'Library filter',
        'Library page',
        'List',
        'Manage publishing',
        'Minutes between videos per account',
        'Monday',
        'Needs review',
        'Next available slots',
        'No planned posts yet.',
        'Not included yet',
        'Only prepared posts listed for review are approved. Blocked or unfinished posts stay unapproved. Each destination uploads independently.',
        'Open published post',
        'Planner view',
        'Post to review',
        'Posting defaults saved.',
        'Posting schedules',
        'Posting times (HH:MM, comma separated)',
        'Posting weekdays',
        'Posts still preparing',
        'Preparation automation saved.',
        'Preparation creates separate drafts for every video and destination. Nothing is uploaded until you review and approve the prepared posts.',
        'Prepare a batch from Content Library first.',
        'Prepare publishing batch',
        'Prepare selected videos',
        'Prepared posts',
        'Publishing',
        'Publishing batch',
        'Publishing destinations',
        'Ready to publish',
        'Ready videos',
        'Rebuild thumbnail',
        'Refresh batch',
        'Refresh planner',
        'Remove this thumbnail',
        'Retry this preparation',
        'Review completed videos here. Editing is optional; choose an original or an OpenCut export as the final version.',
        'Review these defaults before saving.',
        'Saturday',
        'Save draft changes',
        'Save final version',
        'Save posting defaults',
        'Save preparation automation',
        'Scheduled YouTube posts use public release, even if the immediate-upload default is private. Review the exact settings in each batch.',
        'Some automatic AI preparations failed. Batch preparation retries missing copy; an edited export may need an updated summary in the individual composer.',
        'Sunday',
        'The selected final version is unavailable. Select and review another version.',
        'Thursday',
        'Times are shown in UTC. Each account has its own timezone and posting schedule. Open a batch to review or manage a delivery.',
        'Tuesday',
        'Updated video summary',
        'Use this if an edited export changes the saved script. Leave blank to use the original script.',
        'Video summary for AI (optional)',
        'Videos found',
        'Wednesday',
        'Week containing',
        'YouTube cancellation keeps the upload private. Facebook cancellation deletes only a confirmed unpublished upload.',
        'posts',
        # AI publishing labels use English fallback in secondary locales.
        'AI copy filled in below. Review it before preparing the delivery.',
        'AI preparation runs only when requested. Reloading this page never calls the model or approves a post.',
        'AI publishing preparation',
        'Build thumbnail from video',
        'Facebook uses the description and hashtags below. Thumbnail ideas are advisory; this uploader does not set a Facebook cover.',
        'For edited OpenCut exports, supply an updated summary if the saved script no longer matches the video.',
        'Generate AI publishing package',
        'Include this thumbnail in the reviewed YouTube delivery',
        'Leave blank to use the saved script. Include only what the finished video actually contains.',
        'Main topic',
        'Preparing publishing copy with AI...',
        'Preview the text and choose an installed font that supports your language.',
        'Publishing language',
        'Suggested title',
        'The video or saved script changed. Regenerate AI copy and review any text remaining in the form.',
        'This thumbnail is included in your delivery approval.',
        'Thumbnail font',
        'Thumbnail frame time (seconds)',
        'Thumbnail idea',
        'Thumbnail overlay text',
        'Use auto for the script language, or enter a language such as English or Urdu.',
        'Use selected title and AI copy',
        'Uses your configured LLM and saved script. Accurate titles, descriptions and hashtags help viewers understand the video; ranking is not guaranteed.',
        'Video summary override (optional)',
        # Direct Facebook dashboard uses English fallback in secondary locales.
        'Approve direct Facebook delivery',
        'Attach selected Facebook Page',
        'Authorize on Facebook, return here, refresh available Pages, then attach the intended Page. Connecting an account alone never approves a post.',
        'Cancel Facebook delivery',
        'Cancel delivery and delete any confirmed unpublished Facebook upload',
        'Change Facebook publication time',
        'Check Facebook Page connection',
        'Configure one Meta app, then connect your Facebook account and explicitly attach the Pages you want to manage. Upload-Post is not required.',
        'Connect Facebook',
        'Connect Facebook and attach a Page in Accounts first.',
        'Connected directly to Meta',
        'Continue with Facebook',
        'Delete Facebook video',
        'Disconnect Facebook account and its Pages',
        'Enable Facebook Login with Page permissions. Register this exact callback URL. Development mode uses app-role/test accounts; other users can require App Review and business verification.',
        'Existing Upload-Post records remain separate. They are never converted or resent through Meta automatically.',
        'Expired credentials were removed locally. Revocation was not confirmed; remove the app in Facebook Business Integrations settings.',
        'Facebook Login for Business configuration ID (optional)',
        'Facebook Page identity verified.',
        'Facebook Page to attach',
        'Facebook access revoked and local connections removed.',
        'Facebook callback URL',
        'Facebook changes saved. Reload Page videos for current values.',
        'Facebook content type',
        'Facebook video',
        'I reviewed these changes to the Facebook video',
        'I reviewed this Facebook delivery and approve resuming it',
        'If using a Business Login configuration, choose a user access token configuration with Page permissions.',
        'Load Facebook Page videos',
        'Meta Graph API version',
        'Meta app ID',
        'Meta app secret',
        'Meta application setup',
        'Meta developer applications',
        'Meta returned no videos for this Page and content type.',
        'No direct Facebook drafts or deliveries yet.',
        'No publishable Pages are available. Check Page selection, content creation tasks and app permissions, then reconnect.',
        'Permanently delete Facebook video',
        'Published Facebook Page videos are public. WebM exports are converted locally to MP4 before review.',
        'Refresh available Facebook Pages',
        'Review direct Facebook delivery',
        'Revoke Facebook access and remove these Page connections',
        'Save Facebook changes',
        'Save Meta application',
        'Saves recheck Page ownership and the current video. Meta can restrict editing some published media.',
        'Social platform',
        'This app accepts Reels of 4–60 seconds, 9:16, at least 540×960 and 24–60 fps. Use Page video for other formats.',
        'This app schedules Facebook publication 15 minutes to seven days ahead. Meta must confirm acceptance.',
        'This permanently deletes the remote Facebook video. Your local MoneyPrinter video/project remains.',
        "This revokes this Meta app's Facebook access, removes its attached Pages and local delivery history, and retains your local videos. It does not disconnect YouTube.",
        'YouTube connects directly to Google; Facebook Pages connect directly to Meta. Upload-Post is only used by legacy publishing.',
        'Project Archive Help',
        'Prepare Project Download',
        'Preparing Project',
        'Download Editable Project',
        'Project Snapshot Help',
        'Import Editable Project',
        'Project Import Help',
        'Project Archive',
        'Import And Open Project',
        'Validating Project',
        'All Captions',
        'Apply Selected Text Color',
        'Caption Appearance',
        'Caption Style Preview Help',
        'Caption Style Scope',
        'Clear Text Colors',
        'Reset Caption Style',
        'Save Caption Style',
        'Selected Caption',
        'Selected Text Color',
        'Text Selection End',
        'Text Selection Start',
        'Add Audio To Timeline',
        'Apply Audio And Export',
        'Audio Arrangement Preview',
        'Audio Asset',
        'Audio Clip',
        'Audio Clip Muted',
        'Audio Clip Type',
        'Audio Clip Volume',
        'Audio Editor Unavailable',
        'Audio Fade In',
        'Audio Fade Out',
        'Audio Layers Help',
        'Audio Library',
        'Audio Music And SFX',
        'Audio Preview And Export',
        'Audio Sound Effects',
        'Audio Source In',
        'Audio Source Out',
        'Audio Timeline Start',
        'Audio Upload Limits',
        'Duplicate Audio Clip',
        'Import Audio',
        'Keep Existing Background Music',
        'Preview Audio Arrangement',
        'Refresh',
        'Remove Audio Clip',
        'Reset Audio Draft',
        'Restore Original Audio Arrangement',
        'Save Audio Clip',
        'Save Background Music Choice',
        'Upload Music Or SFX',
        'Edit Saved Background Music',
        'Audio Rendering Preview',
        'Audio Applying Arrangement',
        'Audio Restoring Arrangement',
        'Audio Saving Draft',
        # Direct YouTube dashboard: en/zh with English fallback elsewhere.
        '22 is People & Blogs. Use a YouTube video category ID.',
        'A scheduled publication goes public at the reviewed UTC time. Uploads begin privately; YouTube controls processing and publication eligibility.',
        'Accounts',
        'Approve direct YouTube delivery',
        'Calendar / Queue',
        'Cancel delivery; keep any uploaded video private',
        'Change publication time',
        'Channel identity verified.',
        'Check channel connection',
        'Connect YouTube',
        'Connect a YouTube channel in Accounts first.',
        'Connected directly to Google',
        'Content',
        'Continue with Google',
        'Create post',
        'Custom thumbnail',
        'Delete YouTube video',
        'Delivery',
        'Disconnect and remove credentials',
        'Enable YouTube Data API v3, configure the consent screen, and register this exact callback URL in your Web application client.',
        'Existing Upload-Post records remain separate. They are never converted or resent through Google automatically.',
        'External Google apps in Testing may require reconnection after seven days. Production use can require Google verification and YouTube compliance review.',
        'Google Cloud credentials',
        'Google application saved. You can now connect a channel.',
        'Google application setup',
        'Google callback URL',
        'Google client ID',
        'Google client secret',
        'Google opens in a new tab. Authorize the intended channel, then return and refresh accounts.',
        'Google revocation can affect other channels authorized with the same Google app. They may need reconnection. Uploaded videos are not deleted.',
        'I approve the new public publication time',
        'I reviewed these changes to the existing YouTube video',
        'I reviewed this delivery and approve resuming it',
        'I reviewed this thumbnail for the selected YouTube video',
        'JPG or PNG thumbnail, up to 10 MiB',
        'Leave blank to keep the saved secret. Credentials are encrypted on this server.',
        'Legacy Facebook publishing',
        'Legacy YouTube publishing',
        'Legacy publishing',
        'Load channel videos',
        'Load existing videos directly from YouTube. This does not upload or change anything.',
        'Load more videos',
        'Metadata edits retain an existing private video schedule. Changing visibility can remove that schedule.',
        'No channel videos returned by YouTube.',
        'No direct YouTube drafts or deliveries yet.',
        'Permanently delete YouTube video',
        'Refresh accounts',
        'Resume existing delivery',
        'Review direct YouTube delivery',
        'Revoke Google access and remove this connection',
        'Save Google application',
        'Save YouTube changes',
        'Schedule public release',
        'Social Dashboard',
        'The operator configures one Google Web application. Channel owners then use Connect YouTube; no Upload-Post account is required.',
        'This deletes the remote YouTube video permanently. The local MoneyPrinter project is retained.',
        'Thumbnail submitted to YouTube.',
        'Type the video ID to confirm deletion',
        'Update publication time',
        'Upload thumbnail',
        'YouTube category ID',
        'YouTube changes saved. Reload channel videos to see current values.',
        'YouTube channel',
        'YouTube connects directly to Google. Facebook currently uses the separate legacy Upload-Post integration.',
        'YouTube data last loaded in this session. Reload before making changes; saves verify the current channel and video again.',
        'YouTube video',
        # Facebook Studio maintains en/zh; other locales use English fallback.
        'Approve Facebook upload',
        'Choose a Page',
        'Complete sign-in in the new tab, return here, then refresh Facebook Pages.',
        'Connect / reconnect Facebook',
        'Connect Facebook and refresh available Pages first.',
        'Connect a Facebook Page, review a completed video, then publish or schedule it.',
        'Connect an account you manage, then choose a Facebook Page. Personal profiles are not supported.',
        'Connected Facebook Pages',
        'Continue to Facebook sign-in',
        'Destination Facebook Page',
        'Disconnect Facebook',
        'Disconnect Facebook from this profile',
        'Facebook Page posts are public. Review your Page before approving.',
        'Facebook description',
        'Facebook format',
        'Facebook title',
        'I reviewed the Facebook Page before retrying this failed delivery',
        'I reviewed this video, Facebook Page and public publishing settings',
        'Label this Reel as AI-generated',
        'No available Pages. Check your Page permissions on the provider connection page, then refresh.',
        'Open Facebook post',
        'Page video',
        'Pages',
        'Prepare a Facebook post',
        'Provider-pinned Page',
        'Reel',
        'Reels: 3–90 seconds, 9:16, at least 540×960 and 24–60 fps. Use Page video for other formats.',
        'Refresh Facebook Pages',
        'Refresh existing profiles or create a publishing profile to connect Facebook.',
        'The provider AI-generated label is available for Reels only. Add any needed disclosure to the description for Page videos.',
        # YouTube Studio maintains en/zh; other locales use the English fallback.
        'A permanent identifier, for example my_channel. This is not your Google email or channel name.',
        'Add publishing profile',
        'All reviewed settings',
        'Approve YouTube upload',
        'Approve schedule',
        'Audience declaration',
        'Cancel delivery',
        'Cancel draft',
        'Channel ID',
        'Channels',
        'Choose an audience',
        'Complete a generated video or export a video from OpenCut first.',
        'Complete sign-in in the new tab, return here, then refresh channels.',
        'Completed video',
        'Compose & review',
        'Connect / reconnect YouTube',
        'Connect a channel, review a completed video, then publish or schedule it. Facebook is available in Facebook Studio; TikTok and Instagram are planned for later.',
        'Connect and refresh a YouTube channel first.',
        'Connected',
        'Connected YouTube channels',
        'Contains paid product placement',
        'Contains realistic altered or synthetic content',
        'Continue to YouTube sign-in',
        'Create profile',
        'Date, time and timezone apply only when Schedule is selected.',
        'Delivery approved. Track it in Delivery history.',
        'Delivery details',
        'Delivery history',
        'Delivery time',
        'Destination channel',
        'Disconnect channel',
        'Disconnect this YouTube channel from this profile',
        'I reviewed the channel before retrying this failed delivery',
        'I reviewed this video, destination channel and publishing settings',
        'Immediately after approval',
        'Last checked',
        'Legacy automatic cross-posting is enabled. Turn it off in Settings if you want all videos to use this reviewed workflow.',
        'Live delivery status',
        'Made for children',
        'No channel connected',
        'No publishing drafts or deliveries yet.',
        'Not connected',
        'Not made for children',
        'One Upload-Post profile can connect one YouTube channel. Create another profile for another channel.',
        'Open YouTube video',
        'Post',
        'Prepare a YouTube post',
        'Prepare for review',
        'Profile created. Select it above and connect YouTube.',
        'Profile identifier',
        'Profile label',
        'Publish after approval',
        'Publishing profile',
        'Reconnect required',
        'Refresh channels',
        'Refresh delivery status',
        'Refresh existing profiles or create a publishing profile to connect your channel.',
        'Retry failed delivery',
        'Review before delivery',
        'Schedule',
        'Scheduled date',
        'Scheduled time',
        'Scheduled time (UTC)',
        'Tags, separated by commas',
        'This feature uses the existing Upload-Post provider. Configure its API key and enable the integration in Settings → Auto-Publish.',
        'This post is already submitted. Its status is in Delivery history.',
        'Timezone (IANA)',
        'Upload-Post API keys',
        'Visibility',
        'YouTube description',
        'YouTube sign-in is completed on the provider connection page. MoneyPrinter does not collect your Google password.',
        'YouTube title',
        # New factual-mode labels follow tr()'s English fallback contract;
        # only en/zh maintain the long operator explanation for this slice.
        'Add Caption Cue',
        'Apply Captions And Export',
        'Caption Cue',
        'Caption Draft Required',
        'Caption Edit Queued',
        'Caption Editor Unavailable',
        'Caption End',
        'Caption Preview Help',
        'Caption Second Text',
        'Caption Split Time',
        'Caption Start',
        'Caption Text',
        'Download Caption Draft',
        'Empty Caption Track',
        'Independent Caption Editor',
        'Independent Caption Help',
        'Merge Next Caption',
        'Prepare Caption Draft',
        'Preview Caption Draft',
        'Remove Caption Cue',
        'Restore Base Captions',
        'Save Caption Cue',
        'Split Caption Cue',
        'Back To Generator',
        'Edit Video',
        'Editor Back To Tasks',
        'Editor Caption Draft',
        'Editor Caption Preview',
        'Editor Captions',
        'Editor Change Queued',
        'Editor Clip Missing',
        'Editor Clips',
        'Editor Export',
        'Editor Export Help',
        'Editor Export Queued',
        'Editor Find Scene',
        'Editor Inspector',
        'Editor Legacy Layout Help',
        'Editor Media',
        'Editor Media Page',
        'Editor Music',
        'Editor Narration',
        'Editor Next Frame',
        'Editor Pause',
        'Editor Play',
        'Editor Play Failed',
        'Editor Preview',
        'Editor Preview Missing',
        'Editor Previous Frame',
        'Editor Processing',
        'Editor Program',
        'Editor Render Export',
        'Editor Saved Layout',
        'Editor Selected Clip',
        'Editor Source Status',
        'Editor Start',
        'Editor Timeline',
        'Editor Timeline Hint',
        'Editor Tracks',
        'Editor Unavailable',
        'Editor Zoom',
        'Video Editor',
        "Voice Volume",
        "Transition Mode",
        "Editor Caption Actions",
        "Editor Narration Actions",
        "Content Mode",
        "Creative",
        "Factual (Evidence Review)",
        "Factual Sources",
        "Factual Sources Help",
        "Factual Sources Invalid",
        "Source Page URL",
        "Source Page Import Help",
        "Import Source Excerpt",
        "Source Page Import Failed",
        "Review Imported Excerpt",
        "Factual Review",
        "Review Script Only",
        "Review Script Only Help",
        "Factual Review Queued",
        "Reviewed Script",
        "Factual Review Only Help",
        "Factual Review Approved",
        "Factual Review Blocked",
        "Factual Review Unavailable",
        "Factual Review Sources",
        "No Supporting Source",
        "Factual Review Limitation",
        "AI Video Quote Required",
        "AI Video Quote Retained For Retry",
        "AI Video Quote Estimate Incomplete",
        "AI Video Quote Summary",
        "AI Video Quote Summary Singular",
        "AI Video Model",
        "AI Video Model Reference Price",
        "AI Video Model List Load Failed",
        "AI Video Duration Basis Actual",
        "AI Video Duration Basis Estimated",
        "AI Video Material Coverage",
        "AI Video Scene Count",
        "Confirm AI Video Charge",
        "Confirm AI Video Charge Help",
        "Confirm AI Video Charge Required",
        "Custom API Endpoint",
        "API Platform",
        "llm_provider_endpoint_selector.moonshot",
        "llm_provider_endpoint_selector_help.moonshot",
        "llm_provider_endpoint.moonshot.china",
        "llm_provider_endpoint.moonshot.global",
        "llm_provider_authentication_error.moonshot",
        "Local LLM Script Generation",
        "Local AI Video",
        "LTX 2.5 Local",
        "LTX 2.5 Local Help",
        "Check LTX 2.5 Readiness",
        "Checking LTX 2.5 Readiness",
        "LTX 2.5 Ready",
        "LTX 2.5 Not Ready",
        "Local AI Generation Mode",
        "Local AI Generation Mode Help",
        "LTX Fast Distilled",
        "LTX Quality DFR",
        "Local AI Seed",
        "Local AI Seed Help",
        "Local AI Visual Style",
        "Local AI Visual Style Help",
        "Scene",
        "Scenes",
        "Artifacts",
        "Artifact Package",
        "Artifact Package Help",
        "Artifact Package Unavailable",
        "Scene Editor",
        "Automatic Clip Duration",
        "Automatic Clip Duration Help",
        "Automatic Timing Estimated",
        "Automatic Shared Footage",
        "Keep Natural Narration Duration",
        "Preview Revised Timeline",
        "Natural Timeline Help",
        "Timeline Duration Change",
        "Revised Narration Ranges",
        "Revised Visual Coverage",
        "Longer Footage Required",
        "Timeline Preview Required",

        "Download Edited Narration",
        "Download Edited Captions",
        "Download Edited Script",
        "Narration Fit Result",

        "Rebuild Scene Captions",
        "Scene Captions Help",
        "Replacement Narration Text",
        "Fit Narration Duration",
        "Narration Text Help",
        "Generate Scene Speech",
        "Save Draft Transcript",

        "Narration Mix Active",
        "Narration Mix Help",
        "Narration Mix Confirm",
        "Apply Narration Drafts",
        "Restore Original Narration",

        "Narration Draft Help",
        "Narration Draft Upload",
        "Save Narration Draft",
        "Remove Narration Draft",
        "Preview Narration Draft",
        "Narration Draft Saved",

        "Adjusted Narration Range",
        "Narration Range End",
        "Apply Narration Boundary",
        "Mark Narration Reviewed",
        "Narration Reviewed By You",
        "Narration Ranges Help",
        "Narration Ranges Unavailable",
        "Prepare Narration Previews",
        "Narration Previews Queued",
        "Estimated Narration Range",
        "Preview Narration",
        "Scene Timing Help",
        "Scene Screen Duration",
        "Apply Scene Timing",
        "Reset Scene Timing",
        "Scene Timing Failed",
        "Scene Timing Queued",
        "Move Earlier",
        "Move Later",
        "Scene Reorder Help",
        "Scene Reorder Failed",
        "Scene Reorder Queued",
        "Uploaded Clip",
        "Uploaded Clip Active",
        "Clip Start Seconds",
        "Trim Saved Clip",
        "Clip Trim Help",
        "Trimmed Clip",
        "Trimmed Clip Active",

        "Replacement Clip",
        "Replacement Clip Help",
        "Replace Scene Clip",
        "Clip Replacement Failed",
        "Clip Replacement Queued",
        "Scene Versions",
        "Current Version",
        "Scene Prompt",
        "Scene Seed",
        "Rerender Existing AI Scenes",
        "Rerender Existing AI Scenes Help",
        "Rerender Existing AI Scenes Queued",
        "Rerender Existing AI Scenes Failed",
        "Regenerate Scene",
        "Regenerate Scene Help",
        "New Variation",
        "New Variation Help",
        "Restore Scene Version",
        "Restore Scene Version Help",
        "Legacy Scene Version Help",
        "Cancel Task",
        "Cancellation Requested",
        "Cancellation Unavailable",
        "Video Generation Cancelled",
        "Task Status Cancelled",
        "Scene Version Restore Queued",
        "Scene Regeneration Queued",
        "Scene Regeneration Failed",
        "No Scene Plan",
        "Scene Plan",
        "Scene Plan Source",
        "Visual Bible",
        "Wan 2.2 Local",
        "Wan 2.2 Local Help",
        "Check Wan 2.2 Readiness",
        "Checking Wan 2.2 Readiness",
        "Wan 2.2 Ready",
        "Wan 2.2 Not Ready",
        "llm_provider_label.apimart",
        "llm_provider_label.openrouter",
        "llm_provider_label.api_route",
        "llm_provider_label.fluxionai",
        "llm_provider_label.cheaperinference",
        "llm_provider_label.shengsuanyun",
        "LoomLoom Poll Retry Pending",
        "LoomLoom Poll Retry Warning",
        "Resume LoomLoom Status Check",
        "Refresh AI Video Models",
        "Retry AI Video Quote",
        "LoomLoom Quote Summary Singular",
        "LoomLoom Video Terms Reuse Help",
        "Metaso MiniMax H3",
        "Metaso MiniMax H3 Help",
        "Metaso MiniMax API Key",
        "Metaso MiniMax API Key Help",
        "Metaso MiniMax Base URL",
        "Metaso MiniMax Resolution",
        "Metaso MiniMax Resolution Help",
        "Metaso MiniMax Invalid Resolution",
        "Select Metaso MiniMax Resolution",
        "Please Enter the Metaso MiniMax API Key",
        "Metaso MiniMax Billing Notice",
        "Metaso MiniMax Billing Notice Uploaded Audio",
        "Metaso MiniMax Billing Notice Without Script",
        "Confirm Metaso MiniMax Charge",
        "Confirm Metaso MiniMax Charge Help",
        "Confirm Metaso MiniMax Charge Required",
        "MuAPI AI Video",
        "MuAPI AI Video Help",
        "MuAPI API Key",
        "MuAPI API Key Help",
        "MuAPI Base URL",
        "MuAPI Base URL Help",
        "MuAPI Video Endpoint",
        "MuAPI Video Endpoint Help",
        "MuAPI Resolution",
        "MuAPI Resolution Help",
        "Please Enter the MuAPI API Key",
        "MuAPI Billing Notice",
        "MuAPI Billing Notice Without Script",
        "Confirm MuAPI Charge",
        "Confirm MuAPI Charge Help",
        "Confirm MuAPI Charge Required",
        "Script Generation Method",
        "Script Generation Method Help",
        "Shengsuan Cloud AI Video",
        "Shengsuan Cloud AI Video Help",
        "Shengsuan Cloud API Key",
        "Shengsuan Cloud API Key Help",
        "Shengsuan Cloud API Key Link",
        "Shengsuan Cloud API Key Placeholder",
        "Shengsuan Cloud API Key Required",
        "Shengsuan Cloud API Key Reused",
        "Shengsuan Cloud Batch Script Generation",
        "Selected AI Video Model Unavailable",
        "Selected AI Video Ratio Unavailable",
        "Stop Tracking LoomLoom Run",
        "Stop Tracking LoomLoom Run Help",
        "Unavailable AI Video Model",
        "VoxCPM Speed Not Supported",
        "VoxCPM Reference Audio",
        "VoxCPM Reference Audio Help",
        "VoxCPM Reference Audio Notice",
        "VoxCPM Reference Audio Empty",
        "VoxCPM Reference Audio Upload Too Large",
        "Validating VoxCPM Reference Audio",
        "VoxCPM Reference Audio Invalid",
        "VoxCPM High Fidelity Delivery",
        "VoxCPM High Fidelity Delivery Help",
        "VoxCPM Separate Prompt Audio",
        "VoxCPM Separate Prompt Audio Help",
        "VoxCPM Prompt Audio",
        "VoxCPM Prompt Audio Help",
        "VoxCPM Prompt Text",
        "VoxCPM Prompt Text Help",
        "Transcribe VoxCPM Prompt Audio",
        "Transcribe VoxCPM Prompt Audio Help",
        "Transcribing VoxCPM Prompt Audio",
        "VoxCPM Prompt Audio Transcribed",
        "VoxCPM Prompt Audio Transcription Failed",
        "VoxCPM Prompt Transcript Review",
        "VoxCPM Prompt Audio Empty",
        "VoxCPM Prompt Audio Upload Too Large",
        "Validating VoxCPM Prompt Audio",
        "VoxCPM Prompt Text Required",
        "VoxCPM Prompt Pair Required",
        "VoxCPM Prompt Invalid",
        "None (Animation)",
    }
)
FORMAT_PLACEHOLDER_PATTERN = re.compile(r"(?<!\{)\{([a-zA-Z_][a-zA-Z0-9_]*)\}(?!\})")
MARKDOWN_URL_PATTERN = re.compile(r"\[[^\]]+\]\((https?://[^)]+)\)")


class _TrKeyVisitor(ast.NodeVisitor):
    def __init__(self):
        self.keys = set()

    def visit_Call(self, node):
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "tr"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            self.keys.add(node.args[0].value)
        self.generic_visit(node)


def _load_translation(locale):
    data = json.loads((I18N_DIR / f"{locale}.json").read_text(encoding="utf-8"))
    return data.get("Translation", {})


def _duplicate_translation_keys(path):
    """返回 locale 原始文本中重复定义的键，JSON 解析只保留最后一个。"""
    duplicates = []

    def collect(pairs):
        seen = set()
        for key, _ in pairs:
            if key in seen:
                duplicates.append(key)
            seen.add(key)
        return dict(pairs)

    json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=collect)
    return duplicates


def _required_translation_keys(translations):
    """返回二级语言必须维护的 key，Provider 长说明统一回退英文。"""
    return {
        key
        for key in translations
        if key not in ENGLISH_FALLBACK_KEYS
        and not key.startswith(PROVIDER_TIPS_PREFIXES)
    }


def _format_placeholders(value):
    """提取运行时格式化变量，防止翻译遗漏或误改变量名。"""
    return set(FORMAT_PLACEHOLDER_PATTERN.findall(value))


def _markdown_urls(value):
    """提取 Markdown 链接目标，允许翻译链接文字但不允许改坏地址。"""
    return set(MARKDOWN_URL_PATTERN.findall(value))


class TestWebuiI18n(unittest.TestCase):
    def test_catalan_locale_is_discovered_and_matches_browser_variants(self):
        """语言文件自动注册；区域变体回退到 ca，但不覆盖用户已保存的选择。"""
        locales = utils.load_locales(str(I18N_DIR))
        self.assertEqual(locales["ca"]["Language"], "Català")
        for browser_locale in ("ca", "ca-ES", "ca_AD", "CA-es", "ca-ES-valencia"):
            with self.subTest(browser_locale=browser_locale):
                self.assertEqual(
                    utils.resolve_ui_language("", browser_locale, locales), "ca"
                )
        self.assertEqual(utils.resolve_ui_language("en", "ca-ES", locales), "en")
        self.assertEqual(utils.resolve_ui_language("ca", "en-US", locales), "ca")

    def test_catalan_pause_examples_use_supported_syntax(self):
        """帮助中的停顿标签必须能被解析，不能把关键字翻成不支持的语法。"""
        help_text = _load_translation("ca")["Video Script Help"]
        examples = re.findall(r"\[pausa: [^\]]+\]", help_text)
        self.assertTrue(examples)
        for example in examples:
            with self.subTest(example=example):
                self.assertTrue(utils.has_pause_tags(example))
                self.assertEqual(utils.remove_pause_tags(example).strip(), "")

    def test_saved_ui_language_takes_priority_over_browser_locale(self):
        language = utils.resolve_ui_language(
            saved_language="de",
            browser_locale="zh-CN",
            supported_languages=["zh", "en", "de"],
        )

        self.assertEqual(language, "de")

    def test_browser_locale_is_normalized_to_supported_base_language(self):
        self.assertEqual(
            utils.resolve_ui_language("", "zh-CN", ["zh", "en"]),
            "zh",
        )
        self.assertEqual(
            utils.resolve_ui_language(None, "pt_BR", ["en", "pt"]),
            "pt",
        )

    def test_unsupported_browser_locale_falls_back_to_english(self):
        language = utils.resolve_ui_language(
            saved_language="",
            browser_locale="fr-FR",
            supported_languages=["zh", "en"],
        )

        self.assertEqual(language, "en")

    def test_english_locale_covers_static_webui_labels(self):
        tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
        visitor = _TrKeyVisitor()
        visitor.visit(tree)

        en_keys = set(_load_translation("en"))

        self.assertEqual(sorted(visitor.keys - en_keys), [])

    def test_shengsuanyun_provider_tips_keep_registration_and_model_links(self):
        """合作入口和模型目录属于产品配置，避免后续改文案时误删追踪链接。"""
        expected_urls = {
            "https://www.shengsuanyun.com/?from=CH_XUQ4OTSK",
            "https://global.modelmesh.info/model",
        }

        for locale in ("zh", "en"):
            with self.subTest(locale=locale):
                tips = _load_translation(locale)["llm_provider_tips.shengsuanyun"]
                provider = get_llm_provider("shengsuanyun")
                rendered = tips.format(
                    api_key_url=provider.effective_api_key_url(),
                    default_base_url=provider.effective_default_base_url,
                    default_model=provider.default_model,
                )
                self.assertEqual(_markdown_urls(rendered), expected_urls)

    def test_metaso_api_key_label_keeps_mpt_referral_link(self):
        """秘塔 Key 获取入口必须保留 MPT 追踪参数，避免赞助转化链路失效。"""
        expected_url = "https://metaso.cn/minimax-h3/?s=MPT"

        for locale in ("zh", "en"):
            with self.subTest(locale=locale):
                label = _load_translation(locale)["Metaso MiniMax API Key"]
                self.assertEqual(_markdown_urls(label), {expected_url})

    def test_secondary_locales_cover_english_locale(self):
        en_translations = _load_translation("en")
        required_en_keys = _required_translation_keys(en_translations)

        for locale in SECONDARY_LOCALES:
            with self.subTest(locale=locale):
                locale_keys = set(_load_translation(locale))
                self.assertEqual(sorted(required_en_keys - locale_keys), [])

    def test_secondary_locales_do_not_duplicate_provider_tips(self):
        # Provider 配置长说明只维护中英文，其它语言运行时回退英文。
        # 禁止复制这些 key，避免出现不会持续维护的半翻译内容。
        for locale in SECONDARY_LOCALES:
            with self.subTest(locale=locale):
                locale_keys = set(_load_translation(locale))
                duplicated_keys = sorted(
                    key for key in locale_keys if key.startswith(PROVIDER_TIPS_PREFIXES)
                )
                self.assertEqual(duplicated_keys, [])

    def test_secondary_locales_do_not_duplicate_english_fallback_keys(self):
        for locale in SECONDARY_LOCALES:
            with self.subTest(locale=locale):
                locale_keys = set(_load_translation(locale))
                self.assertEqual(sorted(ENGLISH_FALLBACK_KEYS & locale_keys), [])

    def test_secondary_locales_cover_static_webui_labels(self):
        tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
        visitor = _TrKeyVisitor()
        visitor.visit(tree)

        for locale in SECONDARY_LOCALES:
            with self.subTest(locale=locale):
                locale_keys = set(_load_translation(locale))
                self.assertEqual(
                    sorted(visitor.keys - locale_keys - ENGLISH_FALLBACK_KEYS),
                    [],
                )

    def test_secondary_locales_preserve_format_placeholders(self):
        en_translations = _load_translation("en")

        for locale in SECONDARY_LOCALES:
            locale_translations = _load_translation(locale)
            for key in _required_translation_keys(en_translations):
                with self.subTest(locale=locale, key=key):
                    self.assertEqual(
                        _format_placeholders(locale_translations[key]),
                        _format_placeholders(en_translations[key]),
                    )

    def test_secondary_locales_preserve_markdown_urls(self):
        en_translations = _load_translation("en")

        for locale in SECONDARY_LOCALES:
            locale_translations = _load_translation(locale)
            for key in _required_translation_keys(en_translations):
                with self.subTest(locale=locale, key=key):
                    self.assertEqual(
                        _markdown_urls(locale_translations[key]),
                        _markdown_urls(en_translations[key]),
                    )

    def test_script_language_options_include_russian_and_catalan(self):
        tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
        support_locales = None

        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if any(
                isinstance(target, ast.Name) and target.id == "support_locales"
                for target in node.targets
            ):
                support_locales = ast.literal_eval(node.value)
                break

        self.assertIsNotNone(support_locales)
        self.assertIn("ru-RU", support_locales)
        self.assertIn("ca-ES", support_locales)

    def test_locale_files_do_not_redefine_a_translation_key(self):
        """
        同一 JSON 对象里出现重复键时，解析只保留最后一个，前一个被静默丢弃。
        视频转场与字幕动画曾共用 "None" 键，中文转场下拉因此显示成「无动画」。
        这里直接检查原始 locale 文本，避免同类覆盖再次逃过 tr() 键覆盖测试。
        """

        for path in sorted(I18N_DIR.glob("*.json")):
            with self.subTest(locale=path.stem):
                self.assertEqual(_duplicate_translation_keys(path), [])
