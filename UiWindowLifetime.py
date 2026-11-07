"""Local window factories own Tcl callbacks without patching Tk/CTk classes."""
import tkinter as tk
from weakref import WeakSet


_windows = WeakSet()
_running_services = {}


def _ctk_services():
    try:
        from customtkinter.windows.widgets.appearance_mode.appearance_mode_tracker import AppearanceModeTracker
        from customtkinter.windows.widgets.scaling.scaling_tracker import ScalingTracker
    except ImportError:
        return ()
    return ((AppearanceModeTracker, 'update'), (ScalingTracker, 'check_dpi_scaling'))


def _service_for(callback):
    return next(((tracker, name) for tracker, name in _ctk_services()
                 if callback == getattr(tracker, name)), None)


def _exists(window):
    try:
        return bool(window.winfo_exists())
    except (tk.TclError, RuntimeError, AttributeError):
        return False


def _usable(window):
    return (not getattr(window, '_window_retiring', False)
            and not getattr(window, '_window_destroyed', False) and _exists(window))


def cancel_widget_after_jobs(window):
    """Cancel exact single-command timers owned by this current widget subtree.

    Use raw Tcl cancellation. Each widget retains ownership of deleting its
    registered command during normal destroy, including child widget timers.
    """
    interpreter = getattr(window, 'tk', None)
    if interpreter is None:
        return
    commands = set()

    def collect(widget):
        commands.update(getattr(widget, '_tclCommands', ()) or ())
        for child in widget.winfo_children():
            collect(child)

    try:
        collect(window)
        for job in interpreter.splitlist(interpreter.call('after', 'info')):
            script, _kind = interpreter.call('after', 'info', job)
            words = interpreter.splitlist(script)
            if len(words) == 1 and words[0] in commands:
                interpreter.call('after', 'cancel', job)
    except (tk.TclError, RuntimeError):
        pass


def _forget_closed_window(window):
    if _exists(window):
        return
    for tracker, name in _ctk_services():
        if name == 'update':
            tracker.app_list[:] = [app for app in tracker.app_list if app is not window]
        else:
            tracker.window_widgets_dict.pop(window, None)
            tracker.window_dpi_scaling_dict.pop(window, None)


def _handoff_service(service, ms, callback, args):
    """Continue a retired scheduler's one shared poll on a surviving window."""
    if _running_services.get(service):
        # Its real callback is already executing and will choose its next
        # scheduler. Closed factory windows reject new after registrations.
        return
    for window in tuple(_windows):
        if not _usable(window):
            continue
        for job, (pending, _args, _delay) in window._window_after.items():
            if pending == callback:
                try:
                    window.tk.call('after', 'info', job)
                    return
                except (tk.TclError, RuntimeError):
                    pass
    tracker, name = service
    candidates = (tuple(tracker.app_list) if name == 'update'
                  else tuple(tracker.window_widgets_dict))
    for candidate in candidates:
        if not _usable(candidate):
            continue
        scheduler = candidate._root()
        if not _usable(scheduler):
            continue
        try:
            scheduler.after(ms, callback, *args)
        except (tk.TclError, RuntimeError):
            continue
        tracker.update_loop_running = True
        return
    # The last pending poll has ended. Let CTk's normal add()/add_widget()
    # start its service again if a later application root is created.
    tracker.update_loop_running = False


def scoped_window_class(base):
    """Wrap only our requested window class; leave the library class intact."""
    if getattr(base, '_image_draw_bot_scoped_window', False) is True:
        return base

    class ScopedWindow(base):
        _image_draw_bot_scoped_window = True

        def __init__(self, *args, **kwargs):
            self._window_after = {}
            self._window_bindings = []
            self._window_destroying = self._window_retiring = self._window_destroyed = False
            try:
                super().__init__(*args, **kwargs)
                _windows.add(self)
            except BaseException:
                try:
                    self.destroy()
                except (tk.TclError, RuntimeError, AttributeError):
                    pass
                raise

        def bind_all(self, sequence=None, func=None, add=None):
            token = super().bind_all(sequence, func, add)
            if token is not None and func is not None:
                self._window_bindings.append((self._root(), sequence, token))
            return token

        def after(self, ms, func=None, *args):
            service = _service_for(func) if func is not None else None
            if service is not None:
                scheduler = self._root()
                if scheduler is not self:
                    return scheduler.after(ms, func, *args)
            if self._window_retiring or self._window_destroyed:
                raise RuntimeError('The window has closed and cannot own a new callback.')
            if func is None:
                return super().after(ms)

            def run():
                if self._window_after.pop(job, None) is None:
                    return
                if self._window_retiring or self._window_destroyed:
                    return
                if service is not None:
                    _running_services[service] = _running_services.get(service, 0) + 1
                try:
                    func(*args)
                finally:
                    if service is not None:
                        count = _running_services[service] - 1
                        if count:
                            _running_services[service] = count
                        else:
                            _running_services.pop(service, None)

            job = super().after(ms, run)
            self._window_after[job] = (func, args, ms)
            return job

        def after_cancel(self, job):
            self._window_after.pop(job, None)
            return super().after_cancel(job)

        def destroy(self):
            if self._window_destroying or self._window_destroyed:
                return
            self._window_destroying = self._window_retiring = True
            services = {}
            try:
                for job, (callback, args, ms) in tuple(self._window_after.items()):
                    service = _service_for(callback)
                    if service is not None:
                        services[service] = (ms, callback, args)
                    try:
                        self.after_cancel(job)
                    except (tk.TclError, RuntimeError):
                        pass
                bindings, self._window_bindings = self._window_bindings, []
                for root, sequence, token in bindings:
                    try:
                        root._unbind(('bind', 'all', sequence), token)
                    except (tk.TclError, RuntimeError):
                        pass
                cancel_widget_after_jobs(self)
                super().destroy()
                self._window_destroyed = True
                _windows.discard(self)
            finally:
                # A real teardown error remains visible and retryable; do not
                # report successful destruction merely because it was tried.
                self._window_destroying = False
                if not self._window_destroyed:
                    self._window_retiring = False
                _forget_closed_window(self)
                for service, (ms, callback, args) in services.items():
                    _handoff_service(service, ms, callback, args)

    return ScopedWindow
