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

## Scene Director and prompt preview

For local AI video tasks, scene planning happens only after narration has been
generated and its actual duration is known. The director treats that narration
as fixed: it may direct the visuals, but it does not rewrite, reorder, merge or
split the already-recorded narration.

The task stores a canonical `scene_plan.json` beside its other task artifacts.
It records the visual bible and each scene's fixed narration segment, duration,
beat, prompt, camera direction, continuity notes, exclusions and deterministic
seed. When the planning inputs are unchanged, retries reuse this file instead of
asking the LLM to produce a new answer. That keeps scene fingerprints stable so
valid completed clips remain reusable.

MoneyPrinterTurbo uses the already configured LLM provider for visual direction.
If the director response is unavailable or invalid, generation falls back to a
deterministic CPU-safe visual plan rather than failing the video task. The M1
fake provider always uses the deterministic path so CI never depends on an
external LLM.

In the WebUI, the current local-AI task exposes a read-only **Scene Plan**
expander once the plan exists. It shows the visual bible and the final prompt
sent for each scene without exposing model/checkpoint host paths.

## LTX 2.5 Fast and Quality modes

`ltx25_local` uses one stable provider ID. Each task selects
`local_ai_generation_mode = "fast"` or `"quality"`.

- **Fast / Distilled** uses the official LTX-2.5 `DistilledPipeline` and is the
  default for iteration.
- **Quality / DFR** uses the official `DFRPipeline` with the configured
  detailing IC-LoRA. Set `ltx25_local.detailing_lora_path` before selecting
  Quality. Quality preflight fails before script/TTS work when that asset is
  missing.
- `local_ai_seed` is an optional portable task parameter. When supplied it is
  the first scene seed and later scenes increment it deterministically.
- LTX native audio is intentionally stripped from generated scene clips in both
  modes. MoneyPrinterTurbo narration, subtitles and BGM remain authoritative.

LTX-2.5 versions released since 11 August 2026 are governed by Lightricks'
**LTX-2.x Community License Agreement**, not the repository's earlier LTX-2
license. Review the current upstream license before commercial deployment:
https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x

The current license states that entities with annual revenue of at least
USD 10,000,000 require a paid license for commercial use except for the
license's defined non-commercial cases. This project does not redistribute LTX
model weights, and this note is not legal advice.

## Capability-driven local AI controls

The WebUI does not expose arbitrary model parameters for local/remote AI video.
Each public AI source declares a product-safe capability profile containing the
model, execution backend, supported generation modes, aspect ratios, derived
generation resolution, clip-duration choices, seed range and prompt-guidance
limit. The same capability contract is checked by task preflight so API or CLI
requests cannot bypass the supported domain.

Users choose an aspect ratio such as 9:16 or 16:9; they do not type raw width
and height values. MoneyPrinter derives the tested generation dimensions for the
selected model/backend and shows them beside the ratio. Unsupported modes,
durations and seed values are not offered by the WebUI and are rejected before
provider startup. The visual prompt field is guidance for the Scene Director;
MoneyPrinter still produces per-scene prompts from the script, and those scene
prompts remain editable through the existing scene-regeneration flow.

## LTX 2.5 Hugging Face ZeroGPU source

The stable source ID is `ltx25_hf`. It reuses MoneyPrinter's existing local-AI
scene planning, generation manifest, scene regeneration, composer and final-output
validation, but delegates scene inference to an operator-owned Hugging Face
Gradio Space. Hugging Face-specific transport is isolated under
`app/services/local_ai/remote_gpu/`; the task pipeline does not depend on
Hugging Face APIs directly.

The current MVP targets the official LTX-2.5 distilled ZeroGPU implementation.
Create or duplicate a Gradio ZeroGPU Space, keep the optimized LTX pipeline in
that Space, and give the generation button a stable API name:

```python
go.click(run, _INPUTS, _OUTPUTS, api_name="generate_scene")
```

Configure MoneyPrinter:

```toml
[ltx25_hf]
space_url = "https://YOUR-SPACE.hf.space"
api_name = "generate_scene"
token_env = "HF_TOKEN"
deployment_revision = "YOUR_SPACE_REVISION"
seed = 42
max_scene_duration = 5.0
decoder = "conv"
job_timeout_seconds = 900
```

Set the token only in the MoneyPrinter process environment:

```text
HF_TOKEN=hf_...
```

The provider requires an authenticated token so ZeroGPU usage is attributed to
the caller account instead of the anonymous pool. The token is used only for
HTTP authorization and is never written to scene plans, manifests or safe
provider metadata.

