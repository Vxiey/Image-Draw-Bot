"""Actual Requests/urllib3 responses cannot hide wire work in a decoder loop."""
from contextlib import closing, contextmanager
import gzip
from io import BytesIO
import threading
import unittest
from unittest.mock import patch

from PIL import Image
import requests
from requests.adapters import BaseAdapter
from requests.structures import CaseInsensitiveDict
from urllib3.response import HTTPResponse

import ImageImport as imports


class Wire(BytesIO):
    def __init__(self, body, on_read=None):
        super().__init__(body)
        self.consumed = 0
        self.on_read = on_read

    def read1(self, size=-1):
        data = super().read1(min(size, 4096))
        self.consumed += len(data)
        if self.on_read is not None:
            self.on_read(self.consumed)
        return data


class RealRawAdapter(BaseAdapter):
    def __init__(self, route, on_read=None):
        self.route, self.on_read = route, on_read
        self.requests, self.responses, self.wires = [], [], []

    def send(self, request, **options):
        self.requests.append(request)
        status, headers, body = self.route(len(self.requests)-1)
        wire = Wire(body, self.on_read)
        response = requests.Response()
        response.status_code, response.headers = status, CaseInsensitiveDict(headers)
        response.url, response.request = request.url, request
        response.raw = HTTPResponse(body=wire, headers=dict(headers), preload_content=False,
                                    decode_content=False)
        self.wires.append(wire); self.responses.append(response)
        return response

    def close(self):
        pass


class IdentityTransferTests(unittest.TestCase):
    def setUp(self):
        with closing(Image.new('RGB',(2,2),'red')) as image, BytesIO() as output:
            image.save(output,format='PNG')
            self.png = output.getvalue()

    @contextmanager
    def transport(self, adapter):
        initialize = requests.Session.__init__
        def mount(session):
            initialize(session)
            session.mount('https://', adapter)
        with patch.object(requests.Session,'__init__',mount):
            yield

    def test_many_empty_gzip_members_are_rejected_without_consuming_any_wire_body(self):
        # A modest legal multi-member gzip body: previously read1 consumed all
        # 160 KiB internally before yielding the final small PNG to Stop checks.
        body = gzip.compress(b'',mtime=0)*8000 + gzip.compress(self.png,mtime=0)
        stopped = threading.Event()
        adapter = RealRawAdapter(lambda _: (200,{'Content-Type':'image/png','Content-Encoding':'gzip'},body),
                                 on_read=lambda total: stopped.set() if total >= 4096 else None)
        with self.transport(adapter), self.assertRaisesRegex(ValueError,'Save the image locally'):
            imports.read_image('https://images.invalid/image.png',stopped.is_set,max_download_bytes=65536)
        self.assertEqual(adapter.requests[0].headers['Accept-Encoding'],'identity')
        self.assertEqual(adapter.wires[0].consumed,0)
        self.assertTrue(adapter.wires[0].closed)

    def test_every_unrequested_encoding_fails_before_body_read(self):
        for encoding in ('gzip','deflate','br','zstd','gzip, deflate'):
            with self.subTest(encoding=encoding):
                adapter = RealRawAdapter(lambda _: (200,{'Content-Type':'image/png',
                    'Content-Encoding':encoding},gzip.compress(self.png)))
                with self.transport(adapter), self.assertRaisesRegex(ValueError,'compressed download'):
                    imports.read_image('https://images.invalid/image.png')
                self.assertEqual(adapter.wires[0].consumed,0)
                self.assertTrue(adapter.wires[0].closed)

    def test_identity_png_survives_relative_redirect_with_unread_compressed_intermediate_body(self):
        def route(index):
            return ((302,{'Location':'/final','Content-Encoding':'gzip'},gzip.compress(b'not the image'))
                    if index == 0 else (200,{'Content-Type':'image/png','Content-Length':str(len(self.png)),
                                            'Content-Encoding':' Identity\t'},self.png))
        adapter = RealRawAdapter(route)
        with self.transport(adapter), closing(imports.read_image('https://images.invalid/start')) as image:
            self.assertEqual(image.size,(2,2))
            self.assertEqual(image.getpixel((0,0)),(255,0,0,255))
        self.assertEqual(adapter.wires[0].consumed,0)
        self.assertEqual(adapter.wires[1].consumed,len(self.png))
        self.assertEqual(adapter.requests[1].url,'https://images.invalid/final')
        self.assertTrue(all(request.headers['Accept-Encoding']=='identity' for request in adapter.requests))
        self.assertTrue(all(wire.closed for wire in adapter.wires))

    def test_available_identity_wire_data_returns_to_stop_and_elapsed_checks(self):
        body = self.png + b'\0'*(160*1024)
        for kind in ('stop','deadline'):
            stopped = threading.Event(); clock = [100.0]
            def read(total):
                if total >= 4096:
                    if kind == 'stop': stopped.set()
                    else: clock[0] += imports._DOWNLOAD_SECONDS + 1
            adapter = RealRawAdapter(lambda _: (200,{'Content-Type':'image/png'},body),on_read=read)
            expected = InterruptedError if kind == 'stop' else ValueError
            with self.subTest(kind=kind), self.transport(adapter), \
                    patch.object(imports.time,'monotonic',side_effect=lambda:clock[0]), \
                    self.assertRaises(expected):
                imports.read_image('https://images.invalid/image.png',stopped.is_set,max_download_bytes=200*1024)
            self.assertEqual(adapter.wires[0].consumed,4096)
            self.assertTrue(adapter.wires[0].closed)


if __name__ == '__main__':
    unittest.main()
