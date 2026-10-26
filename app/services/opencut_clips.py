"""Independent OpenCut clip candidates. Never mutate the generation manifest/render."""
from __future__ import annotations

import json
import math
import os
import re
import secrets
import shutil
import subprocess
from filelock import FileLock, Timeout
from app.utils import utils
import threading
import uuid
from queue import Queue, Full
from contextlib import ExitStack
from pathlib import Path
from functools import lru_cache

from loguru import logger

from app.services import generation_manifest as gm, opencut, scene_planner, task
from app.services import local_ai
from app.services.local_ai.media import validate_video_clip

_queue = Queue(maxsize=16)
_worker_started = False
_lock = threading.RLock()
_owner = uuid.uuid4().hex


def _read(task_id, name, default):
    target = opencut.directory(task_id) / name
    if not target.exists():
        return default
    if target.is_symlink() or target.stat().st_size > opencut.MAX_PROJECT:
        raise ValueError('invalid OpenCut clip metadata')
    return json.loads(target.read_text(encoding='utf-8'))


def _write(task_id, name, value):
    scene_planner._atomic_write_json(opencut.directory(task_id) / name, value)


def _scene(task_id, scene_id):
    params, plan, *_ = task._load_scene_regeneration_context(task_id)
    scene = next((s for s in plan.scenes if s.scene_id == scene_id), None)
    if scene is None:
        raise ValueError('scene is unavailable')
    return params, plan, scene


@lru_cache(maxsize=512)
def _cached_digest(filename, size, modified_ns):
    return gm.media_sha256(Path(filename))


def catalog(task_id):
    params, plan, *_ = task._load_scene_regeneration_context(task_id)
    manifest = gm.load_manifest(task_id)
    candidates = _read(task_id, 'clips.json', [])
    scenes = []
    for scene in plan.scenes:
        record = gm.scene_record(manifest, scene.scene_id)
        versions = []
        for relative in record.get('versions', []):
            try:
                source = gm.resolve_asset(task_id, relative)
                if not source.is_file():
                    continue
            except ValueError:
                continue
            metadata = gm.scene_version_metadata(record, relative) or record
            versions.append({'id': _cached_digest(str(source), source.stat().st_size, source.stat().st_mtime_ns), 'name': Path(relative).stem,
                'origin': metadata.get('asset_origin', 'generated'),
                'source': relative, 'duration': metadata.get('actual_duration') or scene.target_duration,
                'prompt': metadata.get('prompt') or scene.prompt, 'seed': metadata.get('seed', scene.seed)})
        versions += [v for v in candidates if v['scene_id'] == scene.scene_id]
        scenes.append({'id': scene.scene_id, 'label': scene.narration_segment,
            'prompt': scene.prompt, 'seed': scene.seed, 'duration': scene.target_duration,
            'provider': params.video_source, 'mode': scene.provider_settings.get('mode', params.local_ai_generation_mode),
            'versions': versions})
    job = _read(task_id, 'clip-job.json', None)
    if job and job['status'] in {'queued', 'generating'}:
        try:
            lease = _claim(task_id)
        except ValueError:
            pass
        else:
            lease.release()
            job = {**job, 'status': 'interrupted', 'message': 'Generation was interrupted. Generate again when ready.'}
    if job and _cancel_file(task_id, job['id']).exists() and job['status'] in {'queued', 'generating'}:
        job = {**job, 'message': 'Cancelling after the current provider request returns…'}
    return {'scenes': scenes, 'job': job}


def version_file(task_id, scene_id, version_id):
    for scene in catalog(task_id)['scenes']:
        if scene['id'] == scene_id:
            for version in scene['versions']:
                if version['id'] == version_id:
                    target = gm.resolve_asset(task_id, version['source'])
                    if gm.media_sha256(target) != version.get('blob', version_id):
                        raise ValueError('clip changed; refresh the editor')
                    return target
    raise ValueError('clip version is unavailable')


