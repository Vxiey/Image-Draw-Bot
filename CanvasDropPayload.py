"""Parse drag/drop payloads for direct game-canvas image drops.

Browser drags are not identical to File Explorer drags. Depending on Chrome,
Edge, Windows and TkDND, Image Draw Bot may receive a local file path, a file://
URI, plain URL text or a small HTML fragment containing an image URL. This
module normalizes those forms without performing network access.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from pathlib import Path
import re
from urllib.parse import parse_qs, unquote, urlparse

_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.jpe', '.jfif', '.webp', '.bmp', '.gif'}
MAX_DROP_CHARACTERS = 32_000_000
MAX_DROP_ITEMS = 256
_URL_RE = re.compile(r'https?://[^\s<>"\']+', re.IGNORECASE)
_IMG_SRC_RE = re.compile(
    r'''(?:src|data-src|data-original)\s*=\s*["'](https?://[^"']+)["']''',
    re.IGNORECASE,
)
_DATA_IMAGE_RE = re.compile(
    r'''data:image/(?:png|jpe?g|webp|gif);base64,[A-Za-z0-9+/=_-]+''',
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CanvasDropSource:
    source: str
    label: str
    kind: str  # 'file', 'url' or bounded 'data' image URI


def _file_uri_to_path(value: str) -> str | None:
    try:
        parsed = urlparse(value)
    except Exception:
        return None
    if parsed.scheme.lower() != 'file':
        return None
    path = unquote(parsed.path or '')
    # file:///C:/... -> C:/... on Windows. UNC keeps //host/share.
    if parsed.netloc and parsed.netloc.casefold() != 'localhost':
        path = f'//{parsed.netloc}{path}'
    elif len(path) >= 3 and path[0] == '/' and path[2] == ':':
        path = path[1:]
    if any(ord(char) < 32 or ord(char) == 127 for char in path):
        return None
    return path or None


def _host_is_or_subdomain(host: str, domain: str) -> bool:
    """Return True only when *host* is *domain* or a real DNS subdomain.

    Comparing hostname labels avoids substring checks such as ``'bing.com' in
    host`` which would also trust attacker-controlled hosts like
    ``bing.com.evil.example`` or ``notbing.com``.
    """
    normalized_host = str(host or '').strip().lower().rstrip('.')
    normalized_domain = str(domain or '').strip().lower().rstrip('.')
    if not normalized_host or not normalized_domain:
        return False
    return normalized_host == normalized_domain or normalized_host.endswith('.' + normalized_domain)


def _looks_like_image_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        suffix = Path(parsed.path).suffix.lower()
        host = (parsed.hostname or '').lower()
    except Exception:
        return False
    if suffix in _IMAGE_EXTENSIONS:
        return True
    # Google Images commonly supplies extensionless CDN URLs.
    return any(
        _host_is_or_subdomain(host, domain)
        for domain in ('gstatic.com', 'googleusercontent.com', 'ggpht.com')
    )


def _clean_url(value: str) -> str:
    # Strip only drag/drop wrappers. Punctuation and percent escapes can be part
    # of a signed URL and must survive normalization unchanged.
    return str(value or '').strip().strip('{}').strip('\"\'')


def _is_http_url(value: str) -> bool:
    """Validate URL structure without making a network request."""
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in value):
        return False
    try:
        parsed = urlparse(value)
        if parsed.scheme.lower() not in ('http', 'https') or not parsed.hostname:
            return False
        # Accessing port validates malformed and out-of-range port numbers.
        parsed.port
    except (ValueError, TypeError):
        return False
    return True


def _unwrap_image_search_url(url: str) -> str:
    """Unwrap common image-search redirect URLs without network access."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or '').lower()
        query = parse_qs(parsed.query)
    except Exception:
        return url

    keys = ()
    if _host_is_or_subdomain(host, 'google.com'):
        keys = ('imgurl', 'mediaurl')
    elif _host_is_or_subdomain(host, 'bing.com'):
        keys = ('mediaurl', 'imgurl')

    for key in keys:
        for value in query.get(key) or ():
            # parse_qs has already decoded this query parameter once.
            # Decoding again corrupts escaped path/query bytes in signed URLs.
            candidate = str(value).strip()
            if _is_http_url(candidate):
                return candidate
    return url


def parse_canvas_drop(raw_data: object, *, split_items=()) -> CanvasDropSource:
    """Return one safe file/HTTP image source from a TkDND payload.

    ``split_items`` should normally be ``root.tk.splitlist(event.data)`` when
    available. It is optional so the parser can also handle DND_TEXT/HTML data.
    """
    raw = str(raw_data or '')
    if len(raw) > MAX_DROP_CHARACTERS:
        raise ValueError('The dropped image payload is too large.')
    raw = raw.strip()
    items = []
    characters = len(raw)
    for index, item in enumerate(split_items or ()):
        if index >= MAX_DROP_ITEMS:
            raise ValueError('Drop at most 256 items at a time.')
        value = str(item)
        characters += len(value)
        if characters > 2 * MAX_DROP_CHARACTERS:
            raise ValueError('The dropped image payload is too large.')
        value = value.strip().strip('{}')
        if value:
            items.append(value)

    # 1) Local files and file:// URIs take priority because they need no network.
    unsupported_file = False
    for item in items + ([raw] if raw else []):
        candidate = item.strip().strip('{}').strip('"')
        file_path = _file_uri_to_path(candidate)
        if file_path:
            candidate = file_path
        try:
            path = Path(candidate)
            exists = path.is_file()
        except (OSError, ValueError):
            exists = False
        if exists:
            if path.suffix.lower() not in _IMAGE_EXTENSIONS:
                unsupported_file = True
                continue
            return CanvasDropSource(str(path), path.name, 'file')

    # 2) Chromium/Google Images may drag an in-memory thumbnail as a data URI.
    # Accept only common image MIME types and keep the encoded payload bounded;
    # load_image performs the strict decoded-size validation before Pillow sees it.
    for value in items + ([raw] if raw else []):
        for match in _DATA_IMAGE_RE.finditer(unescape(str(value))):
            if match.end() - match.start() <= 28_000_000:
                return CanvasDropSource(match.group(), 'Dropped web image', 'data')

    # 3) Prefer explicit <img src=...> or lazy-load image attributes from HTML.
    for match in _IMG_SRC_RE.finditer(raw):
        url = _clean_url(unescape(match.group(1)))
        if _is_http_url(url):
            return CanvasDropSource(_unwrap_image_search_url(url), 'Dropped web image', 'url')

    # 4) Plain text/URI-list drops. Rank likely image URLs before generic URLs.
    best_url = None
    best_rank = None
    for text in items + ([raw] if raw else []):
        direct = _clean_url(text)
        if _is_http_url(direct):
            candidates = [direct]
        else:
            candidates = (_clean_url(match.group()) for match in _URL_RE.finditer(text))
        for url in candidates:
            if _is_http_url(url):
                rank = (not _looks_like_image_url(url), len(url))
                if best_rank is None or rank < best_rank:
                    best_url, best_rank = url, rank
    if best_url is not None:
        return CanvasDropSource(_unwrap_image_search_url(best_url), 'Dropped web image', 'url')

    if unsupported_file:
        raise ValueError('Drop an image file (PNG, JPG, WEBP or BMP).')
    raise ValueError(
        'No image was found in the drop. Drag the image itself from Chrome/Edge or drop a local image file.'
    )
