"""Real worker preparation and decoded-image handoff retain Stop and ownership."""
from pathlib import Path
import queue
import threading
from types import MethodType
from unittest.mock import patch

from PIL import Image

import DrawBot
from ScreenTaskWindow import ScreenTaskWindow
from test_v148_ui_batch16_plan_status import PlanStatusFixture
from test_v148_ui_batch20_auto_preview import ScheduledRoot


ASSET = Path(__file__).with_name('assets') / 'image-draw-bot-icon.png'


class WindowStateBoundary(ScheduledRoot):
    """Native visibility calls only; the product ScreenTaskWindow runs unchanged."""
    def __init__(self):
        super().__init__()
        del self.deiconify  # Replace the inherited native-call stub with state.
        self.visibility = 'normal'
        self.on_idle = lambda: None

    def state(self, value=None):
        if value is not None:self.visibility = value
        return self.visibility

    def winfo_exists(self):return True
    def iconify(self):self.visibility = 'iconic'
    def deiconify(self):self.visibility = 'normal'
    def withdraw(self):self.visibility = 'withdrawn'
    def lift(self):pass
    def update_idletasks(self):self.on_idle()


class WorkerHandoffFixture(PlanStatusFixture):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch('DrawBot.log_error'))
        self.stack.enter_context(patch.object(DrawBot.DrawBotApp, '_schedule_poll'))

    def image(self, _color):
        with Image.open(ASSET) as asset:
            image = asset.convert('RGBA')
        self.images.append(image)
        return image

    def app(self):
        app = super().app()
        app.root = WindowStateBoundary()
        app.events = queue.Queue()
        app.preview_after = app.preview_render_after = None
        for name in ('begin_worker', 'load_source', '_handle_event'):
            setattr(app, name, MethodType(getattr(DrawBot.DrawBotApp, name), app))
        return app

    def finish(self, app, *, deliver=True):
        self.assertIsInstance(app.worker, threading.Thread)
        app.worker.join(timeout=5)
        self.assertFalse(app.worker.is_alive())
        events = []
        while not app.events.empty():
            item = app.events.get_nowait()
            events.append(item)
            if deliver:app._handle_event(*item)
        if deliver:self.assertIsNone(app.activity)
        return events


class WorkerHandoffTests(WorkerHandoffFixture):
    def test_stop_during_real_window_preparation_never_runs_the_new_task(self):
        for activity, phase in (('load', 'constructor'), ('calibration', 'constructor'),
                                ('calibration', 'hide')):
            with self.subTest(activity=activity, phase=phase):
                app = self.app()
                invoked, cleaned = [], []
                app.stop.set()  # The prior operation must not block a fresh request.
                def prepare(root):
                    result = ScreenTaskWindow(root)
                    if phase == 'constructor':DrawBot.DrawBotApp._request_stop(app)
                    return result
                if phase == 'hide':app.root.on_idle = lambda: DrawBot.DrawBotApp._request_stop(app)
                with patch('ScreenTaskWindow.ScreenTaskWindow', side_effect=prepare):
                    self.assertTrue(app.begin_worker(activity, lambda: invoked.append('ran'),
                                                     cleanup=lambda: cleaned.append('closed')))
                events = self.finish(app)
                self.assertEqual(invoked, [])
                self.assertEqual(cleaned, ['closed'])
                self.assertTrue(app.stop.is_set())
                self.assertEqual([kind for kind, _ in events], ['status', 'done'])
                self.assertEqual(app.root.visibility, 'normal')

    def test_old_stop_clears_once_but_rejected_and_preserving_requests_never_clear_it(self):
        app = self.app(); app.stop.set(); invoked = []
        self.assertTrue(app.begin_worker('load', lambda: invoked.append('accepted')))
        self.finish(app)
        self.assertEqual(invoked, ['accepted'])
        self.assertFalse(app.stop.is_set())
        for field, value in (('activity', 'draw'), ('closing', True),
                             ('pending_clear_drawing', True),
                             ('profile_change_after', 'owned-profile-job'),
                             ('profile_change_in_progress', True)):
            with self.subTest(field=field):
                app = self.app(); setattr(app, field, value); app.stop.set()
                with patch('ScreenTaskWindow.ScreenTaskWindow') as prepare:
                    self.assertFalse(app.begin_worker('load', lambda: invoked.append('invalid')))
                self.assertTrue(app.stop.is_set()); prepare.assert_not_called()
        app = self.app(); app.stop.set()
        self.assertFalse(app.begin_worker('load', lambda: invoked.append('invalid'), reset_stop=False))
        self.assertTrue(app.stop.is_set())
        self.assertEqual(invoked, ['accepted'])

    def test_late_stop_closes_the_actual_decoded_image_before_worker_completion(self):
        app = self.app(); original = app.original; before = original.tobytes()
        decoded = []
        actual = DrawBot.load_image
        def load(*args, **kwargs):
            image = actual(*args, **kwargs)
            decoded.append(image); self.images.append(image)
            DrawBot.DrawBotApp._request_stop(app)
            return image
        with patch('DrawBot.load_image', side_effect=load):
            self.assertTrue(app.load_source(str(ASSET), ASSET.name))
            events = self.finish(app)
        self.assertEqual(len(decoded), 1)
        with self.assertRaises(ValueError):decoded[0].getpixel((0, 0))
        self.assertFalse(any(kind == 'loaded' for kind, _ in events))
        self.assertIs(app.original, original)
        self.assertEqual(original.tobytes(), before)

    def test_failed_queue_publication_closes_decode_and_success_transfers_owned_pixels(self):
        class RejectLoaded(queue.Queue):
            def put(self, item, *args, **kwargs):
                if item[0] == 'loaded':raise RuntimeError('native queue publication boundary')
                return super().put(item, *args, **kwargs)
        for reject in (True, False):
            with self.subTest(reject=reject):
                app = self.app()
                if reject:app.events = RejectLoaded()
                decoded = []
                actual = DrawBot.load_image
                def load(*args, **kwargs):
                    image = actual(*args, **kwargs)
                    decoded.append(image); self.images.append(image)
                    return image
                with patch('DrawBot.load_image', side_effect=load):
                    self.assertTrue(app.load_source(str(ASSET), ASSET.name))
                    events = self.finish(app, deliver=reject)
                self.assertEqual(len(decoded), 1)
                if reject:
                    with self.assertRaises(ValueError):decoded[0].getpixel((0, 0))
                    self.assertFalse(any(kind == 'loaded' for kind, _ in events))
                else:
                    self.assertEqual(events[0][0], 'loaded')
                    self.assertIs(events[0][1][0], decoded[0])
                    self.assertEqual(decoded[0].tobytes(), app.original.tobytes())
                    for item in events:app._handle_event(*item)
                    self.assertIs(app.original, decoded[0])
                    self.assertIsNone(app.activity)

    def test_pending_profile_rejects_load_before_changing_status_or_source(self):
        for field, value in (('profile_change_after', 'owned-profile-job'),
                             ('profile_change_in_progress', True),
                             ('pending_clear_drawing', True)):
            with self.subTest(field=field):
                app = self.app(); setattr(app, field, value)
                app.status.set('Current operation'); app.stop.set()
                with patch('DrawBot.load_image', wraps=DrawBot.load_image) as decoder:
                    self.assertFalse(app.load_source(str(ASSET), ASSET.name))
                self.assertEqual(app.status.get(), 'Current operation')
                self.assertTrue(app.stop.is_set())
                self.assertIsNone(app.worker); decoder.assert_not_called()
