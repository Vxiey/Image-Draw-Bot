"""Main-thread guide for suggesting and confirming a visible drawing canvas."""
from dataclasses import dataclass, field
import threading
import time
import tkinter as tk
from tkinter import messagebox

from OneClickSetupVerification import setup_mode
from GuidedCanvasOutline import CanvasOutline, outline_supported


@dataclass(eq=False)
class _Search:
    context: tuple
    profile_key: str
    previous: dict | None
    explicit: bool
    deadline: float
    stopped: threading.Event = field(default_factory=threading.Event)

    def cancelled(self):
        return self.stopped.is_set() or time.monotonic() >= self.deadline


class GuidedSetupController:
    SEARCH_SECONDS = 8
    OFFER_SECONDS = 45
    OUTLINE_SECONDS = 2.5

    def __init__(self, app, profiles):
        self.app = app
        self.profiles = profiles
        self.request = None
        self.worker = None
        self.offer = None
        self.accepted = None
        self.note = ''
        self.after = None
        self.timeout_after = None
        self.hidden_state = None
        self.start_consent = None
        self.outline = None
        self.outline_after = None
        self.outline_stop = None
        self.stop_ui = threading.Event()

    def refresh(self):
        callback = getattr(self.app, 'refresh_guided_setup', None)
        if callback and not self.app.closing:
            callback()

    def simple_mode(self):
        var = getattr(self.app, 'ui_mode', None)
        return var is not None and var.get() == 'Simple'

    def _key(self):
        return self.profiles.get(self.app.game.get(), ('generic',))[0]

    def _context(self):
        app = self.app
        return (id(app.original), app.game.get(), app.target_window, app.target_client_rect,
                app.target_dpi, tuple(tuple(p) for p in app.corners))

    def _available(self):
        a = self.app
        return (self.simple_mode() and not a.closing and a.original is not None and
                not getattr(a, 'profile_change_in_progress', False) and
                not getattr(a, 'profile_change_ticket', None) and
                getattr(a, 'pending_clear_drawing', None) is None and
                getattr(a, 'profile_change_after', None) is None and
                not getattr(a, 'browser_one_click_pending', False) and
                not getattr(a, 'drop_action_pending', None))

    def _offer(self):
        if self.offer is not None:
            context, expiry, candidate = self.offer
            if context == self._context() and time.monotonic() < expiry:
                return candidate
            self.offer = None
            self._hide_outline()
        return None

    def _hide_outline(self):
        token, self.outline_after = self.outline_after, None
        outline, self.outline = self.outline, None
        self.outline_stop = None
        try:
            if token is not None:
                self.app.root.after_cancel(token)
        except (ValueError, tk.TclError):
            pass
        finally:
            if outline is not None:
                outline.close()

    def show_canvas(self):
        self._hide_outline()
        offer = self._offer()
        if (offer is None or not outline_supported() or not self._available() or
                self.app.activity or self.request is not None or
                (len(self.app.corners) == 2 and self.app.target_window)):
            return False
        try:
            meta, box = self.app._guided_canvas_payload(offer)
            stop = self.outline_stop = threading.Event()
            outline = self.outline = CanvasOutline(box, meta)
            deadline = time.monotonic() + self.OUTLINE_SECONDS

            def check():
                if self.outline is not outline:
                    return
                self.outline_after = None
                try:
                    if (stop.is_set() or time.monotonic() >= deadline or not self._available()
                            or self.app.activity or self._offer() is not offer):
                        self._hide_outline()
                        return
                    outline.check_target()
                    self.outline_after = self.app.root.after(100, check)
                except (ValueError, OSError, tk.TclError):
                    self._hide_outline()

            self.outline_after = self.app.root.after(100, check)
            return True
        except (ValueError, OSError, tk.TclError) as error:
            self._hide_outline()
            if not self.app.closing:
                self.app.status.set(str(error))
            return False

    def accepted_canvas(self):
        """Only reuse an explicit selection with the same target and bounds."""
        if self.accepted and self.accepted[0] == self._context()[1:]:
            return self.accepted[1]
        return None

    def browser_identity_check(self):
        """Capture the guide's choice on Tk; worker checks never read UI state."""
        candidate = self.accepted_canvas()
        if not candidate or setup_mode(candidate['profile_key']) != 'browser':
            return None
        from GuidedCanvasDiscovery import recheck_guided_window
        cancelled = self.app.stop.is_set
        next_check = 0.0

        def check(monitor, *, force=False):
            nonlocal next_check
            now = time.monotonic()
            if force or now >= next_check:
                try:
                    recheck_guided_window(candidate, monitor=monitor, cancelled=cancelled)
                except (OSError, ValueError) as error:
                    raise InterruptedError(str(error)) from error
                next_check = now + .35
        return check

    def state(self):
        a = self.app
        profile = a.game.get()
        mode = setup_mode(self._key())
        has_canvas = len(a.corners) == 2 and a.target_window is not None
        offer = self._offer() if not has_canvas else None
        target = profile + (' · window selected' if has_canvas else ' · profile selected')
        canvas = 'Choose a drawing area'
        if offer or has_canvas:
            x, y, r, b = offer['canvas_box'] if offer else (*a.corners[0], *a.corners[1])
            canvas = f'{r-x} × {b-y} px at ({x}, {y})'
            if offer:
                target = profile + ' · window detected'
                canvas += ' · awaiting confirmation'
            else:
                canvas += ' · selected'
        palette_ready = a._palette_preflight_ready()
        palette = ('Palette ready' if a.palette_ready else
                   'Selected tool does not need a palette' if palette_ready else
                   'Calibrated during Paint preparation' if a._automatic_paint_preparation() else
                   'Palette setup needed')
        enabled = not (a.closing or a.activity or getattr(a, 'profile_change_in_progress', False)
                       or getattr(a, 'profile_change_ticket', None) or getattr(a, 'profile_change_after', None)
                       or getattr(a, 'pending_clear_drawing', None) is not None)
        if not enabled:
            stage, title, detail, label = 'busy', 'Working', 'Wait for the current task, or use Stop.', 'Working…'
        elif a.original is None:
            stage, title, detail, label = 'image', 'Choose an image', 'Open, paste or drop the image you want to draw.', 'Open image'
        elif self.request is not None:
            confirming = self.request.previous is not None
            stage, title, detail, label = ('detecting', 'Checking the canvas' if confirming else 'Looking for the canvas',
                'Checking the visible drawing window. You can also select the area manually.', 'Checking…')
            enabled = False
        elif offer:
            stage, title, detail, label = ('confirm_canvas', 'Use this drawing area?',
                'Check the canvas size and position. The area is checked again when you confirm.', 'Use detected canvas')
        elif not has_canvas:
            stage, title = 'canvas', 'Select the drawing area'
            detail = self.note or ('Open the drawing app and show its canvas.' if mode != 'manual' else
                                   'Mark two opposite corners inside the drawable area.')
            label = 'Find canvas' if mode != 'manual' else 'Select area manually'
        elif a._automatic_paint_preparation():
            stage, title, detail, label = ('ready', 'Ready to prepare Paint',
                'Paint will calibrate its tools and colors before drawing inside the selected area.', 'Prepare Paint & draw')
        else:
            ready, reason = a._start_guard_ready(require_image=True)
            if not ready:
                stage, title, detail, label = ('calibration', 'Complete target setup',
                    reason.removeprefix('Start locked: ').capitalize(),
                    'Verify canvas & palette' if mode == 'browser' else
                    'Read palette' if not palette_ready else 'Calibrate Paint tools')
            elif not a._full_draw_unlocked():
                stage, title, detail, label = ('unlock', 'Ready to draw',
                    'You can build a preview first or unlock drawing for 12 seconds.', 'Unlock drawing')
            else:
                stage, title, detail, label = ('ready', 'Drawing unlocked',
                    'Start drawing inside the selected area. Press Esc to stop.', 'Start drawing')
        return dict(stage=stage, title=title, detail=detail, action_label=label, enabled=enabled,
                    show_canvas_enabled=stage == 'confirm_canvas' and outline_supported(),
                    target_text=target, canvas_text=canvas, palette_text=palette,
                    primary_selects_canvas=stage == 'canvas' and mode == 'manual',
                    manual_canvas_enabled=not a.activity and not a.closing and a.original is not None
                    and not getattr(a, 'profile_change_ticket', None))

    def run(self):
        a = self.app
        view = self.state()
        if not self.simple_mode() or not view['enabled']:
            return False
        stage = view['stage']
        if stage == 'image':
            return a.open_file()
        if stage == 'canvas':
            if setup_mode(self._key()) == 'manual':
                return a.set_boundary()
            return self.queue(explicit=True)
        if stage == 'confirm_canvas':
            candidate = self._offer()
            return bool(candidate and self.queue(explicit=True, previous=candidate))
        if stage == 'calibration':
            if setup_mode(self._key()) == 'browser':
                return a.run_one_click_setup_verify()
            return a.calibrate() if not a._palette_preflight_ready() else a.calibrate_paint_tools()
        if stage == 'unlock':
            result = a.unlock_full_drawing()
            self.refresh()
            return result
        if stage == 'ready':
            if self.start_consent is not None:
                return False
            context = self._context()
            consent = threading.Event()
            self.start_consent = consent
            try:
                approved = messagebox.askyesno('Start drawing?', f'{view["action_label"]} in {a.game.get()}?\n'
                                               f'{view["canvas_text"]}. Press Esc to stop.', parent=a.root, default='no')
                if (approved and not consent.is_set() and self.simple_mode() and self._context() == context
                        and self.state()['stage'] == 'ready'):
                    return a.start_full_drawing()
            finally:
                self.start_consent = None
        return False

    def _cancel_timers(self):
        for token in (self.after, self.timeout_after):
            if token is not None:
                try:
                    self.app.root.after_cancel(token)
                except (tk.TclError, ValueError):
                    pass
        self.after = self.timeout_after = None

    def _restore(self):
        state, self.hidden_state = self.hidden_state, None
        if state and not self.app.closing:
            try:
                if self.app.root.state() == 'iconic':
                    self.app.root.deiconify()
                    if state == 'zoomed':
                        self.app.root.state('zoomed')
            except tk.TclError:
                pass

    def signal_stop(self):
        """May be called from the global keyboard hook; never access Tk here."""
        self.stop_ui.set()
        consent = self.start_consent
        if consent is not None:
            consent.set()
        request = self.request
        if request is not None:
            request.stopped.set()
        outline_stop = self.outline_stop
        if outline_stop is not None:
            outline_stop.set()

    def consume_stop(self):
        if self.stop_ui.is_set():
            self.cancel()

    def cancel(self, *, refresh=True):
        self.signal_stop()
        self._hide_outline()
        self.stop_ui.clear()
        self.request = self.offer = None
        self.note = ''
        self._cancel_timers()
        self._restore()
        if refresh:
            self.refresh()

    def queue(self, *, explicit=False, previous=None):
        a = self.app
        if (not self._available() or setup_mode(self._key()) == 'manual' or
                (len(a.corners) == 2 and a.target_window) or a.activity not in (None, 'load')):
            return False
        if not explicit and ((self.request and self.request.context == self._context()) or self._offer()):
            return True
        self.cancel(refresh=False)
        request = _Search(self._context(), self._key(), previous, explicit,
                          time.monotonic() + self.SEARCH_SECONDS)
        self.request = request
        if explicit:
            state = a.root.state()
            if state in ('normal', 'zoomed'):
                self.hidden_state = state
                a.root.iconify()
        self.after = a.root.after(180 if explicit else 100, lambda: self._start(request))
        self.timeout_after = a.root.after(self.SEARCH_SECONDS * 1000, lambda: self._expire(request))
        self.refresh()
        return True

    def _expire(self, request):
        if self.request is request:
            self.cancel(refresh=False)
            self.note = 'Canvas search timed out. Show the drawing window and try again, or select the area manually.'
            self.refresh()

    def _start(self, request):
        if self.request is not request:
            return
        self.after = None
        if request.cancelled() or not self._available() or self._context() != request.context:
            self.cancel()
            return
        if self.app.activity == 'load' or self.worker is not None:
            self.after = self.app.root.after(100, lambda: self._start(request))
            return
        if self.app.activity:
            self.cancel()
            return
        self.worker = request
        handle = self.app.target_window[0] if self.app.target_window else None
        if request.previous:
            handle = request.previous['target_meta']['handle']

        def work():
            result = error = None
            try:
                from GuidedCanvasDiscovery import discover_guided_canvas
                result = discover_guided_canvas(request.profile_key, preferred_handle=handle,
                                                previous=request.previous, cancelled=request.cancelled)
            except Exception as exc:
                error = str(exc) or 'Canvas search cancelled.'
            finally:
                self.app.events.put(('guided_canvas_complete', (request, result, error)))

        try:
            threading.Thread(target=work, daemon=True, name='guided-canvas').start()
        except RuntimeError as error:
            self.finish(request, None, str(error))

    def finish(self, request, result, error):
        if self.worker is request:
            self.worker = None
        if self.request is not request:
            return False
        current = (not request.cancelled() and self._available() and not self.app.activity and
                   request.context == self._context())
        self.cancel(refresh=False)
        if current:
            try:
                if error:
                    raise ValueError(error)
                if not isinstance(result, dict) or result.get('profile_key') != request.profile_key:
                    raise ValueError('The target changed. Find the canvas again.')
                meta, box = self.app._guided_canvas_payload(result)
                if request.previous is None:
                    self.offer = (request.context, time.monotonic() + self.OFFER_SECONDS, result)
                    self.after = self.app.root.after(self.OFFER_SECONDS * 1000, self.refresh)
                else:
                    old_meta, old_box = self.app._guided_canvas_payload(request.previous)
                    if (old_box != box or
                            request.previous.get('_window_title_fingerprint') != result.get('_window_title_fingerprint') or
                            any(meta.get(k) != old_meta.get(k) for k in
                                ('handle', 'rect', 'client_rect', 'dpi', 'target_pid', 'target_thread'))):
                        raise ValueError('The target or canvas changed. Find the canvas again.')
                    self.app._apply_guided_canvas(request.profile_key, meta, box)
                    self.accepted = (self._context()[1:], result)
            except (TypeError, ValueError, OSError) as exc:
                self.note = str(exc)
                if request.explicit:
                    self.app.status.set(self.note)
                self.refresh()
                return False
        self.refresh()
        return bool(current)
