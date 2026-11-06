"""Opt-in local-network mobile preview server for Image Draw Bot.

No cloud service, telemetry or external assets are used.  The server binds only
when the user explicitly starts Mobile Preview and serves a random, per-session
URL on the local network.  Images are held in memory and disappear when the
server/app stops.
"""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import ipaddress
import json
import secrets
import socket
import threading
from typing import Dict, Iterable, Optional
from urllib.parse import urlsplit


MOBILE_PREVIEW_MAX_DIMENSION = 1600
MOBILE_PREVIEW_MAX_CLIENTS = 12
MOBILE_PREVIEW_CLIENT_TIMEOUT = 5.0
MOBILE_PREVIEW_HEADER_DEADLINE = 5.0
_PRIVATE_NETWORKS = tuple(ipaddress.IPv4Network(value) for value in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))


def _is_private_ipv4(value: str) -> bool:
    try:
        address = ipaddress.IPv4Address(value)
    except (ipaddress.AddressValueError, TypeError):
        return False
    return any(address in network for network in _PRIVATE_NETWORKS)


def _is_local_client(value: str) -> bool:
    try:
        address = ipaddress.IPv4Address(value)
    except (ipaddress.AddressValueError, TypeError):
        return False
    return address.is_loopback or address.is_link_local or _is_private_ipv4(value)


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
        if isinstance(value,str) and _is_local_client(value) and not value.startswith('127.') and value not in result:
            result.append(value)
    result.sort(key=lambda ip: (not _is_private_ipv4(ip), int(ipaddress.IPv4Address(ip))))
    return result


class _PreviewHTTPServer(ThreadingHTTPServer):
    """Bound LAN connections and expire clients that stop sending/reading."""
    daemon_threads = True
    request_queue_size = MOBILE_PREVIEW_MAX_CLIENTS

    def __init__(self, *args, **kwargs):
        self._client_slots = threading.BoundedSemaphore(MOBILE_PREVIEW_MAX_CLIENTS)
        super().__init__(*args, **kwargs)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(MOBILE_PREVIEW_CLIENT_TIMEOUT)
        return connection, address

    def process_request(self, request, client_address):
        if not self._client_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._client_slots.release()
            self.shutdown_request(request)
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._client_slots.release()


