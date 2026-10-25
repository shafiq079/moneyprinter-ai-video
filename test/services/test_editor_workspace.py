from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from app.config import config
from app.models.schema import VideoParams
from app.services import local_ai, scene_planner, task, webui_task
from app.services import editor_workspace as editor
from app.services.local_ai.fake import FakeLocalVideoProvider
from app.services.local_ai.orchestrator import generate_scene_materials
from app.services.state import MemoryState
from app.utils import utils
from test.services.test_local_ai import LocalAITestCase


class TestEditorWorkspace(LocalAITestCase):
    def setUp(self):
        super().setUp()
        self.task_id = 'workspace'
        self.root = Path(utils.task_dir(self.task_id))
        self.state = MemoryState()
        self.params = VideoParams(video_subject='Garden project', video_script='Flowers. Bees.',
            video_source=local_ai.FAKE_SOURCE_ID, video_clip_duration=2, local_ai_duration_mode='auto',
            subtitle_enabled=True, font_name='MicrosoftYaHeiBold.ttc')
        self.plan = scene_planner.get_or_create_scene_plan(self.task_id, self.params.video_script,
            audio_duration=4, max_scene_duration=2, aspect='9:16', use_llm=False)
        generate_scene_materials(self.task_id, scenes=list(self.plan.scenes), provider=FakeLocalVideoProvider())
        task.save_script_data(self.task_id, self.params.video_script, [], self.params)
        self.audio = self.make_audio(self.task_id, 3)
        (self.root / 'subtitle.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\nFlowers.\n\n2\n00:00:01,000 --> 00:00:03,000\nBees.\n\n')
        self.state.update_task(self.task_id, state=task.const.TASK_STATE_COMPLETE, progress=100, audio_file=str(self.audio))
        for item in (patch.object(task.sm, 'state', self.state), patch.object(local_ai, 'is_public_source', return_value=True)):
            item.start()
            self.addCleanup(item.stop)

    def prepare_captions(self):
        context = task.caption_editor_context(self.task_id)
        task.edit_local_ai_captions(self.task_id, action='prepare', expected_revision='missing', expected_binding=context['binding'])

    def test_read_only_view_thumbnail_and_revision(self):
        protected = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch.object(local_ai, 'prepare_provider', side_effect=AssertionError('GPU')):
            view = editor.build_view(self.task_id)
            self.assertEqual(view['order'], [1, 2])
            self.assertEqual([r['id'] for r in view['rows']][:3], ['visual', 'narration', 'captions'])
            self.assertFalse(view['caption_draft'])
            image = editor.thumbnail(self.task_id, view['scenes'][0]['asset'])
            self.assertTrue(image.startswith(b'\xff\xd8'))
        self.assertEqual(editor.build_view(self.task_id)['revision'], view['revision'])
        for path, content in protected.items():
            self.assertEqual(path.read_bytes(), content)
        for value in ('../workspace', '/tmp', 'x/y', '..', 'a' * 129):
            with self.assertRaises(ValueError):
                editor.task_root(value)
        self.prepare_captions()
        self.assertNotEqual(editor.build_view(self.task_id)['revision'], view['revision'])

    def test_timeline_commands_use_existing_validated_queues(self):
        self.prepare_captions()
        view = editor.build_view(self.task_id)
        with patch.object(webui_task, 'submit_scene_reorder') as reorder:
            editor.dispatch(self.task_id, {'kind': 'reorder', 'scene_id': 2, 'start': 0, 'revision': view['revision']}, view)
            reorder.assert_called_once_with(self.task_id, [2, 1], expected_order=[1, 2])
        with patch.object(webui_task, 'submit_scene_timing') as resize:
            editor.dispatch(self.task_id, {'kind': 'resize', 'scene_id': 1, 'duration': 1.5, 'revision': view['revision']}, view)
            self.assertEqual(resize.call_args.args[1], {'1': 1.5, '2': 2.5})
            self.assertEqual(resize.call_args.kwargs['expected_snapshot'], view['snapshot'])
        with patch.object(webui_task, 'submit_caption_edit') as captions:
            editor.dispatch(self.task_id, {'kind': 'caption', 'index': 0, 'start': 0.1, 'end': 0.9, 'revision': view['revision']}, view)
            request = captions.call_args.kwargs['request']
            self.assertEqual(request['text'], 'Flowers.')
            self.assertEqual(request['expected_revision'], view['caption_revision'])
        selection = editor.dispatch(self.task_id, {'kind': 'text_selection', 'index': 0, 'start': 1,
            'end': 4, 'text': 'Flowers.', 'revision': view['revision']}, view)
        self.assertEqual(selection['selection'], {'index': 0, 'start': 1, 'end': 4})
        with self.assertRaises(ValueError):
            editor.dispatch(self.task_id, {'kind': 'text_selection', 'index': 0, 'start': 0,
                'end': 50, 'text': 'unsaved', 'revision': view['revision']}, view)
        result = editor.dispatch(self.task_id, {'kind': 'select', 'target': 'caption-1', 'revision': view['revision']}, view)
        self.assertEqual(result['panel'], 'captions')
        self.assertEqual(result['action']['index'], 1)
        with self.assertRaisesRegex(ValueError, 'project changed'):
            editor.dispatch(self.task_id, {'kind': 'caption', 'index': 0, 'start': 0, 'end': 1, 'revision': 'stale'}, view)
        self.state.update_task(self.task_id, state=task.const.TASK_STATE_PROCESSING)
        busy = editor.build_view(self.task_id)
        with self.assertRaisesRegex(ValueError, 'busy'):
            editor.dispatch(self.task_id, {'kind': 'reorder', 'scene_id': 2, 'start': 0, 'revision': busy['revision']}, busy)

    def test_restart_caption_queue_retains_completed_status(self):
        self.prepare_captions()
        (self.root / 'final-1.mp4').write_bytes(b'existing output')
        self.state.delete_task(self.task_id)
        view = editor.build_view(self.task_id)
        with patch.object(webui_task._task_manager, 'add_task') as submit:
            editor.dispatch(self.task_id, {'kind': 'caption', 'index': 0, 'start': 0.1, 'end': 0.9, 'revision': view['revision']}, view)
        result = submit.call_args.args[0](**submit.call_args.kwargs)
        self.assertNotIn('error', result)
        self.assertEqual(self.state.get_task(self.task_id)['state'], task.const.TASK_STATE_COMPLETE)

    def test_reload_keeps_last_completed_preview_and_location_without_submitting(self):
        from app.services import editor_preview
        from webui.editor_workspace import timeline_component
        original = editor.build_view(self.task_id)
        final = self.root / 'final-1.mp4'
        final.write_bytes((self.root / original['scenes'][0]['asset']).read_bytes())
        task._backup_render_paths(str(self.root), suffix='audio-layers-backup')
        snapshot = editor_preview.program(self.task_id, busy=True)
        self.assertEqual(snapshot.name, editor_preview.SNAPSHOT)
        completed = snapshot.read_bytes()
        final.write_bytes(b'partial encode')
        self.assertEqual(editor_preview.program(self.task_id, busy=True).read_bytes(), completed)
        final.unlink()
        self.assertEqual(editor_preview.program(self.task_id, busy=False).read_bytes(), completed)
        snapshot.unlink()
        self.assertTrue(editor_preview.program(self.task_id, busy=True).name.endswith('audio-layers-backup'))
        combined = self.root / 'combined-1.mp4'
        combined.write_bytes(completed)
        sources = task.generation_manifest.active_scene_paths(self.task_id)
        key = editor_preview.combined_key(self.task_id, self.params, sources, self.audio)
        editor_preview.record_combined(combined, key)
        self.assertTrue(editor_preview.reusable_combined(self.task_id, combined, key, sources, self.audio))
        self.assertEqual(key, editor_preview.combined_key(self.task_id, self.params.model_copy(update={'font_size': 99}), sources, self.audio))
        changed = editor_preview.combined_key(self.task_id, self.params.model_copy(update={'video_fit_mode': 'contain'}), sources, self.audio)
        self.assertFalse(editor_preview.reusable_combined(self.task_id, combined, changed, sources, self.audio))
        combined.write_bytes(b'partial render')
        self.assertFalse(editor_preview.reusable_combined(self.task_id, combined, key, sources, self.audio))
        self.state.update_task(self.task_id, state=task.const.TASK_STATE_PROCESSING, current_stage='audio_layers_queued')
        timeline_component.clear()
        with (patch.object(config, 'try_save_config', return_value=True),
              patch.object(webui_task, 'submit_audio_layers', side_effect=AssertionError('reload queued an edit'))):
            app = AppTest.from_file(str(Path(__file__).parents[2] / 'webui/Main.py'), default_timeout=60)
            app.session_state['ui_language'] = 'en'
            app.query_params.update({'editor': self.task_id, 'editor_scene': '2', 'editor_panel': 'audio',
                                     'editor_source': 'program', 'editor_item': 'scene-2'})
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state['editor_scene_workspace'], 2)
            self.assertEqual(app.session_state['editor_panel'], 'audio')
            self.assertEqual(app.session_state['editor_source_workspace'], 'program')
            self.assertFalse(any('No exported preview' in str(item.value) for item in app.info))
            app.button(key='editor_refresh').click().run()
            self.assertFalse(app.exception)

    def test_dedicated_page_routes_selection_and_back_to_tasks(self):
        self.prepare_captions()
        with (patch.object(config, 'app', dict(config.app, llm_provider='openai')),
              patch.object(config, 'ui', {}), patch.object(config, 'try_save_config', return_value=True),
              patch.object(local_ai, 'prepare_provider', side_effect=AssertionError('GPU'))):
            from webui.editor_workspace import timeline_component
            timeline_component.clear()
            app = AppTest.from_file(str(Path(__file__).parents[2] / 'webui/Main.py'), default_timeout=60)
            app.session_state['ui_language'] = 'en'
            app.query_params['editor'] = self.task_id
            app.run()
            self.assertFalse(app.exception)
            self.assertTrue(any('Video editor' in h.value for h in app.markdown))
            self.assertEqual(len([b for b in app.button if str(b.key).startswith('regenerate_scene_')]), 1)
            self.assertFalse(any(str(b.key).startswith('generate_video') for b in app.button))
            app.button(key='editor_media_workspace_2').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state['editor_scene_workspace'], 2)
            app.button(key='editor_open_export').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state['editor_panel'], 'export')
            # A background-job rerun can clean up the widget key; durable panel
            # choice must still restore the caption inspector and its styles.
            from webui.editor_workspace import timeline_component
            timeline_component.clear()  # AppTest replaces Streamlit's component registry.
            reopened = AppTest.from_file(str(Path(__file__).parents[2] / 'webui/Main.py'), default_timeout=60)
            reopened.session_state['ui_language'] = 'en'
            reopened.session_state['editor_panel_choice'] = 'captions'
            reopened.query_params['editor'] = self.task_id
            app = reopened.run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state['editor_panel'], 'captions')
            self.assertTrue(any(b.label == 'Save Caption Style' for b in app.button))

            app.button(key='editor_back').click().run()
            self.assertFalse(app.exception)
            self.assertNotIn('editor', app.query_params)
            self.assertEqual(app.query_params['view'], ['tasks'])
            self.assertFalse(any(str(b.key).startswith('regenerate_scene_') for b in app.button))