def _publish(task_id, scene, target, *, origin):
    if not 0 < target.stat().st_size <= opencut.MAX_ASSET:
        raise ValueError('clip exceeds the 512 MiB limit')
    probe = validate_video_clip(target, scene)
    digest = gm.media_sha256(target)
    media = opencut.directory(task_id) / 'media'
    media.mkdir(exist_ok=True)
    destination = media / digest
    if not destination.exists():
        temporary = media / ('.' + uuid.uuid4().hex)
        try:
            shutil.copyfile(target, temporary)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
    with _lock:
        versions = _read(task_id, 'clips.json', [])
        if len(versions) >= 512:
            raise ValueError('this project has reached its 512 candidate limit')
        version_id = uuid.uuid4().hex
        versions.append({'id': version_id, 'blob': digest, 'scene_id': scene.scene_id,
            'name': f'Version {len([v for v in versions if v["scene_id"] == scene.scene_id]) + 1}',
            'source': 'opencut/media/' + digest, 'duration': probe.duration,
            'prompt': scene.prompt, 'seed': scene.seed, 'origin': origin})
        if len(json.dumps(versions).encode()) > 2 * 1024 * 1024:
            raise ValueError('clip history exceeds the portable project metadata limit')
        _write(task_id, 'clips.json', versions)
    return version_id


def _claim(task_id):
    lease = FileLock(opencut.directory(task_id) / '.clip-generation.lock', thread_local=False)
    try:
        lease.acquire(timeout=0)
    except Timeout as exc:
        raise ValueError('a clip operation is already running for this project') from exc
    return lease


def _cancel_file(task_id, job_id):
    return opencut.directory(task_id) / ('.clip-cancel-' + job_id)


def _run(task_id, job, scene, source, lease):
    target = opencut.directory(task_id) / ('.candidate-' + job['id'] + '.mp4')
    try:
        if _cancel_file(task_id, job['id']).exists():
            job.update(status='cancelled', message='Generation cancelled.')
            return
        job.update(status='generating', message='Generating clip. Your current timeline is unchanged.')
        _write(task_id, 'clip-job.json', job)
        provider = local_ai.prepare_provider(source, generation_mode=str(scene.provider_settings.get('mode', 'fast')))
        with ExitStack() as stack:
            factory = getattr(provider, 'generation_session', None)
            if callable(factory):
                stack.enter_context(factory())
            provider.preflight()
            provider.load_runtime()
            provider.generate(scene, target)
            provider.validate_output(target, scene)
        with _lock:
            if _cancel_file(task_id, job['id']).exists():
                job.update(status='cancelled', message='Result discarded; your current clip is unchanged.')
            else:
                digest = _publish(task_id, scene, target, origin='generated')
                job.update(status='ready', version_id=digest, message='New version ready to preview.')
    except Exception as exc:
        logger.warning('OpenCut clip generation failed: scene={}, error={}', scene.scene_id, type(exc).__name__)
        job.update(status='failed', message='Clip generation failed. Check provider configuration and retry; your current clip is unchanged.')
    finally:
        target.unlink(missing_ok=True)
        try:
            with _lock:
                _write(task_id, 'clip-job.json', job)
            _cancel_file(task_id, job['id']).unlink(missing_ok=True)
        finally:
            lease.release()


def _work():
    while True:
        arguments = _queue.get()
        try:
            _run(*arguments)
        except Exception:
            logger.error('OpenCut clip worker could not publish job status')
        finally:
            arguments[-1].release()
            _queue.task_done()


def _enqueue(arguments):
    global _worker_started
    if not _worker_started:
        # The gateway can stop promptly during provider work. Immutable media and
        # atomic sidecars keep interrupted jobs recoverable; OS leases auto-release.
        threading.Thread(target=_work, name='opencut-clip', daemon=True).start()
        _worker_started = True
    try:
        _queue.put_nowait(arguments)
    except Full as exc:
        raise ValueError('clip queue is full; try again later') from exc