def _image_png_bytes(image) -> Optional[bytes]:
    if image is None:
        return None
    from PIL import Image
    target = None
    if max(image.size) > MOBILE_PREVIEW_MAX_DIMENSION:
        ratio = MOBILE_PREVIEW_MAX_DIMENSION / float(max(image.size))
        target = (max(1, round(image.width * ratio)), max(1, round(image.height * ratio)))
    if target is not None and image.mode in ('RGB', 'L') and 'transparency' not in image.info:
        # Opaque sources do not need a full-size RGBA conversion before reduction.
        # Alpha/color-key sources retain the original premultiplied-alpha path.
        with closing(image.resize(target, Image.Resampling.LANCZOS)) as reduced:
            copy = reduced.convert('RGBA')
    else:
        copy = image.convert('RGBA')
        if target is not None:
            previous = copy
            try:
                copy = previous.resize(target, Image.Resampling.LANCZOS)
            finally:
                previous.close()
    # Flatten transparency because phone browsers can otherwise show a black
    # background depending on theme/rendering path.
    try:
        with closing(Image.new('RGBA', copy.size, 'white')) as background:
            background.alpha_composite(copy)
            with closing(background.convert('RGB')) as flattened, BytesIO() as out:
                flattened.save(out, format='PNG', optimize=True)
                return out.getvalue()
    finally:
        copy.close()


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
        self._update_sequence = 0
        self._token = ''
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._port = 0
        self._addresses: tuple[str, ...] = ()

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
            self._update_sequence += 1
            sequence = self._update_sequence
        encoded = {
            'original': _image_png_bytes(original),
            'preview': _image_png_bytes(preview),
            'safety': _image_png_bytes(safety),
        }
        with self._lock:
            # Encoding happens outside the lock. A stop must not be undone by
            # an older, slower encode completing after its session was cleared.
            if generation != self._generation or sequence != self._update_sequence:
                return self._revision
            if encoded == self._images:
                return self._revision
            self._images.update(encoded)
            self._revision += 1
            return self._revision

    def urls(self) -> list[str]:
        with self._lock:
            if not self.running:
                return []
            return [f'http://{ip}:{self.port}/{self.token}/' for ip in self._addresses]

    def state(self) -> MobilePreviewState:
        with self._lock:
            return MobilePreviewState(self.running, self.port, self.token, self._revision, tuple(self.urls()))

    def refresh_addresses(self) -> MobilePreviewState:
        """Refresh the share links when the user reopens the preview panel."""
        with self._lock:
            server, generation = self._server, self._generation
            if server is None:
                return self.state()
        addresses = tuple(local_ipv4_addresses()) or ('127.0.0.1',)
        with self._lock:
            if self._server is server and self._generation == generation:
                self._addresses = addresses
            return self.state()

    def start(self, port: int = 0) -> MobilePreviewState:
        with self._lock:
            if self.running:
                return self.state()
            generation = self._generation
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError('Mobile preview port must be an integer from 0 to 65535.')
        # DNS/interface discovery may block. Never perform it while holding the
        # lock used by image encoding, HTTP responses, state() and stop().
        addresses = tuple(local_ipv4_addresses()) or ('127.0.0.1',)
        with self._lock:
            if generation != self._generation:
                raise InterruptedError('Mobile preview start was cancelled.')
            if self.running:
                return self.state()
            return self._start(port, addresses)

    def _start(self, port: int, addresses: tuple[str, ...]) -> MobilePreviewState:
        """Create one session while holding the state lock."""
        owner = self
        session_token = secrets.token_urlsafe(12).replace('-', '').replace('_', '')

        class Handler(BaseHTTPRequestHandler):
            server_version = 'ImageDrawBotMobilePreview/1.0'
            sys_version = ''

            def setup(self):
                super().setup()
                # Socket timeouts limit inactivity, not a client continuously
                # trickling an unfinished header. Bound the whole header phase.
                self._header_timer = threading.Timer(MOBILE_PREVIEW_HEADER_DEADLINE, self._expire_headers)
                self._header_timer.daemon = True
                self._header_timer.start()

            def _expire_headers(self):
                try:
                    self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

            def parse_request(self):
                try:
                    return super().parse_request()
                finally:
                    self._header_timer.cancel()

            def finish(self):
                self._header_timer.cancel()
                try:
                    super().finish()
                except OSError:
                    pass

            def handle_one_request(self):
                try:
                    super().handle_one_request()
                except OSError:
                    self.close_connection = True

            def log_message(self, _format, *_args):
                return

            def _send(self, code: int, content_type: str, body: bytes):
                try:
                    self.send_response(code)
                    self.send_header('Content-Type', content_type)
                    self.send_header('Content-Length', str(len(body)))
                    self.send_header('Cache-Control', 'no-store, max-age=0')
                    self.send_header('X-Content-Type-Options', 'nosniff')
                    self.send_header('Referrer-Policy', 'no-referrer')
                    self.end_headers()
                    if self.command != 'HEAD':
                        self.wfile.write(body)
                except OSError:
                    self.close_connection = True

            def do_HEAD(self):
                self.do_GET()

            def do_GET(self):
                client_ip = str(self.client_address[0]) if self.client_address else ''
                if not _is_local_client(client_ip):
                    self._send(403, 'text/plain; charset=utf-8', b'Local network access only')
                    return
                try:
                    path = urlsplit(self.path).path
                except ValueError:
                    self._send(400, 'text/plain; charset=utf-8', b'Invalid request target')
                    return
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
                try:
                    self._send(*response)
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
                    # A tab closing or a slow phone must not produce a server
                    # traceback or hold the image lock/worker indefinitely.
                    self.close_connection = True

        server = _PreviewHTTPServer(('0.0.0.0', port), Handler)
        self._server = server
        self._token = session_token
        self._port = int(server.server_address[1])
        self._addresses = addresses
        try:
            self._thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .1}, name='mobile-preview', daemon=True)
            self._thread.start()
        except BaseException:
            server.server_close()
            self._server = None
            self._thread = None
            self._token = ''
            self._port = 0
            self._addresses = ()
            raise
        return self.state()

    def stop(self) -> None:
        with self._lock:
            server = self._server
            thread = self._thread
            self._server = None
            self._thread = None
            self._port = 0
            self._addresses = ()
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
const token={json.dumps(token)}; let view='preview', revision=-1, available={{}}; const img=document.getElementById('image'), empty=document.getElementById('empty'), status=document.getElementById('status');
function loadImage(){{if(available[view]!==true){{img.hidden=true;img.removeAttribute('src');empty.hidden=false;return;}}img.alt=view==='original'?'Original image':view==='safety'?'Drawing safety map':'Planned drawing preview';img.src=`/${{token}}/${{view}}.png?v=${{revision}}`; img.hidden=false; empty.hidden=true;}}
img.onerror=()=>{{revision=-1;img.hidden=true;empty.hidden=false}};
document.querySelectorAll('button[data-view]').forEach(b=>{{b.setAttribute('aria-pressed',String(b.dataset.view===view));b.onclick=()=>{{document.querySelectorAll('button[data-view]').forEach(x=>{{x.classList.remove('active');x.setAttribute('aria-pressed','false');}});b.classList.add('active');b.setAttribute('aria-pressed','true');view=b.dataset.view;loadImage();}};}});
async function poll(){{if(document.hidden){{setTimeout(poll,1000);return;}}const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),5000);try{{const r=await fetch(`/${{token}}/status.json?x=${{Date.now()}}`,{{cache:'no-store',signal:controller.signal}});if(!r.ok)throw new Error('Preview unavailable');const s=await r.json();available=s.available||{{}};status.textContent=Object.values(available).some(Boolean)?'Connected locally · live refresh':'Connected locally · waiting for preview…';if(s.revision!==revision){{revision=s.revision;loadImage();}}}}catch(e){{status.textContent='Connection lost · keep Image Draw Bot running';revision=-1;img.hidden=true;empty.hidden=false;}}finally{{clearTimeout(timer);setTimeout(poll,1000);}}}} loadImage();poll();
</script></body></html>'''
