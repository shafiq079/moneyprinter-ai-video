"""Editor view/command adapter over existing task assets and validated queues."""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from functools import lru_cache
from pathlib import Path

from app.models.schema import VideoParams
from app.services import caption_edits as ce, generation_manifest as gm, local_ai, narration_ranges as nr
from app.services import scene_planner, task as tm, webui_task, audio_layers as al
from app.utils import utils


def task_root(task_id: str) -> Path:
    if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", task_id):
        raise ValueError("invalid editor task")
    return Path(tm._scene_regeneration_task_root(task_id))


def build_view(task_id: str) -> dict:
    root = task_root(task_id)
    script_file = root / 'script.json'
    if script_file.stat().st_size > 2 * 1024 * 1024:
        raise ValueError('task script is too large')
    script = json.loads(script_file.read_text(encoding='utf-8'))
    params = VideoParams.model_validate(script['params'])
    if not local_ai.is_local_ai_source(params.video_source):
        raise ValueError('this editor requires a saved AI scene project')
    plan = scene_planner.load_scene_plan(task_id)
    manifest = gm.load_manifest(task_id)
    if plan is None or manifest is None or len(plan.scenes) > 512:
        raise ValueError('saved scene project is unavailable')
    order = gm.scene_playback_order(manifest)
    by_id = {s.scene_id: s for s in plan.scenes}
    if set(order) != set(by_id):
        raise ValueError('scene plan does not match saved clips')
    state = tm.sm.state.get_task(task_id) or {}
    snapshot = gm.scene_timing_snapshot(manifest)
    durations = gm.scene_playback_durations(manifest)
    audio_duration = sum(durations.values())
    binding, draft_revision, captions, notes = None, 'missing', [], []
    caption_draft = False
    context = None
    try:
        context = tm.caption_editor_context(task_id, read_only=True)
        binding = context['binding']
        audio_duration = context['duration_ms'] / 1000
        draft_revision = ce.revision(task_id)
        if ce.file(task_id).exists():
            draft = ce.load_validated(task_id, binding, context['duration_ms'])
            captions, caption_draft = draft['cues'], True
        elif ce.file(task_id, ce.ACTIVE).exists():
            captions = ce.resolve(task_id, binding, context['duration_ms'])['cues']
        elif context['base']:
            captions = ce.parse_srt(Path(context['base']).read_text(encoding='utf-8'))
            ce.validate_cues(captions, context['duration_ms'])
    except (OSError, ValueError, KeyError, TypeError):
        notes.append('captions_unavailable')
    natural = False
    try:
        if context and tm.narration_mix.file(task_id).exists():
            metadata = json.loads(tm.narration_mix.file(task_id).read_text(encoding='utf-8'))
            if metadata.get('schema_version') == 3:
                ranges = nr.load_validated(task_id, plan, context['audio'])
                timeline, durations = tm.narration_timeline.visual_durations(ranges, manifest)
                audio_duration, natural = timeline['audio_duration'], True
    except (OSError, ValueError, KeyError, TypeError):
        notes.append('narration_unavailable')
    rows, elapsed, scenes = [], 0.0, []
    for sid in order:
        record = gm.scene_record(manifest, sid)
        duration = durations[str(sid)]
        available = False
        asset = record.get('active_asset')
        if asset:
            try:
                available = gm.resolve_asset(task_id, asset).is_file()
            except ValueError:
                pass
        scenes.append({'id': sid, 'start': elapsed, 'end': elapsed + duration,
                       'duration': duration, 'label': by_id[sid].narration_segment,
                       'ready': record.get('status') == 'ready' and available, 'asset': asset,
                       'version': Path(asset).name if asset else 'missing'})
        elapsed += duration
    busy = tm.is_task_busy(state)
    exact = natural or 'playback_durations' in manifest or params.local_ai_duration_mode == 'auto'
    rows.append({'id': 'visual', 'actions': [
        {'id': f'scene-{s["id"]}', 'effectId': 'visual', 'start': s['start'], 'end': s['end'],
         'label': f'{i + 1:02d}  {s["label"]}', 'scene_id': s['id'], 'selected': False,
         'movable': not busy, 'flexible': not busy and exact and not natural and i + 1 < len(scenes),
         'minStart': 0, 'maxEnd': max(elapsed, audio_duration)} for i, s in enumerate(scenes)]})
    narration = []
    try:
        ranges = nr.read_ranges(task_id)
        if ranges:
            timeline = tm.narration_timeline.audio_timeline(ranges) if natural else None
            for i, item in enumerate(ranges['ranges']):
                segment = timeline['segments'][i] if timeline else item
                narration.append({'id': f'narration-{item["scene_id"]}', 'effectId': 'narration',
                    'start': segment['start'], 'end': segment['end'], 'scene_id': item['scene_id'],
                    'label': (item.get('replacement') or {}).get('text') or by_id[item['scene_id']].narration_segment,
                    'movable': False, 'flexible': False})
    except (OSError, ValueError, KeyError, TypeError):
        pass
    if not narration:
        narration = [{'id': 'narration', 'effectId': 'narration', 'start': 0, 'end': audio_duration,
                      'label': 'Narration', 'movable': False, 'flexible': False}]
    rows.append({'id': 'narration', 'actions': narration})
    rows.append({'id': 'captions', 'actions': [
        {'id': f'caption-{i}', 'effectId': 'captions', 'start': c['start_ms'] / 1000, 'end': c['end_ms'] / 1000,
         'label': c['text'], 'index': i, 'movable': caption_draft and not busy,
         'flexible': caption_draft and not busy, 'minStart': 0, 'maxEnd': audio_duration}
        for i, c in enumerate(captions)]})
    audio_draft, audio_binding = None, None
    audio_revision = al.revision(task_id)
    if binding:
        audio_binding = binding['source_audio']['sha256']
        audio_draft = al.load(task_id, audio_binding)
        # Separate overlapping clips into lanes so every clip remains selectable.
        for kind in ('music', 'sfx'):
            lanes = []
            for clip in sorted((c for c in audio_draft['clips'] if c['kind'] == kind), key=lambda c: (c['start_ms'], c['id'])):
                lane = next((lane for lane in lanes if lane[-1]['end'] <= clip['start_ms'] / 1000), None)
                if lane is None:
                    lane = []
                    lanes.append(lane)
                asset = audio_draft['assets'][clip['asset_id']]
                lane.append({'id': f'audio-{clip["id"]}', 'effectId': kind, 'clip_id': clip['id'],
                    'start': clip['start_ms'] / 1000, 'end': (clip['start_ms'] + clip['out_ms'] - clip['in_ms']) / 1000,
                    'label': ('🔇 ' if clip['muted'] else '') + asset['name'],
                    'movable': not busy, 'flexible': not busy, 'minStart': 0, 'maxEnd': audio_duration})
            for index, actions in enumerate(lanes or [[]]):
                rows.append({'id': f'{kind}-{index}', 'kind': kind, 'actions': actions})
    if params.bgm_type and params.bgm_volume > 0 and (audio_draft is None or audio_draft['include_base']):
        rows.append({'id': 'music', 'actions': [{'id': 'music', 'effectId': 'music', 'start': 0,
                     'end': audio_duration, 'label': 'Existing background music', 'movable': False, 'flexible': False}]})
    revision = hashlib.sha256(json.dumps({'snapshot': snapshot, 'caption_revision': draft_revision,
        'binding': binding, 'audio_revision': audio_revision, 'params': ce.render_signature(params), 'natural': natural}, sort_keys=True).encode()).hexdigest()
    return {'task_id': task_id, 'subject': params.video_subject or script.get('script', '')[:80],
            'params': params, 'snapshot': snapshot, 'order': order, 'scenes': scenes, 'rows': rows,
            'duration': audio_duration, 'extent': max(elapsed, audio_duration), 'revision': revision,
            'caption_revision': draft_revision, 'audio_revision': audio_revision, 'audio_binding': audio_binding, 'audio_draft': audio_draft, 'binding': binding, 'caption_draft': caption_draft,
            'busy': busy, 'state': state, 'notes': notes, 'exact': exact, 'natural': natural}


