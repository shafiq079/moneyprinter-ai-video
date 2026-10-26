"""Task-scoped OpenCut handoff; original generation/edit artifacts remain intact."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import threading
from pathlib import Path

from app.services import audio_layers as al, caption_edits as ce, editor_workspace as editor
from app.services import generation_manifest as gm, narration_mix as nm, scene_planner, task
from app.utils import utils

_save_lock = threading.RLock()
MAX_PROJECT = 8 * 1024 * 1024
MAX_ASSET = 512 * 1024 * 1024


def _secret():
    directory = Path(utils.storage_dir('opencut', create=True))
    target = directory / 'session.key'
    try:
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(secrets.token_bytes(32))
    return target.read_bytes()


def ticket(task_id):
    root = editor.task_root(task_id)
    if not (root / 'script.json').is_file():
        raise ValueError('saved task is unavailable')
    payload = base64.urlsafe_b64encode(json.dumps({'task': task_id, 'expires': int(time.time()) + 43200,
        'nonce': secrets.token_hex(12)}, separators=(',', ':')).encode()).decode().rstrip('=')
    return payload + '.' + hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()


def authorize(token):
    try:
        payload, signature = token.split('.')
        if not hmac.compare_digest(hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest(), signature):
            raise ValueError('invalid OpenCut session')
        data = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
        if data['expires'] < time.time():
            raise ValueError('OpenCut session expired; reopen it from Task Manager')
        editor.task_root(data['task'])
        return data['task']
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError('OpenCut session is invalid or expired; reopen it from Task Manager') from exc


def directory(task_id):
    target = editor.task_root(task_id) / 'opencut'
    if target.is_symlink():
        raise ValueError('invalid OpenCut project directory')
    target.mkdir(exist_ok=True)
    return target


def seed(task_id):
    """Build a portable import recipe with task-relative, opaque asset IDs."""
    root = editor.task_root(task_id)
    params, _, audio, captions, duration, _ = task._load_scene_regeneration_context(task_id)
    view = editor.build_view(task_id)
    if not all(s['ready'] for s in view['scenes']):
        raise ValueError('finish or resume the scene project before opening OpenCut')
    resources = {}
    def asset(filename):
        candidate = Path(filename).resolve()
        relative = candidate.relative_to(root.resolve()).as_posix()
        candidate = gm.resolve_asset(task_id, relative)
        key = hashlib.sha256(relative.encode()).hexdigest()
        resources[key] = {'asset': relative, 'name': candidate.name, 'size': candidate.stat().st_size}
        return key
    scenes = [{**{k: s[k] for k in ('id', 'start', 'duration', 'label')}, 'asset': asset(root / s['asset'])}
              for s in view['scenes']]
    audio_effective = nm.resolve(task_id, audio)
    tracks = [{'name': 'Narration', 'asset': asset(audio_effective), 'start': 0,
               'duration': view['duration'], 'in': 0, 'gain': params.voice_volume or 0, 'muted': False}]
    binding, milliseconds, base = task._caption_sources(task_id, audio)
    cues, style = [], {}
    if ce.file(task_id, ce.ACTIVE).exists():
        current = ce.resolve(task_id, binding, milliseconds)
        cues, style = current['cues'], current.get('style', {})
    elif base:
        cues = ce.parse_srt(Path(base).read_text(encoding='utf-8'))
    notes = []
    active = al.load(task_id, gm.media_sha256(Path(audio)), al.ACTIVE)
    al.resolve_assets(task_id, active)
    for clip in active['clips']:
        data = active['assets'][clip['asset_id']]
        # Each placement is an independent OpenCut audio element.
        source, source_in = root / data['asset'], clip['in_ms'] / 1000
        clip_duration = (clip['out_ms'] - clip['in_ms']) / 1000
        if clip['fade_in_ms'] or clip['fade_out_ms']:
            prepared = {**active, 'clips': [{**clip, 'start_ms': 0, 'gain': 1, 'muted': False}]}
            source = Path(al.render_mix(task_id, prepared, clip_duration))
            source_in = 0
            notes.append('Existing audio fades are retained in the imported audio clip; original recordings stay in MoneyPrinter.')
        tracks.append({'name': data['name'], 'asset': asset(source),
            'start': clip['start_ms'] / 1000, 'duration': clip_duration,
            'in': source_in, 'gain': clip['gain'], 'muted': clip['muted']})
    if active['include_base'] and params.bgm_type and params.bgm_volume > 0:
        if params.bgm_type in task._VIDEO_MUSIC_PROVIDERS:
            provider = task._VIDEO_MUSIC_PROVIDERS[params.bgm_type]
            saved = root / f"{params.bgm_type}-bgm-1{provider['suffix']}"
            song = str(saved) if saved.is_file() else ''
        else:
            song = al.saved_base_music(task_id, params)
        if song:
            song_duration = task.voice.get_audio_duration(song)
            at = 0
            while song_duration > 0 and at < view['duration']:
                length = min(song_duration, view['duration'] - at)
                tracks.append({'name': 'Background music', 'asset': asset(song), 'start': at,
                    'duration': length, 'in': 0, 'gain': params.bgm_volume, 'muted': False})
                at += length
        else:
            notes.append('The previous background song is unavailable; no replacement was generated.')
    if any(c.get('spans') for c in cues):
        notes.append('Selected-word caption colors use the cue color on initial OpenCut import.')
    settings = params.model_dump(mode='json')
    return {'schema_version': 1, 'task_id': task_id, 'name': view['subject'], 'duration': view['duration'],
            'scenes': scenes, 'audio': tracks, 'captions': cues, 'caption_style': style, 'settings': {
                k: settings[k] for k in ('video_aspect', 'font_size', 'font_name', 'text_fore_color',
                    'text_background_color', 'subtitle_position', 'custom_position', 'stroke_color', 'stroke_width')},
            'resources': resources, 'notes': list(dict.fromkeys(notes))}


def session(task_id):
    saved = directory(task_id) / 'project.json'
    if saved.is_file():
        if saved.stat().st_size > MAX_PROJECT:
            raise ValueError('OpenCut project metadata is too large')
        data = json.loads(saved.read_text(encoding='utf-8'))
        validate_saved(data, saved.parent)
        return {'task_id': task_id, 'mode': 'restore', 'revision': gm.media_sha256(saved), **data}
    return {'task_id': task_id, 'mode': 'seed', 'revision': 'missing', 'seed': seed(task_id)}


def validate_saved(value, root):
    if not isinstance(value, dict) or set(value) != {'project', 'media'}:
        raise ValueError('invalid OpenCut project')
    project, media = value['project'], value['media']
    if not isinstance(project, dict) or not isinstance(project.get('metadata'), dict) or not isinstance(project.get('scenes'), list):
        raise ValueError('invalid OpenCut project metadata')
    if not isinstance(media, list) or len(media) > 1024:
        raise ValueError('OpenCut supports up to 1024 media assets per task')
    for record in media:
        if not isinstance(record, dict) or not isinstance(record.get('id'), str):
            raise ValueError('invalid OpenCut media reference')
        digest = record.get('blob')
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('invalid OpenCut media digest')
        if not (root / 'media' / digest).is_file():
            raise ValueError('save all media before saving the OpenCut project')
    if len(json.dumps(value).encode()) > MAX_PROJECT:
        raise ValueError('OpenCut project metadata exceeds 8 MiB')


def save(task_id, value, expected_revision):
    validate_saved(value, directory(task_id))
    target = directory(task_id) / 'project.json'
    with _save_lock:
        revision = gm.media_sha256(target) if target.exists() else 'missing'
        if revision != expected_revision:
            raise ValueError('OpenCut project changed in another tab; reopen it before saving')
        scene_planner._atomic_write_json(target, value)
        os.utime(target.parent.parent, None)
        return gm.media_sha256(target)
