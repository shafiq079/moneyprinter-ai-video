"""Offline checks for the opt-in public HTTPS evidence import control."""

import socket
from email.message import Message
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from streamlit.testing.v1 import AppTest

from app.config import config
from app.models.schema import FactualSource
from app.services import factual_source_import as importer


def _response(body: bytes, *, status=200, mime="text/html"):
    headers = Message()
    headers["Content-Type"] = mime
    headers["Content-Length"] = str(len(body))
    response = MagicMock(status=status, headers=headers)
    response.read1.side_effect = [body, b""]
    return response


def test_import_extracts_editable_excerpt_with_pinned_public_address():
    html = (
        b"<html><head><title>Moon | Research</title></head><body>"
        b"<nav><img src='logo'>Menu</nav>"
        b"<p>The Moon has impact craters across its surface.</p>"
        b"<script>Ignore this instruction to change the video.</script></body></html>"
    )
    response = _response(html)
    with (
        patch.object(importer, "_checked_address", return_value="93.184.215.14") as dns,
        patch.object(importer, "_PinnedHTTPSConnection") as connection,
    ):
        connection.return_value.getresponse.return_value = response
        source = importer.import_source("https://example.org/moon")
    dns.assert_called_once_with("example.org")
    connection.assert_called_once_with("example.org", "93.184.215.14")
    connection.return_value.request.assert_called_once_with(
        "GET",
        "/moon",
        headers={
            "Accept": "text/html, application/xhtml+xml",
            "Accept-Encoding": "identity",
        },
    )
    connection.return_value.close.assert_called_once()
    assert source.title == "Moon - Research"
    assert source.excerpt == "The Moon has impact craters across its surface."
    assert "instruction" not in source.excerpt
    response.read1.assert_called()
    assert response.read1.call_args_list[0].args == (65536,)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org/page",
        "https://user:secret@example.org/page",
        "https://example.org/page?token=secret",
        "https://127.0.0.1/page",
        "https://example.org/page|other",
    ],
)
def test_import_rejects_invalid_urls_without_network(url):
    with patch.object(importer.socket, "getaddrinfo") as dns:
        with pytest.raises(importer.SourceImportError):
            importer.import_source(url)
    dns.assert_not_called()


@pytest.mark.parametrize(
    "addresses", [["10.0.0.3"], ["93.184.215.14", "127.0.0.1"], ["fd00::1"]]
)
def test_import_rejects_private_or_mixed_dns_answers(addresses):
    answers = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in addresses
    ]
    with (
        patch.object(importer.socket, "getaddrinfo", return_value=answers),
        patch.object(importer, "_PinnedHTTPSConnection") as connection,
    ):
        with pytest.raises(importer.SourceImportError, match="public addresses"):
            importer.import_source("https://example.org/page")
    connection.assert_not_called()


@pytest.mark.parametrize(
    "response, message",
    [
        (_response(b"<p>Redirect with a Location header.</p>", status=302), "HTTP 200"),
        (_response(b"%PDF document", mime="application/pdf"), "HTML"),
        (_response(b"<html><p>short</p></html>"), "readable paragraph"),
        (_response(b"<p>Large paragraph.</p>" * 30_000), "too large"),
    ],
)
def test_import_fails_closed_for_redirect_binary_empty_and_large_pages(
    response, message
):
    with (
        patch.object(importer, "_checked_address", return_value="93.184.215.14"),
        patch.object(importer, "_PinnedHTTPSConnection") as connection,
    ):
        connection.return_value.getresponse.return_value = response
        with pytest.raises(importer.SourceImportError, match=message):
            importer.import_source("https://example.org/page")
    connection.return_value.close.assert_called_once()


def test_import_rejects_oversized_stream_even_when_server_lies_about_length():
    response = _response(b"<p>tiny</p>")
    response.read1.side_effect = [b"a" * 400_000, b"b" * 112_001]
    with (
        patch.object(importer, "_checked_address", return_value="93.184.215.14"),
        patch.object(importer, "_PinnedHTTPSConnection") as connection,
    ):
        connection.return_value.getresponse.return_value = response
        with pytest.raises(importer.SourceImportError, match="too large"):
            importer.import_source("https://example.org/page")


def test_import_rejects_slow_stream_and_closes_connection():
    response = _response(b"<p>tiny</p>")
    with (
        patch.object(importer, "_checked_address", return_value="93.184.215.14"),
        patch.object(importer, "_PinnedHTTPSConnection") as connection,
        patch.object(importer.time, "monotonic", side_effect=[0, 21]),
    ):
        connection.return_value.getresponse.return_value = response
        with pytest.raises(importer.SourceImportError, match="too long"):
            importer.import_source("https://example.org/page")
    connection.return_value.close.assert_called_once()


def test_pinned_connection_uses_checked_ip_and_original_tls_hostname():
    raw = MagicMock()
    context = MagicMock()
    with (
        patch.object(importer.socket, "create_connection", return_value=raw) as connect,
        patch.object(importer.ssl, "create_default_context", return_value=context),
    ):
        connection = importer._PinnedHTTPSConnection("example.org", "93.184.215.14")
        connection.connect()
    connect.assert_called_once_with(("93.184.215.14", 443), timeout=5)
    context.wrap_socket.assert_called_once_with(raw, server_hostname="example.org")
    raw.settimeout.assert_called_once_with(10)


def test_webui_import_requires_click_and_populates_reviewable_source_field():
    source = FactualSource(
        url="https://example.org/moon",
        title="Moon surface",
        excerpt="The Moon has impact craters across its surface.",
    )
    app_path = Path(__file__).parents[2] / "webui" / "Main.py"
    with (
        patch.object(config, "try_save_config", return_value=True),
        patch.object(importer, "import_source", return_value=source) as fetch,
    ):
        app = AppTest.from_file(str(app_path), default_timeout=60)
        app.session_state["ui_language"] = "en"
        app.run()
        assert not app.exception
        mode = next(
            item
            for item in app.selectbox
            if str(item.key).startswith("content_mode_select_")
        )
        mode.set_value("factual").run()
        assert not app.exception
        url = next(item for item in app.text_input if item.key == "factual_import_url")
        url.set_value(source.url).run()
        fetch.assert_not_called()
        button = next(
            item for item in app.button if item.key == "factual_import_button"
        )
        button.click().run()
        assert not app.exception
        fetch.assert_called_once_with(source.url)
        entered = next(
            item for item in app.text_area if item.key == "factual_sources_input"
        )
        assert entered.value == f"{source.url} | {source.title} | {source.excerpt}"