Readiness checks call the Space's Gradio API metadata endpoint and do not invoke
the GPU. Actual generation submits a text-to-video request to the named endpoint,
waits for the Gradio queue result, downloads the returned MP4 from the same Space
origin, strips LTX native audio, trims the clip to the requested scene duration,
and then runs the normal MoneyPrinter media validation.

This remote provider is **Fast/Distilled only** for the MVP. MoneyPrinter keeps
its own narration, captions and BGM authoritative. On 30 September 2026 an
authenticated MoneyPrinter smoke run against the operator-owned ZeroGPU Space
completed successfully: a requested 2.0-second landscape scene returned a
768x512 MP4 through the full provider -> Gradio -> download -> normalization
path. That first smoke run proved integration, but it also exposed that the
early adapter treated orientation as aspect ratio: 768x512 is 3:2, not 16:9.
The production mapping was therefore corrected to exact 1024x576 landscape and
576x1024 portrait requests, and media validation now rejects materially wrong
ratios instead of checking orientation only. The smoke run is not a latency or
visual-quality benchmark; no standardized timing measurement was captured.

## Local AI generation telemetry

The generation manifest records CPU-safe wall-clock telemetry for local
providers:

- last/total runtime-load or runtime-reuse time and load count;
- per-scene generation time;
- per-scene validation time;
- the same timings in version metadata so regenerated scene versions retain
  their own generation history.

Providers may expose an optional `runtime_telemetry()` dictionary. It is passed
through the same metadata sanitizer before persistence; credential-like fields
and host paths are removed. Runtime and scene log lines include safe task,
provider, scene/stage and elapsed-time context so failures can be correlated
without persisting checkpoint paths or credentials. Real GPU memory metrics
should be supplied only when the installed GPU runtime can measure them reliably.

## Deferred GPU benchmark harness

The benchmark tooling can be developed and CI-tested without a GPU. Do not treat
its presence as evidence that Wan or LTX quality/performance has been validated.

When a CUDA machine is available, run the same prompt across all three modes:

```bash
uv run python scripts/local_ai_benchmark.py \
  --target wan22_local \
  --target ltx25_local:fast \
  --target ltx25_local:quality \
  --duration 3 \
  --aspect 9:16 \
  --seed 42 \
  --repeats 2 \
  --output-dir storage/benchmarks/local-ai
```

The harness performs provider preflight, measures one cold runtime load, then
records per-generation wall time, media validation time, output duration,
dimensions and file size. When `nvidia-smi` is available it samples peak
reported GPU memory use and utilization. Results are written to
`benchmark.json` beside the generated clips. Provider metadata and model
fingerprints are recorded through the same safe metadata surfaces used by the
product; checkpoint/repository paths are not added to the report.

The remote Hugging Face target is intentionally not part of the default target
set because invoking it consumes external ZeroGPU quota. Benchmark it only when
an operator explicitly wants to spend quota:

```bash
uv run python scripts/local_ai_benchmark.py \\
  --target ltx25_hf:fast \\
  --duration 2 \\
  --aspect 16:9 \\
  --seed 42 \\
  --repeats 1 \\
  --output-dir storage/benchmarks/ltx25-hf
```

For remote targets the local process does not sample `nvidia-smi`; the report
marks GPU measurement scope as `remote_backend`. Provider-side GPU telemetry
must come from a safe remote telemetry surface if one is added later.

Actual default tuning, provider comparisons and hardware guidance remain
deferred until standardized measurements are collected.

## Manual GPU validation pack

After provisioning a CUDA host, model files and the isolated provider worker
environments, run the end-to-end acceptance pack:

```bash
uv run python scripts/local_ai_gpu_validate.py
```

The default run validates `wan22_local`, `ltx25_local:fast` and
`ltx25_local:quality`. Wan and LTX Fast are required. LTX Quality is reported
as `SKIPPED` when its provider preflight is unavailable (for example, the
detailing LoRA has not been provisioned). Use
`--require-ltx-quality` when DFR is part of the deployment release gate.

Each available target uses an offline fixed script and No Voice timing audio, so
the validation command does not need a remote LLM/TTS or paid video provider.
It keeps the generated MoneyPrinter task artifacts and checks:

- provider/model/CUDA preflight plus safe worker Python, Torch, CUDA and NumPy versions;
- at least two real generated and validated scene clips;
- one initial runtime load/reuse operation across the multi-scene batch;
- a validated final MP4 through the normal MoneyPrinter composer;
- one versioned single-scene regeneration while the other active scenes remain unchanged;
- render-only rerender with no generation-manifest change;
- `nvidia-smi` peak memory/utilization sampling;
- the portable local-AI output package.

The machine-readable report is written to
`storage/validation/local-ai-gpu/gpu-validation.json`. It records task IDs,
safe provider/model fingerprints, worker/runtime versions, GPU measurements,
PASS/FAIL/SKIPPED checks and task-relative artifact references. Model/checkpoint
host paths and credentials are not added to the report.

A green CPU CI result for this command's orchestration tests is **not** evidence
of Wan/LTX inference quality or performance. Release evidence exists only after
the command is run successfully on the actual deployment GPU with the intended
model revisions.

## No Voice and output artifacts

The existing **No Voiceover** selection is a real local-AI production path. It
does not call a speech provider. MoneyPrinterTurbo writes a deterministic silent
timing track so the existing scene planner/composer has a duration reference;
custom uploaded audio still takes precedence. If captions are enabled, No Voice
uses the script-derived timing data rather than transcribing silence with
Whisper.

Completed local-AI tasks expose a portable artifact package through existing
task/history/API surfaces. It uses safe task-relative references for final and
combined videos, script, captions, audio, `scene_plan.json`,
`generated_ai/generation_manifest.json`, and active generated scene clips.
Host model/checkpoint paths and credentials are not part of this package.

## Final output validation and recovery

For local-AI tasks, the final MP4 is validated after the existing composer writes
it and before the task can be marked complete. The check requires a non-empty,
decodable file, the expected output dimensions, duration within the configured
validation tolerance of the **measured written narration audio**, and an audio
stream that covers the narration target. The rounded duration used for scene
planning is intentionally not used for this final integrity check.

If this validation fails, the invalid final file is not published as a completed
result. Task state reports a `video`-stage failure, identifies the selected
local provider, marks the failure recoverable, and recommends
`rerender_final_video`. Stored local scene clips remain available, so repairing
the renderer/environment and rerendering does not require new Wan/LTX inference.

Visual-only scene regeneration likewise reuses the existing narration and
caption artifacts; it regenerates the requested scene and reruns composition
without invoking TTS or caption generation. The shared MoneyPrinter composer
continues to apply the configured narration and BGM gain controls.

## Local AI disk cleanup

Generated scene versions are intentionally retained for comparison and rollback.
Operators can inspect cleanup candidates without deleting anything:

```bash
uv run python scripts/local_ai_cleanup.py
```

Apply the configured policy explicitly:

```bash
uv run python scripts/local_ai_cleanup.py --apply
```

The `[local_ai_cleanup]` policy defaults to keeping two scene versions,
waiting 24 hours before deleting crash/temp or unreferenced scene assets, and
never deleting whole completed tasks. Set
`completed_task_retention_days` to a positive value only when automatic
retention cleanup of old completed task directories is desired.

Cleanup skips tasks that are still generating or cross-posting. The active scene
asset is always retained, even when an older restored version is active. The
command is dry-run by default and supports `--task-id` plus policy overrides.

## Runtime and deployment boundaries

- Wan and LTX keep their compatible local workers persistent so the heavyweight
  runtime can be reused across scenes/tasks instead of reloaded per scene.
- `LocalAIRuntimeManager` uses an in-process reentrant lock plus a
  cross-process OS advisory lock keyed by configured CUDA device. Lock files are
  stored under `storage/local_ai_locks/gpu-N.lock`.
- The lock is reentrant for nested provider calls within the same task, so the
  outer generation session can safely call runtime load/generation helpers.
- Independent application worker processes targeting the same CUDA device are
  serialized at this boundary; different device indices use different locks.
- Switching local model families on the same device can still evict the
  previous family runtime before the next family initializes.
- CPU tests cover thread/process serialization and reentrancy. Real
  multi-process CUDA contention, VRAM usage, generation speed and visual quality
  still need validation on the exact deployment GPU before operational
  throughput claims.

## Troubleshooting

If readiness fails, check the returned safe error first. Common classes are:
missing/invalid checkout or checkpoint files, incompatible Wan worker
dependencies, NumPy 2.x in the worker environment, unavailable CUDA, invalid
device selection, FFmpeg not found, or failure importing the official TI2V
modules.

The application intentionally fails closed. It does not fall back to a paid
remote video provider when `wan22_local` is selected.
