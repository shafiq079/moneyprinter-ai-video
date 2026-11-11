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

## Voice availability and timing

The dropdown uses the backend's `GET /engines/tts` preset catalog. It shows
every preset advertised by a runnable engine whose required model terms have
been accepted. The engine and preset are saved together. Engines without
advertised presets, gallery designs, cloned profiles, OpenAI aliases, and
models absent from the connected backend have no preset entries. Check the
specific weights and preset terms for your intended use, including monetized
videos. Models download through VoiceStudio. MoneyPrinter uses the local
speech endpoint and does not switch to another provider if a preset becomes
unavailable.

MoneyPrinter applies speed locally and measures the rendered narration for
video timing. VoiceStudio's speech endpoint returns audio without word
timestamps. Use MoneyPrinter's existing Whisper subtitle setting when you
need audio-derived caption timing.
