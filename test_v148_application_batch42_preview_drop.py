"""All actual preview registrations feed the same real bounded image loader."""
from contextlib import ExitStack, closing
from pathlib import Path
import queue
import threading
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image
import tkinter as tk

from DrawBot import DrawBotApp
from PreviewViews import VIEW_SPECS
from test_v148_application_batch04_settings import Value
from test_v148_application_batch14_browser_start import ScheduledRoot


ASSET = Path(__file__).parent / 'assets' / 'image-draw-bot-icon.png'


class DropWidget:
    """Native registration/event boundary; callbacks remain production code."""
    def __init__(self):
        self.registrations = []
        self.callbacks = {}
        self.background = None

    def drop_target_register(self, *types):
        self.registrations.append(types)

    def dnd_bind(self, event, callback):
        if event in self.callbacks:
            raise AssertionError('a drop event was bound twice to one widget')
        self.callbacks[event] = callback

    def configure(self, **options):
        self.background = options.get('bg', self.background)


class DropRoot(DropWidget, ScheduledRoot):
    def __init__(self):
        DropWidget.__init__(self)
        ScheduledRoot.__init__(self)
        # The parser below is real; only Tk's split-list boundary is substituted.
        self.tk = SimpleNamespace(splitlist=lambda text: (text,))


class PreviewDropTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch('DrawBot.log_event'))
        self.stack.enter_context(patch('DrawBot.log_error'))

    def app(self, game='Gartic Phone'):
        app = SimpleNamespace(root=DropRoot(), game=Value(game), activity=None, closing=False,
            status=Value(''), stop=threading.Event(), events=queue.Queue(), worker=None,
            browser_one_click_enabled=Value(False), browser_one_click_request=None,
            manual_drop_in_start=Value(False), target_window=None, corners=[],
            palette_ready=False, original=None)
        app.set_busy = lambda activity: setattr(app, 'activity', activity)
        for name in ('load_source', 'begin_worker', 'drop_image', '_install_image_drop_targets'):
            setattr(app, name, MethodType(getattr(DrawBotApp, name), app))
        for _label, attribute, _layer, _filename in VIEW_SPECS:
            setattr(app, attribute, DropWidget())
        app._install_image_drop_targets()
        return app

    def import_from(self, app, widget):
        result = widget.callbacks['<<Drop>>'](SimpleNamespace(data=str(ASSET)))
        self.assertEqual(result, 'copy', app.status.get())
        worker = app.worker
        self.assertIsNotNone(worker)
        worker.join(3)
        self.assertFalse(worker.is_alive())
        events = []
        while not app.events.empty():
            events.append(app.events.get_nowait())
        self.assertEqual([kind for kind, _payload in events], ['loaded', 'done'])
        image, label, action, force = events[0][1]
        self.addCleanup(image.close)
        with Image.open(ASSET) as source, closing(source.convert('RGBA')) as expected:
            self.assertEqual((image.mode, image.size, image.tobytes()),
                             ('RGBA', expected.size, expected.tobytes()))
        self.assertIsNone(app.original, 'The image worker must leave adoption to the UI')
        self.assertEqual(events[1][1], 'load')
        return action, force

    def test_all_twelve_registered_pages_keep_the_verified_browser_drop_gesture(self):
        from tkinterdnd2 import DND_FILES, DND_TEXT
        for label, attribute, _layer, _filename in VIEW_SPECS:
            with self.subTest(page=label):
                app = self.app()
                self.assertEqual(app.root.registrations, [(DND_FILES, DND_TEXT)])
                for _name, current, _key, _stem in VIEW_SPECS:
                    canvas = getattr(app, current)
                    self.assertEqual(canvas.registrations, [(DND_FILES, DND_TEXT)])
                    self.assertEqual(set(canvas.callbacks), {'<<Drop>>', '<<DropEnter>>', '<<DropLeave>>'})
                canvas = getattr(app, attribute)
                self.assertEqual(canvas.callbacks['<<DropEnter>>'](None), 'copy')
                self.assertEqual(canvas.background, '#254237')
                self.assertEqual(canvas.callbacks['<<DropLeave>>'](None), 'copy')
                self.assertEqual(canvas.background, '#131a25')
                self.assertEqual(self.import_from(app, canvas), (None, True))

    def test_window_paint_and_unready_generic_drops_remain_import_only(self):
        cases = (('Gartic Phone', 'root'), ('Microsoft Paint', 'coverage_canvas'),
                 ('Other drawing app', 'delta_e_canvas'))
        for game, widget_name in cases:
            with self.subTest(game=game, target=widget_name):
                app = self.app(game)
                self.assertEqual(self.import_from(app, getattr(app, widget_name)), (None, False))
                self.assertFalse(app.manual_drop_in_start.get())

    def test_busy_closed_and_missing_native_dnd_support_never_start_an_import(self):
        for field, value in (('activity', 'draw'), ('closing', True)):
            with self.subTest(state=field):
                app = self.app()
                setattr(app, field, value)
                self.assertEqual(app.accuracy_error_canvas.callbacks['<<Drop>>'](
                    SimpleNamespace(data=str(ASSET))), 'none')
                self.assertIsNone(app.worker)
                self.assertTrue(app.events.empty())
        app = SimpleNamespace(root=object(), status=Value('unchanged'))
        DrawBotApp._install_image_drop_targets(app)
        self.assertEqual(app.status.get(), 'unchanged')

    def test_missing_or_aliased_legacy_views_bind_each_existing_widget_once(self):
        app = SimpleNamespace(root=DropRoot(), status=Value(''), drop_image=lambda event, **kwargs: kwargs)
        common = DropWidget()
        app.original_canvas = common
        app.result_canvas = common
        app.coverage_canvas = app.root
        DrawBotApp._install_image_drop_targets(app)
        self.assertEqual(len(common.registrations), 1)
        self.assertEqual(len(app.root.registrations), 1)
        self.assertEqual(common.callbacks['<<Drop>>'](None), {'drop_to_draw': True})
        self.assertEqual(app.root.callbacks['<<Drop>>'](None), {'drop_to_draw': False})

    def test_native_child_registration_failure_retains_window_import_fallback(self):
        app = SimpleNamespace(root=DropRoot(), status=Value(''), drop_image=lambda event, **kwargs: kwargs)
        app.original_canvas = SimpleNamespace(drop_target_register=lambda *types: (_ for _ in ()).throw(
            tk.TclError('native drop target unavailable')))
        DrawBotApp._install_image_drop_targets(app)
        self.assertEqual(app.root.callbacks['<<Drop>>'](None), {'drop_to_draw': False})
        self.assertIn('Use Select image or Ctrl+V', app.status.get())


if __name__ == '__main__':
    unittest.main()
