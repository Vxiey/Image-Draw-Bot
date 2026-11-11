"""Selected PNG exports and visible navigation metadata share actual images."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import queue
import threading
import unittest
from unittest.mock import Mock,patch

from PIL import Image
from DrawBot import DrawBotApp
from PreviewViews import VIEW_SPECS
from test_v148_application_batch04_settings import Value


class PreviewViewTests(unittest.TestCase):
    def app(self):
        images={key:Image.new('RGBA',(20,10),(i*17,50,80,120+i))
                for i,(_,_,key,_) in enumerate(VIEW_SPECS)}
        for image in images.values():self.addCleanup(image.close)
        fallback=Image.new('RGB',(20,10),'blue');self.addCleanup(fallback.close)
        app=SimpleNamespace(activity=None,closing=False,original=images['original'],
            plan={'preview':fallback,'ui_previews':images},preview_tabs=Value('Original'),
            status=Value(''),events=queue.Queue(),stop=threading.Event(),jobs=[])
        def begin(activity,job,*,reset_stop=True,cleanup=None):
            self.assertIs(reset_stop,False)
            app.jobs.append(job);return True
        app.begin_worker=Mock(side_effect=begin)
        return app

    def test_each_view_exports_its_complete_source_pixels_and_descriptive_filename(self):
        app=self.app()
        with TemporaryDirectory() as temporary:
            for name,_,key,slug in VIEW_SPECS:
                with self.subTest(view=name):
                    app.preview_tabs.set(name);path=Path(temporary)/f'{slug}.png'
                    with patch('DrawBot.filedialog.asksaveasfilename',return_value=str(path)) as dialog:
                        self.assertTrue(DrawBotApp.export_preview(app))
                    self.assertFalse(path.exists(),'PNG encoding must wait for the worker')
                    self.assertEqual(dialog.call_args.kwargs['initialfile'],f'ImageDrawBot-{slug}.png')
                    app.jobs.pop()()
                    with Image.open(path) as exported:
                        self.assertEqual(exported.size,(20,10))
                        self.assertEqual(exported.tobytes(),app.plan['ui_previews'][key].tobytes())
                    self.assertIn(name,app.events.get_nowait()[1])

    def test_background_toggle_exports_the_same_stroke_image_as_the_visible_final_view(self):
        app=self.app();app.preview_tabs.set('Simulated final');app.preview_show_background=Value(False)
        with TemporaryDirectory() as temporary:
            path=Path(temporary)/'image.png'
            with patch('DrawBot.filedialog.asksaveasfilename',return_value=str(path)):
                self.assertTrue(DrawBotApp.export_preview(app))
            app.jobs.pop()()
            with Image.open(path) as result:
                self.assertEqual(result.tobytes(),app.plan['ui_previews']['stroke'].tobytes())

    def test_missing_or_hidden_layer_never_silently_exports_another_image(self):
        app=self.app()
        for name,flag in (('Fill regions','preview_show_fill'),('Stroke plan','preview_show_strokes')):
            app.preview_tabs.set(name);setattr(app,flag,Value(False))
            with patch('DrawBot.filedialog.asksaveasfilename') as dialog:
                self.assertFalse(DrawBotApp.export_preview(app))
            dialog.assert_not_called();self.assertIn(name,app.status.get())
        app.preview_tabs.set('ΔE heatmap');del app.plan['ui_previews']['delta_e']
        with patch('DrawBot.filedialog.asksaveasfilename') as dialog:
            self.assertFalse(DrawBotApp.export_preview(app))
        dialog.assert_not_called();app.begin_worker.assert_not_called()

    def test_modal_clear_shutdown_busy_or_view_change_cannot_export_a_different_image(self):
        for change in ('clear','closing','busy','view'):
            app=self.app();app.preview_tabs.set('Simulated final')
            def dialog(**kwargs):
                if change=='clear':app.plan=None
                elif change=='closing':app.closing=True
                elif change=='busy':app.activity='draw'
                else:app.preview_tabs.set('Safety map')
                return 'unused.png'
            with self.subTest(change=change),patch('DrawBot.filedialog.asksaveasfilename',side_effect=dialog):
                self.assertFalse(DrawBotApp.export_preview(app))
            app.begin_worker.assert_not_called()

    def test_png_source_export_rechecks_image_identity_after_dialog(self):
        app=self.app()
        def clear(**kwargs):app.original=None;return 'unused.png'
        with patch('DrawBot.filedialog.asksaveasfilename',side_effect=clear):
            self.assertFalse(DrawBotApp.save_png_copy(app))
        app.begin_worker.assert_not_called()

    def test_render_publishes_effective_pan_and_releases_its_owned_viewport(self):
        from PreviewQuality import viewport_image
        canvas=Mock();canvas.winfo_exists.return_value=True;canvas.winfo_ismapped.return_value=True
        canvas.winfo_width.return_value=216;canvas.winfo_height.return_value=116
        canvas._preview_pan=(1000,1000)
        source=Image.new('RGB',(1000,500),'red');self.addCleanup(source.close)
        app=SimpleNamespace(closing=False,original=source,plan=None,original_canvas=canvas,
            result_canvas=Mock(winfo_exists=Mock(return_value=False)),preview_zoom=Value(1.))
        viewports=[]
        def render(*args):
            result=viewport_image(*args);viewports.append(result[0]);return result
        with patch('PreviewQuality.viewport_image',side_effect=render),patch('PIL.ImageTk.PhotoImage',return_value='photo'):
            DrawBotApp.show_previews(app)
        self.assertEqual(canvas._preview_pan,(400,200));self.assertEqual(canvas._preview_scale,1.)
        self.assertEqual(canvas._preview_image_size,(1000,500))
        self.assertEqual(canvas._preview_viewport_size,(200,100))
        with self.assertRaises(ValueError):viewports[0].getpixel((0,0))
        self.assertEqual(source.getpixel((0,0)),(255,0,0))
        app.original=None
        DrawBotApp.show_previews(app)
        self.assertNotIn('_preview_image_size',canvas.__dict__)
        self.assertEqual(canvas._preview_pan,(0,0))


if __name__=='__main__':unittest.main()
