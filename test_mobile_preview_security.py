import http.client
import json
import socket
import threading
import unittest
from unittest.mock import patch

from PIL import Image

import MobilePreview
from MobilePreview import MobilePreviewServer


class MobilePreviewSecurityTests(unittest.TestCase):
    def make_server(self):
        server = MobilePreviewServer()
        self.addCleanup(server.stop)
        return server

    def request(self, state, path):
        connection = http.client.HTTPConnection("127.0.0.1", state.port, timeout=3)
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def pending_connection(self, server):
        accepted = threading.Event()
        handler = server._server.RequestHandlerClass
        original_setup = handler.setup

        def record_setup(request):
            original_setup(request)
            accepted.set()

        with patch.object(handler, "setup", record_setup):
            connection = socket.create_connection(("127.0.0.1", server.port), timeout=3)
            self.addCleanup(connection.close)
            self.assertTrue(accepted.wait(3), "Preview server did not accept test connection")
        return connection

    def test_stop_discards_encoded_images_even_before_server_start(self):
        server = self.make_server()
        server.update_images(original=Image.new("RGB", (8, 8), "red"))
        self.assertTrue(server._images["original"])
        server.stop()
        self.assertTrue(all(data is None for data in server._images.values()))

    def test_restart_rotates_url_and_does_not_serve_previous_images(self):
        server = self.make_server()
        server.update_images(preview=Image.new("RGB", (8, 8), "red"))
        first = server.start()
        server.stop()
        second = server.start()
        self.assertNotEqual(first.token, second.token)
        code, body = self.request(second, f"/{second.token}/status.json")
        self.assertEqual(code, 200)
        self.assertFalse(any(json.loads(body)["available"].values()))
        self.assertEqual(self.request(second, f"/{first.token}/preview.png")[0], 404)
        self.assertEqual(self.request(second, f"/{second.token}/preview.png")[0], 404)

    def test_images_prepared_before_start_are_preserved_after_restart(self):
        server = self.make_server()
        for color in ("red", "blue"):
            server.update_images(preview=Image.new("RGB", (8, 8), color))
            state = server.start()
            code, body = self.request(state, f"/{state.token}/preview.png")
            self.assertEqual(code, 200)
            self.assertTrue(body.startswith(b"\x89PNG\r\n\x1a\n"))
            server.stop()

    def test_start_while_running_preserves_current_session(self):
        server = self.make_server()
        server.update_images(preview=Image.new("RGB", (8, 8), "red"))
        first = server.start()
        second = server.start()
        self.assertEqual((first.port, first.token), (second.port, second.token))
        self.assertEqual(self.request(second, f"/{first.token}/preview.png")[0], 200)

    def test_old_connections_cannot_read_new_session_using_either_token(self):
        server = self.make_server()
        first = server.start()
        connections = [self.pending_connection(server) for _ in range(2)]
        server.stop()
        server.update_images(preview=Image.new("RGB", (8, 8), "blue"))
        second = server.start()
        for connection, token in zip(connections, (first.token, second.token)):
            connection.sendall(
                f"GET /{token}/preview.png HTTP/1.0\r\nHost: localhost\r\n\r\n".encode("ascii")
            )
            response = http.client.HTTPResponse(connection)
            try:
                response.begin()
                self.assertEqual(response.status, 404)
                self.assertFalse(response.read().startswith(b"\x89PNG"))
            finally:
                response.close()

    def test_encode_in_flight_at_stop_cannot_repopulate_images(self):
        server = self.make_server()
        image = Image.new("RGB", (8, 8), "red")
        encoding = threading.Event()
        resume = threading.Event()
        original_encode = MobilePreview._image_png_bytes

        def delayed_encode(value):
            if value is image:
                encoding.set()
                if not resume.wait(3):
                    raise TimeoutError("Image encode test did not resume")
            return original_encode(value)

        with patch("MobilePreview._image_png_bytes", delayed_encode):
            worker = threading.Thread(target=lambda: server.update_images(original=image))
            worker.start()
            try:
                self.assertTrue(encoding.wait(3))
                server.stop()
            finally:
                resume.set()
                worker.join(timeout=3)
            self.assertFalse(worker.is_alive())
        self.assertTrue(all(data is None for data in server._images.values()))


if __name__ == "__main__":
    unittest.main()
