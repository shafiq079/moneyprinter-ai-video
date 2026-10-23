import ast
import subprocess
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import av
from streamlit.testing.v1 import AppTest

from app.models import const
from app.models.schema import VideoParams
from app.services import generation_manifest as gm
from app.services import scene_planner, task, video, webui_task
from app.services.local_ai import FAKE_SOURCE_ID
from app.services.local_ai.fake import FakeLocalVideoProvider
from app.services.local_ai.orchestrator import generate_scene_materials
from app.services.state import MemoryState
from app.utils import utils
from test.services.test_local_ai import LocalAITestCase


class TestSceneTiming(LocalAITestCase):
    def setUp(self):
        super().setUp()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.state = MemoryState()
        self.stack.enter_context(patch.object(task.sm, 'state', self.state))
        self.public_patch = patch.object(task.local_ai, 'is_public_source', return_value=True)
        self.public_patch.start()
        self.addCleanup(self.public_patch.stop)
        self.task_id = 'timing'
        self.params = VideoParams(
            video_subject='Garden', video_script='Flowers. Bees. Night.',
            video_source=FAKE_SOURCE_ID, video_clip_duration=1, video_aspect='9:16',
            subtitle_enabled=True, font_name='MicrosoftYaHeiBold.ttc', font_size=32,
            bgm_type='', bgm_volume=0, n_threads=1,
        )
        self.plan = scene_planner.get_or_create_scene_plan(
            self.task_id, self.params.video_script, audio_duration=3,
            max_scene_duration=1, aspect='9:16', base_seed=42, use_llm=False,
        )
        generate_scene_materials(self.task_id, provider=FakeLocalVideoProvider(), scenes=list(self.plan.scenes))
        task.save_script_data(self.task_id, self.params.video_script, [], self.params)
        self.root = Path(utils.task_dir(self.task_id))
        self.make_audio(self.task_id, duration=2.9)
        (self.root / 'subtitle.srt').write_text('1\n00:00:00,000 --> 00:00:02,900\nGarden.\n\n')
        # Generation can return more footage than the requested timeline slot.
        manifest = gm.load_manifest(self.task_id)
        record = gm.scene_record(manifest, 1)
        source = gm.resolve_asset(self.task_id, record['active_asset'])
        subprocess.run([
            utils.get_ffmpeg_binary(), '-y', '-f', 'lavfi', '-i',
            'color=c=blue:s=90x160:r=24:d=1.75', '-c:v', 'libx264',
            '-threads', '1', '-pix_fmt', 'yuv420p', str(source),
        ], capture_output=True, check=True)
        record['actual_duration'] = 1.75
        gm.remember_scene_version(record, record['active_asset'])
        gm.save_manifest(self.task_id, manifest)
        self.durations = {'1': 1.5, '2': 0.5, '3': 1.0}

    def manifest(self):
        return gm.load_manifest(self.task_id)

    def stub_render(self, *_args, **_kwargs):
        for name in ('final-1.mp4', 'combined-1.mp4'):
            (self.root / name).write_bytes(b'new')
        return [str(self.root / 'final-1.mp4')], [str(self.root / 'combined-1.mp4')], []

    def test_real_export_moves_cut_without_generation_or_asset_changes(self):
        before = self.manifest()
        immutable = {name: (self.root / name).read_bytes() for name in (
            'scene_plan.json', 'audio.mp3', 'subtitle.srt',
        )}
        clips = {p: Path(p).read_bytes() for p in gm.active_scene_paths(self.task_id)}
        with ExitStack() as stack:
            for module, name in (
                (task.local_ai, 'prepare_provider'), (task.voice, 'tts'),
                (task, 'generate_subtitle'), (task.sonilo, 'generate_bgm'),
                (task, '_schedule_cross_post'), (task, 'generate_script'),
            ):
                stack.enter_context(patch.object(module, name, side_effect=AssertionError(name)))
            result = task.retime_local_ai_scenes(self.task_id, self.durations)
        self.assertTrue(result['retimed'])
        self.assertEqual(self.manifest(), {**before, 'playback_durations': self.durations})
        for name, content in immutable.items():
            self.assertEqual((self.root / name).read_bytes(), content)
        for name, content in clips.items():
            self.assertEqual(Path(name).read_bytes(), content)
        with av.open(result['videos'][0]) as container:
            sampled = {}
            for frame in container.decode(video=0):
                for moment in (1.25, 1.75, 2.4):
                    if moment not in sampled and frame.time >= moment:
                        rgb = frame.to_ndarray(format='rgb24')
                        sampled[moment] = rgb[:100, :100].mean(axis=(0, 1))
            self.assertGreater(sampled[1.25][2], sampled[1.25][1] + 100)
            self.assertGreater(sampled[1.75][1], sampled[1.75][2] + 10)
            self.assertGreater(sampled[2.4][0], sampled[2.4][1] + 10)
        self.assertEqual(gm.local_ai_material_records(self.task_id)[0]['playback_duration'], 1.5)

    def test_invalid_maps_speed_busy_and_stale_requests_do_not_mutate(self):
        original = gm.manifest_path(self.task_id).read_bytes()
        for bad in ({'1': 1}, {'1': 0, '2': 2, '3': 1}, {'1': float('nan'), '2': 1, '3': 1}, {'1': True, '2': 1, '3': 1}, {'1': 1, '2': 1, '3': 2}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                task.retime_local_ai_scenes(self.task_id, bad)
        self.assertFalse(task.retime_local_ai_scenes(self.task_id, {'1': 1, '2': 1, '3': 1})['retimed'])
        snapshot = gm.scene_timing_snapshot(self.manifest())
        snapshot['assets']['1'] = 'stale.mp4'
        with self.assertRaisesRegex(ValueError, 'changed'):
            task.retime_local_ai_scenes(self.task_id, self.durations, expected_snapshot=snapshot)
        self.state.update_task(self.task_id, state=const.TASK_STATE_PROCESSING)
        with self.assertRaises(RuntimeError):
            task.retime_local_ai_scenes(self.task_id, self.durations)
        self.state.update_task(self.task_id, state=const.TASK_STATE_COMPLETE)
        self.params.video_clip_speed = 2
        task.save_script_data(self.task_id, self.params.video_script, [], self.params)
        with self.assertRaisesRegex(ValueError, 'normal'):
            task.retime_local_ai_scenes(self.task_id, self.durations)
        self.assertEqual(gm.manifest_path(self.task_id).read_bytes(), original)

    def test_short_source_and_render_failure_roll_back_manifest_and_outputs(self):
        before = gm.manifest_path(self.task_id).read_bytes()
        for name in ('final-1.mp4', 'combined-1.mp4'):
            (self.root / name).write_bytes(b'previous')
        for durations in ({'1': 0.5, '2': 1.5, '3': 1}, self.durations):
            with self.subTest(durations=durations):
                context = patch.object(task, 'generate_final_videos', side_effect=RuntimeError('render')) if durations == self.durations else ExitStack()
                with context, self.assertRaises((ValueError, RuntimeError)):
                    task.retime_local_ai_scenes(self.task_id, durations)
                self.assertEqual(gm.manifest_path(self.task_id).read_bytes(), before)
                for name in ('final-1.mp4', 'combined-1.mp4'):
                    self.assertEqual((self.root / name).read_bytes(), b'previous')
        self.assertEqual(self.state.get_task(self.task_id)['state'], const.TASK_STATE_COMPLETE)

    def test_cached_partial_resume_reorder_replacement_and_reset_keep_contract(self):
        with patch.object(task, 'generate_final_videos', side_effect=self.stub_render):
            task.retime_local_ai_scenes(self.task_id, self.durations)
            task.reorder_local_ai_scenes(self.task_id, [3, 1, 2])
        provider = FakeLocalVideoProvider()
        gm.resolve_asset(self.task_id, gm.scene_record(self.manifest(), 3)['active_asset']).unlink()
        paths = generate_scene_materials(self.task_id, provider=provider, scenes=list(self.plan.scenes))
        self.assertEqual(provider.generated_scene_ids, [3])
        self.assertEqual(gm.scene_playback_durations(self.manifest()), self.durations)
        self.assertEqual(Path(paths[1]).name, 'v001.mp4')
        # A replacement must retain enough footage for the longer timeline slot.
        content = gm.resolve_asset(self.task_id, gm.scene_record(self.manifest(), 1)['active_asset']).read_bytes()
        with patch.object(task, 'generate_final_videos', side_effect=self.stub_render):
            task.replace_local_ai_scene_clip(self.task_id, 1, content)
        record = gm.scene_record(self.manifest(), 1)
        self.assertGreaterEqual(record['actual_duration'], 1.5)
        with patch.object(task, 'generate_final_videos', side_effect=self.stub_render):
            task.restore_local_ai_scene_version(self.task_id, 1, 'generated_ai/scene-001/v001.mp4')
            task.retime_local_ai_scenes(self.task_id, {'1': 1, '2': 1, '3': 1})
        self.assertNotIn('playback_durations', self.manifest())
        self.assertEqual(gm.scene_playback_order(self.manifest()), [3, 1, 2])

    def test_task_resume_after_restart_uses_saved_timing_and_only_missing_scene(self):
        with patch.object(task, 'generate_final_videos', side_effect=self.stub_render):
            task.retime_local_ai_scenes(self.task_id, self.durations)
        scene_three = gm.scene_record(self.manifest(), 3)['active_asset']
        gm.resolve_asset(self.task_id, scene_three).unlink()
        restarted = MemoryState()
        restarted.update_task(self.task_id, state=const.TASK_STATE_FAILED)
        provider = FakeLocalVideoProvider()
        self.public_patch.stop()
        with (
            patch.object(task.sm, 'state', restarted),
            patch.object(task.local_ai, 'prepare_provider', return_value=provider),
            patch.object(task, 'generate_script', side_effect=AssertionError('script')),
            patch.object(task, 'generate_audio', side_effect=AssertionError('audio')),
            patch.object(task, 'generate_subtitle', side_effect=AssertionError('caption')),
            patch.dict('os.environ', {'MPT_ENABLE_LOCAL_AI_FAKE_PROVIDER': '1'}),
        ):
            context = task.load_local_ai_resume_context(self.task_id)
            result = task.start(self.task_id, context['params'], resume_context=context)
        self.assertTrue(result['videos'])
        self.assertEqual(provider.generated_scene_ids, [3])
        self.assertEqual(gm.scene_playback_durations(self.manifest()), self.durations)

    def test_fractional_cut_rounding_does_not_accumulate_duration_drift(self):
        values = video._quantize_scene_durations([1.01] * 10)
        self.assertAlmostEqual(sum(values), 10.1)
        elapsed = 0
        for index, duration in enumerate(values, start=1):
            elapsed += duration
            self.assertLessEqual(abs(elapsed - index * 1.01), 1 / video.fps)
        with self.assertRaises(ValueError):
            video._quantize_scene_durations([0.0001, 1.9999])

    def test_invalid_saved_timing_blocks_before_inference(self):
        manifest = self.manifest()
        manifest['playback_durations'] = {'1': 1}
        gm.save_manifest(self.task_id, manifest)
        provider = FakeLocalVideoProvider()
        with self.assertRaises(ValueError):
            generate_scene_materials(self.task_id, provider=provider, scenes=list(self.plan.scenes))
        self.assertEqual(provider.generated_scene_ids, [])
        self.assertEqual(provider.runtime_load_count, 0)

    def test_worker_rechecks_snapshot_and_queue_failure_releases_reservation(self):
        with patch.object(webui_task._task_manager, 'add_task') as queue:
            webui_task.submit_scene_timing(self.task_id, self.durations, capture_logs=False)
        with patch.object(task, 'generate_final_videos', side_effect=self.stub_render):
            call = queue.call_args
            self.assertNotIn('error', call.args[0](**call.kwargs))
        with patch.object(webui_task._task_manager, 'add_task', side_effect=RuntimeError('queue')):
            with self.assertRaises(RuntimeError):
                webui_task.submit_scene_timing(self.task_id, {'1': 1, '2': 1, '3': 1})
        self.assertEqual(self.state.get_task(self.task_id)['state'], const.TASK_STATE_COMPLETE)
        with patch.object(webui_task._task_manager, 'add_task') as queue:
            webui_task.submit_scene_timing(self.task_id, {'1': 1, '2': 1, '3': 1}, capture_logs=False)
        manifest = self.manifest()
        manifest['playback_order'] = [3, 1, 2]
        gm.save_manifest(self.task_id, manifest)
        before = gm.manifest_path(self.task_id).read_bytes()
        call = queue.call_args
        self.assertIn('error', call.args[0](**call.kwargs))
        self.assertEqual(gm.manifest_path(self.task_id).read_bytes(), before)
        self.assertEqual(self.state.get_task(self.task_id)['state'], const.TASK_STATE_COMPLETE)

    def test_ui_balances_following_scene_and_disables_last_and_busy_controls(self):
        source = (Path(__file__).parents[2] / 'webui/Main.py').read_text(encoding='utf-8')
        node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == '_render_scene_editor')
        harness = '''
import os
import streamlit as st
from app.services import generation_manifest, scene_planner, webui_task
from app.services import state as sm
from app.services import task as tm
from app.utils import utils
from app.services.local_ai.clip_import import MAX_CLIP_UPLOAD_BYTES
def tr(value): return value
st.session_state['scene_editor_task_id'] = 'timing'
'''
        app = AppTest.from_string(harness + ast.get_source_segment(source, node) + '\n_render_scene_editor()\n', default_timeout=30).run()
        self.assertFalse(app.exception)
        self.assertTrue(app.button(key='apply_scene_timing_timing_3').disabled)
        with patch.object(webui_task, 'submit_scene_timing') as submit, patch('streamlit.rerun'):
            app.number_input(key='scene_screen_duration_timing_1_1.0').set_value(1.5).run()
            app.button(key='apply_scene_timing_timing_1').click().run()
            submit.assert_called_once_with(self.task_id, self.durations, expected_snapshot=gm.scene_timing_snapshot(self.manifest()))
        self.state.update_task(self.task_id, state=const.TASK_STATE_PROCESSING)
        app.run()
        self.assertTrue(app.button(key='apply_scene_timing_timing_1').disabled)
        self.assertFalse(app.exception)
