import json
import tempfile
import unittest
from pathlib import Path

from app.services.local_ai.remote_gpu.huggingface import (
    HuggingFaceGradioBackend,
    HuggingFaceRemoteError,
)


class _Response:
    def __init__(self, *, payload=None, lines=None, chunks=None, status_code=200):
        self._payload = payload
        self._lines = list(lines or [])
        self._chunks = list(chunks or [])
        self.status_code = status_code
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._payload

    def iter_lines(self, decode_unicode=False):
        yield from self._lines

    def iter_content(self, chunk_size=0):
        yield from self._chunks

    def close(self):
        self.closed = True


class _Session:
    def __init__(self, *, output_url=None):
        self.calls = []
        self.output_url = output_url or (
            "https://owner-space.hf.space/gradio_api/file=/tmp/gradio/video.mp4"
        )

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if url.endswith("/gradio_api/info"):
            return _Response(
                payload={
                    "named_endpoints": {
                        "/generate_scene": {"parameters": []}
                    }
                }
            )
        if "/gradio_api/call/v2/generate_scene" in url:
            return _Response(payload={"event_id": "event-123"})
        if "/gradio_api/call/generate_scene/event-123" in url:
            payload = [{"url": self.output_url}, "prompt", 42, "49 frames"]
            return _Response(
                lines=[
                    "event: heartbeat",
                    "data: null",
                    "",
                    "event: complete",
                    "data: " + json.dumps(payload),
                    "",
                ]
            )
        return _Response(status_code=404)

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return _Response(chunks=[b"fake-", b"video"])


class TestHuggingFaceGradioBackend(unittest.TestCase):
    def test_preflight_and_generation_use_authenticated_named_endpoint(self):
        session = _Session()
        backend = HuggingFaceGradioBackend(
            space_url="https://owner-space.hf.space",
            api_name="generate_scene",
            token="hf_test_token",
            job_timeout_seconds=300,
            session=session,
        )

        metadata = backend.preflight()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "scene.mp4"
            result = backend.generate(
                {"prompt": "test", "image_path": None},
                output,
            )
            self.assertEqual(output.read_bytes(), b"fake-video")

        self.assertEqual(metadata["backend"], "huggingface_zerogpu")
        self.assertEqual(result["event_id"], "event-123")
        post_call = next(
            call for call in session.calls
            if call[0] == "POST"
        )
        self.assertTrue(
            post_call[1].endswith("/gradio_api/call/v2/generate_scene")
        )
        self.assertEqual(post_call[2]["json"]["prompt"], "test")
        self.assertEqual(
            post_call[2]["headers"]["Authorization"],
            "Bearer hf_test_token",
        )

    def test_cross_origin_output_url_is_rejected(self):
        session = _Session(output_url="https://example.com/video.mp4")
        backend = HuggingFaceGradioBackend(
            space_url="https://owner-space.hf.space",
            api_name="generate_scene",
            token="hf_test_token",
            session=session,
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                HuggingFaceRemoteError,
                "unsafe output URL",
            ):
                backend.generate(
                    {"prompt": "test"},
                    Path(directory) / "scene.mp4",
                )


if __name__ == "__main__":
    unittest.main()
