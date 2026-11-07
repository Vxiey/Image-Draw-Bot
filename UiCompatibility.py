"""Small runtime compatibility guards for third-party UI widgets.

No telemetry/networking. The patch is deliberately narrow and idempotent.
"""
from __future__ import annotations
import tkinter as tk

_PATCHED = False


def scoped_window_class(base):
    """Use a local root/window subclass without changing third-party classes."""
    from UiWindowLifetime import scoped_window_class as owned_class
    return owned_class(base)


def scoped_toplevel(parent, **kwargs):
    """Create an application CTk dialog with owned callbacks and shared polls."""
    import customtkinter as ctk
    return scoped_window_class(ctk.CTkToplevel)(parent, **kwargs)


def _scoped_scrollable_class(base):
    class ScopedScrollableFrame(base):
        """Own the global callbacks CTk installs for this particular frame."""

        def __init__(self, *args, **kwargs):
            self._owned_scroll_bindings = []
            self._scroll_destroyed = False
            try:
                super().__init__(*args, **kwargs)
            except BaseException:
                self._release_scroll_bindings()
                try:
                    super().destroy()
                except Exception:
                    pass
                raise

        def bind_all(self, sequence=None, func=None, add=None):
            token = super().bind_all(sequence, func, add)
            if token is not None and func is not None:
                self._owned_scroll_bindings.append((self._root(), sequence, token))
            return token

        def _release_scroll_bindings(self):
            bindings = self._owned_scroll_bindings
            self._owned_scroll_bindings = []
            for root, sequence, token in bindings:
                try:
                    # Tkinter's targeted remover keeps every other bind_all
                    # callback and deletes only this frame's Tcl command.
                    root._unbind(('bind', 'all', sequence), token)
                except (tk.TclError, RuntimeError):
                    pass

        def destroy(self):
            if self._scroll_destroyed:
                return
            self._scroll_destroyed = True
            self._release_scroll_bindings()
            super().destroy()

    return ScopedScrollableFrame


def scoped_scrollable_frame(parent, **kwargs):
    """Create a CTk scroll frame whose root bindings end with its lifetime."""
    import customtkinter as ctk
    return _scoped_scrollable_class(ctk.CTkScrollableFrame)(parent, **kwargs)


def patch_customtkinter_scroll_guard() -> bool:
    """Prevent CTkScrollableFrame from dereferencing non-widget event targets.

    Some Tk/CustomTkinter combinations deliver ``event.widget`` as a Tcl path
    string after a widget has been destroyed/reparented. CustomTkinter 5.x then
    assumes ``.master`` exists and raises inside the global mouse-wheel binding.
    Returning False for non-widget targets is equivalent to 'not scrollable'.
    """
    global _PATCHED
    if _PATCHED:
        return True
    try:
        from customtkinter.windows.widgets.ctk_scrollable_frame import CTkScrollableFrame
    except Exception:
        return False
    original = getattr(CTkScrollableFrame, '_check_if_valid_scroll', None)
    if not callable(original):
        return False
    if getattr(original, '_imagedrawbot_safe_scroll_guard', False):
        _PATCHED = True
        return True

    def guarded(self, widget):
        if widget is None or isinstance(widget, str) or not hasattr(widget, 'master'):
            return False
        try:
            return original(self, widget)
        except (AttributeError, RuntimeError, tk.TclError):
            return False

    guarded._imagedrawbot_safe_scroll_guard = True
    guarded._imagedrawbot_original = original
    CTkScrollableFrame._check_if_valid_scroll = guarded
    _PATCHED = True
    return True
