"""UI lifecycle and absolute placement through fakes, plus Windows Tk smoke."""
from contextlib import ExitStack
import ctypes
from types import SimpleNamespace
import sys
import threading
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

import GettingStarted as guide
import SmartDropInCanvas as smart_drop
from UiCompatibility import _scoped_scrollable_class
import RegionPicker


class Widget:
    def __init__(self, master=None, **options):
        self.master = master
        self.children = []
        self.options = dict(options)
        self.bindings = {}
        self.protocols = {}
        self.jobs = {}
        self.serial = 0
        self.destroyed = False
        self.width = 700
        self.scale = 1.0
        self.width_reads = 0
        self.configurations = []
        self._parent_canvas = SimpleNamespace(yview_moveto=Mock())
        self.deiconify = Mock()
        self.lift = Mock()
        if master is not None:
            master.children.append(self)
    def pack(self, **kwargs): pass
    def title(self, value): pass
    def transient(self, value): pass
    def configure(self, **kwargs):
        if self.destroyed: raise tk.TclError('destroyed widget')
        self.configurations.append(kwargs)
        self.options.update(kwargs)
    def set(self, value): self.options['value'] = value
    def winfo_children(self): return list(self.children)
    def winfo_exists(self): return not self.destroyed
    def winfo_width(self):
        self.width_reads += 1
        return self.width
    def _get_widget_scaling(self): return self.scale
    def bind(self, name, callback, **kwargs): self.bindings[name] = callback
    def protocol(self, name, callback): self.protocols[name] = callback
    def after_idle(self, callback):
        self.serial += 1
        self.jobs[self.serial] = callback
        return self.serial
    def after_cancel(self, token): self.jobs.pop(token, None)
    def flush(self):
        for _ in range(100):
            if not self.jobs: return
            _, callback = self.jobs.popitem()
            callback()
        raise AssertionError('UI jobs did not settle')
    def destroy(self):
        if self.destroyed: return
        for child in list(self.children): child.destroy()
        self.destroyed = True
        if self.master is not None: self.master.children.remove(self)
        callback = self.bindings.get('<Destroy>')
        if callback is not None: callback(SimpleNamespace(widget=self))


class GuideHarness:
    def __enter__(self):
        self.stack = ExitStack()
        self.interpreter = tk.Tcl()
        self.app = SimpleNamespace(root=Widget(), game=tk.StringVar(self.interpreter, 'Microsoft Paint'))
        for name in ('CTkToplevel', 'CTkLabel', 'CTkOptionMenu', 'CTkFrame', 'CTkButton'):
            self.stack.enter_context(patch('customtkinter.' + name, Widget))
        self.stack.enter_context(patch('UiCompatibility.scoped_scrollable_frame', Widget))
        self.stack.enter_context(patch('WorkspaceLayout.fit_window', return_value=(840, 760)))
        self.seen = self.stack.enter_context(patch('ReleaseState.mark_welcome_seen'))
        self.window = guide.show_guide(self.app)
        self.window.flush()
        self.menu = next(child for child in self.window.children if 'values' in child.options)
        self.body = next(child for child in self.window.children if '<Configure>' in child.bindings)
        return self
    def __exit__(self, *args):
        self.window.destroy()
        self.stack.close()
    def page(self, title):
        self.menu.options['command'](title)
        self.window.flush()
    def labels(self):
        def walk(widget):
            if 'text' in widget.options: yield widget
            for child in widget.children: yield from walk(child)
        return list(walk(self.body))
    def texts(self):
        return [label.options['text'] for label in self.labels()]


