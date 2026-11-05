"""Opt-in local-network mobile preview server for Image Draw Bot.

No cloud service, telemetry or external assets are used.  The server binds only
when the user explicitly starts Mobile Preview and serves a random, per-session
URL on the local network.  Images are held in memory and disappear when the
server/app stops.
"""
from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import secrets
import socket
import threading
from typing import Dict, Iterable, Optional
from urllib.parse import urlsplit


MOBILE_PREVIEW_MAX_DIMENSION = 1600


def _is_private_ipv4(value: str) -> bool:
    try:
        parts = [int(p) for p in value.split('.')]
    except (TypeError, ValueError):
        return False
    if len(parts) != 4 or any(p < 0 or p > 255 for p in parts):
        return False
    return (
        parts[0] == 10
        or (parts[0] == 172 and 16 <= parts[1] <= 31)
        or (parts[0] == 192 and parts[1] == 168)
    )


def local_ipv4_addresses() -> list[str]:
    """Return useful LAN IPv4 addresses without making an HTTP/network request."""
    found: list[str] = []
    try:
        _host, _aliases, values = socket.gethostbyname_ex(socket.gethostname())
        found.extend(values)
    except OSError:
        pass
    # A UDP connect chooses the machine's routed interface but sends no packet.
    # It remains local-only discovery and works even when the destination is not
    # actually reachable.
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(('8.8.8.8', 80))
            found.append(probe.getsockname()[0])
        finally:
            probe.close()
    except OSError:
        pass
    result: list[str] = []
    for value in found:
        if value and value != '0.0.0.0' and not value.startswith('127.') and value not in result:
            result.append(value)
    result.sort(key=lambda ip: (not _is_private_ipv4(ip), ip))
    return result


def _image_png_bytes(image) -> Optional[bytes]:
    if image is None:
        return None
    copy = image.convert('RGBA')
    if max(copy.size) > MOBILE_PREVIEW_MAX_DIMENSION:
        ratio = MOBILE_PREVIEW_MAX_DIMENSION / float(max(copy.size))
        target = (max(1, round(copy.width * ratio)), max(1, round(copy.height * ratio)))
        from PIL import Image
        copy = copy.resize(target, Image.Resampling.LANCZOS)
    # Flatten transparency because phone browsers can otherwise show a black
    # background depending on theme/rendering path.
    from PIL import Image
    background = Image.new('RGBA', copy.size, 'white')
    background.alpha_composite(copy)
    out = BytesIO()
    background.convert('RGB').save(out, format='PNG', optimize=True)
    return out.getvalue()


@dataclass(frozen=True)
class MobilePreviewState:
    running: bool
    port: int
    token: str
    revision: int
    urls: tuple[str, ...]


class MobilePreviewServer:
    """Small local HTTP server with in-memory Image Draw Bot preview images."""

    def __init__(self):
        self._lock = threading.RLock()
        self._images: Dict[str, Optional[bytes]] = {'original': None, 'preview': None, 'safety': None}
        self._revision = 0
        self._generation = 0
        self._token = ''
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._port = 0

    @property
    def running(self) -> bool:
        return self._server is not None

    @property
    def token(self) -> str:
        return self._token

    @property
    def port(self) -> int:
        return int(self._port)

    def update_images(self, *, original=None, preview=None, safety=None) -> int:
        with self._lock:
            generation = self._generation
        encoded = {
            'original': _image_png_bytes(original),
            'preview': _image_png_bytes(preview),
            'safety': _image_png_bytes(safety),
        }
        with self._lock:
            # Encoding happens outside the lock. A stop must not be undone by
            # an older, slower encode completing after its session was cleared.
            if generation != self._generation:
                return self._revision
            self._images.update(encoded)
            self._revision += 1
            return self._revision

    def urls(self) -> list[str]:
        if not self.running:
            return []
        addresses = local_ipv4_addresses()
        if not addresses:
            addresses = ['127.0.0.1']
        return [f'http://{ip}:{self.port}/{self.token}/' for ip in addresses]

    def state(self) -> MobilePreviewState:
        with self._lock:
            return MobilePreviewState(self.running, self.port, self.token, self._revision, tuple(self.urls()))

    def start(self, port: int = 0) -> MobilePreviewState:
        with self._lock:
            if self.running:
                return self.state()
            return self._start(port)

    def _start(self, port: int) -> MobilePreviewState:
        """Create one session while holding the state lock."""
        owner = self
        session_token = secrets.token_urlsafe(12).replace('-', '').replace('_', '')

        class Handler(BaseHTTPRequestHandler):
            server_version = 'ImageDrawBotMobilePreview/1.0'
            sys_version = ''

            def log_message(self, _format, *_args):
                return

            def _send(self, code: int, content_type: str, body: bytes):
                self.send_response(code)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store, max-age=0')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.end_headers()
                if self.command != 'HEAD':
                    self.wfile.write(body)

            def do_HEAD(self):
                self.do_GET()

            def do_GET(self):
                client_ip = str(self.client_address[0]) if self.client_address else ''
                if not (client_ip.startswith('127.') or _is_private_ipv4(client_ip) or client_ip.startswith('169.254.')):
                    self._send(403, 'text/plain; charset=utf-8', b'Local network access only')
                    return
                path = urlsplit(self.path).path
                prefix = f'/{session_token}/'
                if not path.startswith(prefix):
                    self._send(404, 'text/plain; charset=utf-8', b'Not found')
                    return
                rest = path[len(prefix):] or 'index.html'
                with owner._lock:
                    # Accepted connections can outlive shutdown. Bind both
                    # authorization and data access to this exact server session.
                    if owner._server is not self.server or owner._token != session_token:
                        response = (404, 'text/plain; charset=utf-8', b'Not found')
                    elif rest in ('', 'index.html'):
                        response = (200, 'text/html; charset=utf-8', owner._html(session_token).encode('utf-8'))
                    elif rest == 'status.json':
                        payload = {
                            'revision': owner._revision,
                            'available': {name: data is not None for name, data in owner._images.items()},
                        }
                        response = (200, 'application/json; charset=utf-8', json.dumps(payload).encode('utf-8'))
                    elif rest.endswith('.png'):
                        data = owner._images.get(rest[:-4])
                        if data is None:
                            response = (404, 'text/plain; charset=utf-8', b'Preview not available yet')
                        else:
                            response = (200, 'image/png', data)
                    else:
                        response = (404, 'text/plain; charset=utf-8', b'Not found')
                # Never hold the state lock while writing to a slow client.
                self._send(*response)

        server = ThreadingHTTPServer(('0.0.0.0', int(port)), Handler)
        server.daemon_threads = True
        self._server = server
        self._token = session_token
        self._port = int(server.server_address[1])
        self._thread = threading.Thread(target=server.serve_forever, name='mobile-preview', daemon=True)
        self._thread.start()
        return self.state()

    def stop(self) -> None:
        with self._lock:
            server = self._server
            thread = self._thread
            self._server = None
            self._thread = None
            self._port = 0
            self._token = ''
            self._generation += 1
            self._images = {name: None for name in self._images}
            self._revision = 0
        if server is not None:
            try:
                server.shutdown()
            finally:
                server.server_close()
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.5)

    def _html(self, token: str | None = None) -> str:
        token = self.token if token is None else token
        return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="dark"><title>Image Draw Bot Mobile Preview</title>
