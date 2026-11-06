"""Small runtime compatibility guards for third-party UI widgets.

No telemetry/networking. The patch is deliberately narrow and idempotent.
"""
from __future__ import annotations
import tkinter as tk

_PATCHED = False

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
