# Local AI Video Operator Guide

This fork adds self-hosted AI video generation to MoneyPrinterTurbo while keeping
the original script, narration, subtitle, music and final composition pipeline.

## Wan 2.2 local source

The stable source ID is `wan22_local`. It targets the official
`Wan-Video/Wan2.2` TI2V-5B implementation and operator-supplied
`Wan-AI/Wan2.2-TI2V-5B` checkpoint files.

The integration does **not** download model weights during a task and does not
put model/checkpoint paths in public task payloads or generation manifests.

### 1. Prepare the official Wan checkout

Clone or otherwise provision the official Wan2.2 repository outside this
application repository. Pin the revision you validate in production rather than
silently updating it underneath a running worker.

M2 was implemented after rechecking official Wan2.2 main at
`1ea34ff48f87168174e12956e200b1d908b1c5ff`. Revalidate the upstream API and
requirements before changing that revision.

### 2. Create a dedicated Wan Python environment

Use the official Wan2.2 requirements in a separate Python environment. This is
intentional: the inspected Wan requirements currently constrain NumPy to
`<2`, while MoneyPrinterTurbo's locked application environment resolves NumPy
2.x. Keeping Wan isolated avoids replacing or weakening the application's
dependency lock.

The Wan worker preflight checks the required imports, NumPy major version, CUDA
availability, selected device and TI2V module imports before a generation task
continues.

### 3. Provision the TI2V-5B checkpoint

Prepare the official TI2V-5B checkpoint directory outside this Git repository.
The provider validates the checkpoint index, referenced model shards, VAE, T5
weights and tokenizer directory before use. Do not commit model weights.

### 4. Configure MoneyPrinterTurbo

Copy `config.example.toml` to `config.toml` if needed and configure:

```toml
[wan22_local]
repo_path = "/opt/models/Wan2.2"
checkpoint_path = "/opt/models/Wan2.2-TI2V-5B"
python_executable = "/opt/venvs/wan22/bin/python"
device = 0
seed = 42
offload_model = true
t5_cpu = true
convert_model_dtype = true
```

Environment overrides are also supported for the operator:
`WAN22_REPO`, `WAN22_CHECKPOINT`, `WAN22_PYTHON`, `WAN22_DEVICE`,
`WAN22_SEED`, `WAN22_OFFLOAD_MODEL`, `WAN22_T5_CPU` and
`WAN22_CONVERT_MODEL_DTYPE`.

### 5. Check readiness before generation

CLI:

```bash
uv run python cli.py --video-source wan22_local --check-local-ai-source
```

API (the normal API-key policy still applies):

```text
GET /api/v1/local-ai/providers/wan22_local/preflight
```

WebUI:

Select **Local AI Video → Wan 2.2 Local**, then use
**Check Wan 2.2 readiness**. The WebUI intentionally does not expose editable
server model paths.

A readiness failure is expected on CPU-only machines. It should fail before
script/TTS/video generation consumes unnecessary work.

### 6. Generate normally

After readiness passes, choose `wan22_local` as the video source. The existing
MoneyPrinterTurbo pipeline supplies narration duration, creates ordered local-AI
scenes, generates and validates each scene, persists versioned scene clips, and
then reuses the existing composer for narration, captions, music, transitions
and final MP4 output.

Completed scene clips are fingerprinted and reused on retry. Missing or corrupt
clips are regenerated without discarding valid completed scenes.

## Runtime and deployment boundaries

- Wan model inference is serialized inside one MoneyPrinterTurbo process.
- The Wan worker is persistent across compatible tasks so the model can be
  reused instead of reloaded per scene.
- Switching local model families can evict the previous family runtime.
- This is **not** a multi-process GPU lock. Run local GPU inference through one
  application worker process until a cross-process guard or dedicated GPU
  service is implemented.
- Real Wan inference, VRAM usage, generation speed and visual quality still need
  validation on the exact deployment GPU. CPU CI validates contracts and mocked
  runtime behavior only.

## Troubleshooting

If readiness fails, check the returned safe error first. Common classes are:
missing/invalid checkout or checkpoint files, incompatible Wan worker
dependencies, NumPy 2.x in the worker environment, unavailable CUDA, invalid
device selection, FFmpeg not found, or failure importing the official TI2V
modules.

The application intentionally fails closed. It does not fall back to a paid
remote video provider when `wan22_local` is selected.
