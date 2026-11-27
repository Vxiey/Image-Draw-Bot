import unittest
from unittest.mock import patch
from contextlib import closing
from pathlib import Path
from PIL import Image
from PreviewQuality import full_preview_options,viewport_geometry,viewport_image

class PreviewQualityTests(unittest.TestCase):
    def test_panning_downsampled_alpha_premultiplies_only_a_filter_padded_window(self):
        asset = Path(__file__).with_name('assets') / 'image-draw-bot-app-screenshot.png'
        with Image.open(asset) as rgba, closing(rgba.convert('LA')) as grey:
            for source in (rgba, grey):
                for size, zoom, pan, expect_window in (
                        ((160, 112), .5, (330.125, -105.25), True),
                        ((230, 180), .375, (-750, 300), True),
                        # A narrow view would reverse Pillow's horizontal/vertical
                        # filtering order if the same ROI optimization were used.
                        ((25, 127), .845113026089916, (-210.72052355633718, 228.35043715258485), None),
                        ((160, 112), 0, (0, 0), False)):
                    with self.subTest(mode=source.mode, size=size, zoom=zoom):
                        observed = []
                        convert = Image.Image.convert
                        def measure(image, mode, *args, **kwargs):
                            if mode in ('RGBa', 'La'):
                                observed.append(image.size)
                            return convert(image, mode, *args, **kwargs)
                        with patch.object(Image.Image, 'convert', measure):
                            actual, _ = viewport_image(source, size, zoom, pan)
                        self.assertEqual(len(observed), 1)
                        if expect_window:
                            self.assertLess(2 * observed[0][0] * observed[0][1], source.width * source.height)
                        elif expect_window is False:
                            self.assertEqual(observed[0], source.size)
                        geometry = viewport_geometry(source.size, size, zoom, pan)
                        with closing(actual), closing(source.resize(geometry.target, Image.Resampling.LANCZOS,
                                box=geometry.box)) as reference, closing(reference.convert('RGBA')) as layer, \
                                closing(Image.new('RGB', geometry.target, 'white')) as expected:
                            expected.paste(layer, (0, 0), layer)
                            self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_failed_alpha_resample_closes_the_window_and_preserves_the_source(self):
        asset = Path(__file__).with_name('assets') / 'image-draw-bot-icon.png'
        with Image.open(asset) as source:
            source.load()
            windows = []
            def fail(image, *_args, **_kwargs):
                windows.append(image)
                raise MemoryError('Unable to premultiply')
            with patch.object(Image.Image, 'convert', fail), self.assertRaises(MemoryError):
                viewport_image(source, (42, 36), .5, (40, -10))
            self.assertEqual(len(windows), 1)
            self.assertIsNot(windows[0], source)
            with self.assertRaises(ValueError):
                windows[0].getpixel((0, 0))
            source.getpixel((0, 0))

    def test_opaque_keyed_and_alpha_assets_match_white_compositing(self):
        assets = Path(__file__).with_name('assets')
        for name, keyed in (('image-draw-bot-app-screenshot.webp', False),
                            ('image-draw-bot-app-screenshot.webp', True),
                            ('image-draw-bot-icon.png', False)):
            with self.subTest(name=name, keyed=keyed), Image.open(assets / name) as source:
                if keyed:
                    source.info['transparency'] = source.getpixel((0, 0))
                with closing(source.convert('RGBA')) as rgba, \
                        closing(Image.new('RGBA', source.size, 'white')) as background:
                    background.alpha_composite(rgba)
                    result, _ = viewport_image(source, source.size, zoom=1)
                    with closing(result), closing(background.convert('RGB')) as expected:
                        self.assertEqual(result.mode, 'RGB')
                        self.assertEqual(result.info, {})
                        self.assertEqual(result.tobytes(), expected.tobytes())
                source.getpixel((0, 0))

    def test_options_preserve_quality_and_time(self):
        original={'ram_budget_mb':1024,'color_layers':'All','max_seconds':90,'detail':1}
        result=full_preview_options(original,(1200,800))
        for key in original:self.assertEqual(original[key],result[key])
        self.assertNotIn('_full_detail_preview',original)
        self.assertEqual(result['_preview_area'],(1200,800))
        self.assertFalse(result['_preview_plan'])
        self.assertGreaterEqual(result['cpu_workers_resolved'],1)
        self.assertLessEqual(result['cpu_workers_resolved'],4)

    def test_memory_and_invalid_area_guard(self):
        for area in ((2000,2000),(0,100),(-1,20)):
            with self.assertRaises(ValueError):full_preview_options({'ram_budget_mb':128},area)
        with self.assertRaises(ValueError):full_preview_options({'ram_budget_mb':65536},(10000,10000))

    def test_native_pixels_and_panning(self):
        image=Image.new('RGB',(100,60));image.putdata([(x,y,0) for y in range(60) for x in range(100)])
        out,scale=viewport_image(image,(20,20),1)
        self.assertEqual(scale,1);self.assertEqual(out.tobytes(),image.crop((40,20,60,40)).tobytes())
        out,_=viewport_image(image,(20,20),1,(999,999))
        self.assertEqual(out.tobytes(),image.crop((80,40,100,60)).tobytes())

    def test_zoom_output_is_bounded(self):
        image=Image.new('RGB',(2000,1000),'black')
        for zoom in (0,.125,1,8,999):
            out,_=viewport_image(image,(320,200),zoom)
            self.assertLessEqual(out.width,320);self.assertLessEqual(out.height,200)
        self.assertEqual(image.size,(2000,1000))

    def test_alpha_and_tiny_viewport(self):
        image=Image.new('RGBA',(10,10),(0,0,0,0))
        out,_=viewport_image(image,(0,0))
        self.assertEqual(out.size,(1,1));self.assertEqual(out.getpixel((0,0)),(255,255,255))

    def test_native_plan_and_actual_color_map(self):
        from DrawBot import finish_plan
        image=Image.new('RGB',(1800,100),'white')
        plan=finish_plan(image,image.size,[[(0,20,100,20)]],{'delay':.01,'_full_detail_preview':True,'paint_current_color':True,'brush_px':1,'human_mode':'Off'})
        self.assertEqual(plan['preview'].size,(1800,100))
        self.assertIs(plan['ui_previews']['color'],plan['preview'])

    def test_optional_map_failure_preserves_main_image(self):
        from DrawBot import finish_plan
        image=Image.new('RGB',(40,30),'white')
        with patch('PreviewLayers.build_auxiliary_previews',side_effect=ValueError('bad layer')):
            plan=finish_plan(image,image.size,[[(0,10,30,10)]],{'delay':.01,'paint_current_color':True})
        self.assertIs(plan['ui_previews']['color'],plan['preview'])
