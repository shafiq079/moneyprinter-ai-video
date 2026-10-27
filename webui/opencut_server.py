"""Same-origin OpenCut + Streamlit gateway, used only on the OpenCut branch."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import socket
import subprocess
import sys
import tempfile
import uuid
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket
from starlette.responses import FileResponse, StreamingResponse
from starlette.staticfiles import StaticFiles
import websockets

from app.services import opencut as bridge
from app.utils import utils

FRONTEND = Path(__file__).parent / 'opencut_frontend' / 'dist'
HOP_HEADERS = {'connection', 'transfer-encoding', 'keep-alive', 'upgrade', 'proxy-connection'}
LOGGER = logging.getLogger(__name__)


def _authority(value, scheme):
    """Compare authorities without rejecting HTTPS default ports/case changes."""
    try:
        parsed = urlsplit(scheme + '://' + value.strip())
        if not parsed.hostname or parsed.username or parsed.password or parsed.path:
            return None
        return (parsed.hostname.lower(), parsed.port or (443 if scheme == 'https' else 80))
    except (ValueError, AttributeError):
        return None


def _origin_allowed(origin, headers, public_hosts=()):
    if origin is None:
        return True
    try:
        parsed = urlsplit(origin)
        if parsed.scheme not in {'http', 'https'} or parsed.path or parsed.query or parsed.fragment:
            return False
        authority = _authority(parsed.netloc, parsed.scheme)
        if authority is None:
            return False
        # A forwarding header must not override an already-correct Host header.
        candidates = [headers.get('host', ''), headers.get('x-forwarded-host', '').split(',')[0].strip(), *public_hosts]
        return any(_authority(value, parsed.scheme) == authority for value in candidates if value)
    except (ValueError, AttributeError):
        return False


def _codespace_hosts(public_port):
    name = os.environ.get('CODESPACE_NAME', '')
    domain = os.environ.get('GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN', '')
    if (public_port and 1 <= public_port <= 65535 and re.fullmatch(r'[A-Za-z0-9-]+', name)
            and re.fullmatch(r'[A-Za-z0-9.-]+', domain)):
        return (f'{name}-{public_port}.{domain}',)
    return ()


def authenticated(request: Request):
    header = request.headers.get('authorization', '')
    if not header.startswith('Bearer '):
        raise HTTPException(401, 'OpenCut session required')
    try:
        return bridge.authorize(header[7:])
    except ValueError as exc:
        raise HTTPException(401, str(exc)) from exc


async def bounded_upload(request, destination, limit):
    size = 0
    digest = hashlib.sha256()
    with destination.open('wb') as stream:
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                raise HTTPException(413, 'OpenCut upload exceeds its size limit')
            digest.update(chunk)
            stream.write(chunk)
    if not size:
        raise HTTPException(400, 'empty upload')
    return digest.hexdigest()


def create_app(streamlit_port=None, public_port=None):
    public_hosts = _codespace_hosts(public_port)
    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(timeout=None, trust_env=False) as client:
            app.state.proxy = client
            yield
    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(ValueError)
    async def bad_value(request, exc):
        from starlette.responses import JSONResponse
        return JSONResponse({'detail': str(exc)}, status_code=400)

    # OAuth routes precede the Streamlit catch-all. No credential-bearing
    # callback parameters are proxied into Streamlit or returned in redirects.
    from webui.youtube_oauth import install_routes
    install_routes(app)

    @app.get('/opencut/api/session')
    async def session(task_id=Depends(authenticated)):
        return await asyncio.to_thread(bridge.session, task_id)

    @app.get('/opencut/api/fonts')
    async def fonts(task_id=Depends(authenticated)):
        from app.services import opencut_fonts
        return await asyncio.to_thread(opencut_fonts.catalog)

    @app.get('/opencut/api/fonts/{font_id}')
    async def font(font_id: str, task_id=Depends(authenticated)):
        from app.services import opencut_fonts
        return FileResponse(await asyncio.to_thread(opencut_fonts.font_file, font_id))

    @app.get('/opencut/api/clips')
    async def clips(task_id=Depends(authenticated)):
        from app.services import opencut_clips
        return await asyncio.to_thread(opencut_clips.catalog, task_id)

    @app.post('/opencut/api/clips/{scene_id}/generate')
    async def generate_clip(scene_id: int, request: Request, task_id=Depends(authenticated)):
        from app.services import opencut_clips
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 16384:
                raise HTTPException(413, 'clip request is too large')
        return await asyncio.to_thread(opencut_clips.submit, task_id, scene_id, json.loads(body))

    @app.post('/opencut/api/clips/cancel')
    async def cancel_clip(task_id=Depends(authenticated)):
        from app.services import opencut_clips
        return await asyncio.to_thread(opencut_clips.cancel, task_id)

    @app.get('/opencut/api/clips/{scene_id}/{version_id}')
    async def clip_version(scene_id: int, version_id: str, task_id=Depends(authenticated)):
        from app.services import opencut_clips
        return FileResponse(await asyncio.to_thread(opencut_clips.version_file, task_id, scene_id, version_id), media_type='video/mp4')

    @app.post('/opencut/api/clips/{scene_id}/upload')
    async def upload_clip(scene_id: int, request: Request, task_id=Depends(authenticated)):
        from app.services import opencut_clips
        directory = bridge.directory(task_id)
        target = directory / ('.clip-upload-' + uuid.uuid4().hex + '.mp4')
        try:
            await bounded_upload(request, target, 100 * 1024 * 1024)
            digest = await asyncio.to_thread(opencut_clips.upload, task_id, scene_id, target)
            return {'version_id': digest}
        finally:
            target.unlink(missing_ok=True)

    @app.get('/opencut/api/archive')
    async def archive(task_id=Depends(authenticated)):
        from app.services import project_archive
        from starlette.background import BackgroundTask
        target = await asyncio.to_thread(project_archive.export_project, task_id)
        return FileResponse(target, filename=task_id + '.mptproject.zip', media_type='application/zip',
            background=BackgroundTask(target.unlink, missing_ok=True))

    @app.get('/opencut/api/source/{asset_id}')
    async def source(asset_id: str, task_id=Depends(authenticated)):
        data = await asyncio.to_thread(bridge.seed, task_id)
        record = data['resources'].get(asset_id)
        if record is None:
            raise HTTPException(404, 'source asset is unavailable')
        from app.services import generation_manifest as gm
        return FileResponse(gm.resolve_asset(task_id, record['asset']))

    @app.get('/opencut/api/media/{digest}')
    async def media(digest: str, task_id=Depends(authenticated)):
        if not re.fullmatch('[a-f0-9]{64}', digest):
            raise HTTPException(400, 'invalid media identifier')
        target = bridge.directory(task_id) / 'media' / digest
        if not target.is_file() or target.is_symlink():
            raise HTTPException(404, 'saved OpenCut media is unavailable')
        return FileResponse(target, media_type='application/octet-stream')

    @app.put('/opencut/api/media/{digest}')
    async def put_media(digest: str, request: Request, task_id=Depends(authenticated)):
        if not re.fullmatch('[a-f0-9]{64}', digest):
            raise HTTPException(400, 'invalid media identifier')
        directory = bridge.directory(task_id) / 'media'
        directory.mkdir(exist_ok=True)
        target = directory / digest
        if target.is_file():
            return {'sha256': digest}
        handle, name = tempfile.mkstemp(dir=directory, prefix='.upload-')
        os.close(handle)
        temporary = Path(name)
        try:
            actual = await bounded_upload(request, temporary, bridge.MAX_ASSET)
            if actual != digest:
                raise HTTPException(400, 'media checksum does not match')
            temporary.replace(target)
            return {'sha256': digest}
        finally:
            temporary.unlink(missing_ok=True)

    @app.put('/opencut/api/project')
    async def put_project(request: Request, task_id=Depends(authenticated)):
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > bridge.MAX_PROJECT:
                raise HTTPException(413, 'OpenCut project exceeds 8 MiB')
            chunks.append(chunk)
        try:
            value = json.loads(b''.join(chunks))
        except ValueError as exc:
            raise HTTPException(400, 'invalid project JSON') from exc
        revision = await asyncio.to_thread(bridge.save, task_id, value, request.headers.get('if-match'))
        return {'saved': True, 'revision': revision}

    @app.post('/opencut/api/export/{format}')
    async def export(format: str, request: Request, task_id=Depends(authenticated)):
        if format not in {'mp4', 'webm'}:
            raise HTTPException(400, 'unsupported export format')
        directory = bridge.directory(task_id) / 'exports'
        directory.mkdir(exist_ok=True)
        target = directory / (uuid.uuid4().hex + '.' + format)
        temporary = directory / ('.' + target.name)
        try:
            await bounded_upload(request, temporary, bridge.MAX_ASSET)
            def validate():
                result = subprocess.run([utils.get_ffmpeg_binary(), '-nostdin', '-v', 'error',
                    '-protocol_whitelist', 'file,pipe', '-f', 'mov' if format == 'mp4' else 'matroska',
                    '-i', str(temporary), '-t', '0.04', '-f', 'null', '-'], capture_output=True, timeout=30)
                if result.returncode:
                    raise ValueError('OpenCut export is not a decodable video')
            await asyncio.to_thread(validate)
            temporary.replace(target)
            os.utime(directory.parent.parent, None)
            return {'asset': target.relative_to(bridge.directory(task_id).parent).as_posix()}
        finally:
            temporary.unlink(missing_ok=True)

    @app.get('/opencut/OPENCUT_LICENSE')
    async def license_file():
        return FileResponse(FRONTEND.parent / 'OPENCUT_LICENSE', media_type='text/plain')

    @app.get('/opencut/THIRD_PARTY_NOTICES.txt')
    async def notices():
        return FileResponse(FRONTEND / 'THIRD_PARTY_NOTICES.txt', media_type='text/plain')

    @app.get('/opencut/')
    async def index():
        if not (FRONTEND / 'index.html').is_file():
            raise HTTPException(503, 'Build OpenCut first: uv run python scripts/setup_opencut.py')
        return FileResponse(FRONTEND / 'index.html')

    if FRONTEND.is_dir():
        app.mount('/opencut/assets', StaticFiles(directory=FRONTEND / 'assets'), name='opencut-assets')
        for folder in FRONTEND.iterdir():
            if folder.is_dir() and folder.name != 'assets':
                app.mount('/' + folder.name, StaticFiles(directory=folder), name='opencut-' + folder.name)

    if streamlit_port:
        @app.websocket('/{path:path}')
        async def websocket_proxy(websocket: WebSocket, path: str):
            origin = websocket.headers.get('origin')
            if not _origin_allowed(origin, websocket.headers, public_hosts):
                LOGGER.warning('Rejected Streamlit WebSocket origin=%r host=%r forwarded_host=%r',
                    origin, websocket.headers.get('host'), websocket.headers.get('x-forwarded-host'))
                await websocket.close(code=1008)
                return
            protocols = websocket.scope.get('subprotocols', [])
            headers = {k: v for k, v in websocket.headers.items()
                       if k.lower() not in HOP_HEADERS | {'host', 'sec-websocket-key', 'sec-websocket-version', 'sec-websocket-protocol', 'sec-websocket-extensions', 'origin'}}
            uri = f'ws://127.0.0.1:{streamlit_port}/{path}'
            if websocket.url.query:
                uri += '?' + websocket.url.query
            async with websockets.connect(uri, additional_headers=headers,
                    origin=f'http://127.0.0.1:{streamlit_port}' if origin else None, subprotocols=protocols,
                    max_size=None, proxy=None, open_timeout=5, close_timeout=2) as upstream:
                await websocket.accept(subprotocol=upstream.subprotocol)
                async def browser_to_backend():
                    while True:
                        value = await websocket.receive()
                        if value['type'] == 'websocket.disconnect':
                            break
                        await upstream.send(value.get('bytes') if value.get('bytes') is not None else value.get('text', ''))
                async def backend_to_browser():
                    async for value in upstream:
                        if isinstance(value, bytes):
                            await websocket.send_bytes(value)
                        else:
                            await websocket.send_text(value)
                jobs = [asyncio.create_task(browser_to_backend()), asyncio.create_task(backend_to_browser())]
                try:
                    _, pending = await asyncio.wait(jobs, return_when=asyncio.FIRST_COMPLETED)
                    for job in pending:
                        job.cancel()
                finally:
                    for job in jobs:
                        job.cancel()
                    await asyncio.gather(*jobs, return_exceptions=True)

        @app.api_route('/{path:path}', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS', 'HEAD'])
        async def http_proxy(request: Request, path: str):
            headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_HEADERS}
            url = f'http://127.0.0.1:{streamlit_port}/{path}'
            if request.url.query:
                url += '?' + request.url.query
            upstream_request = app.state.proxy.build_request(request.method, url, headers=headers, content=request.stream())
            response = await app.state.proxy.send(upstream_request, stream=True)
            async def body():
                try:
                    async for part in response.aiter_raw():
                        yield part
                finally:
                    await response.aclose()
            return StreamingResponse(body(), status_code=response.status_code,
                headers={k: v for k, v in response.headers.items() if k.lower() not in HOP_HEADERS})
    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default=os.environ.get('MPT_WEBUI_HOST', '127.0.0.1'))
    parser.add_argument('--port', type=int, default=int(os.environ.get('MPT_WEBUI_PORT', '8501')))
    args = parser.parse_args()
    if not (FRONTEND / 'index.html').is_file():
        raise SystemExit('Run uv run python scripts/setup_opencut.py once before starting this branch.')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        internal_port = sock.getsockname()[1]
    env = {**os.environ, 'MPT_OPENCUT': '1', 'MPT_PUBLIC_PORT': str(args.port)}
    process = subprocess.Popen([sys.executable, '-m', 'streamlit', 'run', str(Path(__file__).parent / 'Main.py'),
        '--server.address=127.0.0.1', f'--server.port={internal_port}', f'--browser.serverPort={args.port}',
        '--browser.gatherUsageStats=False', '--server.headless=True'], env=env)
    try:
        import time
        for _ in range(100):
            try:
                if httpx.get(f'http://127.0.0.1:{internal_port}/_stcore/health', timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if process.poll() is not None:
                raise RuntimeError('Streamlit exited before startup completed')
            time.sleep(.2)
        else:
            raise RuntimeError('Streamlit startup timed out')
        uvicorn.run(create_app(internal_port, args.port), host=args.host, port=args.port,
                    log_level='warning', access_log=False, timeout_graceful_shutdown=5)
    finally:
        process.terminate()
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=10)
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


if __name__ == '__main__':
    main()
