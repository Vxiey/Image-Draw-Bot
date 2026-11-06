"""One visual identity for Tk windows, taskbar grouping and the app header."""
import sys
import logging
import tkinter as tk

from RuntimePaths import resource_path

APP_USER_MODEL_ID = 'Vxiey.ImageDrawBot'
ICON_PNG = 'assets/image-draw-bot-icon.png'
ICON_ICO = 'assets/image-draw-bot-icon.ico'


def set_windows_app_id():
    """Call before creating windows; source launches should not group as Python."""
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        setter = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        setter.argtypes = [ctypes.c_wchar_p]
        setter.restype = ctypes.c_int32
        result = setter(APP_USER_MODEL_ID)
        if result < 0:
            raise OSError(f'AppUserModelID failed: {result}')
    except (AttributeError, OSError):
        pass


def _already_destroyed_tcl_error(error):
    """Return True only for Tk's harmless repeated/interpreter teardown error."""
    message = str(error).lower()
    return (
        'application has been destroyed' in message
        or ('can\'t invoke "destroy" command' in message and 'destroyed' in message)
    )


def _install_destroy_guard(root):
    """Make branded root destruction idempotent before any optional UI setup."""
    if sys.platform != 'win32' or getattr(root, '_image_draw_bot_destroy_wrapped', False):
        return
    # Some deterministic unit-test roots intentionally implement only the Tk
    # methods needed by the subsystem under test. Branding must remain optional
    # for those objects rather than turning a missing destroy method into a
    # startup/shutdown failure.
    original_destroy = getattr(root, 'destroy', None)
    if not callable(original_destroy):
        return

    def destroy():
        if (getattr(root, '_image_draw_bot_destroying', False)
                or getattr(root, '_image_draw_bot_destroyed', False)):
            return
        root._image_draw_bot_destroying = True
        try:
            from TaskbarIdentity import clear_window_identity
            try:
                clear_window_identity(root)
            except Exception:
                logging.getLogger(__name__).exception('Taskbar identity cleanup failed')
            try:
                original_destroy()
            except tk.TclError as error:
                # Shutdown paths can converge after Tk/CTk has already torn
                # down the interpreter. Treat only that exact state as a
                # successful no-op; unrelated Tcl errors must still surface.
                if not _already_destroyed_tcl_error(error):
                    raise
            root._image_draw_bot_destroyed = True
        finally:
            root._image_draw_bot_destroying = False

    root.destroy = destroy
    root._image_draw_bot_destroy_wrapped = True


def configure_root(root):
    """Apply the same artwork to this Tcl interpreter and future toplevels.

    Images are retained on their own root, never in a process-global Tk cache.
    Failure to load decorative artwork must not prevent starting the app.
    """
    _install_destroy_guard(root)
    if getattr(root, '_image_draw_bot_branding', False):
        return root
    try:
        from PIL import Image, ImageTk
        with Image.open(resource_path(ICON_PNG)) as image:
            root._image_draw_bot_icons = tuple(
                ImageTk.PhotoImage(image.resize((n,n), Image.Resampling.LANCZOS), master=root)
                for n in (16,32,48,64,128,256))
        root.iconphoto(True, *root._image_draw_bot_icons)
    except Exception:
        return root
    ico = resource_path(ICON_ICO)

    def apply(window):
        try:
            if not window.winfo_exists():
                return
            if sys.platform == 'win32' and ico.is_file():
                # CTk's override also records that its default icon must not win.
                window.iconbitmap(str(ico))
                if window is root:
                    from TaskbarIdentity import set_window_identity
                    set_window_identity(root, APP_USER_MODEL_ID, ico)
            else:
                window.iconphoto(False, *root._image_draw_bot_icons)
        except Exception:
            logging.getLogger(__name__).exception('Could not apply Image Draw Bot window/taskbar icon')

    def mapped(event):
        window = event.widget
        try:
            if window.winfo_toplevel() != window:
                return
            window._image_draw_bot_icon_set = True
            apply(window)
            # CustomTkinter also schedules its default Windows icon at startup.
            pending = getattr(window, '_image_draw_bot_icon_after', None)
            if pending:
                window.after_cancel(pending)
            window._image_draw_bot_icon_after = window.after(300, lambda: apply(window))
        except Exception:
            pass

    apply(root)
    root.after(300, lambda: apply(root))
    root.bind_all('<Map>', mapped, add='+')
    root._image_draw_bot_branding = True
    return root


def header_image(size=42):
    """Use the same high-resolution master for both CustomTkinter themes/DPI."""
    import customtkinter as ctk
    from PIL import Image
    with Image.open(resource_path(ICON_PNG)) as source:
        image = source.convert('RGBA')
    return ctk.CTkImage(light_image=image, dark_image=image, size=(size,size))
