# Instagram and TikTok publishing

The workspace opens Create, Campaigns, Content Library, Publishing and Accounts
in the same browser tab. Campaigns starts with the brief and video count. Open
an existing campaign to review and approve its video plan separately from
publishing. The account picker in Accounts includes four providers. The
existing YouTube and Facebook scheduling workflows are also available.

## Instagram Reels

1. In **Accounts → Instagram**, open Meta application setup. Configure a Meta
   app with Facebook Login for Business and a user-token configuration ID.
   Register the Facebook callback shown in the form. Include the existing Page
   permissions and `instagram_basic` and `instagram_content_publish` in the
   business login configuration. The Instagram professional account must be
   linked to a Facebook Page the authorized person can publish from.
2. Select **Connect Meta for Instagram**, continue through Meta consent, then
   explicitly attach the desired Instagram account. Instagram shares the Meta
   grant. Detaching the Instagram destination leaves the Facebook Page grant
   usable. Revoking the shared grant in Facebook removes its attached accounts.
3. Mark the final video reviewed in **Content Library**. In **Accounts →
   Instagram → Create post**, select the final video and account, write the
   caption and review the AI disclosure. Prepare and approve the frozen Reel
   draft. The worker uploads the MP4 to Meta, checks the container and publishes
   it when Meta reports it ready. Keep MoneyPrinter running during delivery.
4. Use **Calendar / Queue** to refresh an existing delivery. An interrupted
   publication is checked against the same container. When Meta does not
   confirm an outcome, inspect that attempt before taking any further action.

The app accepts 3–180 seconds, 9:16, at least 540×960, 23–60 fps and up to
512 MiB for this Instagram Reel workflow. Export MP4 for best compatibility.
The app can convert a WebM export to MP4. Meta can apply additional codec,
permission, publishing-limit and account requirements.

## TikTok creator inbox

1. Add **Login Kit for Web** and **Content Posting API Upload** in the TikTok
   developer portal. Request `user.info.basic` and `video.upload` and register
   the exact HTTPS callback shown in **Accounts → TikTok**. TikTok must grant
   the application access and the creator must authorize both scopes. The
   server also accepts `MPT_TIKTOK_CLIENT_KEY`, `MPT_TIKTOK_CLIENT_SECRET` and
   `MPT_TIKTOK_REDIRECT_URI` in its environment.
2. Connect the intended creator account. Prepare a reviewed final video in
   **Create post** and approve its inbox upload. The app accepts 3–600 seconds
   and up to 512 MiB. TikTok applies its own account and media limits.
3. When the queue says the video is in the inbox, open the TikTok notification.
   Review the edit, add the caption and required disclosures, choose visibility
   and finish publishing there. MoneyPrinter keeps caption notes for copying.
   A status refresh can confirm when TikTok reports publication.

TikTok's Direct Post guidelines exclude tools limited to uploading to the
accounts their operators manage. The supported flow uploads a draft to the
creator inbox. It leaves the publishing decision in TikTok.

## Campaigns and the publishing planner

Choose either account in campaign destinations or prepare a batch from
Content Library. Before creating a batch, save the account's defaults in
**Publishing → Posting schedules**. Batches that include Instagram or TikTok
use **Publish after approval**. Instagram then publishes a Reel and TikTok
delivers to the creator inbox. Preparation generates editable copy and freezes
the selected video. Every upload still requires explicit batch approval.

Credentials and delivery records use the existing encrypted social storage.
Keep the social encryption key with the deployment. Approval and recovery use
persisted job IDs. When an upload or publish request has an uncertain outcome,
the app checks the existing ID when available. It does not automatically start
another upload. TikTok can resume a known upload when its status reports a
usable byte offset and the upload URL is still valid.

## Operator verification

Run `sh webui.sh` so the same-origin gateway serves both OAuth callbacks. Sign
in with app-authorized accounts, send a small reviewed Reel and TikTok draft,
verify the account shown during review, and confirm the results in each app.
Live account authorization, app review and real delivery depend on the
operator's developer applications.

- [Meta Content Publishing](https://developers.facebook.com/documentation/instagram-platform/content-publishing)
- [TikTok Login Kit for Web](https://developers.tiktok.com/docs/en/login-kit-web)
- [TikTok Upload API](https://developers.tiktok.com/docs/en/content-posting-api-reference-upload-video)
- [TikTok status API](https://developers.tiktok.com/docs/en/content-posting-api-reference-get-video-status)
- [TikTok Content Sharing Guidelines](https://developers.tiktok.com/docs/en/content-sharing-guidelines)
