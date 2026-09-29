from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import requests


class HuggingFaceRemoteError(RuntimeError):
    """Safe Hugging Face transport failure exposed to the provider layer."""

    def __init__(self, message: str, *, code: str = "remote_error") -> None:
        super().__init__(message)
        self.code = code


class HuggingFaceGradioBackend:
    """Small authenticated Gradio queue client for an operator-owned HF Space."""

    backend_id = "huggingface_zerogpu"

    def __init__(
        self,
        *,
        space_url: str,
        api_name: str,
        token: str,
        job_timeout_seconds: int = 900,
        session: requests.Session | None = None,
    ) -> None:
        normalized_url = str(space_url or "").strip().rstrip("/")
        parsed = urlparse(normalized_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise HuggingFaceRemoteError(
                "Hugging Face Space URL must be an absolute HTTPS URL",
                code="invalid_space_url",
            )
        normalized_api = str(api_name or "").strip().strip("/")
        if not normalized_api:
            raise HuggingFaceRemoteError(
                "Hugging Face Gradio API name is missing",
                code="invalid_api_name",
            )
        if not str(token or "").strip():
            raise HuggingFaceRemoteError(
                "Hugging Face token is missing",
                code="missing_token",
            )

        self.space_url = normalized_url
        self.api_name = normalized_api
        self._token = str(token).strip()
        self.job_timeout_seconds = max(int(job_timeout_seconds), 60)
        self._session = session or requests.Session()
        self._space_origin = f"{parsed.scheme}://{parsed.netloc}"

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def _url(self, path: str) -> str:
        return urljoin(f"{self.space_url}/", path.lstrip("/"))

    def _request(
        self,
        method: str,
        path: str,
        *,
        timeout: int | tuple[int, int] = 30,
        **kwargs: Any,
    ) -> requests.Response:
        try:
            response = self._session.request(
                method,
                self._url(path),
                headers=self._headers,
                timeout=timeout,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise HuggingFaceRemoteError(
                "Hugging Face Space request failed",
                code="space_request_failed",
            ) from exc

        if response.status_code in {401, 403}:
            response.close()
            raise HuggingFaceRemoteError(
                "Hugging Face Space authentication failed",
                code="space_auth_failed",
            )
        if response.status_code == 429:
            response.close()
            raise HuggingFaceRemoteError(
                "Hugging Face ZeroGPU quota or rate limit was reached",
                code="quota_or_rate_limited",
            )
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            response.close()
            raise HuggingFaceRemoteError(
                "Hugging Face Space request failed",
                code="space_request_failed",
            ) from exc
        return response

    def preflight(self) -> dict[str, Any]:
        response = self._request("GET", "/gradio_api/info", timeout=30)
        try:
            payload = response.json()
        except ValueError as exc:
            raise HuggingFaceRemoteError(
                "Hugging Face Space returned invalid Gradio metadata",
                code="invalid_gradio_metadata",
            ) from exc
        finally:
            response.close()

        named = payload.get("named_endpoints") if isinstance(payload, dict) else None
        expected = f"/{self.api_name}"
        if not isinstance(named, dict) or (
            expected not in named and self.api_name not in named
        ):
            raise HuggingFaceRemoteError(
                f"Hugging Face Space does not expose API endpoint {expected}",
                code="missing_api_endpoint",
            )
        return {
            "backend": self.backend_id,
            "api_name": self.api_name,
        }

    def _submit(self, inputs: dict[str, Any]) -> str:
        response = self._request(
            "POST",
            f"/gradio_api/call/v2/{self.api_name}",
            timeout=60,
            json=inputs,
        )
        try:
            payload = response.json()
            event_id = str(payload["event_id"]).strip()
        except (ValueError, KeyError, TypeError) as exc:
            raise HuggingFaceRemoteError(
                "Hugging Face Space did not return a Gradio event ID",
                code="invalid_event_response",
            ) from exc
        finally:
            response.close()
        if not event_id:
            raise HuggingFaceRemoteError(
                "Hugging Face Space returned an empty Gradio event ID",
                code="invalid_event_response",
            )
        return event_id

    def _wait_for_result(self, event_id: str) -> Any:
        response = self._request(
            "GET",
            f"/gradio_api/call/{self.api_name}/{quote(event_id, safe='')}",
            timeout=(30, 90),
            stream=True,
        )
        deadline = time.monotonic() + self.job_timeout_seconds
        current_event = ""
        data_lines: list[str] = []

        def consume_event() -> tuple[bool, Any]:
            nonlocal current_event, data_lines
            event = current_event
            raw_data = "\n".join(data_lines).strip()
            current_event = ""
            data_lines = []
            if event == "error":
                raise HuggingFaceRemoteError(
                    "Hugging Face Space generation failed",
                    code="generation_failed",
                )
            if event == "complete":
                try:
                    return True, json.loads(raw_data) if raw_data else None
                except ValueError as exc:
                    raise HuggingFaceRemoteError(
                        "Hugging Face Space returned invalid completion data",
                        code="invalid_generation_response",
                    ) from exc
            return False, None

        try:
            for raw_line in response.iter_lines(decode_unicode=True):
                if time.monotonic() > deadline:
                    raise HuggingFaceRemoteError(
                        "Hugging Face Space generation timed out",
                        code="generation_timeout",
                    )
                if isinstance(raw_line, bytes):
                    line = raw_line.decode("utf-8", errors="replace")
                else:
                    line = str(raw_line or "")
                if not line:
                    completed, payload = consume_event()
                    if completed:
                        return payload
                    continue
                if line.startswith("event:"):
                    current_event = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    data_lines.append(line.split(":", 1)[1].lstrip())

            completed, payload = consume_event()
            if completed:
                return payload
        finally:
            response.close()

        raise HuggingFaceRemoteError(
            "Hugging Face Space closed the result stream before completion",
            code="incomplete_generation_response",
        )

    def _file_url(self, payload: Any) -> str:
        if isinstance(payload, dict):
            candidate = payload.get("url")
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
            path = payload.get("path")
            if isinstance(path, str) and path.strip():
                return self._url(
                    "/gradio_api/file=" + quote(path.strip(), safe="/:")
                )
            for value in payload.values():
                try:
                    return self._file_url(value)
                except HuggingFaceRemoteError:
                    pass
        elif isinstance(payload, (list, tuple)):
            for value in payload:
                try:
                    return self._file_url(value)
                except HuggingFaceRemoteError:
                    pass
        elif isinstance(payload, str):
            candidate = payload.strip()
            if candidate.startswith(("https://", "/")) and ".mp4" in candidate.lower():
                return candidate
        raise HuggingFaceRemoteError(
            "Hugging Face Space response did not contain a generated video file",
            code="missing_output_file",
        )

    def _validated_download_url(self, candidate: str) -> str:
        url = urljoin(f"{self.space_url}/", str(candidate))
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if parsed.scheme != "https" or origin != self._space_origin:
            raise HuggingFaceRemoteError(
                "Hugging Face Space returned an unsafe output URL",
                code="unsafe_output_url",
            )
        return url

    def _download(self, file_url: str, output_path: Path) -> int:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        partial = output.with_name(f".{output.name}.hf-download")
        partial.unlink(missing_ok=True)
        url = self._validated_download_url(file_url)
        response = None

        try:
            response = self._session.get(
                url,
                headers=self._headers,
                timeout=(30, 120),
                stream=True,
            )
            if response.status_code in {401, 403}:
                raise HuggingFaceRemoteError(
                    "Hugging Face Space output authentication failed",
                    code="space_auth_failed",
                )
            response.raise_for_status()
            size = 0
            with partial.open("wb") as stream:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > 512 * 1024 * 1024:
                        raise HuggingFaceRemoteError(
                            "Hugging Face Space output exceeded the 512 MB safety limit",
                            code="output_too_large",
                        )
                    stream.write(chunk)
            if size <= 0:
                raise HuggingFaceRemoteError(
                    "Hugging Face Space returned an empty video file",
                    code="empty_output_file",
                )
            os.replace(partial, output)
            return size
        except HuggingFaceRemoteError:
            partial.unlink(missing_ok=True)
            raise
        except (OSError, requests.RequestException) as exc:
            partial.unlink(missing_ok=True)
            raise HuggingFaceRemoteError(
                "Hugging Face Space output download failed",
                code="output_download_failed",
            ) from exc
        finally:
            if response is not None:
                response.close()

    def generate(
        self,
        inputs: dict[str, Any],
        output_path: Path,
    ) -> dict[str, Any]:
        event_id = self._submit(inputs)
        payload = self._wait_for_result(event_id)
        file_url = self._file_url(payload)
        size = self._download(file_url, Path(output_path))
        return {
            "backend": self.backend_id,
            "event_id": event_id,
            "output_bytes": size,
        }
