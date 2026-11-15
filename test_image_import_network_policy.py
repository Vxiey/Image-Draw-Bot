import socket
import time
import unittest
from unittest.mock import patch

import requests
from urllib3.connection import HTTPSConnection

import ImageImport as imports
from CanvasDropPayload import parse_canvas_drop


class ImageImportNetworkPolicy(unittest.TestCase):
    def test_rejects_unsupported_web_form_before_opening_transport(self):
        with patch.object(requests.Session, 'get') as get:
            for url in ('http://images.invalid/image.png', 'https://user@images.invalid/image.png'):
                with self.subTest(url=url), self.assertRaisesRegex(ValueError, 'public HTTPS'):
                    imports.read_image(url)
            get.assert_not_called()

    def test_remote_share_never_reaches_filesystem(self):
        with patch('pathlib.Path.is_file') as stat:
            with self.assertRaisesRegex(ValueError, 'network shares'):
                imports.read_image('//files.invalid/share/image.png')
            for value in ('//files.invalid/share/image.png', 'file://files.invalid/share/image.png'):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    parse_canvas_drop(value)
            stat.assert_not_called()

    def test_only_checked_public_address_is_passed_to_connection(self):
        def record(value):
            return (socket.AF_INET, socket.SOCK_STREAM, 0, '', (value, 443))

        with requests.Session() as session:
            imports._mount_public_image_adapter(session, cancelled=lambda: False, deadline=time.monotonic() + 20)
            pool = session.get_adapter('https://').poolmanager.connection_from_url('https://images.invalid')
            connection = pool.ConnectionCls('images.invalid', 443, timeout=5)
            with patch('ImageImport.socket.getaddrinfo', return_value=[record('127.0.0.1')]), \
                    patch.object(HTTPSConnection, '_new_conn') as connect:
                with self.assertRaisesRegex(ValueError, 'public HTTPS'):
                    connection._new_conn()
                connect.assert_not_called()
            with patch('ImageImport.socket.getaddrinfo', return_value=[record('127.0.0.1'), record('8.8.8.8')]), \
                    patch.object(HTTPSConnection, '_new_conn') as connect:
                connect.side_effect = lambda: connection.host
                self.assertEqual(connection._new_conn(), '8.8.8.8')
                self.assertEqual(connection.host, 'images.invalid')

    def test_preserves_fully_qualified_dns_name(self):
        with requests.Session() as session:
            imports._mount_public_image_adapter(session, cancelled=lambda: False, deadline=time.monotonic() + 20)
            pool = session.get_adapter('https://').poolmanager.connection_from_url('https://images.invalid.')
            connection = pool.ConnectionCls('images.invalid.', 443, timeout=5)
            with patch('ImageImport.socket.getaddrinfo', return_value=[]) as resolver:
                with self.assertRaisesRegex(ValueError, 'public HTTPS'):
                    connection._new_conn()
                resolver.assert_called_once_with('images.invalid.', 443, type=socket.SOCK_STREAM)