class GuideTests(unittest.TestCase):
    def test_profile_change_refreshes_the_current_topic_without_navigation(self):
        with GuideHarness() as h:
            h.page('Choose your target')
            self.assertIn('Prepare Paint', h.texts())
            h.app.game.set('Gartic Phone')
            h.window.flush()
            self.assertIn('First browser attempt', h.texts())
            self.assertNotIn('Prepare Paint', h.texts())
            self.assertEqual(h.menu.options['value'], 'Choose your target')
            self.assertTrue(any('Profile: Gartic Phone' in child.options.get('text', '')
                                for child in h.window.children))

    def test_manual_targets_are_not_told_to_use_an_unavailable_browser_detector(self):
        for profile in ('Other drawing app', 'Drawize', 'Gartic.io', 'Kleki', 'Magma', 'My custom profile'):
            with self.subTest(profile=profile):
                pages = guide.guide_pages(profile)
                self.assertEqual(pages[1][1][1][0], 'Manual target setup')
                self.assertIn('no verified automatic browser detector', pages[2][1][1][1])

    def test_height_only_events_are_coalesced_without_reconfiguring_labels(self):
        with GuideHarness() as h:
            labels = h.labels()
            before = sum(len(label.configurations) for label in labels)
            reads = h.body.width_reads
            for _ in range(100):
                h.body.bindings['<Configure>'](SimpleNamespace(widget=h.body, width=700, height=400))
            self.assertEqual(len(h.window.jobs), 1)
            h.window.flush()
            self.assertEqual(sum(len(label.configurations) for label in labels), before)
            self.assertEqual(h.body.width_reads - reads, 1)
            h.body.width = 600
            h.body.bindings['<Configure>'](SimpleNamespace(widget=h.body))
            h.window.flush()
            self.assertEqual([label.options['wraplength'] for label in labels], [544] * len(labels))

    def test_wrap_uses_logical_ctk_pixels_and_fits_a_compact_body(self):
        body = Widget()
        body.width = 1050
        body.scale = 1.5
        self.assertEqual(guide._guide_wrap_length(body), 644)
        body.width = 200
        self.assertLessEqual(guide._guide_wrap_length(body) * body.scale, body.width)
        body.width = 1
        self.assertIsNone(guide._guide_wrap_length(body))

    def test_keyboard_navigation_is_bounded_and_close_is_idempotent(self):
        with GuideHarness() as h:
            h.window.bindings['<Alt-Left>']()
            self.assertEqual(h.menu.options['value'], 'Your first drawing')
            h.window.bindings['<Alt-Right>']()
            self.assertEqual(h.menu.options['value'], 'Choose your target')
            h.window.bindings['<Escape>']()
            h.window.bindings['<Escape>']()
            h.seen.assert_called_once()
            self.assertIsNone(h.app._getting_started_window)

    def test_close_removes_profile_trace_and_both_pending_jobs(self):
        with GuideHarness() as h:
            h.app.game.set('Gartic Phone')
            h.body.bindings['<Configure>'](SimpleNamespace(widget=h.body))
            callbacks = list(h.window.jobs.values())
            self.assertEqual(len(callbacks), 2)
            h.window.destroy()
            self.assertFalse(h.app.game.trace_info())
            self.assertFalse(h.window.jobs)
            for callback in callbacks: callback()
            self.assertIsNone(h.app._getting_started_window)
            h.seen.assert_not_called()

    def test_reopening_an_iconified_existing_guide_makes_it_visible(self):
        with GuideHarness() as h:
            self.assertIs(guide.show_guide(h.app), h.window)
            h.window.deiconify.assert_called_once()
            h.window.lift.assert_called_once()

    def test_construction_failure_clears_the_window_reference(self):
        app = SimpleNamespace(root=Widget(), game=tk.StringVar(tk.Tcl(), 'Microsoft Paint'))
        with patch('customtkinter.CTkToplevel', Widget), \
             patch('WorkspaceLayout.fit_window', side_effect=ValueError('failed geometry')):
            with self.assertRaisesRegex(ValueError, 'failed geometry'):
                guide.show_guide(app)
        self.assertIsNone(app._getting_started_window)
        self.assertEqual(app.root.children, [])


