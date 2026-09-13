import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from CanvasDropPayload import parse_canvas_drop
from DrawBot import DrawBotApp
from SmartDropInCanvas import canvas_overlay_geometry
from Version import APP_VERSION, FILE_VERSION


class Value:
    def __init__(self,value=''):self.value=value
    def get(self):return self.value
    def set(self,value):self.value=value

class Root:
    def __init__(self):self.calls=[]
    def after(self,delay,callback):self.calls.append((delay,callback));return 'after-id'

class CanvasWebDropV10121Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc1')
        self.assertEqual(FILE_VERSION,'1.0.146')

    def test_local_file_drop(self):
        with tempfile.NamedTemporaryFile(suffix='.png') as handle:
            result=parse_canvas_drop(handle.name, split_items=(handle.name,))
            self.assertEqual(result.kind,'file')
            self.assertEqual(Path(result.source).name,Path(handle.name).name)

    def test_direct_google_cdn_url_drop(self):
        url='https://encrypted-tbn0.gstatic.com/images?q=tbn:abc123'
        result=parse_canvas_drop(url, split_items=(url,))
        self.assertEqual(result.kind,'url')
        self.assertEqual(result.source,url)

    def test_html_image_drag_prefers_img_src(self):
        html='<a href="https://example.com/page"><img data-src="https://images.example.com/photo.webp"></a>'
        result=parse_canvas_drop(html)
        self.assertEqual(result.source,'https://images.example.com/photo.webp')

    def test_google_imgres_url_is_unwrapped_without_network(self):
        raw='https://www.google.com/imgres?imgurl=https%3A%2F%2Fcdn.example.com%2Fcat.jpg&imgrefurl=https%3A%2F%2Fexample.com'
        result=parse_canvas_drop(raw)
        self.assertEqual(result.source,'https://cdn.example.com/cat.jpg')

    def test_plain_text_with_page_and_image_prefers_image(self):
        raw='https://example.com/page https://cdn.example.com/picture.jpg'
        result=parse_canvas_drop(raw)
        self.assertEqual(result.source,'https://cdn.example.com/picture.jpg')

    def test_rejects_non_image_local_file(self):
        with tempfile.NamedTemporaryFile(suffix='.txt') as handle:
            with self.assertRaisesRegex(ValueError,'image file'):
                parse_canvas_drop(handle.name, split_items=(handle.name,))

    def test_canvas_only_overlay_geometry(self):
        self.assertEqual(canvas_overlay_geometry((496,312,1446,842)),'950x530+496+312')
        self.assertEqual(canvas_overlay_geometry((-1200,-10,-200,590)),'1000x600-1200-10')


    def test_game_canvas_drop_can_force_one_click_for_one_image(self):
        app=SimpleNamespace(
            original=object(),game=Value('Gartic Phone'),browser_one_click_enabled=Value(False),
            browser_one_click_force=False,browser_one_click_pending=False,browser_one_click_source_label='',
            browser_one_click_text=Value(),browser_one_click_after=None,root=Root(),
            _run_browser_one_click=lambda:None,
        )
        with mock.patch.object(DrawBotApp,'_browser_one_click_supported',return_value=True), \
             mock.patch.object(DrawBotApp,'_browser_one_click_active',return_value=False), \
             mock.patch.object(DrawBotApp,'_cancel_after_attr',return_value=False):
            self.assertTrue(DrawBotApp._queue_browser_one_click_after_import(app,'Dropped web image',force=True))
        self.assertTrue(app.browser_one_click_force)
        self.assertTrue(app.browser_one_click_pending)
        self.assertEqual(app.browser_one_click_after,'after-id')

    def test_forced_one_click_is_consumed_before_draw(self):
        app=SimpleNamespace(
            closing=False,activity=None,original=object(),browser_one_click_force=True,
            status=Value(),browser_one_click_text=Value(),
        )
        with mock.patch.object(DrawBotApp,'_browser_one_click_authorized',return_value=True), \
             mock.patch.object(DrawBotApp,'_start_guard_ready',return_value=(True,'ok')), \
             mock.patch.object(DrawBotApp,'draw',return_value=True) as draw:
            self.assertTrue(DrawBotApp._finish_browser_one_click(app))
        self.assertFalse(app.browser_one_click_force)
        draw.assert_called_once_with(app,user_initiated=True)


if __name__=='__main__':
    unittest.main()
