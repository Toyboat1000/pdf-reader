"""Open web links: fetch a page (or a linked PDF or e-book) over the internet.

This is the only part of the app that uses the network, and only when the user
opens a link. Pages are read with :func:`pdf_reader.sources.html.extract_article`;
links to PDFs and e-books are downloaded and opened like local files.
"""

import hashlib
import logging
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import truststore

from pdf_reader.config.constants import APP_NAME, APP_VERSION
from pdf_reader.sources.html import extract_article
from pdf_reader.sources.models import SourceError, TextSource

log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 20.0
MAX_PAGE_BYTES = 15 * 1024 * 1024
MAX_FILE_BYTES = 300 * 1024 * 1024

_DOWNLOAD_TYPES = {
    "application/pdf": ".pdf",
    "application/x-pdf": ".pdf",
    "application/epub+zip": ".epub",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}
_HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_TEXT_TYPES = frozenset({"text/plain", "text/markdown"})
_ADDRESS = re.compile(r"^(?:https?://)?(?:www\.)?[\w-]+(?:\.[\w-]+)+(?::\d+)?(?:[/?#]\S*)?$")
_META_CHARSET = re.compile(rb"""<meta[^>]+charset=["']?([\w-]+)""", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class FetchResult:
    """What a link led to: an article to read, or a downloaded document file.

    Attributes:
        url: The final address (after redirects).
        article: The page's text, for web pages.
        file: The downloaded file, for links to PDFs, e-books, and Word documents.
    """

    url: str
    article: TextSource | None = None
    file: Path | None = None


def is_web_address(text: str) -> bool:
    """Return whether ``text`` is a single web address (``https://...`` or ``www...``)."""
    text = text.strip()
    if not text or any(c.isspace() for c in text):
        return False
    if text.lower().startswith(("http://", "https://")):
        return bool(urllib.parse.urlsplit(text).netloc)
    return text.lower().startswith("www.") and bool(_ADDRESS.match(text))


def normalize_address(text: str) -> str:
    """Return ``text`` as a full address, adding ``https://`` if it is missing."""
    text = text.strip()
    return text if text.lower().startswith(("http://", "https://")) else f"https://{text}"


def fetch(address: str, download_dir: Path, timeout: float = TIMEOUT_SECONDS) -> FetchResult:
    """Fetch a web page or document. Blocking; call it off the UI thread.

    Args:
        address: The link, with or without ``https://``.
        download_dir: Where linked documents (PDFs, e-books) are saved.
        timeout: Seconds to wait for the server.

    Raises:
        SourceError: The link could not be opened or read.
    """
    url = normalize_address(address)
    if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        raise SourceError("Only web links (http:// or https://) can be opened.")
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) {APP_NAME}/{APP_VERSION}",
            "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
            "Accept-Language": "en",
        },
    )
    # Windows checks the website's certificate, exactly as browsers on this PC do.
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            final_url = response.geturl()
            content_type = response.headers.get_content_type()
            charset = response.headers.get_content_charset()
            suffix = _DOWNLOAD_TYPES.get(content_type) or _document_suffix(final_url, content_type)
            limit = MAX_FILE_BYTES if suffix else MAX_PAGE_BYTES
            data = response.read(limit + 1)
    except urllib.error.HTTPError as exc:
        log.warning("HTTP %s for %s", exc.code, url)
        raise SourceError(_http_message(exc.code)) from exc
    except TimeoutError as exc:
        raise SourceError("The website took too long to respond. Please try again.") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        log.warning("Cannot fetch %s: %s", url, exc)
        raise SourceError(
            "Couldn't reach this link. Please check the address and your internet connection."
        ) from exc
    if len(data) > limit:
        raise SourceError("This page or file is too large to open.")
    if suffix:
        return FetchResult(final_url, file=_save(data, final_url, suffix, download_dir))
    if content_type in _TEXT_TYPES:
        text = data.decode(_charset(b"", charset), errors="replace")
        paragraphs = tuple(p.strip() for p in re.split(r"\n\s*\n", text) if p.strip())
        return FetchResult(final_url, article=TextSource(_name_from(final_url), paragraphs))
    if content_type not in _HTML_TYPES and data.lstrip()[:1] != b"<":
        raise SourceError("This link doesn't lead to a web page or document this app can read.")
    html = data.decode(_charset(data, charset), errors="replace")
    return FetchResult(final_url, article=extract_article(html, _name_from(final_url)))


def _document_suffix(url: str, content_type: str) -> str | None:
    """Spot documents served with a generic type (``application/octet-stream``)."""
    if content_type in _HTML_TYPES:
        return None
    path = urllib.parse.urlsplit(url).path.lower()
    return next((s for s in (".pdf", ".epub", ".docx") if path.endswith(s)), None)


def _save(data: bytes, url: str, suffix: str, folder: Path) -> Path:
    """Save a downloaded document under a name taken from its address."""
    digest = hashlib.sha256(data).hexdigest()[:16]
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", _name_from(url))[:80] or "document"
    if not name.lower().endswith(suffix):
        name += suffix
    target = folder / digest / name
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            temporary = target.with_suffix(target.suffix + ".part")
            temporary.write_bytes(data)
            temporary.replace(target)
    except OSError as exc:
        log.warning("Cannot save download to %s", target, exc_info=True)
        raise SourceError("Couldn't save the downloaded document.") from exc
    return target


def _name_from(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    last = urllib.parse.unquote(parts.path.rstrip("/").rsplit("/", 1)[-1])
    return last or parts.netloc


def _charset(data: bytes, declared: str | None) -> str:
    """Return the page's text encoding: as the server said, as the page says, or UTF-8."""
    match = _META_CHARSET.search(data[:4096])
    candidate = declared or (match.group(1).decode("ascii", "ignore") if match else "utf-8")
    try:
        "".encode(candidate)
    except LookupError:
        return "utf-8"
    return candidate


def _http_message(code: int) -> str:
    if code in (401, 403):
        return (
            "This website doesn't allow the page to be read outside a browser "
            "(it may need you to sign in)."
        )
    if code == 404:
        return "This page wasn't found. Please check the address."
    if code == 429:
        return "The website is busy. Please wait a moment and try again."
    if code >= 500:
        return "The website had a problem. Please try again later."
    return f"The website refused the request (error {code})."