class ScopedScrollTests(unittest.TestCase):
    def test_destroy_removes_only_its_owned_root_bindings_once(self):
        root = Mock()
        class Base:
            def __init__(self, parent):
                self.parent = parent
                self.bind_all('<MouseWheel>', self.wheel, True)
                self.bind_all('<KeyPress-Shift_L>', self.wheel, True)
            def wheel(self, event): pass
            def _root(self): return self.parent
            def bind_all(self, sequence, func, add): return sequence + '-owned-id'
            def destroy(self): self.parent.destroyed_frame()
        frame = _scoped_scrollable_class(Base)(root)
        frame.destroy()
        frame.destroy()
        root._unbind.assert_any_call(('bind', 'all', '<MouseWheel>'), '<MouseWheel>-owned-id')
        root._unbind.assert_any_call(('bind', 'all', '<KeyPress-Shift_L>'), '<KeyPress-Shift_L>-owned-id')
        self.assertEqual(root._unbind.call_count, 2)
        root.unbind_all.assert_not_called()
        root.destroyed_frame.assert_called_once()

    def test_partial_construction_releases_bindings_before_propagating_failure(self):
        root = Mock()
        class Base:
            def __init__(self, parent):
                self.parent = parent
                self.bind_all('<MouseWheel>', lambda event: None, True)
                raise ValueError('partial frame')
            def _root(self): return self.parent
            def bind_all(self, sequence, func, add): return 'owned-id'
            def destroy(self): self.parent.destroyed_frame()
        with self.assertRaisesRegex(ValueError, 'partial frame'):
            _scoped_scrollable_class(Base)(root)
        root._unbind.assert_called_once_with(('bind', 'all', '<MouseWheel>'), 'owned-id')


class OverlayPlacementTests(unittest.TestCase):
    def harness(self):
        trace = []
        state = {'alpha': .34, 'withdrawn': False, 'rect': (0, 0, 1, 1)}
        window = Mock()
        def attributes(name, *values):
            if values:
                state['alpha'] = values[0]
                trace.append(('alpha', values[0]))
            return state['alpha']
        window.attributes.side_effect = attributes
        window.withdraw.side_effect = lambda: state.update(withdrawn=True)
        def mapped():
            state.update(withdrawn=False, rect=(0, 0, 10, 10))
        window.deiconify.side_effect = mapped
        def idle():
            self.assertTrue(state['withdrawn'] or state['alpha'] == 0)
        window.update_idletasks.side_effect = idle
        window.winfo_id.return_value = 0x100000003
        api = Mock()
        api.GetAncestor.return_value = 0x100000005
        def position(handle, after, x, y, width, height, flags):
            state['rect'] = (x, y, x+width, y+height)
            trace.append(('position', state['rect']))
            return True
        api.SetWindowPos.side_effect = position
        def read(handle, pointer):
            value = pointer._obj
            value.left, value.top, value.right, value.bottom = state['rect']
            trace.append(('verified', state['rect']))
            return True
        api.GetWindowRect.side_effect = read
        return window, api, state, trace

    def test_signed_desktop_coordinates_are_verified_before_becoming_visible(self):
        window, api, state, trace = self.harness()
        wanted = (-1200, -10, -200, 590)
        with patch('WindowsSystem.load_system_library', return_value=api) as loader:
            self.assertEqual(smart_drop.place_canvas_overlay(window, wanted), wanted)
        loader.assert_called_once_with('user32.dll', use_last_error=True)
        self.assertEqual(api.GetAncestor.restype, ctypes.c_void_p)
        self.assertEqual(api.GetAncestor.call_args.args, (0x100000003, 2))
        for call in api.SetWindowPos.call_args_list:
            self.assertEqual(call.args, (0x100000005, None, -1200, -10, 1000, 600, 0x14))
        self.assertEqual(api.SetWindowPos.call_count, 2)
        self.assertEqual(state['rect'], wanted)
        self.assertFalse(state['withdrawn'])
        self.assertEqual(trace[-2:], [('verified', wanted), ('alpha', .34)])

    def test_native_failure_or_mismatch_leaves_the_overlay_hidden(self):
        for stage in ('handle', 'position', 'read', 'mismatch', 'mapped-position'):
            with self.subTest(stage=stage):
                window, api, state, _ = self.harness()
                if stage == 'handle': api.GetAncestor.return_value = None
                elif stage == 'position': api.SetWindowPos.side_effect = None; api.SetWindowPos.return_value = False
                elif stage == 'read': api.GetWindowRect.side_effect = None; api.GetWindowRect.return_value = False
                elif stage == 'mismatch': api.GetWindowRect.side_effect = None; api.GetWindowRect.return_value = True
                else:
                    original = api.SetWindowPos.side_effect
                    count = [0]
                    def position(*args):
                        count[0] += 1
                        return original(*args) if count[0] == 1 else False
                    api.SetWindowPos.side_effect = position
                with patch('WindowsSystem.load_system_library', return_value=api), self.assertRaises(OSError):
                    smart_drop.place_canvas_overlay(window, (-20, -10, 30, 40))
                self.assertTrue(state['withdrawn'])
                self.assertEqual(state['alpha'], 0)

    def test_invalid_or_unrepresentable_geometry_never_reaches_win32(self):
        for box in ((0, 0, 1.5, 20), (False, 0, 20, 20), (-2**31, 0, 2**31-1, 10)):
            with self.subTest(box=box), patch('WindowsSystem.load_system_library') as loader, self.assertRaises(ValueError):
                smart_drop.place_canvas_overlay(Mock(), box)
            loader.assert_not_called()


