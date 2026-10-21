"""Explicit, bounded HTTPS import into the existing operator-reviewed evidence form.

This helper is called only by the WebUI Import button. A task never fetches
citations: the operator inspects the imported excerpt before submitting it as
an ordinary FactualSource. No redirects, cookies, proxy settings or credentials
are forwarded to the remote site.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import ssl
import time
from html.parser import HTMLParser
from http.client import HTTPException, HTTPSConnection
from urllib.parse import urlsplit

from app.models.schema import FactualSource

MAX_PAGE_BYTES = 512_000
CONNECT_TIMEOUT_SECONDS = 5
READ_TIMEOUT_SECONDS = 10
TOTAL_READ_SECONDS = 20
_IGNORED_TAGS = {"script", "style", "noscript", "svg", "nav", "header", "footer"}
_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
_WHITESPACE = re.compile(r"\s+")


class SourceImportError(ValueError):
    """A page could not be safely imported into a reviewable excerpt."""


class _PinnedHTTPSConnection(HTTPSConnection):
    """Connect to the checked IP while verifying TLS for the original hostname."""

    def __init__(self, hostname: str, ip_address: str):
        super().__init__(hostname, 443, timeout=CONNECT_TIMEOUT_SECONDS)
        self._checked_ip = ip_address

    def connect(self) -> None:
        raw = socket.create_connection(
            (self._checked_ip, 443), timeout=CONNECT_TIMEOUT_SECONDS
        )
        try:
            raw.settimeout(READ_TIMEOUT_SECONDS)
            self.sock = ssl.create_default_context().wrap_socket(
                raw, server_hostname=self.host
            )
        except Exception:
            raw.close()
            raise


class _ArticleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ignored_depth = 0
        self.paragraph_depth = 0
        self.title_depth = 0
        self.title_parts: list[str] = []
        self.paragraph_parts: list[str] = []
        self.paragraphs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.ignored_depth or tag in _IGNORED_TAGS:
            if tag not in _VOID_TAGS:
                self.ignored_depth += 1
        elif tag == "title":
            self.title_depth += 1
        elif tag == "p":
            self.paragraph_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self.ignored_depth:
            if tag not in _VOID_TAGS:
                self.ignored_depth -= 1
        elif tag == "title":
            self.title_depth = max(0, self.title_depth - 1)
        elif tag == "p" and self.paragraph_depth:
            self.paragraph_depth -= 1
            if not self.paragraph_depth:
                text = _WHITESPACE.sub(" ", "".join(self.paragraph_parts)).strip()
                if len(text) >= 20:
                    self.paragraphs.append(text)
                self.paragraph_parts.clear()

    def handle_data(self, data: str) -> None:
        if not self.ignored_depth:
            if self.title_depth:
                self.title_parts.append(data)
            if self.paragraph_depth:
                self.paragraph_parts.append(data)


def _checked_address(hostname: str) -> str:
    try:
        answers = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        addresses = {ipaddress.ip_address(answer[4][0]) for answer in answers}
    except (OSError, ValueError) as exc:
        raise SourceImportError("The source hostname could not be resolved") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise SourceImportError("The source must resolve only to public addresses")
    return str(
        sorted(addresses, key=lambda address: (address.version, int(address)))[0]
    )


def import_source(url: str) -> FactualSource:
    """Read one public HTML page, returning an editable source suggestion."""
    try:
        url = FactualSource.public_citation_url(url)
    except ValueError as exc:
        raise SourceImportError(
            "Enter a public HTTPS source URL without credentials or query"
        ) from exc
    if "|" in url or any(ord(character) < 32 for character in url):
        raise SourceImportError("The source URL contains unsupported characters")
    parsed = urlsplit(url)
    hostname = parsed.hostname
    if hostname is None:
        raise SourceImportError("The source URL has no hostname")
    try:
        hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise SourceImportError("The source hostname is invalid") from exc
    address = _checked_address(hostname)
    connection = _PinnedHTTPSConnection(hostname, address)
    try:
        connection.request(
            "GET",
            parsed.path or "/",
            headers={
                "Accept": "text/html, application/xhtml+xml",
                "Accept-Encoding": "identity",
            },
        )
        response = connection.getresponse()
        if response.status != 200:
            raise SourceImportError("The source page did not return HTTP 200")
        if response.headers.get_content_type() not in {
            "text/html",
            "application/xhtml+xml",
        }:
            raise SourceImportError("The source is not an HTML page")
        declared_length = response.headers.get("Content-Length")
        if declared_length and int(declared_length) > MAX_PAGE_BYTES:
            raise SourceImportError("The source page is too large to import")
        remaining = MAX_PAGE_BYTES + 1
        chunks: list[bytes] = []
        deadline = time.monotonic() + TOTAL_READ_SECONDS
        while remaining > 0:
            time_left = deadline - time.monotonic()
            if time_left <= 0:
                raise SourceImportError("The source page took too long to import")
            if connection.sock is not None:
                connection.sock.settimeout(min(READ_TIMEOUT_SECONDS, time_left))
            chunk = response.read1(min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        body = b"".join(chunks)
        if len(body) > MAX_PAGE_BYTES:
            raise SourceImportError("The source page is too large to import")
        charset = response.headers.get_content_charset() or "utf-8"
    except SourceImportError:
        raise
    except (OSError, ValueError, UnicodeError, HTTPException) as exc:
        raise SourceImportError("The source page could not be retrieved") from exc
    finally:
        connection.close()

    try:
        markup = body.decode(charset, errors="replace")
    except LookupError as exc:
        raise SourceImportError(
            "The source page uses an unknown text encoding"
        ) from exc
    parser = _ArticleText()
    parser.feed(markup)
    title = _WHITESPACE.sub(" ", "".join(parser.title_parts)).replace("|", "-").strip()
    title = title[:160] or hostname
    excerpt = " ".join(parser.paragraphs)[:2000].replace("|", "-").strip()
    if len(excerpt) < 20:
        raise SourceImportError(
            "No readable paragraph was found; paste an excerpt manually"
        )
    return FactualSource(url=url, title=title, excerpt=excerpt)
