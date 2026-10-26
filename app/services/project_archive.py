"""Versioned, self-contained editor projects over the existing task contracts."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from app.models.schema import VideoParams
from app.services import audio_layers as al, caption_edits as ce, generation_manifest as gm
from app.services import editor_workspace as editor, narration_mix as nm, narration_ranges as nr
from app.services import scene_planner, task, webui_task
from app.utils import utils

FORMAT = 'moneyprinter-editable-project'
VERSION = 1
MAX_ARCHIVE = 512 * 1024 * 1024
MAX_TOTAL = 2 * 1024 * 1024 * 1024
MAX_FILES = 4096
MAX_JSON = 2 * 1024 * 1024
ROOT_FILES = {'script.json', 'scene_plan.json', 'audio.mp3', 'subtitle.srt',
              'narration_ranges.json', nm.NAME,
              ce.DRAFT, ce.ACTIVE, al.DRAFT, al.ACTIVE, 'audio_base_music.json'}
FOLDERS = {'generated_ai', 'narration_previews', 'narration_replacements', 'narration_mixes', 'audio_assets',
           'audio_base_music', 'caption_tracks', 'project_audio', 'custom-audio'}


def _name(value):
    if (not isinstance(value, str) or not value or len(value) > 240 or '\\' in value
            or any(ord(c) < 32 for c in value) or ':' in value or any(p in {'', '.', '..'} for p in value.split('/'))
            or any(p.endswith((' ', '.')) for p in value.split('/'))
            or PurePosixPath(value).is_absolute()):
        raise ValueError('unsafe project path')
    return value


def _allowed(name):
    _name(name)
    if name.startswith('opencut/'):
        return bool(re.fullmatch(r'opencut/(?:project\.json|media/[a-f0-9]{64}|exports/[a-f0-9]{32}\.(?:mp4|webm))', name))
    p = PurePosixPath(name)
    if len(p.parts) == 1:
        return name in ROOT_FILES or bool(re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_. -]*\.(?:mp3|wav|m4a|ogg|flac)', name)) or bool(re.fullmatch(r'(custom-audio-[A-Za-z0-9_.-]+\.(?:mp3|wav|m4a|ogg|flac)|final-\d+\.mp4|[a-z0-9_-]+-bgm-\d+\.[a-z0-9]+)', name))
    return p.parts[0] in FOLDERS and p.suffix.lower() in {'.json', '.mp4', '.wav', '.mp3', '.m4a', '.ogg', '.flac', '.srt'} and not any(part.startswith('.') for part in p.parts)


def _json(path):
    limit = 8 * 1024 * 1024 if path.name == 'project.json' and path.parent.name == 'opencut' else MAX_JSON
    if path.stat().st_size > limit:
        raise ValueError('project metadata is too large')
    return json.loads(path.read_text(encoding='utf-8'))


def _write(path, data):
    scene_planner._atomic_write_json(path, data)


def _references(value, root, key=''):
    """Reject external/missing references before any media parser sees metadata."""
    if isinstance(value, dict):
        for k, v in value.items():
            if gm._metadata_key_is_private(k):
                raise ValueError('private host configuration is not allowed in a project')
            if '/' in k and k.endswith('.mp4'):
                _reference(k, root)
            _references(v, root, k)
    elif isinstance(value, list):
        for v in value:
            _references(v, root, key)
    elif isinstance(value, str) and value and (key in {'asset', 'active_asset', 'audio_asset', 'captions_asset', 'script_asset', 'preview_asset', 'versions', 'custom_audio_file', 'bgm_file'}):
        _reference(value, root)


def _reference(value, root):
    _name(value)
    if not (root / value).is_file():
        raise ValueError(f'project asset is missing: {value}')


def _validate_media(root):
    formats = {'.webm': 'matroska', '.mp4': 'mov', '.m4a': 'mov', '.mp3': 'mp3', '.wav': 'wav', '.ogg': 'ogg', '.flac': 'flac'}
    for candidate in root.rglob('*'):
        fmt = formats.get(candidate.suffix.lower())
        if not candidate.is_file() or not fmt:
            continue
        result = subprocess.run([utils.get_ffmpeg_binary(), '-nostdin', '-v', 'error',
            '-protocol_whitelist', 'file,pipe', '-format_whitelist', 'matroska,webm,mov,wav,mp3,ogg,flac',
            '-f', fmt, '-i', str(candidate), '-t', '0.04', '-threads', '1', '-f', 'null', '-'],
            capture_output=True, timeout=20)
        if result.returncode:
            raise ValueError('project media cannot be decoded safely: ' + candidate.name)


def _validate(task_id, audio_ref):
    root = Path(utils.task_dir(task_id))
    for candidate in root.rglob('*.json'):
        _references(_json(candidate), root)
    _validate_media(root)
    data = _json(root / 'script.json')
    params = VideoParams.model_validate(data['params'])
    if params.content_mode != 'creative' or not task.local_ai.is_local_ai_source(params.video_source):
        raise ValueError('project archives currently support creative AI scene projects')
    if params.font_name:
        from app.utils import file_security
        file_security.resolve_path_within_directory(utils.font_dir(), params.font_name)
    selected = task._load_scene_regeneration_context(task_id)[2]
    if Path(selected).resolve() != (root / audio_ref).resolve():
        raise ValueError('project narration reference disagrees with saved settings')
    if params.video_count > 16 or not 1 <= (params.n_threads or 2) <= 16:
        raise ValueError('project export settings exceed supported limits')
    _reference(audio_ref, root)
    duration = task.voice.get_audio_duration(str(root / audio_ref))
    if not 0 < duration <= 3600:
        raise ValueError('project narration must be between zero and one hour')
    plan = scene_planner.load_scene_plan(task_id)
    manifest = gm.load_manifest(task_id)
    order = gm.scene_playback_order(manifest)
    gm.active_scene_paths(task_id)
    from app.services.local_ai.media import validate_video_clip
    for record in manifest['scenes']:
        if record.get('asset_origin') != 'imported':
            validate_video_clip(gm.resolve_asset(task_id, record['active_asset']), gm.scene_spec_from_version_metadata(record))
    if plan is None or len(order) > 512 or set(order) != {s.scene_id for s in plan.scenes}:
        raise ValueError('all project scenes must have a saved ready clip')
    # Decode all retained versions, including inactive ones, before publishing.
    for candidate in root.rglob('*.mp4'):
        clip = task.video._open_video_clip_quietly(str(candidate))
        try:
            if not clip.duration or clip.duration <= 0:
                raise ValueError('project video has no frames')
        finally:
            task.video.close_clip(clip)
    plan = scene_planner.load_scene_plan(task_id)
    if nr._file(task_id).exists():
        ranges = nr.load_validated(task_id, plan, str(root / audio_ref))
        for item in ranges['ranges']:
            nr._preview(task_id, item)
            if item.get('replacement'):
                nr._preview(task_id, {**item, **item['replacement']}, replacement=True)
    nm.resolve(task_id, str(root / audio_ref))
    context = task.caption_editor_context(task_id, read_only=True)
    for name in (ce.DRAFT, ce.ACTIVE):
        if ce.file(task_id, name).exists():
            ce.load_validated(task_id, context['binding'], context['duration_ms'], name)
            if name == ce.ACTIVE:
                ce.resolve(task_id, context['binding'], context['duration_ms'])
    for name in (al.DRAFT, al.ACTIVE):
        if al.file(task_id, name).exists():
            al.resolve_assets(task_id, al.load(task_id, gm.media_sha256(root / audio_ref), name))
    saved_opencut = root / 'opencut' / 'project.json'
    if saved_opencut.is_file():
        from app.services import opencut
        opencut.validate_saved(_json(saved_opencut), saved_opencut.parent)
    return params, duration


def export_project(task_id):
    """Return a temporary ZIP path. Caller owns deletion after offering download."""
    with webui_task._resume_submission_lock:
        view = editor.build_view(task_id)
        if view['busy']:
            raise ValueError('wait for the current task operation before exporting a project')
        if view['params'].content_mode != 'creative':
            raise ValueError('project archives currently support creative AI scene projects')
        root = editor.task_root(task_id)
        params, _, audio, _, _, _ = task._load_scene_regeneration_context(task_id)
        audio_path = Path(audio).resolve()
        audio_ref = audio_path.relative_to(root.resolve()).as_posix()
        # Freeze legacy music before copying so a random song does not change on import.
        music = ''
        if params.bgm_type and params.bgm_type not in task._VIDEO_MUSIC_PROVIDERS and params.bgm_volume > 0:
            music = al.saved_base_music(task_id, params)
        before = {p.relative_to(root).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns)
                  for p in root.rglob('*') if p.is_file() and _allowed(p.relative_to(root).as_posix())}
        if sum(size for size, _ in before.values()) > MAX_ARCHIVE or len(before) > MAX_FILES:
            raise ValueError('project exceeds archive limits')
        with tempfile.TemporaryDirectory(prefix='mpt-project-') as directory:
            stage = Path(directory)
            for name in before:
                source = root / name
                if source.is_symlink() or source.resolve().is_relative_to(root.resolve()) is False:
                    raise ValueError('project assets cannot be symbolic links')
                destination = stage / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            if audio_ref not in before:
                raise ValueError('original narration must use a supported task-local audio location')
            script = _json(stage / 'script.json')
            portable_params = params.model_dump(mode='json')
            portable_params['custom_audio_file'] = audio_ref if audio_ref != 'audio.mp3' else None
            portable_params['video_materials'] = None
            portable_params['bgm_file'] = ''
            if music:
                portable_params['bgm_type'] = 'custom'
                portable_params['bgm_file'] = Path(music).relative_to(root).as_posix()
                record = _json(stage / 'audio_base_music.json')
                record['settings'] = hashlib.sha256(json.dumps({'type': 'custom', 'file': portable_params['bgm_file']}, sort_keys=True).encode()).hexdigest()
                _write(stage / 'audio_base_music.json', record)
            script = {'script': script['script'], 'search_terms': script.get('search_terms', []), 'params': portable_params}
            _write(stage / 'script.json', script)
            records = {}
            total = 0
            for candidate in sorted(stage.rglob('*')):
                if not candidate.is_file():
                    continue
                name = candidate.relative_to(stage).as_posix()
                if candidate.suffix == '.json':
                    _references(_json(candidate), stage)
                size = candidate.stat().st_size
                total += size
                records[name] = {'size': size, 'sha256': gm.media_sha256(candidate),
                                 'modified_ns': before.get(name, (size, candidate.stat().st_mtime_ns))[1]}
            if total > MAX_TOTAL or len(records) > MAX_FILES:
                raise ValueError('project exceeds archive limits')
            _write(stage / 'project.json', {'format': FORMAT, 'schema_version': VERSION,
                'audio': audio_ref, 'files': records})
            handle, filename = tempfile.mkstemp(suffix='.mptproject.zip')
            os.close(handle)
            output = Path(filename)
            try:
                with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as archive:
                    for candidate in sorted(stage.rglob('*')):
                        if candidate.is_file():
                            archive.write(candidate, candidate.relative_to(stage).as_posix())
                if output.stat().st_size > MAX_ARCHIVE:
                    raise ValueError('project archive exceeds 512 MiB')
                after = {p.relative_to(root).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns)
                         for p in root.rglob('*') if p.is_file() and _allowed(p.relative_to(root).as_posix())}
                if before != after or editor.build_view(task_id)['busy']:
                    raise ValueError('project changed during export; try again when idle')
                return output
            except Exception:
                output.unlink(missing_ok=True)
                raise


def import_project(source):
    """Validate in a hidden staging directory; atomically publish a fresh task."""
    task_id = str(uuid.uuid4())
    staging_id = '.project-import-' + uuid.uuid4().hex
    root = Path(utils.task_dir(staging_id))
    published = None
    try:
        source.seek(0, 2)
        if source.tell() > MAX_ARCHIVE:
            raise ValueError('project archive exceeds 512 MiB')
        source.seek(0)
        with zipfile.ZipFile(source) as archive:
            infos = archive.infolist()
            names = [i.filename for i in infos]
            if len(names) > MAX_FILES + 1 or len(set(n.casefold() for n in names)) != len(names):
                raise ValueError('project contains too many or duplicate files')
            if 'project.json' not in names or sum(i.file_size for i in infos) > MAX_TOTAL:
                raise ValueError('invalid or oversized project archive')
            for info in infos:
                _name(info.filename)
                mode = info.external_attr >> 16
                if (info.is_dir() or stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG))
                        or info.flag_bits & 1 or (info.filename != 'project.json' and not _allowed(info.filename))):
                    raise ValueError('unsupported project archive entry')
                limit = 8 * 1024 * 1024 if info.filename == 'opencut/project.json' else MAX_JSON
                if info.filename.endswith('.json') and info.file_size > limit:
                    raise ValueError('project metadata is too large')
            manifest = json.loads(archive.read('project.json'))
            if manifest.get('format') != FORMAT or manifest.get('schema_version') != VERSION:
                raise ValueError('unsupported editable project version')
            files = manifest.get('files')
            if not isinstance(files, dict) or set(files) != set(names) - {'project.json'}:
                raise ValueError('project inventory does not match archive')
            for name, record in files.items():
                if not isinstance(record, dict) or record.get('size') != archive.getinfo(name).file_size:
                    raise ValueError('invalid project file size')
                destination = root / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as incoming, destination.open('wb') as outgoing:
                    shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
                if gm.media_sha256(destination) != record.get('sha256'):
                    raise ValueError(f'project file checksum failed: {name}')
                modified = record.get('modified_ns')
                if modified is not None:
                    if type(modified) is not int or not 0 <= modified <= 2**63 - 1:
                        raise ValueError('invalid project file timestamp')
                    os.utime(destination, ns=(modified, modified))
        audio_ref = _name(manifest.get('audio'))
        _write(root / 'project_import.json', {'schema_version': 1, 'audio': audio_ref})
        params, duration = _validate(staging_id, audio_ref)
        if params.bgm_file:
            record = _json(root / 'audio_base_music.json')
            expected = hashlib.sha256(json.dumps({'type': params.bgm_type, 'file': params.bgm_file}, sort_keys=True).encode()).hexdigest()
            if (record.get('settings') != expected or record.get('asset') != params.bgm_file
                    or gm.media_sha256(root / params.bgm_file) != record.get('sha256')):
                raise ValueError('saved background music binding changed')
        # Preserve relative references, including original narration bindings.
        destination = Path(utils.task_dir()) / task_id
        if destination.exists():
            raise ValueError('new project ID already exists')
        root.rename(destination)
        published = destination
        final = sorted(str(p) for p in published.glob('final-*.mp4'))
        task.sm.state.update_task(task_id, state=task.const.TASK_STATE_COMPLETE, progress=100,
            audio_file=str(published / audio_ref), audio_duration=duration,
            subtitle_path=str(published / 'subtitle.srt') if (published / 'subtitle.srt').exists() else '',
            videos=final, combined_videos=[], imported_project=True)
        return task_id
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        if published is not None:
            shutil.rmtree(published, ignore_errors=True)
            task.sm.state.delete_task(task_id)
        raise