class RegionCancellationTests(unittest.TestCase):
    def harness(self, stack):
        from PIL import Image
        jobs = {}
        bindings = {}
        serial = [0]
        owner = Mock()
        owner.master = None
        owner.state.return_value = 'normal'
        def after(delay, callback):
            serial[0] += 1
            jobs[serial[0]] = (delay, callback)
            return serial[0]
        owner.after.side_effect = after
        owner.after_cancel.side_effect = lambda token: jobs.pop(token, None)
        overlay = Mock()
        class Top:
            def __new__(cls, *args, **kwargs): return overlay
        canvas = Mock()
        canvas.bind.side_effect = lambda name, callback: bindings.__setitem__(name, callback)
        overlay.bind.side_effect = lambda name, callback: bindings.__setitem__(name, callback)
        api = Mock()
        api.GetSystemMetrics.side_effect = lambda index: {76: 0, 77: 0, 78: 40, 79: 30}[index]
        api.GetAncestor.return_value = 123
        api.SetWindowPos.return_value = True
        raw = Image.new('RGB', (40, 30), 'red')
        stack.callback(raw.close)
        loader = stack.enter_context(patch('WindowsSystem.load_system_library', return_value=api))
        grab = stack.enter_context(patch('RegionPicker.ImageGrab.grab', return_value=raw))
        stack.enter_context(patch('RegionPicker.tk.Toplevel', Top))
        stack.enter_context(patch('RegionPicker.tk.Canvas', return_value=canvas))
        stack.enter_context(patch('RegionPicker.ImageTk.PhotoImage'))
        stop = threading.Event()
        selected = Mock()
        errors = Mock()
        RegionPicker.select_region(owner, selected, errors, cancelled=stop.is_set)
        def run(name):
            token, (_, callback) = next((token, job) for token, job in jobs.items()
                                        if job[1].__name__ == name)
            jobs.pop(token)
            callback()
        return SimpleNamespace(owner=owner, overlay=overlay, raw=raw, grab=grab, jobs=jobs,
                               bindings=bindings, stop=stop, selected=selected, errors=errors,
                               run=run, loader=loader)

    def test_stop_during_the_initial_delay_cancels_capture_and_restores_windows(self):
        with ExitStack() as stack:
            h = self.harness(stack)
            stale_capture = next(callback for _, callback in h.jobs.values()
                                 if callback.__name__ == 'capture')
            h.stop.set()
            h.run('poll_cancelled')
            stale_capture()
            h.grab.assert_not_called()
            h.selected.assert_not_called()
            h.errors.assert_called_once_with('Selection cancelled.')
            h.owner.deiconify.assert_called_once()
            self.assertFalse(h.jobs)

    def test_stop_while_overlay_is_open_releases_capture_and_owned_jobs(self):
        with ExitStack() as stack:
            h = self.harness(stack)
            h.run('capture')
            h.stop.set()
            h.run('poll_cancelled')
            h.loader.assert_called_once_with('user32.dll')
            h.overlay.destroy.assert_called_once()
            h.errors.assert_called_once_with('Selection cancelled.')
            h.selected.assert_not_called()
            self.assertFalse(h.jobs)
            with self.assertRaises(ValueError): h.raw.getpixel((0, 0))

    def test_stop_before_delayed_delivery_closes_the_undelivered_crop(self):
        from PIL import Image
        original = Image.Image.crop
        crops = []
        def crop(image, box):
            result = original(image, box)
            crops.append(result)
            return result
        with ExitStack() as stack:
            stack.enter_context(patch.object(Image.Image, 'crop', crop))
            h = self.harness(stack)
            h.run('capture')
            h.bindings['<ButtonPress-1>'](SimpleNamespace(x=1, y=1))
            h.bindings['<ButtonRelease-1>'](SimpleNamespace(x=21, y=21))
            self.assertEqual(len(crops), 1)
            h.stop.set()
            h.run('finish')
            h.selected.assert_not_called()
            h.errors.assert_called_once_with('Selection cancelled.')
            self.assertFalse(h.jobs)
            with self.assertRaises(ValueError): crops[0].getpixel((0, 0))

    def test_failed_crop_does_not_leave_an_uncancellable_hidden_main_window(self):
        from PIL import Image
        with ExitStack() as stack:
            h = self.harness(stack)
            h.run('capture')
            stack.enter_context(patch.object(Image.Image, 'crop', side_effect=MemoryError('crop allocation failed')))
            h.bindings['<ButtonPress-1>'](SimpleNamespace(x=1, y=1))
            h.bindings['<ButtonRelease-1>'](SimpleNamespace(x=21, y=21))
            h.errors.assert_called_once_with('crop allocation failed')
            h.owner.deiconify.assert_called_once()
            h.overlay.destroy.assert_called_once()
            self.assertFalse(h.jobs)