def dispatch(task_id: str, event: dict, view: dict) -> dict:
    """Never trust browser-proposed assets, snapshots or arbitrary timeline writes."""
    if not isinstance(event, dict) or len(json.dumps(event)) > 16384:
        raise ValueError('invalid timeline event')
    kind = event.get('kind')
    if kind not in {'select', 'reorder', 'resize', 'caption', 'text_selection', 'audio'}:
        raise ValueError('unsupported timeline event')
    if event.get('revision') != view['revision']:
        raise ValueError('project changed; refresh the editor and try again')
    if kind == 'select':
        target = str(event.get('target', ''))
        action = next((a for row in view['rows'] for a in row['actions'] if a['id'] == target), None)
        if action is None:
            raise ValueError('selected timeline item is unavailable')
        return {'action': action, 'panel': {'visual': 'visual', 'narration': 'narration',
                'captions': 'captions', 'music': 'audio', 'sfx': 'audio'}[action['effectId']]}
    if kind == 'text_selection':
        index, start, end = event.get('index'), event.get('start'), event.get('end')
        actions = view['rows'][2]['actions']
        if (not view['caption_draft'] or type(index) is not int or not 0 <= index < len(actions)
                or event.get('text') != actions[index]['label']
                or type(start) is not int or type(end) is not int
                or not 0 <= start < end <= len(actions[index]['label'])):
            raise ValueError('select text in a saved caption before choosing its color')
        return {'selection': {'index': index, 'start': start, 'end': end}}
    if view['busy']:
        raise ValueError('task is busy')
    if kind == 'audio':
        clip = next((c for c in (view['audio_draft'] or {}).get('clips', []) if c['id'] == event.get('clip_id')), None)
        if clip is None:
            raise ValueError('selected audio clip is unavailable')
        start = ce.milliseconds(event.get('start'))
        end = ce.milliseconds(event.get('end'))
        old_end = clip['start_ms'] + clip['out_ms'] - clip['in_ms']
        changes = {'start_ms': start}
        if event.get('resize') is True:
            changes['in_ms'] = clip['in_ms'] + start - clip['start_ms']
            changes['out_ms'] = clip['out_ms'] + end - old_end
        elif end - start != clip['out_ms'] - clip['in_ms']:
            # Browser pixel conversion can differ by a millisecond at either edge.
            if abs(end - start - (clip['out_ms'] - clip['in_ms'])) > 2:
                raise ValueError('moving audio cannot change its duration')
        request = {'action': 'update', 'clip_id': clip['id'], **changes,
                   'expected_revision': view['audio_revision'], 'expected_binding': view['audio_binding']}
        al.edit(view['audio_draft'], 'update', round(view['duration'] * 1000), clip_id=clip['id'], **changes)
        webui_task.submit_audio_layers(task_id, request=request)
        return {'queued': True}
    if kind == 'caption':
        index = event.get('index')
        if not view['caption_draft'] or type(index) is not int or not 0 <= index < len(view['rows'][2]['actions']):
            raise ValueError('prepare a current caption draft before dragging captions')
        webui_task.submit_caption_edit(task_id, request={'action': 'update', 'index': index,
            'start': event.get('start'), 'end': event.get('end'), 'text': view['rows'][2]['actions'][index]['label'],
            'expected_revision': view['caption_revision'], 'expected_binding': view['binding']})
        return {'queued': True}
    sid = event.get('scene_id')
    if type(sid) is not int or sid not in view['order']:
        raise ValueError('selected scene is unavailable')
    position = view['order'].index(sid)
    if kind == 'reorder':
        start = event.get('start')
        if isinstance(start, bool) or not isinstance(start, (int, float)) or not math.isfinite(start):
            raise ValueError('invalid scene position')
        others = [s for s in view['scenes'] if s['id'] != sid]
        target = sum(start > (s['start'] + s['end']) / 2 for s in others)
        order = [i for i in view['order'] if i != sid]
        order.insert(target, sid)
        webui_task.submit_scene_reorder(task_id, order, expected_order=view['order'])
    else:
        if view['natural'] or not view['exact'] or position + 1 >= len(view['order']):
            raise ValueError('use the scene inspector to adjust this timing')
        duration = event.get('duration')
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration):
            raise ValueError('invalid scene duration')
        values = dict(view['snapshot']['durations'])
        current, following = str(sid), str(view['order'][position + 1])
        values[following] += values[current] - duration
        values[current] = duration
        webui_task.submit_scene_timing(task_id, values, expected_snapshot=view['snapshot'])
    return {'queued': True}


@lru_cache(maxsize=256)
def _thumbnail(path: str, size: int, modified: int) -> bytes | None:
    try:
        result = subprocess.run([utils.get_ffmpeg_binary(), '-v', 'error', '-threads', '1', '-i', path,
            '-frames:v', '1', '-vf', 'scale=240:136:force_original_aspect_ratio=decrease,pad=240:136:(ow-iw)/2:(oh-ih)/2',
            '-f', 'image2pipe', '-vcodec', 'mjpeg', '-threads', '1', '-'], capture_output=True, timeout=10)
        return result.stdout if result.returncode == 0 and len(result.stdout) <= 100000 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def thumbnail(task_id: str, asset: str) -> bytes | None:
    path = gm.resolve_asset(task_id, asset)
    if not path.is_file():
        return None
    stat = path.stat()
    return _thumbnail(str(path), stat.st_size, stat.st_mtime_ns)