def submit(task_id, scene_id, value):
    if not isinstance(value, dict) or set(value) - {'prompt', 'seed', 'variation'}:
        raise ValueError('invalid clip request')
    params, plan, scene = _scene(task_id, scene_id)
    versions = _read(task_id, 'clips.json', [])
    if len(versions) >= 512 or len(json.dumps(versions).encode()) > 2 * 1024 * 1024 - 6000:
        raise ValueError('clip history limit reached; start a new project before generating more versions')
    prompt = value.get('prompt', scene.prompt)
    seed = value.get('seed', scene.seed)
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 4000:
        raise ValueError('prompt must contain 1–4000 characters')
    if type(seed) is not int or not 0 <= seed <= 2147483647:
        raise ValueError('seed must be an integer between 0 and 2147483647')
    if value.get('variation'):
        seed = secrets.randbelow(2147483647)
    _, revised = scene_planner.revise_scene_plan(plan, scene_id, prompt=prompt, seed=seed)
    with _lock:
        job = catalog(task_id)['job']
        if job and job['status'] in {'queued', 'generating'}:
            raise ValueError('a clip is already generating for this project')
        lease = _claim(task_id)
        job = {'id': uuid.uuid4().hex, 'owner': _owner, 'scene_id': scene_id,
               'status': 'queued', 'message': 'Waiting to generate clip.', 'prompt': revised.prompt, 'seed': seed}
        try:
            _write(task_id, 'clip-job.json', job)
            _enqueue((task_id, job, revised, params.video_source, lease))
        except Exception:
            lease.release()
            raise
        return job


def cancel(task_id):
    with _lock:
        job = _read(task_id, 'clip-job.json', {})
        if job.get('status') in {'queued', 'generating'}:
            _cancel_file(task_id, job['id']).touch()
            job['message'] = 'Cancelling after the current provider request returns…'
        return job


def upload(task_id, scene_id, target):
    _, _, scene = _scene(task_id, scene_id)
    lease = _claim(task_id)
    normalized = target.with_suffix('.normalized.mp4')
    try:
        result = subprocess.run([utils.get_ffmpeg_binary(), '-nostdin', '-y', '-v', 'error',
            '-xerror', '-protocol_whitelist', 'file,pipe', '-f', 'mov', '-i', str(target),
            '-map', '0:v:0', '-an', '-sn', '-dn', '-map_metadata', '-1',
            '-vf', 'setsar=1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
            '-preset', 'veryfast', '-threads', '1', '-t', '3600', '-movflags', '+faststart',
            str(normalized)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
        if result.returncode:
            raise ValueError('uploaded MP4 could not be decoded')
        return _publish(task_id, scene, normalized, origin='uploaded')
    except subprocess.TimeoutExpired as exc:
        raise ValueError('video upload processing timed out') from exc
    finally:
        normalized.unlink(missing_ok=True)
        lease.release()


def validate_catalog(task_id=None, *, root=None):
    directory = opencut.directory(task_id) if root is None else Path(root) / 'opencut'
    target = directory / 'clips.json'
    if target.is_symlink() or target.stat().st_size > opencut.MAX_PROJECT:
        raise ValueError('invalid OpenCut clip metadata')
    versions = json.loads(target.read_text(encoding='utf-8'))
    if not isinstance(versions, list) or len(versions) > 512:
        raise ValueError('invalid OpenCut version catalog')
    for version in versions:
        if not isinstance(version, dict) or type(version.get('scene_id')) is not int or version['scene_id'] < 1:
            raise ValueError('invalid OpenCut candidate scene')
        if (not isinstance(version.get('prompt'), str) or len(version['prompt']) > 4000
                or type(version.get('seed')) is not int or not 0 <= version['seed'] <= 2147483647
                or not isinstance(version.get('name'), str) or len(version['name']) > 128
                or not isinstance(version.get('duration'), (int, float))
                or not math.isfinite(version['duration']) or not 0 < version['duration'] <= 3600
                or version.get('origin') not in {'generated', 'uploaded'}):
            raise ValueError('invalid OpenCut candidate metadata')
        digest = version.get('blob', '')
        if not re.fullmatch('[a-f0-9]{32}', version.get('id', '')) or not re.fullmatch('[a-f0-9]{64}', digest) or version.get('source') != 'opencut/media/' + digest:
            raise ValueError('invalid OpenCut candidate reference')
        target = directory / 'media' / digest
        if target.is_symlink() or not target.is_file() or gm.media_sha256(target) != digest:
            raise ValueError('OpenCut candidate checksum mismatch')
