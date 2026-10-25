import ast
import json
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
import wave

import pytest
from streamlit.testing.v1 import AppTest

from app.models.schema import TaskArtifactPackageData, VideoAspect, VideoParams
from app.services import caption_edits as ce, generation_manifest as gm, local_ai, narration_ranges as nr
from app.services import scene_planner, task, task_artifacts, webui_task
from app.services.local_ai.fake import FakeLocalVideoProvider
from app.services.local_ai.orchestrator import generate_scene_materials
from app.services.state import MemoryState
from test.services.test_local_ai import LocalAITestCase


class TestCaptionEditor(LocalAITestCase):
    def setUp(self):
        super().setUp()
        self.task_id = 'captions'
        self.root = Path(task.utils.task_dir(self.task_id))
        self.state = MemoryState()
        self.params = VideoParams(video_subject='Garden', video_script='Flowers. Bees.',
            video_source=local_ai.FAKE_SOURCE_ID, video_clip_duration=2, subtitle_enabled=True,
            voice_name='en-US-AriaNeural-Female', bgm_type='', n_threads=1,
            font_name='MicrosoftYaHeiBold.ttc', font_size=14)
        self.plan = scene_planner.get_or_create_scene_plan(self.task_id, self.params.video_script,
            audio_duration=3, max_scene_duration=2, aspect='9:16', use_llm=False)
        generate_scene_materials(self.task_id, scenes=list(self.plan.scenes), provider=FakeLocalVideoProvider())
        task.save_script_data(self.task_id, self.params.video_script, [], self.params)
        self.audio = self.make_audio(self.task_id, 3)
        self.captions = self.root / 'subtitle.srt'
        self.captions.write_text('1\n00:00:00,000 --> 00:00:01,000\nFlowers.\n\n2\n00:00:01,000 --> 00:00:03,000\nBees.\n\n')
        self.state.update_task(self.task_id, state=task.const.TASK_STATE_COMPLETE, progress=100,
                               audio_file=str(self.audio), audio_duration=3, subtitle_path=str(self.captions))
        for guard in (patch.object(task.sm, 'state', self.state),
                      patch.object(local_ai, 'is_public_source', return_value=True),
                      patch.object(VideoAspect, 'to_resolution', return_value=(90, 160))):
            guard.start()
            self.addCleanup(guard.stop)

    def context(self):
        return task.caption_editor_context(self.task_id, read_only=True)

    def request(self, action, **changes):
        return dict(action=action, expected_revision=ce.revision(self.task_id),
                    expected_binding=self.context()['binding'],
                    **({'expected_snapshot': gm.scene_timing_snapshot(gm.load_manifest(self.task_id))}
                       if action in {'apply', 'restore', 'preview'} else {}), **changes)

    def edit(self, action, **changes):
        return task.edit_local_ai_captions(self.task_id, **self.request(action, **changes))

    def initial_render(self):
        result = task.generate_final_videos(self.task_id, self.params, gm.active_scene_paths(self.task_id),
                                            str(self.audio), str(self.captions), 3)
        self.state.update_task(self.task_id, state=task.const.TASK_STATE_COMPLETE, progress=100)
        return result

    def test_styled_captions_preview_export_and_text_ranges(self):
        import numpy as np
        from app.services.caption_render import colored_text_clip
        self.initial_render()
        original = self.captions.read_bytes()
        self.edit('prepare')
        self.edit('style', scope='all', style={'font_size': 18, 'text_fore_color': '#00FF00',
                  'text_background_color': '#000033', 'rounded_subtitle_background': True,
                  'subtitle_position': 'center', 'subtitle_animation': 'none'})
        self.edit('style', index=0, scope='cue', style={'text_fore_color': '#FF0000'})
        self.edit('spans', index=0, spans=[{'start': 0, 'end': 3, 'color': '#FFFF00'}])
        data = ce.read(self.task_id)
        self.assertEqual(data['cues'][0]['style']['text_fore_color'], '#FF0000')
        self.assertNotIn('style', data['cues'][1])
        params = self.params.model_copy(update={**data['style'], **data['cues'][0]['style'], 'stroke_width': 0})
        with colored_text_clip('Flowers.', data['cues'][0]['spans'], params,
                str(Path(task.utils.font_dir()) / params.font_name), 200) as clip:
            frame = clip.get_frame(0)
            self.assertTrue(np.any((frame[:, :, 0] > 200) & (frame[:, :, 1] > 200) & (frame[:, :, 2] < 40)))
            self.assertTrue(np.any((frame[:, :, 0] > 200) & (frame[:, :, 1] < 40) & (frame[:, :, 2] < 40)))
        with patch.object(local_ai, 'prepare_provider', side_effect=AssertionError('GPU')):
            preview = self.edit('preview')
            self.assertTrue(ce.file(self.task_id, preview['preview_asset']).is_file())
            # The unhighlighted second cue must use the global background too.
            from moviepy import VideoFileClip
            with VideoFileClip(str(ce.file(self.task_id, preview['preview_asset']))) as rendered:
                frame = rendered.get_frame(2)
                self.assertTrue(np.any((frame[:, :, 2] > 30) & (frame[:, :, 0] < 15) & (frame[:, :, 1] < 15)))
            self.edit('apply')
            active = ce.resolve(self.task_id, self.context()['binding'], self.context()['duration_ms'])
            self.assertEqual(active['style'], data['style'])
            self.assertEqual(active['cues'], data['cues'])
            task.rerender_local_ai_task(self.task_id)
        self.assertEqual(self.captions.read_bytes(), original)
        # Timing-only edits preserve ranges; changed text clears obsolete offsets.
        self.edit('update', index=0, start=0.1, end=0.9, text='Flowers.')
        self.assertEqual(ce.read(self.task_id)['cues'][0]['spans'], data['cues'][0]['spans'])
        self.edit('update', index=0, start=0.1, end=0.9, text='Different.')
        self.assertNotIn('spans', ce.read(self.task_id)['cues'][0])
        self.assertEqual(ce.read(self.task_id)['cues'][0]['style'], data['cues'][0]['style'])
        for style in ({'font_name': '../outside.ttf'}, {'text_fore_color': 'red'},
                      {'font_size': float('nan')}, {'stroke_width': -1}, {'subtitle_animation': 'bad'},
                      {'unknown': True}, {'rounded_subtitle_background': 1}):
            with self.assertRaises((ValueError, FileNotFoundError)):
                self.edit('style', scope='all', style=style)
        before = ce.file(self.task_id).read_bytes()
        with self.assertRaises(ValueError):
            self.edit('spans', index=0, spans=[{'start': 0, 'end': 100, 'color': '#FFFFFF'}])
        self.assertEqual(ce.file(self.task_id).read_bytes(), before)

    def test_draft_operations_validation_and_source_binding(self):
        protected = {p: (self.root / p).read_bytes() for p in ('script.json', 'scene_plan.json', 'subtitle.srt', 'audio.mp3')}
        self.edit('prepare')
        self.edit('update', index=0, start=0.1, end=0.9, text='Changed text.')
        self.edit('split', index=1, split_at=2, text='First half.', second_text='Second half.')
        self.assertEqual(len(ce.read(self.task_id)['cues']), 3)
        self.edit('merge', index=1)
        self.edit('remove', index=0)
        self.edit('add', start=0.1, end=0.8, text='Added.')
        data = ce.read(self.task_id)
        self.assertEqual([c['text'] for c in data['cues']], ['Added.', 'First half.\nSecond half.'])
        self.assertEqual(ce.parse_srt(ce.srt(data['cues'])), data['cues'])
        before = ce.file(self.task_id).read_bytes()
        for changes in ({'start': 0, 'end': 2}, {'start': -1, 'end': 0.9}, {'start': 0, 'end': 4000},
                        {'start': 0, 'end': float('nan')}, {'start': True, 'end': 1}):
            with self.assertRaises(ValueError):
                self.edit('update', index=0, text='Bad.', **changes)
        with self.assertRaises(ValueError):
            self.edit('split', index=0, split_at=0.1, text='a', second_text='b')
        self.assertEqual(before, ce.file(self.task_id).read_bytes())
        stale = self.request('remove', index=0)
        self.edit('update', index=0, start=0.1, end=0.8, text='New.')
        with self.assertRaisesRegex(ValueError, 'draft changed'):
            task.edit_local_ai_captions(self.task_id, **stale)
        for p, content in protected.items():
            self.assertEqual((self.root / p).read_bytes(), content)
        stale = self.request('remove', index=0)
        self.audio.write_bytes(self.audio.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, 'sources changed'):
            task.edit_local_ai_captions(self.task_id, **stale)
        with self.assertRaises(ValueError):
            ce.validate_cues([{'start_ms': 0, 'end_ms': 1, 'text': '\x00'}], 10)
        with self.assertRaises(ValueError):
            ce.validate_cues([{'start_ms': 0, 'end_ms': 1, 'text': 'a'}] * 2001, 10000)

    def test_real_preview_apply_rerender_and_restore(self):
        finals, _, _ = self.initial_render()
        original_final = Path(finals[0]).read_bytes()
        protected = {p: (self.root / p).read_bytes() for p in ('script.json', 'scene_plan.json', 'subtitle.srt', 'audio.mp3')}
        manifest = gm.manifest_path(self.task_id).read_bytes()
        self.edit('prepare')
        self.edit('update', index=0, start=0.2, end=0.9, text='Edited caption.')
        with (patch.object(local_ai, 'prepare_provider', side_effect=AssertionError('GPU')),
              patch.object(task.voice, 'tts', side_effect=AssertionError('TTS')),
              patch.object(task, 'generate_subtitle', side_effect=AssertionError('Whisper')),
              patch.object(task, '_schedule_cross_post', side_effect=AssertionError('publishing'))):
            preview = self.edit('preview')
            self.assertTrue(ce.file(self.task_id, preview['preview_asset']).is_file())
            self.assertEqual(Path(finals[0]).read_bytes(), original_final)
            self.assertFalse(ce.file(self.task_id, ce.ACTIVE).exists())
            self.assertIsNotNone(ce.load_preview(self.task_id, self.context()['binding'], self.context()['duration_ms'],
                                               gm.scene_timing_snapshot(gm.load_manifest(self.task_id)), ce.render_signature(self.context()['params'])))
            result = self.edit('apply')
            self.assertAlmostEqual(task.voice.get_audio_duration(result['videos'][0]), 3, delta=0.1)
            package = task_artifacts.build_output_package(self.task_id, self.state.get_task(self.task_id))
            self.assertEqual(TaskArtifactPackageData.model_validate(package).caption_track, ce.ACTIVE)
            self.assertIn('Edited caption.', ce.file(self.task_id, package['edited_captions']).read_text())
            active = ce.file(self.task_id, ce.ACTIVE).read_bytes()
            self.edit('update', index=0, start=0.2, end=0.9, text='Unapplied draft.')
            self.assertEqual(ce.file(self.task_id, ce.ACTIVE).read_bytes(), active)
            self.assertIsNone(ce.load_preview(self.task_id, self.context()['binding'], self.context()['duration_ms'],
                                              gm.scene_timing_snapshot(gm.load_manifest(self.task_id)), ce.render_signature(self.context()['params'])))
            task.rerender_local_ai_task(self.task_id, self.params.model_copy(update={'font_size': 16}))
            self.assertEqual(ce.file(self.task_id, ce.ACTIVE).read_bytes(), active)
            # Restore removes only the independent layer, never original files.
            self.edit('restore')
        self.assertFalse(ce.file(self.task_id, ce.ACTIVE).exists())
        self.assertEqual(gm.manifest_path(self.task_id).read_bytes(), manifest)
        for p, content in protected.items():
            if p != 'script.json':  # Explicit render-only font change is saved normally.
                self.assertEqual((self.root / p).read_bytes(), content)

    def test_rollback_corruption_empty_track_and_queue(self):
        self.initial_render()
        self.edit('prepare')
        self.edit('apply')
        active = ce.file(self.task_id, ce.ACTIVE).read_bytes()
        final = (self.root / 'final-1.mp4').read_bytes()
        self.edit('update', index=0, start=0, end=1, text='New draft.')
        def fail(*args, **kwargs):
            (self.root / 'final-1.mp4').write_bytes(b'broken')
            raise RuntimeError('render failed')
        with patch.object(task, 'generate_final_videos', side_effect=fail):
            with self.assertRaises(RuntimeError):
                self.edit('apply')
        self.assertEqual(ce.file(self.task_id, ce.ACTIVE).read_bytes(), active)
        self.assertEqual((self.root / 'final-1.mp4').read_bytes(), final)
        corrupt = json.loads(active)
        corrupt['captions_asset'] = '../outside.srt'
        ce.file(self.task_id, ce.ACTIVE).write_text(json.dumps(corrupt))
        with self.assertRaises(ValueError):
            ce.resolve(self.task_id, self.context()['binding'], self.context()['duration_ms'])
        self.edit('restore')  # Recovery works even when active metadata is damaged.
        for _ in range(2):
            self.edit('remove', index=0)
        self.edit('apply')
        package = task_artifacts.build_output_package(self.task_id, self.state.get_task(self.task_id))
        self.assertTrue(package['captions_omitted'])
        self.edit('restore')
        self.edit('add', start=0, end=1, text='Queued.')
        request = self.request('update', index=0, start=0, end=1, text='Queue snapshot.')
        with patch.object(webui_task._task_manager, 'add_task') as submit:
            webui_task.submit_caption_edit(self.task_id, request=request)
        request['text'] = 'Mutated caller.'
        args = submit.call_args.kwargs
        result = submit.call_args.args[0](**args)
        self.assertNotIn('error', result)
        self.assertEqual(ce.read(self.task_id)['cues'][0]['text'], 'Queue snapshot.')
        self.assertEqual(self.state.get_task(self.task_id)['state'], task.const.TASK_STATE_COMPLETE)
        with patch.object(webui_task._task_manager, 'add_task', side_effect=RuntimeError('full')):
            with self.assertRaises(RuntimeError):
                webui_task.submit_caption_edit(self.task_id, request=self.request('remove', index=0))
        self.assertEqual(self.state.get_task(self.task_id)['state'], task.const.TASK_STATE_COMPLETE)

    def test_restart_resume_and_natural_narration_interaction(self):
        self.initial_render()
        task.prepare_local_ai_narration_ranges(self.task_id)
        for i in (1, 2):
            task.edit_local_ai_narration_range(self.task_id, i, expected_revision=nr.revision(self.task_id), reviewed=True)
        content = BytesIO()
        with wave.open(content, 'wb') as out:
            out.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            out.writeframes(bytes(16000))
        task.replace_local_ai_narration_draft(self.task_id, 1, expected_revision=nr.revision(self.task_id),
                                             content=content.getvalue(), text='Short.', natural_duration=True)
        preview = task.preview_local_ai_narration_timeline(self.task_id, expected_revision=nr.revision(self.task_id))
        task.apply_local_ai_narration_drafts(self.task_id, expected_revision=nr.revision(self.task_id),
            expected_snapshot=gm.scene_timing_snapshot(gm.load_manifest(self.task_id)), expected_timeline=preview['signature'],
            rebuild_captions=True, confirm_transcripts=True)
        self.edit('prepare')
        self.assertEqual(ce.read(self.task_id)['cues'][0]['end_ms'], 500)
        self.edit('update', index=0, start=0, end=0.5, text='Independent.')
        self.edit('apply')
        active = ce.file(self.task_id, ce.ACTIVE).read_bytes()
        with self.assertRaisesRegex(ValueError, 'restore independent captions'):
            task.apply_local_ai_narration_drafts(self.task_id, expected_revision=nr.revision(self.task_id),
                expected_snapshot=gm.scene_timing_snapshot(gm.load_manifest(self.task_id)), rebuild_captions=True, confirm_transcripts=True)
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
            self.assertEqual(ce.file(self.task_id, ce.ACTIVE).read_bytes(), active)
        # A broken narration mix must not trap the operator behind an active
        # caption layer. Original-narration restore rolls back both layers.
        task.narration_mix.file(self.task_id).write_text('{}')
        with patch.object(task, 'generate_final_videos', side_effect=RuntimeError('render failed')):
            with self.assertRaises(RuntimeError):
                task.apply_local_ai_narration_drafts(self.task_id, expected_revision=nr.revision(self.task_id),
                    expected_snapshot=gm.scene_timing_snapshot(gm.load_manifest(self.task_id)), reset=True)
        self.assertEqual(ce.file(self.task_id, ce.ACTIVE).read_bytes(), active)
        self.assertEqual(task.narration_mix.file(self.task_id).read_text(), '{}')
        task.apply_local_ai_narration_drafts(self.task_id, expected_revision=nr.revision(self.task_id),
            expected_snapshot=gm.scene_timing_snapshot(gm.load_manifest(self.task_id)), reset=True)
        self.assertFalse(ce.file(self.task_id, ce.ACTIVE).exists())
        self.edit('prepare')
        self.assertEqual(ce.read(self.task_id)['cues'][0]['text'], 'Flowers.')

    def test_preview_failure_and_active_artifact_download(self):
        self.initial_render()
        self.edit('prepare')
        preview = self.edit('preview')
        before = ce.file(self.task_id, 'caption_preview.json').read_bytes()
        with patch.object(task.video, 'generate_video', side_effect=RuntimeError('preview failed')):
            with self.assertRaises(RuntimeError):
                self.edit('preview')
        self.assertEqual(before, ce.file(self.task_id, 'caption_preview.json').read_bytes())
        self.assertTrue(ce.file(self.task_id, preview['preview_asset']).exists())
        self.assertEqual(len(list((self.root / 'caption_previews').iterdir())), 1)
        self.edit('apply')
        ui_source = (Path(__file__).parents[2] / 'webui/Main.py').read_text()
        function = next(n for n in ast.parse(ui_source).body if isinstance(n, ast.FunctionDef)
                        and n.name == '_render_artifact_package_view')
        harness = """
import json, hashlib
import streamlit as st
from app.services import generation_manifest, task_artifacts
from app.services import state as sm
from app.utils import utils
def tr(value): return value
st.session_state['artifact_package_task_id'] = 'captions'
"""
        downloads = {}
        def capture(label, data, **kwargs):
            downloads[kwargs['file_name']] = data
        with patch('streamlit.download_button', side_effect=capture):
            app = AppTest.from_string(harness + ast.get_source_segment(ui_source, function)
                                      + '\n_render_artifact_package_view()\n', default_timeout=30).run()
        self.assertFalse(app.exception)
        self.assertIn(b'Flowers.', downloads['edited-captions.srt'])
        track = ce.read(self.task_id, ce.ACTIVE)
        ce.file(self.task_id, track['captions_asset']).write_text('tampered')
        self.assertIsNone(task_artifacts.build_output_package(self.task_id)['edited_captions'])
        self.edit('restore')

    def test_no_voice_factual_and_bounded_publication(self):
        task.save_script_data(self.task_id, self.params.video_script, [],
                              self.params.model_copy(update={'voice_name': 'no-voice'}))
        self.edit('prepare')
        self.assertEqual(len(ce.read(self.task_id)['cues']), 2)
        before = ce.file(self.task_id).read_bytes()
        with self.assertRaises(ValueError):
            ce.save(self.task_id, ce.DRAFT, {'text': 'x' * ce.MAX_BYTES})
        self.assertEqual(before, ce.file(self.task_id).read_bytes())
        self.state.update_task(self.task_id, state=task.const.TASK_STATE_PROCESSING, current_stage='other_queued')
        with self.assertRaises(RuntimeError):
            task.edit_local_ai_captions(self.task_id, action='prepare', expected_revision=ce.revision(self.task_id),
                                        expected_binding=self.context()['binding'])
        self.state.update_task(self.task_id, state=task.const.TASK_STATE_COMPLETE)
        task.save_script_data(self.task_id, self.params.video_script, [], self.params.model_copy(update={'content_mode': 'factual'}))
        with self.assertRaisesRegex(ValueError, 'creative'):
            task.caption_editor_context(self.task_id)

    def test_scene_editor_controls_and_preview_download(self):
        self.initial_render()
        self.edit('prepare')
        source = (Path(__file__).parents[2] / 'webui/Main.py').read_text()
        node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == '_render_caption_editor')
        harness = """
import streamlit as st
from app.services import generation_manifest, webui_task
from app.services import task as tm
from app.services import state as sm
def tr(value): return value
st.session_state['scene_editor_task_id'] = 'captions'
"""
        app = AppTest.from_string(harness + ast.get_source_segment(source, node) + '\n_render_caption_editor()\n', default_timeout=30).run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.dataframe), 1)
        for button, action in [('caption_save', 'update'), ('caption_split', 'split'), ('caption_merge', 'merge'),
                               ('caption_remove', 'remove'), ('caption_preview', 'preview'), ('caption_apply', 'apply')]:
            with patch.object(webui_task, 'submit_caption_edit') as submit, patch('streamlit.rerun'):
                app.button(key=f'{button}_{self.task_id}').click().run()
                self.assertEqual(submit.call_args.kwargs['request']['action'], action)
        self.assertFalse(app.exception)


@pytest.mark.parametrize('cues,duration', [(None, 1), ([], True), ([], 3600001),
    ([{'start_ms': 0, 'end_ms': 1, 'text': 'a\n\nb'}], 2),
    ([{'start_ms': 0, 'end_ms': 1, 'text': 'a', 'asset': '../'}], 2)])
def test_malformed_tracks_are_rejected(cues, duration):
    with pytest.raises(ValueError):
        ce.validate_cues(cues, duration)
