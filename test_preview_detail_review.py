"""Review a shipped image using final scoring and the public preview layers."""
from contextlib import closing
from pathlib import Path
import os
import threading
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from DrawBot import DrawBotApp, make_plan
from PreviewDetailReview import PreviewDetailReview, detail_photo, region_view, review_data
from test_pixel_accurate_v1086 import opts
from test_v148_rendering_batch06_canvas import close_plan


class DetailReviewTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).with_name('golden-regression') / 'small-detail-preservation.png'
        self.source = self.enterContext(Image.open(path))
        self.plan = make_plan(self.source, (120, 90), opts(
            brush_px=3, subject_focus='Subject only', subject_region=(.2, .2, .8, .8),
            render_preset='Masterpiece', time_budget_mode='Unlimited', unlimited_time=True,
            _execution_cost_calibration_override={}))
        self.addCleanup(close_plan, self.plan, None)
        self.plan['preview_generation'] = 2
        self.app = SimpleNamespace(plan=self.plan, stop=threading.Event(), closing=False, preview_generation=2)
        self.current = lambda: DrawBotApp._current_detail_review_plan(self.app)
        self.data = review_data(self.plan)
        self.assertEqual(len(self.data['regions']), 3)

    def review(self):
        ui = object.__new__(PreviewDetailReview)
        ui._data = ui._anchor = None
        ui._photos = ()
        ui.panes = [Mock(), Mock()]
        ui.selector = Mock()
        ui.comparison = Mock()
        ui.metrics = Mock()
        ui.pack = Mock()
        ui.pack_forget = Mock()
        ui._current_plan = self.current
        ui.winfo_width = lambda: 480
        return ui

    def test_real_plan_exposes_three_independent_choices_without_replanning(self):
        ui = self.review()
        with patch('DrawBot.make_plan', side_effect=AssertionError('Already planned')):
            ui.publish(self.current())
            choices = ui.selector.configure.call_args.kwargs['values']
            self.assertEqual(len(choices), 4)
            self.assertEqual(len(set(choices)), 4)
            for index, row in enumerate(self.data['regions'], 1):
                ui.selector.current.return_value = index
                with patch('PreviewDetailReview.ImageTk.PhotoImage', side_effect=lambda pixels, **_: pixels.tobytes()):
                    ui.select()
                self.assertEqual(len(ui._photos), 2)
                self.assertIn(f'{row["missing_pixels"]:,} uncovered', ui.metrics.configure.call_args.kwargs['text'])
                self.assertIn(f'{row["wrong_color_pixels"]:,} wrong color', ui.metrics.configure.call_args.kwargs['text'])
                self.assertNotEqual(*ui._photos)

    def test_normalized_region_maps_to_same_source_pixels_at_different_display_resolutions(self):
        normalized, size = region_view((360, 240), (75, 40, 106, 61), (180, 140))
        # Crop bounds include four source pixels of context on every side.
        expected_box = (71, 36, 110, 65)
        with closing(self.source.resize((720, 480), Image.Resampling.NEAREST)) as doubled:
            for image, factor in ((self.source, 1), (doubled, 2)):
                pixels = detail_photo(image, normalized, size, lambda output: output.tobytes())
                with closing(image.resize(size, Image.Resampling.NEAREST,
                                          box=tuple(n * factor for n in expected_box))) as expected:
                    self.assertEqual(pixels, expected.tobytes())
        with self.assertRaises(ValueError):
            region_view((360, 240), (-1, 4, 4, 10), (180, 140))

    def test_queued_selection_and_displayed_bitmaps_are_retired_after_stop_or_replacement(self):
        for change in ('keyboard-stop', 'source', 'profile', 'generation'):
            with self.subTest(change=change):
                self.app.plan = self.plan
                self.app.preview_generation = 2
                self.app.stop.clear()
                self.app._stopped_detail_generation = None
                ui = self.review()
                ui.publish(self.current())
                ui._photos = (object(), object())
                if change == 'keyboard-stop':
                    DrawBotApp._request_stop(self.app)
                    self.app.stop.clear()  # Another operation can consume the global Stop.
                elif change in ('source', 'profile'):
                    self.app.plan = None
                else:
                    self.app.preview_generation += 1
                ui.selector.current.return_value = 1
                with patch('PreviewDetailReview.ImageTk.PhotoImage') as render:
                    ui.select()
                render.assert_not_called()
                ui.pack_forget.assert_called_once()
                self.assertEqual(ui._photos, ())
                self.assertIsNone(ui._data)
                self.assertEqual(ui.selector.configure.call_args.kwargs['values'], ())

    def test_keyboard_stop_during_tk_upload_discards_both_candidates(self):
        ui = self.review()
        ui.publish(self.plan)
        ui.selector.current.return_value = 1
        def upload(_image, **_):
            DrawBotApp._request_stop(self.app)
            return object()
        with patch('PreviewDetailReview.ImageTk.PhotoImage', side_effect=upload):
            ui.select()
        self.assertEqual(ui._photos, ())
        self.assertIsNone(ui._data)
        self.assertFalse(ui.comparison.pack.called)

    @unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'), 'Native Tk display required')
    def test_native_selector_shows_then_releases_both_tk_bitmaps(self):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        anchor = ttk.Frame(root)
        anchor.pack(fill='x')
        ui = PreviewDetailReview(root, anchor, self.current)
        ui.publish(self.plan)
        root.update()
        ui.selector.current(1)
        ui.selector.event_generate('<<ComboboxSelected>>')
        root.update()
        self.assertTrue(ui.comparison.winfo_ismapped())
        names = [str(photo) for photo in ui._photos]
        self.assertEqual(len(names), 2)
        self.assertTrue(all(name in root.tk.call('image', 'names') for name in names))
        ui.clear()
        root.update()
        self.assertFalse(ui.winfo_ismapped())
        self.assertTrue(all(name not in root.tk.call('image', 'names') for name in names))
        ui.publish(self.plan)
        root.update()
        ui.selector.current(2)
        ui.selector.event_generate('<<ComboboxSelected>>')
        root.update()
        names = [str(photo) for photo in ui._photos]
        self.assertEqual(len(names), 2)
        ui.destroy()
        self.assertTrue(all(name not in root.tk.call('image', 'names') for name in names))
        self.assertIsNone(ui._current_plan)
        self.assertFalse(ui._photos)


if __name__ == '__main__':
    unittest.main()
