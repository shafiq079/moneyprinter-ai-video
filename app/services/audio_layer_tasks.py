"""Audio arrangement commands on the existing task reservation/render boundary."""
import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path

from app.services import audio_layers as layers, generation_manifest as gm


def context(task_id, *, queued=False, read_only=False):
    from app.services import task
    value = task.caption_editor_context(task_id, read_only=True)
    if not read_only:
        task._assert_scene_edit_available(value['prior'], queued=queued, stage='audio_layers')
    value['audio_binding'] = value['binding']['source_audio']['sha256']
    return value


def signature(task_id, value, snapshot):
    from app.services import caption_edits
    pieces = {'params': caption_edits.render_signature(value['params']), 'snapshot': snapshot,
              'binding': value['audio_binding'], 'duration_ms': value['duration_ms']}
    for name in ('narration_mix.json', 'caption_track.json'):
        target = layers.file(task_id, name)
        pieces[name] = gm.media_sha256(target) if target.exists() else None
    return hashlib.sha256(json.dumps(pieces, sort_keys=True).encode()).hexdigest()


def preview(task_id, value, snapshot):
    target = layers.file(task_id, 'audio_layers_preview.json')
    try:
        if target.stat().st_size > layers.MAX_BYTES:
            return None
        data = json.loads(target.read_text())
        if data['revision'] != layers.revision(task_id) or data['signature'] != signature(task_id, value, snapshot):
            return None
        if not isinstance(data['asset'], str) or not re.fullmatch(r'audio_previews/[a-f0-9]{32}/preview\.mp4', data['asset']):
            return None
        if gm.media_sha256(layers.file(task_id, data['asset'])) != data['sha256']:
            return None
        return data
    except (OSError, ValueError, KeyError, TypeError):
        return None


def restore_active(task_id, content):
    target = layers.file(task_id, layers.ACTIVE)
    if content is None:
        target.unlink(missing_ok=True)
        return
    handle, name = tempfile.mkstemp(dir=target.parent, prefix='.audio-layer-', suffix='.tmp')
    try:
        with os.fdopen(handle, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)


def run(task_id, *, action, expected_revision, expected_binding, expected_snapshot=None,
        queued=False, content=None, name=None, **changes):
    from app.services import task
    value = context(task_id, queued=queued)
    if value['audio_binding'] != expected_binding:
        raise ValueError('audio sources changed; refresh the editor')
    if layers.revision(task_id) != expected_revision:
        raise ValueError('audio draft changed; refresh the editor')
    data = layers.load(task_id, expected_binding)
    def check():
        if layers.revision(task_id) != expected_revision or context(task_id, read_only=True)['audio_binding'] != expected_binding:
            raise ValueError('audio draft or sources changed while editing')
    if action in {'upload', 'import_base'}:
        if len(data['assets']) >= layers.MAX_ASSETS:
            raise ValueError('audio library is limited to 32 assets')
        if action == 'import_base':
            provider = task._VIDEO_MUSIC_PROVIDERS.get(value['params'].bgm_type)
            if provider:
                source = layers.file(task_id, f"{value['params'].bgm_type}-bgm-1{provider['suffix']}")
            else:
                selected = layers.saved_base_music(task_id, value['params'])
                source = Path(selected) if selected else None
            if source is None or not source.is_file() or source.stat().st_size > layers.MAX_UPLOAD:
                raise ValueError('saved background music is unavailable; upload an audio file instead')
            content, name = source.read_bytes(), source.name
        asset_id, asset = layers.import_asset(task_id, content, name)
        if action == 'import_base':
            asset['name'] = 'Saved background music'
        try:
            check()
            data['assets'][asset_id] = asset
            if action == 'import_base':
                data = layers.edit(data, 'add', value['duration_ms'], asset_id=asset_id, kind='music')
                data['clips'][-1]['gain'] = min(2., max(0., float(value['params'].bgm_volume)))
                data['include_base'] = False
            layers.save(task_id, layers.DRAFT, data)
        except Exception:
            shutil.rmtree(layers.file(task_id, asset['asset']).parent, ignore_errors=True)
            raise
        return {'asset_id': asset_id}
    if action == 'reset':
        active = layers.read(task_id, layers.ACTIVE)
        check()
        layers.save(task_id, layers.DRAFT, active or {'schema_version': 1, 'binding': expected_binding,
            'include_base': True, 'assets': data['assets'], 'clips': []})
        return {'reset': True}
    if action not in {'apply', 'restore', 'preview'}:
        edited = layers.edit(data, action, value['duration_ms'], **changes)
        check()
        layers.save(task_id, layers.DRAFT, edited)
        return {'saved': True}
    snapshot = gm.scene_timing_snapshot(gm.load_manifest(task_id))
    if snapshot != expected_snapshot:
        raise ValueError('scene inputs changed; refresh the editor')
    if action != 'restore':
        layers.resolve_assets(task_id, data)
    expected_signature = signature(task_id, value, snapshot)
    active = layers.file(task_id, layers.ACTIVE)
    old = active.read_bytes() if active.exists() else None
    root = str(layers.file(task_id).parent)
    backups = task._backup_render_paths(root, suffix='audio-layers-backup')
    preview_dir = None
    try:
        check()
        if action == 'restore':
            active.unlink(missing_ok=True)
        else:
            layers.save(task_id, layers.ACTIVE, data)
        task._clear_render_paths(root)
        finals, combined, warnings = task.generate_final_videos(task_id, value['params'], gm.active_scene_paths(task_id),
            value['audio'], value['captions'], value['duration'], reuse_existing_generated_bgm=True)
        check()
        if (gm.scene_timing_snapshot(gm.load_manifest(task_id)) != snapshot
                or signature(task_id, context(task_id, read_only=True), snapshot) != expected_signature):
            raise ValueError('scene inputs changed during audio rendering')
        if action == 'preview':
            preview_dir = layers.file(task_id, f'audio_previews/{uuid.uuid4().hex}/preview.mp4').parent
            preview_dir.mkdir(parents=True)
            output = preview_dir / 'preview.mp4'
            shutil.copy2(finals[0], output)
            result = {'revision': expected_revision, 'signature': signature(task_id, value, snapshot),
                      'asset': output.relative_to(Path(root)).as_posix(), 'sha256': gm.media_sha256(output)}
            task.scene_planner._atomic_write_json(layers.file(task_id, 'audio_layers_preview.json'), result)
        else:
            result = {'task_id': task_id, 'videos': finals}
    except Exception:
        task.sm.state.update_task(task_id, **{key: value['prior'].get(key, default) for key, default in
            (('state', task.const.TASK_STATE_FAILED), ('progress', 0), ('current_stage', None))})
        restore_active(task_id, old)
        task._restore_render_backups(root, backups)
        if preview_dir:
            shutil.rmtree(preview_dir, ignore_errors=True)
        raise
    if action == 'preview':
        task.sm.state.update_task(task_id, **{key: value['prior'].get(key, default) for key, default in
            (('state', task.const.TASK_STATE_FAILED), ('progress', 0), ('current_stage', None))})
        restore_active(task_id, old)
        task._restore_render_backups(root, backups)
    else:
        task._discard_render_backups(backups)
        task.sm.state.update_task(task_id, state=task.const.TASK_STATE_COMPLETE, progress=100,
            current_stage=None, videos=finals, combined_videos=combined, warnings=warnings or None)
    return result
