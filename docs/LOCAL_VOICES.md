# Local Voices through VoiceStudio

## Connect VoiceStudio

1. Install and run the [VoiceStudio backend](https://github.com/debpalash/VoiceStudio#platforms)
   on the MoneyPrinter host or a server reachable over your private network.
   In the VoiceStudio Model Catalogue, install a speech engine that exposes
   presets. **KittenTTS** is a lightweight CPU option with eight English voices.
   Accept any required model terms in VoiceStudio before using that engine.
2. MoneyPrinter connects to `http://127.0.0.1:3900` by default. If VoiceStudio
   listens elsewhere, set `MPT_VOICESTUDIO_URL` in the environment that launches
   MoneyPrinter. Use the backend address, with or without the trailing `/v1`.
   If your backend requires authentication, set `MPT_VOICESTUDIO_API_KEY` to
   its self-hosted API key. This is optional local authentication. A paid
   provider account or key is unnecessary.
3. In **Audio Settings → Voiceover Service**, choose **Local Voices (VoiceStudio)**.
   Pick a voice and use **Play Voice** or **Generate Full Voiceover Preview**.
   Set **Voiceover Speed** and **Voiceover Volume** as usual. New presets appear
   on a subsequent interaction after the 15-second catalog cache expires.

The default address points to the host running MoneyPrinter. For Codespaces
or containers, configure an address reachable from that process. A VoiceStudio
desktop app running on your laptop is only reachable from another host if you
have set up a private connection between them. Follow VoiceStudio's
[authentication guidance](https://github.com/debpalash/VoiceStudio/blob/main/docs/api-auth.md)
when connecting across hosts.

## VoiceStudio Gallery voices

The voice selector combines runnable engine presets with the entries reported
by VoiceStudio's gallery API. The default gallery includes the Starter, World
and Community packs, with names such as The Documentarian, Dutch Narrator,
Thalia and Lucas. If the gallery manifest is unavailable, bundled featured
archetypes can still appear. Selecting a voice saves its gallery ID in the
project. **Play Voice** plays the clip returned by VoiceStudio's gallery
preview route, which can serve a published sample or render a local fallback.
At default speed and volume, MoneyPrinter preserves the clip bytes. **Full
Voiceover Preview** and video generation render your script using VoiceStudio's
native OmniVoice route and the selected profile. That route uses the profile's
reference, language and seed, and MoneyPrinter requests the gallery renderer's
32-step Broadcast settings. Expect longer CPU renders for new text. Native
renders are recorded in the connected VoiceStudio instance's history.

Your existing Codespace VoiceStudio process can handle both gallery voices and
engine presets. MoneyPrinter selects the appropriate engine per request.

Review and accept the required model terms in VoiceStudio before the first
render. For a headless instance, see its local `/docs` API reference. Use
`GET /models/licenses/details/{repo_id}` to review the disclosure and
`POST /models/licenses/accept` with that disclosure's `fingerprint`,
`repo_id`, and `accepted: true` if you agree. VoiceStudio's speech error
lists the model IDs whose terms still need acceptance. The default OmniVoice
weights are noncommercial, and community entries may require attribution or
carry separate terms. The first generation may download multiple gigabytes.
KittenTTS presets remain selectable with their own engine ID.

## Voice availability and timing

The list reflects the connected backend. Separate model downloads or
acceptance may be required for synthesis. Unavailable selections fail without
switching to a different voice. OpenAI compatibility aliases and arbitrary
private voice profiles are outside the gallery list.

MoneyPrinter applies speed locally and measures the rendered narration for
video timing. VoiceStudio's speech endpoint returns audio without word
timestamps. Use MoneyPrinter's existing Whisper subtitle setting when you
need audio-derived caption timing.
