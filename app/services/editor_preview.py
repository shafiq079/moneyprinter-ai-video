"""Stable last-completed video for editor reloads during render transactions."""
import os
import re
import shutil
import uuid
from pathlib import Path

from app.services import generation_manifest as gm

SNAPSHOT = 'editor_last_completed.mp4'
BACKUPS = {'audio-layers-backup', 'caption-edit-backup', 'narration-edit-backup',
           'scene-reorder-backup', 'scene-timing-backup', 'scene-clip-replacement-backup',
           'render-only-rerender-backup', 'resume-backup'}


def preserve(root):
    root = Path(root)
    source = root / 'final-1.mp4'
    if not source.is_file():
        return
    from app.services import video
    try:
        with video._open_video_clip_quietly(str(source)) as completed:
            if completed.duration <= 0:
                return
    except (OSError, ValueError):
        return
    target = root / SNAPSHOT
    temporary = root / f'.editor-preview-{uuid.uuid4().hex}.tmp'
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def program(task_id, busy=False):
    final = gm.resolve_asset(task_id, 'final-1.mp4')
    snapshot = gm.resolve_asset(task_id, SNAPSHOT)
    if not busy and final.is_file():
        return final
    if snapshot.is_file():
        return snapshot
    # Compatibility with an interrupted render started before snapshots existed.
    candidates = []
    for candidate in final.parent.glob('final-1.mp4.*-backup'):
        if re.fullmatch(r'final-1\.mp4\.(.+)', candidate.name).group(1) in BACKUPS:
            safe = gm.resolve_asset(task_id, candidate.name)
            if safe.is_file():
                candidates.append(safe)
    if candidates:
        return max(candidates, key=lambda p: p.stat().st_mtime_ns)
    # A new task with no completed output must not expose a partial encode.
    return None if busy else final if final.is_file() else None


def combined_key(task_id, params, sources, audio):
    import hashlib
    import json
    settings = params.model_dump(mode='json')
    fields = ('video_aspect', 'video_fit_mode', 'video_concat_mode', 'video_transition_mode',
              'video_clip_duration', 'video_clip_speed', 'local_ai_duration_mode')
    manifest = gm.load_manifest(task_id)
    if manifest is None:
        raise ValueError('composition cache requires a saved scene manifest')
    value = {'settings': {key: settings[key] for key in fields},
             'snapshot': gm.scene_timing_snapshot(manifest),
             'sources': [gm.media_sha256(Path(source)) for source in sources],
             'audio': gm.media_sha256(Path(audio))}
    mix = gm.resolve_asset(task_id, 'narration_mix.json')
    value['mix'] = gm.media_sha256(mix) if mix.exists() else None
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def reusable_combined(task_id, candidate, key, sources, audio):
    import json
    target = Path(candidate)
    record = target.with_suffix('.editor.json')
    if not target.is_file():
        return False
    if record.exists():
        try:
            if record.stat().st_size > 4096:
                return False
            data = json.loads(record.read_text())
            return data['key'] == key and data['sha256'] == gm.media_sha256(target)
        except (OSError, ValueError, KeyError, TypeError):
            return False
    # Legacy completed tasks have no composition record. Any newer saved input
    # requires a rebuild; never reuse a video predating a changed scene/settings.
    inputs = [Path(source) for source in sources] + [Path(audio)]
    inputs += [gm.manifest_path(task_id), gm.resolve_asset(task_id, 'script.json')]
    mix = gm.resolve_asset(task_id, 'narration_mix.json')
    if mix.exists():
        inputs.append(mix)
    return all(item.is_file() and item.stat().st_mtime_ns <= target.stat().st_mtime_ns for item in inputs)


def record_combined(candidate, key):
    from app.services import scene_planner
    target = Path(candidate)
    scene_planner._atomic_write_json(target.with_suffix('.editor.json'),
                                     {'key': key, 'sha256': gm.media_sha256(target)})
