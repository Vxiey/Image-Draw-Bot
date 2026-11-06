"""Actual desktop redraws reuse only an unchanged accepted source/viewport."""
from contextlib import closing
import gc
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import weakref

from PIL import Image, ImageTk

from DrawBot import DrawBotApp
from PreviewBitmapCache import photo_for
from PreviewQuality import viewport_image
from test_v148_application_batch04_settings import Value


class Canvas:
    def __init__(self):
        self.exists = True; self.mapped = True
        self.width = 216; self.height = 116
        self._preview_pan = (0, 0)
        self.photo = None; self.text = []
    def winfo_exists(self): return self.exists
    def winfo_ismapped(self): return self.mapped
    def winfo_width(self): return self.width
    def winfo_height(self): return self.height
    def delete(self, *args): self.photo = None; self.text = []
    def create_image(self, *args, image): self.photo = image
    def create_text(self, *args, text, **kwargs): self.text.append(text)
    def create_oval(self, *args, **kwargs): pass
    def create_line(self, *args, **kwargs): pass


class Photo:
    def __init__(self, image):
        self.size = image.size; self.mode = image.mode; self.pixels = image.tobytes()


class DesktopBitmapReuseTests(unittest.TestCase):
    def app(self, original, result=None):
        return SimpleNamespace(closing=False, original=original,
            plan={'preview': result} if result is not None else None,
            original_canvas=Canvas(), result_canvas=Canvas(), preview_zoom=Value(0))

    def test_new_plan_keeps_unchanged_original_bitmap_and_replaces_result_pixels(self):
        with closing(Image.new('RGB', (600, 300), 'red')) as source, \
                closing(Image.new('RGB', (400, 200), 'blue')) as first, \
                closing(Image.new('RGB', (400, 200), 'green')) as second:
            app = self.app(source, first)
            with patch('PreviewQuality.viewport_image', wraps=viewport_image) as raster, \
                    patch('PIL.ImageTk.PhotoImage', side_effect=Photo) as upload:
                DrawBotApp.show_previews(app)
                original_photo = app.original_canvas.photo
                old_result = app.result_canvas.photo
                DrawBotApp.show_previews(app)
                self.assertEqual((raster.call_count, upload.call_count), (2, 2))
                app.plan = {'preview': second}
                DrawBotApp.show_previews(app)
                self.assertEqual((raster.call_count, upload.call_count), (3, 3))
                self.assertIs(app.original_canvas.photo, original_photo)
                self.assertIsNot(app.result_canvas.photo, old_result)
                self.assertEqual(app.result_canvas.photo.pixels[:3], bytes((0, 128, 0)))
                self.assertEqual(len(app.photos), 2)

    def test_exact_viewport_geometry_controls_zoom_pan_and_resize_reuse(self):
        with closing(Image.new('RGB', (1000, 500), 'red')) as source:
            app = self.app(source)
            app.result_canvas.mapped = False
            app.preview_zoom.set(1)
            app.original_canvas._preview_pan = (1000, 1000)
            with patch('PreviewQuality.viewport_image', wraps=viewport_image) as raster, \
                    patch('PIL.ImageTk.PhotoImage', side_effect=Photo):
                DrawBotApp.show_previews(app)
                self.assertEqual(app.original_canvas._preview_pan, (400, 200))
                first = app.original_canvas.photo
                DrawBotApp.show_previews(app)
                self.assertIs(app.original_canvas.photo, first)
                self.assertEqual(raster.call_count, 1)
                app.original_canvas._preview_pan = (350, 200)
                DrawBotApp.show_previews(app)
                app.preview_zoom.set(.5)
                DrawBotApp.show_previews(app)
                app.original_canvas.width = 416
                DrawBotApp.show_previews(app)
                self.assertEqual(raster.call_count, 4)
                with closing(viewport_image(source, (400, 100), .5,
                        app.original_canvas._preview_pan)[0]) as expected:
                    self.assertEqual(app.original_canvas.photo.pixels, expected.tobytes())

    def test_hide_clear_and_destroy_release_the_cached_tk_bitmap(self):
        for action in ('hide', 'clear', 'destroy'):
            with self.subTest(action=action), closing(Image.new('RGB', (80, 40), 'red')) as source:
                app = self.app(source)
                with patch('PIL.ImageTk.PhotoImage', side_effect=Photo):
                    DrawBotApp.show_previews(app)
                    photo = weakref.ref(app.original_canvas.photo)
                    if action == 'hide': app.original_canvas.mapped = False
                    elif action == 'clear': app.original = None
                    else:
                        app.original_canvas.exists = False
                        app.original_canvas.photo = None  # Native destroy drops its items.
                    DrawBotApp.show_previews(app)
                self.assertIsNone(app.original_canvas._preview_bitmap)
                self.assertIsNone(app.original_canvas._preview_photo)
                gc.collect()
                self.assertIsNone(photo())
                self.assertFalse(app.photos)

    def test_failed_upload_closes_viewport_clears_old_image_and_allows_retry(self):
        with closing(Image.new('RGB', (80, 40), 'red')) as source, \
                closing(Image.new('RGB', (80, 40), 'blue')) as changed:
            app = self.app(source)
            with patch('PIL.ImageTk.PhotoImage', side_effect=Photo):
                DrawBotApp.show_previews(app)
            app.original = changed
            owned = []
            def fail(image):
                owned.append(image)
                raise MemoryError('controlled upload failure')
            with patch('PIL.ImageTk.PhotoImage', side_effect=fail):
                DrawBotApp.show_previews(app)
            self.assertIsNone(app.original_canvas._preview_bitmap)
            self.assertIsNone(app.original_canvas.photo)
            self.assertTrue(any('could not be rendered' in text for text in app.original_canvas.text))
            with self.assertRaises(ValueError): owned[0].getpixel((0, 0))
            self.assertEqual(changed.getpixel((0, 0)), (0, 0, 255))
            with patch('PIL.ImageTk.PhotoImage', side_effect=Photo):
                DrawBotApp.show_previews(app)
            self.assertEqual(app.original_canvas.photo.pixels[:3], bytes((0, 0, 255)))

    def test_cache_has_no_strong_source_owner_and_closed_sources_cannot_reuse_old_pixels(self):
        canvas = Canvas()
        image = Image.new('RGBA', (80, 40), 'red')
        source = weakref.ref(image)
        photo_for(canvas, image, (200, 100), 0, (0, 0), make_photo=Photo)
        image.close()
        with self.assertRaises(ValueError):
            photo_for(canvas, image, (200, 100), 0, (0, 0), make_photo=Photo)
        self.assertIsNone(canvas._preview_bitmap)
        image = Image.new('RGBA', (80, 40), 'blue')
        source = weakref.ref(image)
        photo_for(canvas, image, (200, 100), 0, (0, 0), make_photo=Photo)
        del image
        gc.collect()
        self.assertIsNone(source())

    def test_uncached_public_viewport_still_observes_mutable_caller_pixels(self):
        with closing(Image.new('RGB', (4, 4), 'red')) as source:
            with closing(viewport_image(source, (4, 4), 1)[0]) as first:
                source.putpixel((0, 0), (0, 0, 255))
                with closing(viewport_image(source, (4, 4), 1)[0]) as second:
                    self.assertEqual(first.getpixel((0, 0)), (255, 0, 0))
                    self.assertEqual(second.getpixel((0, 0)), (0, 0, 255))

    @unittest.skipUnless(os.name == 'nt', 'Native Tk bitmap lifecycle requires the Windows CI desktop')
    def test_native_tk_redraw_reuses_bitmap_then_releases_hidden_canvas(self):
        import tkinter as tk
        root = tk.Tk()
        try:
            canvas = tk.Canvas(root, width=240, height=160); canvas.pack()
            root.update()
            with closing(Image.new('RGB', (80, 40), 'red')) as source:
                app = SimpleNamespace(closing=False, original=source, plan=None,
                    original_canvas=canvas, preview_zoom=Value(0))
                DrawBotApp.show_previews(app)
                first = canvas._preview_photo
                self.assertEqual(root.tk.call(str(first), 'get', 0, 0), (255, 0, 0))
                DrawBotApp.show_previews(app)
                self.assertIs(canvas._preview_photo, first)
                self.assertEqual(len(canvas.find_all()), 1)
                canvas.pack_forget(); root.update()
                DrawBotApp.show_previews(app)
                self.assertIsNone(canvas._preview_photo)
                self.assertIsNone(canvas._preview_bitmap)
                self.assertFalse(app.photos)
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
