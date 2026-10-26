"""CPU-only browser acceptance with a disposable project; no provider/TTS calls."""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def offline_provider():
    from app.services.local_ai.fake import FakeLocalVideoProvider
    from app.utils import utils
    class CPUProvider(FakeLocalVideoProvider):
        def generate(self, scene, output_path):
            super().generate(scene, output_path)
            # VP9 in MP4 exercises the same editor path in Chromium builds that
            # do not ship proprietary H.264. Production encoding is unchanged.
            converted = Path(output_path).with_suffix('.vp9.mp4')
            try:
                subprocess.run([utils.get_ffmpeg_binary(), '-v', 'error', '-y',
                    '-i', str(output_path), '-an', '-c:v', 'libvpx-vp9', '-crf', '38',
                    '-b:v', '0', '-threads', '1', '-row-mt', '1', '-f', 'mp4',
                    str(converted)], check=True)
                os.replace(converted, output_path)
            finally:
                converted.unlink(missing_ok=True)
    return CPUProvider()


def main():
    from app.models.schema import VideoParams
    from app.services import opencut, scene_planner, task
    from app.services.local_ai.orchestrator import generate_scene_materials
    from app.utils import utils
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'storage' / 'opencut-browser-check')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    task_id = 'opencut-check-' + uuid.uuid4().hex
    task_root = Path(utils.task_dir(task_id))
    with tempfile.TemporaryDirectory(prefix='mpt-opencut-check-') as directory:
        token = Path(directory) / 'session'
        process = None
        try:
            params = VideoParams(video_subject='OpenCut CPU check', video_script='Flowers. Bees.',
                video_source='ltx25_hf', video_clip_duration=2, local_ai_duration_mode='auto',
                bgm_type='', custom_audio_file='narration.wav', font_name='MicrosoftYaHeiBold.ttc', font_size=48)
            subprocess.run([utils.get_ffmpeg_binary(), '-v', 'error', '-y', '-f', 'lavfi', '-i',
                'sine=frequency=440:sample_rate=16000', '-t', '4', str(task_root / 'narration.wav')], check=True)
            plan = scene_planner.get_or_create_scene_plan(task_id, params.video_script,
                audio_duration=4, max_scene_duration=2, aspect='9:16', use_llm=False)
            generate_scene_materials(task_id, scenes=list(plan.scenes), provider=offline_provider())
            task.save_script_data(task_id, params.video_script, [], params)
            (task_root / 'subtitle.srt').write_text('1\n00:00:00,000 --> 00:00:02,000\nFlowers.\n\n2\n00:00:02,000 --> 00:00:04,000\nBees.\n\n')
            token.write_text(opencut.ticket(task_id))
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                port = probe.getsockname()[1]
            log = (args.output / 'server.log').open('w')
            try:
                # Isolate the offline provider substitution to this disposable QA
                # subprocess; production source dispatch is never changed.
                offline_server = (
                    "import runpy; from app.services import local_ai; "
                    "from scripts.verify_opencut import offline_provider; "
                    "local_ai.prepare_provider=lambda *a, **k: offline_provider(); "
                    "runpy.run_module('webui.opencut_server',run_name='__main__')"
                )
                process = subprocess.Popen([sys.executable, '-c', offline_server, '--port', str(port)], cwd=ROOT, stdout=log, stderr=log, start_new_session=os.name != 'nt')
                import httpx
                for _ in range(150):
                    try:
                        if httpx.get(f'http://127.0.0.1:{port}/opencut/', timeout=1, trust_env=False).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(.2)
                else:
                    raise RuntimeError('OpenCut gateway did not become ready')
                env = {**os.environ, 'MPT_BROWSER_BASE': f'http://127.0.0.1:{port}',
                    'MPT_BROWSER_TOKEN_FILE': str(token), 'MPT_BROWSER_OUTPUT': str(args.output.resolve())}
                subprocess.run(['node', 'test/flow.cjs'], cwd=ROOT / 'webui' / 'opencut_frontend', env=env, check=True, timeout=300)
                from moviepy import VideoFileClip
                with VideoFileClip(str(args.output / 'export.webm')) as video:
                    if video.duration < 3.9 or list(video.size) != [1080, 1920] or video.audio is None:
                        raise AssertionError('native OpenCut export failed video/audio validation')
                    if sum(video.audio.get_frame(.5) ** 2) < 1e-6:
                        raise AssertionError('native OpenCut export lost audible narration')
                if not list((task_root / 'opencut' / 'exports').glob('*.webm')):
                    raise AssertionError('native OpenCut export was not saved back to the task')
                print('OpenCut browser acceptance passed: edit/save/reload/fresh-browser/native export/audio/task-manager proxy.')
            finally:
                if process:
                    if os.name != 'nt':
                        os.killpg(process.pid, signal.SIGTERM)
                    else:
                        process.terminate()
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                log.close()
        finally:
            shutil.rmtree(task_root, ignore_errors=True)


if __name__ == '__main__':
    main()
