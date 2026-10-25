from io import BytesIO
from pathlib import Path
from unittest.mock import patch
import wave

import numpy as np
from streamlit.testing.v1 import AppTest

from app.models.schema import VideoAspect, VideoParams, TaskArtifactPackageData
from app.services import audio_layers as al, audio_layer_tasks as commands, generation_manifest as gm
from app.services import editor_workspace as editor, local_ai, scene_planner, task, task_artifacts, webui_task
from app.services.local_ai.fake import FakeLocalVideoProvider
from app.services.local_ai.orchestrator import generate_scene_materials
from app.services.state import MemoryState
from app.utils import utils
from test.services.test_local_ai import LocalAITestCase


def tone(frequency=440, duration=2):
    buffer = BytesIO()
    with wave.open(buffer, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        samples = (np.sin(np.arange(round(duration * 16000)) * 2 * np.pi * frequency / 16000) * 5000).astype('<i2')
        audio.writeframes(samples.tobytes())
    return buffer.getvalue()


class TestAudioLayers(LocalAITestCase):
    def setUp(self):
        super().setUp()
        self.task_id = 'audio-edit'
        self.root = Path(utils.task_dir(self.task_id))
        self.state = MemoryState()
        self.params = VideoParams(video_subject='Garden', video_script='Flowers. Bees.', video_source=local_ai.FAKE_SOURCE_ID,
            video_clip_duration=2, subtitle_enabled=True, font_name='MicrosoftYaHeiBold.ttc', font_size=14, bgm_type='', n_threads=1)
        self.plan = scene_planner.get_or_create_scene_plan(self.task_id, self.params.video_script,
            audio_duration=3, max_scene_duration=2, aspect='9:16', use_llm=False)
        generate_scene_materials(self.task_id, scenes=list(self.plan.scenes), provider=FakeLocalVideoProvider())
        task.save_script_data(self.task_id, self.params.video_script, [], self.params)
        self.audio = self.make_audio(self.task_id, 3)
        self.captions = self.root / 'subtitle.srt'
        self.captions.write_text('1\n00:00:00,000 --> 00:00:03,000\nGarden.\n\n')
        self.state.update_task(self.task_id, state=task.const.TASK_STATE_COMPLETE, progress=100,
                               audio_file=str(self.audio), audio_duration=3, subtitle_path=str(self.captions))
        for item in (patch.object(task.sm, 'state', self.state), patch.object(local_ai, 'is_public_source', return_value=True),
                     patch.object(VideoAspect, 'to_resolution', return_value=(90, 160))):
            item.start()
            self.addCleanup(item.stop)

    def request(self, action, **changes):
        context = commands.context(self.task_id, read_only=True)
        return {'action': action, 'expected_binding': context['audio_binding'], 'expected_revision': al.revision(self.task_id),
                **({'expected_snapshot': gm.scene_timing_snapshot(gm.load_manifest(self.task_id))}
                   if action in {'preview', 'apply', 'restore'} else {}), **changes}

    def run_edit(self, action, **changes):
        return commands.run(self.task_id, **self.request(action, **changes))

    def arrange(self):
        key = self.run_edit('upload', content=tone(), name='Music.wav')['asset_id']
        self.run_edit('add', asset_id=key, kind='music')
        return key, al.read(self.task_id)['clips'][0]['id']

    def initial_render(self):
        return task.generate_final_videos(self.task_id, self.params, gm.active_scene_paths(self.task_id),
                                           str(self.audio), str(self.captions), 3)

    def test_upload_edits_bounds_stale_sources_and_audio_samples(self):
        key, cid = self.arrange()
        protected = {name: (self.root / name).read_bytes() for name in ('script.json', 'audio.mp3', 'subtitle.srt', 'scene_plan.json')}
        self.run_edit('update', clip_id=cid, start_ms=500, in_ms=250, out_ms=1750, gain=.5, fade_in_ms=250, fade_out_ms=250)
        data = al.read(self.task_id)
        mixed = al.render_mix(self.task_id, data, 3)
        with wave.open(mixed, 'rb') as stream:
            samples = np.frombuffer(stream.readframes(stream.getnframes()), dtype='<i2').reshape(-1, 2)[:, 0].astype(float)
        def rms(begin, end):
            return np.sqrt(np.mean(samples[round(begin * 48000):round(end * 48000)] ** 2))
        self.assertLess(rms(0, .4), 1)
        self.assertGreater(rms(1, 1.2), 1100)
        self.assertLess(rms(.5, .55), rms(1, 1.2) / 3)
        self.assertLess(rms(1.95, 2), rms(1, 1.2) / 3)
        self.assertLess(rms(2.1, 2.8), 1)
        self.assertEqual(mixed, al.render_mix(self.task_id, data, 3))
        self.run_edit('duplicate', clip_id=cid)
        self.assertEqual(len(al.read(self.task_id)['clips']), 2)
        duplicate = al.read(self.task_id)['clips'][1]['id']
        self.run_edit('remove', clip_id=duplicate)
        self.run_edit('update', clip_id=cid, muted=True)
        muted = al.render_mix(self.task_id, al.read(self.task_id), 3)
        with wave.open(muted, 'rb') as stream:
            self.assertFalse(np.any(np.frombuffer(stream.readframes(stream.getnframes()), dtype='<i2')))
        before = al.file(self.task_id).read_bytes()
        for changes in ({'gain': float('nan')}, {'gain': -1}, {'start_ms': 2700}, {'in_ms': -1},
                        {'out_ms': 5000}, {'fade_in_ms': 5000}, {'muted': 1}, {'asset_id': '../x'}):
            with self.assertRaises((ValueError, TypeError)):
                self.run_edit('update', clip_id=cid, **changes)
        self.assertEqual(al.file(self.task_id).read_bytes(), before)
        stale = self.request('remove', clip_id=cid)
        self.run_edit('base', include_base=False)
        with self.assertRaisesRegex(ValueError, 'changed'):
            commands.run(self.task_id, **stale)
        for name, content in protected.items():
            self.assertEqual((self.root / name).read_bytes(), content)
        asset = al.read(self.task_id)['assets'][key]
        self.assertEqual(asset['asset'], f'audio_assets/{key}/audio.wav')
        al.file(self.task_id, asset['asset']).write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError, 'missing or changed'):
            al.render_mix(self.task_id, al.read(self.task_id), 3)

    def test_preview_apply_reopen_rerender_restore_and_failure_rollback(self):
        self.initial_render()
        self.state.update_task(self.task_id, state=task.const.TASK_STATE_COMPLETE, progress=100)
        self.arrange()
        self.run_edit('upload', content=tone(880, 1), name='Effect.wav')
        data = al.read(self.task_id)
        effect = next(key for key, a in data['assets'].items() if a['name'] == 'Effect.wav')
        self.run_edit('add', asset_id=effect, kind='sfx', start_ms=1500)
        manifest = gm.manifest_path(self.task_id).read_bytes()
        original = {p.name: p.read_bytes() for p in self.root.glob('*-1.mp4')}
        with patch.object(local_ai, 'prepare_provider', side_effect=AssertionError('GPU')):
            with patch.object(task.video, 'combine_videos', side_effect=AssertionError('audio edit recombined visuals')):
                preview = self.run_edit('preview')
            self.assertTrue(al.file(self.task_id, preview['asset']).is_file())
            self.assertFalse(al.file(self.task_id, al.ACTIVE).exists())
            for name, content in original.items():
                self.assertEqual((self.root / name).read_bytes(), content)
            self.run_edit('apply')
            active = al.file(self.task_id, al.ACTIVE).read_bytes()
            applied = (self.root / 'final-1.mp4').read_bytes()
            self.assertNotEqual(applied, original['final-1.mp4'])
            self.run_edit('base', include_base=False)
            self.assertEqual(al.file(self.task_id, al.ACTIVE).read_bytes(), active)
            task.rerender_local_ai_task(self.task_id)
            self.assertEqual(al.file(self.task_id, al.ACTIVE).read_bytes(), active)
            package = task_artifacts.build_output_package(self.task_id, self.state.get_task(self.task_id))
            TaskArtifactPackageData.model_validate(package)
            self.assertEqual(package['audio_layers_active'], al.ACTIVE)
            self.assertEqual(len(package['audio_layer_assets']), 2)
            final = (self.root / 'final-1.mp4').read_bytes()
            with patch.object(task, 'generate_final_videos', side_effect=RuntimeError('render failed')):
                with self.assertRaisesRegex(RuntimeError, 'render failed'):
                    self.run_edit('apply')
            self.assertEqual(al.file(self.task_id, al.ACTIVE).read_bytes(), active)
            self.assertEqual((self.root / 'final-1.mp4').read_bytes(), final)
            self.state.update_task(self.task_id, state=task.const.TASK_STATE_COMPLETE)
            self.run_edit('restore')
        self.assertFalse(al.file(self.task_id, al.ACTIVE).exists())
        self.assertEqual(gm.manifest_path(self.task_id).read_bytes(), manifest)
        self.assertAlmostEqual(task.voice.get_audio_duration(str(self.root / 'final-1.mp4')), 3, delta=.1)

    def test_editor_lanes_queue_payload_and_restart_status(self):
        _, cid = self.arrange()
        self.run_edit('duplicate', clip_id=cid)
        view = editor.build_view(self.task_id)
        self.assertEqual(len([r for r in view['rows'] if r.get('kind') == 'music']), 2)
        result = editor.dispatch(self.task_id, {'kind': 'select', 'target': f'audio-{cid}', 'revision': view['revision']}, view)
        self.assertEqual(result['panel'], 'audio')
        with patch.object(webui_task, 'submit_audio_layers') as submit:
            editor.dispatch(self.task_id, {'kind': 'audio', 'clip_id': cid, 'start': .2, 'end': 2.2, 'resize': False, 'revision': view['revision']}, view)
            self.assertEqual(submit.call_args.kwargs['request']['start_ms'], 200)
            editor.dispatch(self.task_id, {'kind': 'audio', 'clip_id': cid, 'start': .2, 'end': 2., 'resize': True, 'revision': view['revision']}, view)
            self.assertEqual(submit.call_args.kwargs['request']['in_ms'], 200)
        (self.root / 'final-1.mp4').write_bytes(b'existing final')
        self.state.delete_task(self.task_id)
        with patch.object(webui_task._task_manager, 'add_task') as submit:
            webui_task.submit_audio_layers(self.task_id, request=self.request('base', include_base=False))
            args = submit.call_args.kwargs
        result = webui_task._run_audio_layers(self.task_id, args['request'], args['previous'])
        self.assertNotIn('error', result)
        self.assertEqual(self.state.get_task(self.task_id)['state'], task.const.TASK_STATE_COMPLETE)
        self.assertFalse(task.is_task_busy(self.state.get_task(self.task_id)))

    def test_existing_music_snapshot_import_and_resume(self):
        self.initial_render()
        self.state.update_task(self.task_id, state=task.const.TASK_STATE_COMPLETE, progress=100)
        self.arrange()
        source = self.root / 'existing-music.wav'
        source.write_bytes(tone(330))
        self.params = self.params.model_copy(update={'bgm_type': 'random', 'bgm_volume': .2})
        task.save_script_data(self.task_id, self.params.video_script, [], self.params)
        with patch.object(task.video, 'get_bgm_file', return_value=str(source)) as choose:
            saved = al.saved_base_music(self.task_id, self.params)
            self.assertEqual(saved, al.saved_base_music(self.task_id, self.params))
            self.assertEqual(choose.call_count, 1)
        with patch.object(task.video, 'get_bgm_file', side_effect=AssertionError('new song')):
            self.run_edit('preview')  # Frozen BGM loops through the shared composer.
            self.run_edit('import_base')
            data = al.read(self.task_id)
            self.assertFalse(data['include_base'])
            self.assertEqual(len(data['clips']), 2)
            self.run_edit('apply')
        active = al.file(self.task_id, al.ACTIVE).read_bytes()
        second = gm.resolve_asset(self.task_id, gm.scene_record(gm.load_manifest(self.task_id), 2)['active_asset'])
        second.unlink()
        restarted = MemoryState()
        restarted.update_task(self.task_id, state=task.const.TASK_STATE_FAILED)
        provider = FakeLocalVideoProvider()
        with (patch.object(task.sm, 'state', restarted), patch.object(local_ai, 'is_public_source', return_value=False),
              patch.dict('os.environ', {'MPT_ENABLE_LOCAL_AI_FAKE_PROVIDER': '1'}),
              patch.object(local_ai, 'prepare_provider', return_value=provider),
              patch.object(task, 'generate_script', side_effect=AssertionError('script')),
              patch.object(task, 'generate_audio', side_effect=AssertionError('TTS')),
              patch.object(task, 'generate_subtitle', side_effect=AssertionError('Whisper'))):
            context = task.load_local_ai_resume_context(self.task_id)
            result = task.start(self.task_id, context['params'], resume_context=context)
            self.assertIn('videos', result)
            self.assertEqual(provider.generated_scene_ids, [2])
            self.assertEqual(al.file(self.task_id, al.ACTIVE).read_bytes(), active)

    def test_bad_uploads_busy_and_editor_surface(self):
        for content, name in ((b'invalid', 'x.mp3'), (tone(), 'x.exe'), (b'', 'x.wav')):
            with self.assertRaises(ValueError):
                self.run_edit('upload', content=content, name=name)
        self.assertFalse(al.file(self.task_id).exists())
        self.arrange()
        self.state.update_task(self.task_id, state=task.const.TASK_STATE_PROCESSING)
        with self.assertRaises(RuntimeError):
            webui_task.submit_audio_layers(self.task_id, request=self.request('base', include_base=False))
        self.state.update_task(self.task_id, state=task.const.TASK_STATE_COMPLETE)
        from webui.editor_workspace import timeline_component
        timeline_component.clear()
        with patch.object(task.config, 'try_save_config', return_value=True):
            app = AppTest.from_file(str(Path(__file__).parents[2] / 'webui/Main.py'), default_timeout=60)
            app.session_state['ui_language'] = 'en'
            app.session_state['editor_panel_choice'] = 'audio'
            app.query_params['editor'] = self.task_id
            app.run()
            self.assertFalse(app.exception)
            self.assertTrue(any(b.label == 'Save Audio Clip' for b in app.button))
            app.button(key='editor_back').click().run()
            self.assertFalse(app.exception)
