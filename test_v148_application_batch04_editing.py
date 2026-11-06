"""Edit history follows the currently adopted image and source identity."""
import unittest
from unittest.mock import Mock,patch
from PIL import Image
from BackgroundRemoval import BackgroundRemovalResult
from DrawBot import DrawBotApp
from test_v148_ui_batch03 import app_for_edit


class ImageEditHistoryTests(unittest.TestCase):
    def test_background_removal_after_resize_cannot_undo_the_old_resize(self):
        app=app_for_edit();app.upscale_original=Image.new('RGBA',(1,1),'blue')
        result=BackgroundRemovalResult(Image.new('RGBA',app.original.size,(0,0,0,0)),{})
        expected=app.original.tobytes()
        with patch.object(DrawBotApp,'_clear_render_resume'):
            DrawBotApp._handle_event(app,'background_removed',result)
        self.assertIsNone(app.upscale_original)
        self.assertEqual(app.background_removal_original.tobytes(),expected)

    def test_resize_after_background_removal_cannot_undo_an_older_background(self):
        app=app_for_edit();app.background_removal_original=Image.new('RGBA',app.original.size,'blue')
        previous=app.original;resized=previous.resize((6,4))
        with patch.object(DrawBotApp,'_clear_render_resume'):
            DrawBotApp._handle_event(app,'upscaled',(resized,previous))
        self.assertIsNone(app.background_removal_original)
        self.assertIs(app.upscale_original,previous)
        self.assertIs(app.original,resized)

    def test_stale_or_busy_upscale_dialog_cannot_schedule_an_edit(self):
        for busy,closing,replace in ((True,False,False),(False,True,False),(False,False,True)):
            app=app_for_edit();source=app.original;app.begin_worker=Mock()
            app.activity='draw' if busy else None;app.closing=closing
            if replace:app.original=Image.new('RGBA',(2,2),'green')
            with self.subTest(busy=busy,closing=closing,replace=replace):
                self.assertFalse(DrawBotApp._start_upscale(app,source,2,'Smooth'))
                app.begin_worker.assert_not_called()

    def test_stale_upscaled_result_is_discarded_without_changing_current_history(self):
        app=app_for_edit();current=app.original
        source=Image.new('RGBA',(2,2),'green');result=source.resize((4,4))
        DrawBotApp._handle_event(app,'upscaled',(result,source))
        self.assertIs(app.original,current)
        app.show_previews.assert_not_called()
        with self.assertRaises(ValueError):result.getpixel((0,0))
        self.assertIsNotNone(source.getpixel((0,0)))

    def test_stop_after_upscale_compute_does_not_publish_a_late_image(self):
        app=app_for_edit();tasks=[];app.begin_worker=lambda kind,task:tasks.append(task) or True
        result=Image.new('RGBA',(6,4),'red')
        def upscale(*args):app.stop.set();return result
        with patch('ImageUpscale.upscale_image',side_effect=upscale):
            self.assertTrue(DrawBotApp._start_upscale(app,app.original,2,'Smooth'))
            with self.assertRaises(InterruptedError):tasks[0]()
        self.assertTrue(app.events.empty())
        with self.assertRaises(ValueError):result.getpixel((0,0))


if __name__=='__main__':unittest.main()
