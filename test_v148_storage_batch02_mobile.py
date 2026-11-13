from io import BytesIO
import socket
import time
import unittest
from unittest.mock import Mock, patch

from PIL import Image

import MobilePreview as mobile


def original_png(image):
    copy = image.convert('RGBA')
    if max(copy.size) > mobile.MOBILE_PREVIEW_MAX_DIMENSION:
        ratio = mobile.MOBILE_PREVIEW_MAX_DIMENSION / max(copy.size)
        copy = copy.resize((max(1, round(copy.width * ratio)), max(1, round(copy.height * ratio))),
                           Image.Resampling.LANCZOS)
    background = Image.new('RGBA', copy.size, 'white')
    background.alpha_composite(copy)
    output = BytesIO()
    background.convert('RGB').save(output, format='PNG', optimize=True)
    return output.getvalue()


class StorageMobileBatch02Tests(unittest.TestCase):
    def test_thread_construction_failure_releases_listener_and_session_state(self):
        owner = mobile.MobilePreviewServer()
        native = Mock(server_address=('127.0.0.1', 34567))
        with patch.object(mobile, '_PreviewHTTPServer', return_value=native), \
             patch.object(mobile, 'local_ipv4_addresses', return_value=['127.0.0.1']), \
             patch.object(mobile.threading, 'Thread', side_effect=RuntimeError('no thread resources')):
            with self.assertRaises(RuntimeError):
                owner.start()
        self.assertFalse(owner.running)
        self.assertEqual(owner.port, 0)
        self.assertEqual(owner.token, '')
        native.server_close.assert_called_once()
        owner.stop()
        native.shutdown.assert_not_called()

    def test_opaque_previews_resize_before_rgba_conversion_and_preserve_exact_png(self):
        with patch.object(mobile, 'MOBILE_PREVIEW_MAX_DIMENSION', 40):
            for mode in ('RGB', 'L', 'RGBA'):
                image = Image.effect_noise((160, 100), 75).convert(mode)
                if mode == 'RGBA':
                    image.putalpha(Image.linear_gradient('L').resize(image.size))
                expected = original_png(image)
                self.assertEqual(mobile._image_png_bytes(image), expected)
                self.assertEqual(image.size, (160, 100))
            image = Image.new('RGB', (160, 100), 'red')
            image.info['transparency'] = (255, 0, 0)
            self.assertEqual(mobile._image_png_bytes(image), original_png(image))
            opaque = Image.new('RGB', (160, 100), 'red')
            original_convert = Image.Image.convert
            converted_sizes = []
            def record_convert(source, *args, **kwargs):
                converted_sizes.append(source.size)
                return original_convert(source, *args, **kwargs)
            with patch.object(Image.Image, 'convert', record_convert):
                mobile._image_png_bytes(opaque)
            self.assertNotIn((160, 100), converted_sizes)

    def start_server(self):
        owner = mobile.MobilePreviewServer()
        with patch.object(mobile, 'local_ipv4_addresses', return_value=['127.0.0.1']):
            owner.start()
        self.addCleanup(owner.stop)
        return owner

    def test_encoding_and_alpha_resize_failures_close_owned_pixel_buffers(self):
        original_resize = Image.Image.resize
        original_convert = Image.Image.convert
        original_new = Image.new
        for mode, failure in (('RGB', 'encode'), ('RGBA', 'resize'), ('RGBA', 'encode')):
            with self.subTest(mode=mode, failure=failure):
                source = Image.new(mode, (1700, 20), 'white')
                owned = []
                def resize(image, *args, **kwargs):
                    if failure == 'resize':
                        raise OSError('injected resize failure')
                    result = original_resize(image, *args, **kwargs)
                    if image is source:
                        owned.append(result)
                    return result
                def convert(image, *args, **kwargs):
                    result = original_convert(image, *args, **kwargs)
                    # Pillow may allocate its own premultiplied-alpha temporaries
                    # inside resize; only track buffers returned to our caller.
                    if (image is source and mode != 'RGBA') or any(image is value for value in owned):
                        owned.append(result)
                    return result
                def new(*args, **kwargs):
                    result = original_new(*args, **kwargs)
                    owned.append(result)
                    return result
                try:
                    with patch.object(Image.Image, 'resize', resize), \
                         patch.object(Image.Image, 'convert', convert), \
                         patch.object(Image, 'new', new), \
                         patch.object(Image.Image, 'save', side_effect=OSError('injected encoding failure')):
                        with self.assertRaises(OSError):
                            mobile._image_png_bytes(source)
                    if failure == 'resize':
                        # RGBA now borrows the source until resize succeeds.
                        # A failed resize must allocate no private full-size copy.
                        self.assertEqual(owned, [])
                    else:
                        self.assertGreaterEqual(len(owned), 4 if mode == 'RGB' else 3)
                    for value in owned:
                        with self.assertRaises(ValueError):
                            value.getpixel((0, 0))
                    self.assertIsNotNone(source.getpixel((0, 0)))
                finally:
                    for value in owned:
                        value.close()
                    source.close()

    def test_malformed_absolute_request_target_gets_controlled_bad_request(self):
        owner = self.start_server()
        with socket.create_connection(('127.0.0.1', owner.port), timeout=2) as client:
            client.sendall(b'GET http://[broken/ HTTP/1.0\r\n\r\n')
            response = client.recv(2048)
        self.assertIn(b' 400 ', response)
        self.assertTrue(owner.running)

    def test_header_trickle_cannot_hold_a_client_slot_indefinitely(self):
        # A total deadline remains effective even when each byte arrives well
        # inside the normal socket inactivity timeout.
        owner = self.start_server()
        with patch.object(mobile, 'MOBILE_PREVIEW_HEADER_DEADLINE', .20):
            with socket.create_connection(('127.0.0.1', owner.port), timeout=2) as client:
                client.sendall(b'GET / HTTP/1.0\r\nX-Long: ')
                started = time.monotonic()
                closed = False
                while time.monotonic() - started < 1.5:
                    try:
                        client.sendall(b'x')
                        client.settimeout(.03)
                        if client.recv(1024) == b'':
                            closed = True
                            break
                    except socket.timeout:
                        continue
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        closed = True
                        break
                self.assertTrue(closed, 'trickling headers outlived their absolute deadline')
                self.assertLess(time.monotonic() - started, 1.0)
        with socket.create_connection(('127.0.0.1', owner.port), timeout=2) as client:
            client.sendall(f'GET /{owner.token}/status.json HTTP/1.0\r\n\r\n'.encode())
            self.assertIn(b' 200 ', client.recv(2048))


if __name__ == '__main__':
    unittest.main()
