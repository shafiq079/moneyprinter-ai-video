"""Task-local music/SFX drafts, immutable uploads and deterministic CPU mixing."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import shutil
import subprocess
import uuid
import wave
from pathlib import Path

from app.services import generation_manifest as gm, scene_planner
from app.utils import utils

DRAFT = 'audio_layers.json'
ACTIVE = 'audio_layers_active.json'
MAX_UPLOAD = 50 * 1024 * 1024
MAX_ASSETS = 32
MAX_CLIPS = 32
MAX_BYTES = 1024 * 1024


def file(task_id, name=DRAFT):
    return gm.resolve_asset(task_id, name)


def revision(task_id):
    target = file(task_id)
    if not target.exists():
        return 'missing'
    if target.stat().st_size > MAX_BYTES:
        raise ValueError('audio arrangement metadata is too large')
    return gm.media_sha256(target)


def number(value, minimum, maximum):
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError('audio value is outside its allowed range')
    return value


def validate(data):
    if (not isinstance(data, dict) or data.get('schema_version') != 1
            or type(data.get('include_base')) is not bool or not isinstance(data.get('binding'), str)
            or not re.fullmatch('[a-f0-9]{64}', data['binding'])):
        raise ValueError('invalid audio arrangement')
    assets, clips = data.get('assets'), data.get('clips')
    if not isinstance(assets, dict) or len(assets) > MAX_ASSETS or not isinstance(clips, list) or len(clips) > MAX_CLIPS:
        raise ValueError('audio arrangement allows 32 assets and 32 clips')
    for key, asset in assets.items():
        if (not re.fullmatch('[a-f0-9]{32}', key) or not isinstance(asset, dict)
                or asset.get('asset') != f'audio_assets/{key}/audio.wav'
                or not re.fullmatch('[a-f0-9]{64}', str(asset.get('sha256', '')))
                or not isinstance(asset.get('name'), str) or not 1 <= len(asset['name']) <= 128):
            raise ValueError('invalid audio asset')
        number(asset.get('duration_ms'), 1, 600000)
    ids = set()
    required = {'id', 'asset_id', 'kind', 'start_ms', 'in_ms', 'out_ms', 'gain', 'muted', 'fade_in_ms', 'fade_out_ms'}
    for clip in clips:
        if (not isinstance(clip, dict) or set(clip) != required
                or not re.fullmatch('[a-f0-9]{32}', str(clip['id'])) or clip['id'] in ids
                or clip['asset_id'] not in assets or clip['kind'] not in {'music', 'sfx'}
                or type(clip['muted']) is not bool):
            raise ValueError('invalid audio clip')
        ids.add(clip['id'])
        for key in ('start_ms', 'in_ms', 'out_ms', 'fade_in_ms', 'fade_out_ms'):
            if type(clip[key]) is not int:
                raise ValueError('audio times must be integer milliseconds')
        number(clip['start_ms'], 0, 3600000)
        if not 0 <= clip['in_ms'] < clip['out_ms'] <= assets[clip['asset_id']]['duration_ms']:
            raise ValueError('audio trim must be inside the uploaded recording')
        duration = clip['out_ms'] - clip['in_ms']
        number(clip['fade_in_ms'], 0, duration)
        number(clip['fade_out_ms'], 0, duration)
        number(clip['gain'], 0, 2)
        if clip['start_ms'] + duration > 3600000:
            raise ValueError('audio arrangement cannot exceed one hour')


def read(task_id, name=DRAFT):
    target = file(task_id, name)
    if not target.exists():
        return None
    if target.stat().st_size > MAX_BYTES:
        raise ValueError('audio arrangement metadata is too large')
    data = json.loads(target.read_text(encoding='utf-8'))
    validate(data)
    return data


def save(task_id, name, data):
    validate(data)
    if len(json.dumps(data).encode()) > MAX_BYTES:
        raise ValueError('audio arrangement metadata is too large')
    scene_planner._atomic_write_json(file(task_id, name), data)


def load(task_id, binding, name=DRAFT):
    data = read(task_id, name)
    if data is None:
        return {'schema_version': 1, 'binding': binding, 'include_base': True, 'assets': {}, 'clips': []}
    if data['binding'] != binding:
        raise ValueError('source narration changed; restore or start a new audio arrangement')
    return data


def resolve_assets(task_id, data):
    for asset_id in {clip['asset_id'] for clip in data['clips']}:
        asset = data['assets'][asset_id]
        target = file(task_id, asset['asset'])
        if not target.is_file() or gm.media_sha256(target) != asset['sha256']:
            raise ValueError('uploaded audio is missing or changed; replace its clips')


def import_asset(task_id, content, name):
    if not isinstance(content, bytes) or not 0 < len(content) <= MAX_UPLOAD:
        raise ValueError('audio upload must be at most 50 MiB')
    suffix = Path(str(name)).suffix.lower()
    if suffix not in {'.wav', '.mp3', '.m4a', '.ogg', '.flac'}:
        raise ValueError('upload WAV, MP3, M4A, OGG or FLAC audio')
    key = uuid.uuid4().hex
    directory = file(task_id, f'audio_assets/{key}').parent / key
    directory.mkdir(parents=True, exist_ok=False)
    source, target = directory / f'upload{suffix}', directory / 'audio.wav'
    try:
        source.write_bytes(content)
        result = subprocess.run([utils.get_ffmpeg_binary(), '-nostdin', '-v', 'error', '-y', '-protocol_whitelist', 'file,pipe',
            '-format_whitelist', 'wav,mp3,mov,ogg,flac', '-i', str(source),
            '-map', '0:a:0', '-vn', '-t', '600.001', '-fs', '115265536', '-ac', '2', '-ar', '48000', '-c:a', 'pcm_s16le',
            '-threads', '1', str(target)], capture_output=True, timeout=60)
        if result.returncode:
            raise ValueError('audio upload could not be decoded')
        with wave.open(str(target), 'rb') as audio:
            duration = round(audio.getnframes() * 1000 / audio.getframerate())
        number(duration, 1, 600000)
        return key, {'asset': f'audio_assets/{key}/audio.wav', 'sha256': gm.media_sha256(target),
                     'duration_ms': duration, 'name': ' '.join(Path(str(name).replace('\\', '/')).name.split())[:128] or 'Audio'}
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    finally:
        source.unlink(missing_ok=True)


def edit(data, action, duration_ms, **changes):
    result = copy.deepcopy(data)
    clips = result['clips']
    if action == 'base':
        if type(changes.get('include_base')) is not bool:
            raise ValueError('choose whether to retain existing background music')
        result['include_base'] = changes['include_base']
    elif action == 'add':
        asset_id = changes.get('asset_id')
        if asset_id not in result['assets']:
            raise ValueError('select an uploaded audio asset')
        start = changes.get('start_ms', 0)
        number(start, 0, duration_ms - 1)
        end = min(result['assets'][asset_id]['duration_ms'], duration_ms - start)
        clips.append({'id': uuid.uuid4().hex, 'asset_id': asset_id, 'kind': changes.get('kind', 'music'),
            'start_ms': start, 'in_ms': 0, 'out_ms': end, 'gain': .25 if changes.get('kind', 'music') == 'music' else 1.,
            'muted': False, 'fade_in_ms': 0, 'fade_out_ms': 0})
    else:
        clip = next((item for item in clips if item['id'] == changes.get('clip_id')), None)
        if clip is None:
            raise ValueError('select an existing audio clip')
        if action == 'remove':
            clips.remove(clip)
        elif action == 'duplicate':
            clips.append({**clip, 'id': uuid.uuid4().hex})
        elif action == 'update':
            allowed = set(clip) - {'id', 'asset_id'}
            if set(changes) - allowed - {'clip_id'}:
                raise ValueError('unsupported audio clip change')
            clip.update({key: value for key, value in changes.items() if key in allowed})
        else:
            raise ValueError('unknown audio arrangement action')
    validate(result)
    changed_clips = result['clips'][-1:] if action in {'add', 'duplicate'} else [c for c in clips if c['id'] == changes.get('clip_id')] if action == 'update' else []
    for clip in changed_clips:
        if clip['start_ms'] + clip['out_ms'] - clip['in_ms'] > duration_ms:
            raise ValueError('audio clip must fit the current video; shorten its trim or move it earlier')
    return result


def render_mix(task_id, data, duration):
    """Mix only uploaded layers; upstream remains responsible for voice and BGM."""
    validate(data)
    resolve_assets(task_id, data)
    number(duration, .001, 3600)
    key = hashlib.sha256(json.dumps({'track': data, 'duration': duration}, sort_keys=True).encode()).hexdigest()
    target = file(task_id, f'audio_layer_mixes/{key}.wav')
    if target.is_file():
        with wave.open(str(target), 'rb') as audio:
            if abs(audio.getnframes() / audio.getframerate() - duration) <= .002:
                return str(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f'.{key}-{uuid.uuid4().hex}.wav')
    args, filters, inputs = [utils.get_ffmpeg_binary(), '-nostdin', '-v', 'error', '-y'], [], []
    for clip in data['clips']:
        start, begin, end = (clip[k] / 1000 for k in ('start_ms', 'in_ms', 'out_ms'))
        length = min(end - begin, duration - start)
        if clip['muted'] or clip['gain'] == 0 or length <= 0:
            continue
        index = len(inputs)
        args += ['-i', str(file(task_id, data['assets'][clip['asset_id']]['asset']))]
        chain = f'[{index}:a]atrim=start={begin}:duration={length},asetpts=PTS-STARTPTS,volume={clip["gain"]}'
        if clip['fade_in_ms']:
            chain += f',afade=t=in:d={clip["fade_in_ms"] / 1000}'
        if clip['fade_out_ms']:
            fade = min(length, clip['fade_out_ms'] / 1000)
            chain += f',afade=t=out:st={length - fade}:d={fade}'
        chain += f',adelay={clip["start_ms"]}|{clip["start_ms"]}[layer{index}]'
        filters.append(chain)
        inputs.append(f'[layer{index}]')
    if inputs:
        filters.append(''.join(inputs) + f'amix=inputs={len(inputs)}:normalize=0:dropout_transition=0,apad,atrim=end_sample={round(duration * 48000)},asetpts=N/SR/TB[mix]')
        args += ['-filter_complex', ';'.join(filters), '-map', '[mix]']
    else:
        args += ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-t', str(duration)]
    try:
        result = subprocess.run(args + ['-t', str(duration), '-fs', str(round(duration * 192000) + 65536), '-ac', '2', '-ar', '48000', '-c:a', 'pcm_s16le', '-threads', '1', str(temporary)],
                                capture_output=True, timeout=120)
        if result.returncode:
            raise ValueError('audio layers could not be mixed')
        with wave.open(str(temporary), 'rb') as rendered:
            if abs(rendered.getnframes() / rendered.getframerate() - duration) > .002:
                raise ValueError('audio mix duration validation failed')
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return str(target)


def saved_base_music(task_id, params):
    """Resolve legacy random/custom BGM once, so preview/export use one song."""
    from app.services import video
    key = hashlib.sha256(json.dumps({'type': params.bgm_type, 'file': params.bgm_file}, sort_keys=True).encode()).hexdigest()
    metadata = file(task_id, 'audio_base_music.json')
    if metadata.exists() and metadata.stat().st_size <= 4096:
        record = json.loads(metadata.read_text())
        if record.get('settings') == key and re.fullmatch(r'audio_base_music/[a-f0-9]{64}\.[a-z0-9]{1,8}', str(record.get('asset', ''))):
            candidate = file(task_id, record['asset'])
            if candidate.is_file() and gm.media_sha256(candidate) == record.get('sha256'):
                return str(candidate)
            raise ValueError('saved background music is missing or changed')
    selected = video.get_bgm_file(params.bgm_type, params.bgm_file)
    if not selected:
        return ''
    source = Path(selected)
    if not source.is_file() or source.stat().st_size > MAX_UPLOAD:
        raise ValueError('background music snapshot must be at most 50 MiB')
    digest = gm.media_sha256(source)
    suffix = source.suffix.lower()
    if not re.fullmatch(r'\.[a-z0-9]{1,8}', suffix):
        raise ValueError('unsupported background music file')
    target = file(task_id, f'audio_base_music/{digest}{suffix}')
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        temporary = target.with_name(f'.{digest}-{uuid.uuid4().hex}{suffix}')
        try:
            shutil.copyfile(source, temporary)
            if gm.media_sha256(temporary) != digest:
                raise ValueError('background music changed while saving')
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    scene_planner._atomic_write_json(metadata, {'settings': key, 'asset': target.relative_to(file(task_id).parent).as_posix(), 'sha256': digest})
    return str(target)
