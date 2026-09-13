import json
import unittest
from urllib.request import urlopen
from PIL import Image
from MobilePreview import MobilePreviewServer, _is_private_ipv4
from Version import APP_VERSION, FILE_VERSION


class MobilePreviewTests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc2')
        self.assertEqual(FILE_VERSION,'1.0.146')

    def test_private_ipv4(self):
        self.assertTrue(_is_private_ipv4('192.168.1.20'))
        self.assertTrue(_is_private_ipv4('10.0.0.2'))
        self.assertTrue(_is_private_ipv4('172.20.4.8'))
        self.assertFalse(_is_private_ipv4('8.8.8.8'))

    def test_server_is_opt_in_and_token_scoped(self):
        server=MobilePreviewServer()
        self.assertFalse(server.running)
        server.update_images(original=Image.new('RGB',(20,10),'red'),preview=Image.new('RGB',(20,10),'blue'))
        try:
            state=server.start()
            self.assertTrue(state.running)
            base=f'http://127.0.0.1:{state.port}/{state.token}/'
            html=urlopen(base,timeout=3).read().decode('utf-8')
            self.assertIn('Mobile Preview',html)
            status=json.loads(urlopen(base+'status.json',timeout=3).read().decode('utf-8'))
            self.assertTrue(status['available']['preview'])
            self.assertGreater(len(urlopen(base+'preview.png',timeout=3).read()),50)
        finally:
            server.stop()
        self.assertFalse(server.running)

    def test_source_has_no_cloud_assets(self):
        server=MobilePreviewServer()
        html=server._html()
        self.assertNotIn('https://',html)
        self.assertNotIn('<script src=',html)
        self.assertIn('no cloud scripts',html)


if __name__=='__main__': unittest.main()