@unittest.skipUnless(sys.platform == 'win32', 'Actual Windows Tk lifecycle and placement')
class WindowsWorkflowTests(unittest.TestCase):
    def test_repeated_guide_close_removes_its_global_callbacks(self):
        import customtkinter as ctk
        root = ctk.CTk()
        root.withdraw()
        app = SimpleNamespace(root=root, game=tk.StringVar(root, 'Microsoft Paint'))
        sequences = ('<MouseWheel>', '<Button-4>', '<Button-5>',
                     '<KeyPress-Shift_L>', '<KeyPress-Shift_R>',
                     '<KeyRelease-Shift_L>', '<KeyRelease-Shift_R>')
        delivered = []
        unrelated = root.bind_all('<MouseWheel>', lambda event: delivered.append(event.delta), add='+')

        def binding_lines():
            # Tk's targeted _unbind preserves callbacks but may leave extra
            # empty Tcl lines. Compare the complete nonempty scripts, rather
            # than treating those harmless separators as callback leaks.
            return {sequence: tuple(line for line in root.bind_all(sequence).splitlines() if line.strip())
                    for sequence in sequences}

        before = binding_lines()
        try:
            root.deiconify()
            root.update()
            root.event_generate('<MouseWheel>', delta=120, when='now')
            self.assertEqual(delivered, [120])
            for _ in range(3):
                window = guide.show_guide(app)
                root.update_idletasks()
                pending = list(window.winfo_children())
                body = None
                while pending:
                    child = pending.pop()
                    if isinstance(child, ctk.CTkScrollableFrame):
                        body = child
                        break
                    pending.extend(child.winfo_children())
                self.assertIsNotNone(body)
                tokens = [token for _, _, token in body._owned_scroll_bindings]
                self.assertTrue(tokens)
                window.destroy()
                root.update_idletasks()
                self.assertEqual(binding_lines(), before)
                for token in tokens:
                    self.assertFalse(root.tk.call('info', 'commands', token))
                self.assertTrue(root.tk.call('info', 'commands', unrelated))
                previous_count = len(delivered)
                root.event_generate('<MouseWheel>', delta=-120, when='now')
                self.assertEqual(delivered[previous_count:], [-120])
                self.assertFalse(app.game.trace_info())
        finally:
            root.destroy()

    def test_actual_window_can_be_placed_at_signed_desktop_coordinates(self):
        from DpiSupport import enable_per_monitor_v2
        enable_per_monitor_v2()
        root = tk.Tk()
        root.withdraw()
        overlay = tk.Toplevel(root)
        overlay.withdraw()
        overlay.overrideredirect(True)
        overlay.attributes('-alpha', .34)
        try:
            self.assertEqual(smart_drop.place_canvas_overlay(overlay, (-30, -20, 10, 20)),
                             (-30, -20, 10, 20))
            self.assertEqual(overlay.state(), 'normal')
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
