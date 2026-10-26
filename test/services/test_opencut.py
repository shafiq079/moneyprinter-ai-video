import hashlib
import io
import os
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.models.schema import VideoParams
from app.services import opencut, scene_planner, task
from app.services.local_ai.fake import FakeLocalVideoProvider
from app.services.local_ai.orchestrator import generate_scene_materials
from app.utils import utils
from test.services.test_local_ai import LocalAITestCase
from webui.opencut_server import create_app


class TestOpenCut(LocalAITestCase):
    def setUp(self):
        super().setUp()
        self.task_id = 'opencut-source'
        self.root = Path(utils.task_dir(self.task_id))
        self.params = VideoParams(video_subject='Garden', video_script='Flowers. Bees.', video_source='ltx25_hf',
            video_clip_duration=2, bgm_type='', font_name='MicrosoftYaHeiBold.ttc')
        plan = scene_planner.get_or_create_scene_plan(self.task_id, self.params.video_script,
            audio_duration=3, max_scene_duration=2, aspect='9:16', use_llm=False)
        generate_scene_materials(self.task_id, scenes=list(plan.scenes), provider=FakeLocalVideoProvider())
        task.save_script_data(self.task_id, self.params.video_script, [], self.params)
        self.make_audio(self.task_id, 3)
        (self.root / 'subtitle.srt').write_text('1\n00:00:00,000 --> 00:00:03,000\nGarden.\n\n')
        self.secret_root = self.task_root / 'bridge'
        self.secret_root.mkdir()
        storage_patch = patch.object(utils, 'storage_dir', return_value=str(self.secret_root))
        storage_patch.start()
        self.addCleanup(storage_patch.stop)
        self.token = opencut.ticket(self.task_id)
        self.client = TestClient(create_app())
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.headers = {'Authorization': 'Bearer ' + self.token}

    def test_authenticated_seed_media_save_restore_and_conflicts_preserve_source(self):
        protected = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch.object(task.local_ai, 'prepare_provider', side_effect=AssertionError('provider')):
            response = self.client.get('/opencut/api/session', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['mode'], 'seed')
        self.assertEqual(len(data['seed']['scenes']), 2)
        self.assertEqual(data['seed']['captions'][0]['text'], 'Garden.')
        key = next(iter(data['seed']['resources']))
        media = self.client.get('/opencut/api/source/' + key, headers=self.headers)
        self.assertEqual(media.status_code, 200)
        digest = hashlib.sha256(media.content).hexdigest()
        uploaded = self.client.put('/opencut/api/media/' + digest, content=media.content, headers=self.headers)
        self.assertEqual(uploaded.status_code, 200)
        body = {'project': {'metadata': {'id': 'native-project'}, 'scenes': []},
                'media': [{'id': 'clip-1', 'blob': digest, 'name': 'Clip.mp4', 'type': 'video'}]}
        self.headers['If-Match'] = data['revision']
        saved = self.client.put('/opencut/api/project', json=body, headers=self.headers)
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(self.client.put('/opencut/api/project', json=body, headers=self.headers).status_code, 400)
        restored = self.client.get('/opencut/api/session', headers=self.headers).json()
        self.assertEqual(restored['mode'], 'restore')
        self.assertEqual(restored['project'], body['project'])
        backup = self.client.get('/opencut/api/archive', headers=self.headers)
        self.assertEqual(backup.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(backup.content)) as bundle:
            self.assertIn('opencut/project.json', bundle.namelist())
            self.assertIn('opencut/media/' + digest, bundle.namelist())
        # The persistent signing key supports reopening after server restart.
        self.assertEqual(opencut.authorize(self.token), self.task_id)
        for path, value in protected.items():
            self.assertEqual(path.read_bytes(), value)

    def test_invalid_authentication_paths_sizes_and_missing_media(self):
        self.assertEqual(self.client.get('/opencut/api/session').status_code, 401)
        bad = {'Authorization': 'Bearer ' + self.token[:-1] + ('a' if self.token[-1] != 'a' else 'b')}
        self.assertEqual(self.client.get('/opencut/api/session', headers=bad).status_code, 401)
        with patch.object(opencut.time, 'time', return_value=10**12):
            self.assertEqual(self.client.get('/opencut/api/session', headers=self.headers).status_code, 401)
        self.assertEqual(self.client.get('/opencut/api/source/' + 'f' * 64, headers=self.headers).status_code, 404)
        self.assertEqual(self.client.put('/opencut/api/media/not-a-digest', content=b'x', headers=self.headers).status_code, 400)
        self.assertEqual(self.client.put('/opencut/api/media/' + 'f' * 64, content=b'x', headers=self.headers).status_code, 400)
        with patch.object(opencut, 'MAX_ASSET', 1):
            result = self.client.put('/opencut/api/media/' + 'f' * 64, content=b'xx', headers=self.headers)
            self.assertEqual(result.status_code, 413)
        with patch.object(opencut, 'MAX_PROJECT', 1):
            self.assertEqual(self.client.put('/opencut/api/project', json={}, headers=self.headers).status_code, 413)
        with self.assertRaisesRegex(ValueError, 'save all media'):
            opencut.save(self.task_id, {'project': {'metadata': {}, 'scenes': []},
                'media': [{'id': 'missing', 'blob': 'f' * 64}]}, 'missing')
        self.assertFalse(list(opencut.directory(self.task_id).rglob('.upload-*')))
        self.assertFalse((opencut.directory(self.task_id) / 'project.json').exists())

    def test_export_is_separate_from_original_final_and_rejects_non_video(self):
        (self.root / 'final-1.mp4').write_bytes(b'original')
        self.assertEqual(self.client.post('/opencut/api/export/mp4', content=b'not video', headers=self.headers).status_code, 400)
        self.assertEqual((self.root / 'final-1.mp4').read_bytes(), b'original')
        self.assertFalse(list((opencut.directory(self.task_id) / 'exports').iterdir()))
        from app.services import generation_manifest as gm, task_artifacts
        video = Path(gm.active_scene_paths(self.task_id)[0]).read_bytes()
        completed = self.client.post('/opencut/api/export/mp4', content=video, headers=self.headers)
        self.assertEqual(completed.status_code, 200)
        package = task_artifacts.build_output_package(self.task_id)
        self.assertIn(completed.json()['asset'], package['opencut_exports'])
        self.assertEqual((self.root / 'final-1.mp4').read_bytes(), b'original')

    def test_project_archive_retains_native_project_and_media(self):
        from app.services import project_archive
        source = (self.root / 'audio.mp3').read_bytes()
        digest = hashlib.sha256(source).hexdigest()
        media_root = opencut.directory(self.task_id) / 'media'
        media_root.mkdir()
        (media_root / digest).write_bytes(source)
        native = {'project': {'metadata': {'id': 'opencut-project'}, 'scenes': []},
                  'media': [{'id': 'audio', 'blob': digest, 'name': 'Narration.mp3', 'type': 'audio'}]}
        opencut.save(self.task_id, native, 'missing')
        from app.services import generation_manifest as gm, task_artifacts
        exports = opencut.directory(self.task_id) / 'exports'
        exports.mkdir()
        footage = Path(gm.active_scene_paths(self.task_id)[0]).read_bytes()
        latest = exports / ('a' * 32 + '.mp4')
        older = exports / ('f' * 32 + '.mp4')
        latest.write_bytes(footage)
        older.write_bytes(footage)
        os.utime(older, ns=(1600000000000000000, 1600000000000000000))
        os.utime(latest, ns=(1700000000000000000, 1700000000000000000))
        archive = project_archive.export_project(self.task_id)
        self.addCleanup(archive.unlink, missing_ok=True)
        with archive.open('rb') as stream:
            restored = project_archive.import_project(stream)
        self.assertEqual(opencut.session(restored)['project'], native['project'])
        self.assertTrue(task_artifacts.build_output_package(restored)['opencut_exports'][0].endswith('a' * 32 + '.mp4'))
        self.assertEqual((opencut.directory(restored) / 'media' / digest).read_bytes(), source)

    def test_existing_music_fades_are_retained_in_imported_audio(self):
        from app.services import audio_layers as layers, generation_manifest as gm
        from test.services.test_audio_layers import tone
        import wave
        key, record = layers.import_asset(self.task_id, tone(duration=1), 'Music.wav')
        data = layers.load(self.task_id, gm.media_sha256(self.root / 'audio.mp3'))
        data['assets'][key] = record
        data = layers.edit(data, 'add', 3000, asset_id=key, kind='music', start_ms=250)
        clip = data['clips'][0]
        data = layers.edit(data, 'update', 3000, clip_id=clip['id'], fade_in_ms=200, fade_out_ms=200, gain=.5)
        layers.save(self.task_id, layers.ACTIVE, data)
        value = opencut.seed(self.task_id)
        track = value['audio'][1]
        self.assertEqual(track['start'], .25)
        self.assertEqual(track['gain'], .5)
        source = gm.resolve_asset(self.task_id, value['resources'][track['asset']]['asset'])
        with wave.open(str(source), 'rb') as audio:
            self.assertAlmostEqual(audio.getnframes() / audio.getframerate(), 1, places=2)
        self.assertTrue(any('fades' in note for note in value['notes']))

    def test_gateway_rejects_foreign_websocket_origin_before_proxying(self):
        from starlette.websockets import WebSocketDisconnect
        with TestClient(create_app(streamlit_port=1)) as client:
            with self.assertRaises(WebSocketDisconnect):
                with client.websocket_connect('/_stcore/stream', headers={'Origin': 'https://foreign.example'}):
                    self.fail('foreign origin must not reach Streamlit')
