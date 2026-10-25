import io
import json
import shutil
import stat
import zipfile
from unittest.mock import patch

from app.services import audio_layers as al, generation_manifest as gm, project_archive as pa
from app.services import task, editor_workspace as editor, narration_ranges as nr, narration_mix as nm, caption_edits as ce
from app.models.schema import VideoAspect
from test.services.test_audio_layers import tone
from pathlib import Path
from app.models.schema import VideoParams
from app.services import local_ai, scene_planner
from app.services.state import MemoryState
from app.services.local_ai.fake import FakeLocalVideoProvider
from app.services.local_ai.orchestrator import generate_scene_materials
from app.utils import utils
from test.services.test_local_ai import LocalAITestCase


class TestProjectArchive(LocalAITestCase):
    def setUp(self):
        super().setUp()
        self.task_id = 'archive-source'
        self.root = Path(utils.task_dir(self.task_id))
        self.state = MemoryState()
        self.params = VideoParams(video_subject='Garden project', video_script='Flowers. Bees.',
            video_source=local_ai.FAKE_SOURCE_ID, video_clip_duration=2, local_ai_duration_mode='auto',
            subtitle_enabled=True, font_name='MicrosoftYaHeiBold.ttc', bgm_type='', n_threads=1)
        self.plan = scene_planner.get_or_create_scene_plan(self.task_id, self.params.video_script,
            audio_duration=4, max_scene_duration=2, aspect='9:16', use_llm=False)
        generate_scene_materials(self.task_id, scenes=list(self.plan.scenes), provider=FakeLocalVideoProvider())
        task.save_script_data(self.task_id, self.params.video_script, [], self.params)
        self.audio = self.make_audio(self.task_id, 3)
        (self.root / 'subtitle.srt').write_text('1\n00:00:00,000 --> 00:00:03,000\nFlowers. Bees.\n\n')
        self.state.update_task(self.task_id, state=task.const.TASK_STATE_COMPLETE, progress=100, audio_file=str(self.audio))
        for item in (patch.object(task.sm, 'state', self.state), patch.object(local_ai, 'is_public_source', return_value=True)):
            item.start()
            self.addCleanup(item.stop)

    def prepare_captions(self):
        context = task.caption_editor_context(self.task_id)
        task.edit_local_ai_captions(self.task_id, action='prepare', expected_revision='missing', expected_binding=context['binding'])

    def test_project_roundtrip_edit_and_real_render_without_providers(self):
        ranges = task.prepare_local_ai_narration_ranges(self.task_id)
        task.edit_local_ai_narration_range(self.task_id, 1, expected_revision=nr.revision(self.task_id), reviewed=True)
        first = ranges['ranges'][0]
        task.replace_local_ai_narration_draft(self.task_id, 1, expected_revision=nr.revision(self.task_id),
            content=tone(duration=first['end'] - first['start']), text='Revised flowers.')
        metadata, _ = nm.build(self.task_id, self.plan, str(self.audio), nr.revision(self.task_id))
        scene_planner._atomic_write_json(nm.file(self.task_id), metadata)
        self.prepare_captions()
        caption = ce.read(self.task_id)
        caption = ce.edit(caption, 'add', start=0, end=1, text='Revised flowers.')
        caption = ce.edit(caption, 'style', scope='all', style={'text_fore_color': '#FF0000'})
        caption, _ = ce.stage(self.task_id, caption)
        ce.save(self.task_id, ce.DRAFT, caption)
        ce.save(self.task_id, ce.ACTIVE, caption)
        snapshot = gm.load_manifest(self.task_id)
        snapshot['playback_order'] = [2, 1]
        gm.save_manifest(self.task_id, snapshot)
        track = al.load(self.task_id, gm.media_sha256(self.audio))
        key, asset = al.import_asset(self.task_id, tone(), 'Music.wav')
        track['assets'][key] = asset
        track = al.edit(track, 'add', 3000, asset_id=key, kind='music', start_ms=500)
        al.save(self.task_id, al.DRAFT, track)
        al.save(self.task_id, al.ACTIVE, track)
        with (patch.object(task.local_ai, 'prepare_provider', side_effect=AssertionError('provider call')),
              patch.object(task, 'generate_audio', side_effect=AssertionError('TTS call'))):
            archive = pa.export_project(self.task_id)
            self.addCleanup(archive.unlink, missing_ok=True)
            contents = archive.read_bytes()
            shutil.rmtree(self.root)
            self.state.delete_task(self.task_id)
            restored = pa.import_project(io.BytesIO(contents))
            view = editor.build_view(restored)
            self.assertEqual(view['order'], [2, 1])
            self.assertTrue(view['caption_draft'])
            self.assertEqual(view['audio_draft'], track)
            self.assertEqual(ce.read(restored, ce.ACTIVE), caption)
            self.assertEqual(json.loads(nm.file(restored).read_text()), metadata)
            self.state.delete_task(restored)  # restart must resolve task-local narration
            restored_view = editor.build_view(restored)
            params = restored_view['params'].model_copy(update={'subtitle_enabled': False, 'n_threads': 1})
            with patch.object(VideoAspect, 'to_resolution', return_value=(90, 160)):
                result = task.rerender_local_ai_task(restored, params)
            self.assertTrue(result['videos'])
            self.assertTrue(editor.build_view(restored)['scenes'][0]['ready'])

    def test_archive_rejects_corruption_and_unsafe_entries_without_publishing(self):
        archive = pa.export_project(self.task_id)
        self.addCleanup(archive.unlink, missing_ok=True)
        contents = archive.read_bytes()
        before = set(self.task_root.iterdir())
        def changed(rewrite):
            output = io.BytesIO()
            with zipfile.ZipFile(io.BytesIO(contents)) as original, zipfile.ZipFile(output, 'w') as target:
                for name in original.namelist():
                    target.writestr(name, rewrite(name, original.read(name)))
            output.seek(0)
            return output
        with self.assertRaisesRegex(ValueError, 'checksum'):
            pa.import_project(changed(lambda name, value: b'x' * len(value) if name == 'audio.mp3' else value))
        with self.assertRaisesRegex(ValueError, 'version'):
            pa.import_project(changed(lambda name, value: json.dumps({**json.loads(value), 'schema_version': 99}).encode() if name == 'project.json' else value))
        for name in ('../escape.mp4', '/tmp/escape.mp4', 'C:/escape.mp4', 'generated_ai/../escape.mp4', 'config.toml'):
            output = io.BytesIO()
            with zipfile.ZipFile(output, 'w') as target:
                target.writestr('project.json', '{}')
                target.writestr(name, 'bad')
            with self.assertRaises(ValueError):
                pa.import_project(output)
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as target:
            target.writestr('project.json', '{}')
            info = zipfile.ZipInfo('audio.mp3')
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            target.writestr(info, '/etc/passwd')
        with self.assertRaises(ValueError):
            pa.import_project(output)
        self.assertEqual(before, set(self.task_root.iterdir()))

    def test_busy_export_is_blocked(self):
        self.state.update_task(self.task_id, state=task.const.TASK_STATE_PROCESSING)
        with self.assertRaisesRegex(ValueError, 'wait'):
            pa.export_project(self.task_id)

    def test_custom_narration_and_frozen_music_survive_restart_and_reexport(self):
        custom = self.root / 'narration.wav'
        custom.write_bytes(tone(duration=3))
        music = self.root / 'music.wav'
        music.write_bytes(tone(330))
        self.params.custom_audio_file = str(custom)
        self.params.bgm_type = 'random'
        task.save_script_data(self.task_id, self.params.video_script, [], self.params)
        self.state.update_task(self.task_id, state=task.const.TASK_STATE_COMPLETE, progress=100, audio_file=str(custom))
        with patch.object(task.video, 'get_bgm_file', return_value=str(music)):
            archive = pa.export_project(self.task_id)
        self.addCleanup(archive.unlink, missing_ok=True)
        with zipfile.ZipFile(archive) as bundle:
            script = bundle.read('script.json').decode()
            self.assertNotIn(str(self.root), script)
            self.assertEqual(json.loads(script)['params']['custom_audio_file'], 'narration.wav')
        shutil.rmtree(self.root)
        with archive.open('rb') as stream:
            restored = pa.import_project(stream)
        self.state.delete_task(restored)
        with (patch.object(task.video, 'get_bgm_file', side_effect=AssertionError('new music')),
              patch.object(task.local_ai, 'prepare_provider', side_effect=AssertionError('provider')),
              patch.object(VideoAspect, 'to_resolution', return_value=(90, 160))):
            result = task.rerender_local_ai_task(restored)
            self.assertTrue(result['videos'])
            second = pa.export_project(restored)
            self.addCleanup(second.unlink, missing_ok=True)
            with second.open('rb') as stream:
                self.assertNotEqual(pa.import_project(stream), restored)

    def test_ui_download_snapshot_and_import_are_explicit(self):
        from streamlit.testing.v1 import AppTest
        def app(task_id):
            from webui.project_archive import export_controls, import_controls
            export_controls(task_id, False, lambda s: s)
            import_controls(lambda s: s)
        ui = AppTest.from_function(app, args=(self.task_id,)).run()
        self.assertFalse(ui.exception)
        self.assertTrue(next(b for b in ui.button if b.label == 'Import And Open Project').disabled)
        with patch.object(pa, 'import_project', side_effect=AssertionError('rerun imported')):
            ui.run()
        ui.button[0].click().run()
        self.assertFalse(ui.exception)
        self.assertIn(f'project_archive_{self.task_id}', ui.session_state)

    def test_untrusted_references_missing_media_and_limits_are_rejected(self):
        archive = pa.export_project(self.task_id)
        self.addCleanup(archive.unlink, missing_ok=True)
        with zipfile.ZipFile(archive) as bundle:
            original = {name: bundle.read(name) for name in bundle.namelist()}
        before = set(self.task_root.iterdir())
        import hashlib
        def edited(change):
            files = dict(original)
            change(files)
            inventory = json.loads(files['project.json'])
            inventory['files'] = {name: {'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
                                  for name, content in files.items() if name != 'project.json'}
            files['project.json'] = json.dumps(inventory).encode()
            result = io.BytesIO()
            with zipfile.ZipFile(result, 'w') as output:
                for name, content in files.items():
                    output.writestr(name, content)
            return result
        def external(files):
            script = json.loads(files['script.json'])
            script['params']['custom_audio_file'] = '/etc/passwd'
            files['script.json'] = json.dumps(script).encode()
        with self.assertRaisesRegex(ValueError, 'unsafe'):
            pa.import_project(edited(external))
        def missing(files):
            name = next(name for name in files if name.endswith('v001.mp4'))
            files.pop(name)
        with self.assertRaisesRegex(ValueError, 'missing'):
            pa.import_project(edited(missing))
        def playlist(files):
            files['audio.mp3'] = b'#EXTM3U\nhttp://127.0.0.1:1/secret.mp3\n'
        with self.assertRaisesRegex(ValueError, 'safely'):
            pa.import_project(edited(playlist))
        with patch.object(pa, 'MAX_ARCHIVE', 10):
            with self.assertRaisesRegex(ValueError, '512'):
                pa.import_project(io.BytesIO(archive.read_bytes()))
        with patch.object(pa, 'MAX_TOTAL', 10):
            with self.assertRaisesRegex(ValueError, 'oversized'):
                pa.import_project(io.BytesIO(archive.read_bytes()))
        with patch.object(pa, 'MAX_FILES', 1):
            with self.assertRaisesRegex(ValueError, 'too many'):
                pa.import_project(io.BytesIO(archive.read_bytes()))
        self.assertEqual(before, set(self.task_root.iterdir()))
