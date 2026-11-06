"""Parse drag/drop payloads for direct game-canvas image drops.

Browser drags are not identical to File Explorer drags. Depending on Chrome,
Edge, Windows and TkDND, Image Draw Bot may receive a local file path, a file://
URI, plain URL text or a small HTML fragment containing an image URL. This
module normalizes those forms without performing network access.
"""
from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import parse_qs, unquote, urlparse

IMAGE_FILE_PATTERNS = '*.png *.apng *.jpg *.jpeg *.jpe *.jfif *.webp *.bmp *.gif *.tif *.tiff *.ico'
_IMAGE_EXTENSIONS = frozenset(pattern[1:] for pattern in IMAGE_FILE_PATTERNS.split())
MAX_DROP_CHARACTERS = 32_000_000
MAX_DROP_ITEMS = 256
_URL_RE = re.compile(r'https?://[^\s<>"\']+', re.IGNORECASE)
_DATA_IMAGE_RE = re.compile(
    r'''(?i:data:image/(?:png|jpe?g|webp|gif);base64,)[A-Za-z0-9+/=_-]+''',
    re.ASCII,
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
    return _unwrap_item(str(value or ''))


def _unwrap_item(value: str) -> str:
    value = value.strip()
    for opening, closing in (('{', '}'), ('"', '"'), ("'", "'")):
        if len(value) >= 2 and value.startswith(opening) and value.endswith(closing):
            return value[1:-1].strip()
    return value


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
    except Exception:
        return url

    keys = ()
    if _host_is_or_subdomain(host, 'google.com'):
        keys = ('imgurl', 'mediaurl')
    elif _host_is_or_subdomain(host, 'bing.com'):
        keys = ('mediaurl', 'imgurl')
    if not keys:
        return url
    query = parse_qs(parsed.query)

    for key in keys:
        for value in query.get(key) or ():
            # parse_qs has already decoded this query parameter once.
            # Decoding again corrupts escaped path/query bytes in signed URLs.
            candidate = str(value).strip()
            if _is_http_url(candidate):
                return candidate
    return url


def _data_source(value: str) -> CanvasDropSource | None:
    if len(value) <= 28_000_000:
        match = _DATA_IMAGE_RE.fullmatch(value)
        if match is not None:
            return _matched_data_source(match)
    return None


def _matched_data_source(match) -> CanvasDropSource | None:
    end = match.end()
    # Do not turn an invalid encoded token into a valid image by returning
    # only the regex prefix. Quotes/whitespace delimit an embedded URI.
    boundary = end == len(match.string) or match.string[end].isspace() or match.string[end] in "\"'<>"
    if boundary and end-match.start() <= 28_000_000:
        return CanvasDropSource(match.group(), 'Dropped web image', 'data')
    return None


def _is_html(value: str) -> bool:
    return ('<' in value and '>' in value and
            not value[:16].lower().startswith(('http://', 'https://', 'data:image/')))


class _FoundImage(Exception):
    """Stop parsing once the first usable image element is found."""


class _ImageHTMLParser(HTMLParser):
    """Read image attributes and visible links without building a DOM."""

    _INERT = frozenset(('script', 'style', 'template', 'noscript', 'head'))
    _IMAGE_ATTRIBUTES = frozenset(('src', 'data-src', 'data-original'))

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.inert = []
        self.image = None
        self.inline = None
        self.link = None
        self.link_rank = None

    def _consider_link(self, value):
        value = _clean_url(value)
        if _is_http_url(value):
            rank = (not _looks_like_image_url(value), len(value))
            if self.link_rank is None or rank < self.link_rank:
                self.link, self.link_rank = value, rank

    def handle_starttag(self, tag, attrs):
        if tag in self._INERT:
            if len(self.inert) >= 256:
                raise ValueError('The dropped HTML is nested too deeply.')
            self.inert.append(tag)
        if self.inert:
            return
        seen = set()
        for name, value in attrs:
            # HTML uses the first occurrence of a duplicated attribute.
            if name in seen:
                continue
            seen.add(name)
            if not isinstance(value, str):
                continue
            if tag == 'img' and name in self._IMAGE_ATTRIBUTES:
                value = _clean_url(value)
                source = _data_source(value)
                if source is None and _is_http_url(value):
                    source = CanvasDropSource(_unwrap_image_search_url(value), 'Dropped web image', 'url')
                if source is not None:
                    self.image = source
                    raise _FoundImage()
            elif tag == 'a' and name == 'href':
                self._consider_link(value)

    def handle_endtag(self, tag):
        if self.inert and self.inert[-1] == tag:
            self.inert.pop()

    def handle_data(self, data):
        if self.inert:
            return
        if self.inline is None:
            for match in _DATA_IMAGE_RE.finditer(data):
                self.inline = _matched_data_source(match)
                if self.inline is not None:
                    break
        for match in _URL_RE.finditer(data):
            self._consider_link(match.group())


def _html_source(value: str) -> CanvasDropSource | None:
    parser = _ImageHTMLParser()
    try:
        parser.feed(value)
        parser.close()
    except _FoundImage:
        pass
    if parser.image is not None:
        return parser.image
    if parser.inline is not None:
        return parser.inline
    if parser.link is not None:
        return CanvasDropSource(_unwrap_image_search_url(parser.link), 'Dropped web image', 'url')
    return None


def _uri_list(value: str) -> tuple[str, ...] | None:
    """Recognize URI-list lines without interpreting comment URLs as images."""
    if '\n' not in value and '\r' not in value:
        return None
    values = []
    for match in re.finditer(r'[^\r\n]+', value):
        line = match.group().strip()
        if not line or line.startswith('#'):
            continue
        if not (_is_http_url(line) or line[:7].lower() == 'file://'):
            return None
        if len(values) >= MAX_DROP_ITEMS:
            raise ValueError('Drop at most 256 items at a time.')
        values.append(line)
    return tuple(values)


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
        value = value.strip()
        if value:
            items.append(value)

    # Tcl's splitlist is not an HTML parser. Its fragments can contain URLs
    # from comments or scripts, so the complete HTML payload is authoritative.
    if _is_html(raw):
        source = _html_source(raw)
        if source is not None:
            return source
        raise ValueError('No image was found in the dropped HTML.')
    lines = _uri_list(raw)
    values = list(lines) if lines is not None else items + ([raw] if raw else [])

    # 1) Local files and file:// URIs take priority because they need no network.
    unsupported_file = False
    for item in values:
        candidate = _unwrap_item(item)
        # A multi-megabyte inline image is not a filesystem path. Besides
        # avoiding an irrelevant stat, this avoids Path splitting its base64
        # slashes into thousands of temporary path components.
        if candidate[:16].lower().startswith(('http://', 'https://', 'data:image/')) or _is_html(candidate):
            continue
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
    for value in values:
        if _is_html(value):
            source = _html_source(value)
            if source is not None:
                return source
            continue
        for match in _DATA_IMAGE_RE.finditer(value):
            source = _matched_data_source(match)
            if source is not None:
                return source

    # 4) Plain text/URI-list drops. Rank likely image URLs before generic URLs.
    best_url = None
    best_rank = None
    for text in values:
        if _is_html(text):
            continue
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
        raise ValueError('Drop an image file (PNG, JPG, WEBP, BMP, GIF, TIFF, ICO or APNG).')
    raise ValueError(
        'No image was found in the drop. Drag the image itself from Chrome/Edge or drop a local image file.'
    )