<style>
:root{{--bg:#0d1117;--panel:#171d27;--line:#293445;--text:#eff5ff;--muted:#9eacc1;--accent:#98edce}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,Segoe UI,sans-serif}}
header{{position:sticky;top:0;z-index:3;padding:14px 16px;background:rgba(13,17,23,.94);backdrop-filter:blur(12px);border-bottom:1px solid var(--line)}}
h1{{font-size:18px;margin:0}} .sub{{color:var(--muted);font-size:12px;margin-top:3px}}
.tabs{{display:flex;gap:8px;padding:12px 14px 0;overflow:auto}} button{{border:1px solid var(--line);background:var(--panel);color:var(--text);padding:10px 13px;border-radius:12px;font-weight:650;white-space:nowrap}}
button.active{{background:#254b40;border-color:#3c7766;color:#dffcf2}}
main{{padding:12px 14px 24px}} .viewer{{min-height:65vh;display:grid;place-items:center;background:var(--panel);border:1px solid var(--line);border-radius:16px;overflow:hidden;padding:8px}}
img{{display:block;max-width:100%;max-height:78vh;object-fit:contain;border-radius:9px;background:white}} .empty{{color:var(--muted);text-align:center;padding:28px}}
footer{{padding:0 16px 24px;color:var(--muted);font-size:11px;line-height:1.5}}
</style></head><body>
<header><h1>Image Draw Bot · Mobile Preview</h1><div class="sub" id="status">Connected locally · waiting for preview…</div></header>
<div class="tabs"><button data-view="preview" class="active">Drawing preview</button><button data-view="original">Original</button><button data-view="safety">Safety map</button></div>
<main><div class="viewer"><img id="image" alt="Image Draw Bot preview"><div class="empty" id="empty" hidden>Preview not available yet. Build a preview in Image Draw Bot.</div></div></main>
<footer>Local-network preview only. This page contains no cloud scripts, analytics or telemetry. Keep the PC and phone on the same Wi-Fi/LAN.</footer>
<script>
const token={json.dumps(token)}; let view='preview', revision=-1; const img=document.getElementById('image'), empty=document.getElementById('empty'), status=document.getElementById('status');
function loadImage(){{img.src=`/${{token}}/${{view}}.png?v=${{revision}}`; img.hidden=false; empty.hidden=true;}}
img.onerror=()=>{{img.hidden=true;empty.hidden=false}};
document.querySelectorAll('button[data-view]').forEach(b=>b.onclick=()=>{{document.querySelectorAll('button').forEach(x=>x.classList.remove('active'));b.classList.add('active');view=b.dataset.view;loadImage();}});
async function poll(){{try{{const r=await fetch(`/${{token}}/status.json?x=${{Date.now()}}`,{{cache:'no-store'}});const s=await r.json();status.textContent='Connected locally · live refresh';if(s.revision!==revision){{revision=s.revision;loadImage();}}}}catch(e){{status.textContent='Connection lost · keep Image Draw Bot running';}}setTimeout(poll,1000)}} poll();
</script></body></html>'''
