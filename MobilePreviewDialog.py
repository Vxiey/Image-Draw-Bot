"""One sharing panel whose actions belong to the displayed local session."""
from contextlib import closing
import tkinter as tk


def _release_photo(photo):
    if photo is not None:
        try:
            # A destroyed CTkLabel may remain in Python reference cycles. Its
            # image is ours, so release the native allocation at owner exit.
            photo.tk.call('image', 'delete', str(photo))
        except (tk.TclError, RuntimeError):
            pass


def _cancel_widget_after_jobs(window):
    """Cancel only single-command timers registered by this widget subtree."""
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
                # Each child still owns deletecommand during its normal
                # destroy; cancelling via the panel's after_cancel would
                # remove the command from the wrong Python registry.
                interpreter.call('after', 'cancel', job)
    except (tk.TclError, RuntimeError):
        pass


def _dialog_window_class(base):
    class DialogWindow(base):
        """Scope CTk's native callbacks to this panel, keeping other observers."""
        def __init__(self, *args, **kwargs):
            self._panel_after = set()
            self._panel_bindings = []
            self._panel_destroyed = False
            try:
                super().__init__(*args, **kwargs)
            except BaseException:
                try:
                    self.destroy()
                except (tk.TclError, RuntimeError, AttributeError):
                    pass
                raise

        def bind_all(self, sequence=None, func=None, add=None):
            token = super().bind_all(sequence, func, add)
            if token is not None and func is not None:
                self._panel_bindings.append((self._root(), sequence, token))
            return token

        def after(self, ms, func=None, *args):
            if func is None:
                return super().after(ms)
            from customtkinter.windows.widgets.scaling.scaling_tracker import ScalingTracker
            if func == ScalingTracker.check_dpi_scaling:
                # CTk may start its shared DPI loop on the first widget's
                # Toplevel. Keep that service on the app root when we close.
                return self._root().after(ms, func, *args)

            def run():
                self._panel_after.discard(job)
                if not self._panel_destroyed:
                    func(*args)

            job = super().after(ms, run)
            self._panel_after.add(job)
            return job

        def after_cancel(self, job):
            self._panel_after.discard(job)
            return super().after_cancel(job)

        def destroy(self):
            if self._panel_destroyed:
                return
            self._panel_destroyed = True
            for job in tuple(self._panel_after):
                try:
                    self.after_cancel(job)
                except (tk.TclError, RuntimeError):
                    pass
            bindings, self._panel_bindings = self._panel_bindings, []
            for root, sequence, token in bindings:
                try:
                    root._unbind(('bind', 'all', sequence), token)
                except (tk.TclError, RuntimeError):
                    pass
            _cancel_widget_after_jobs(self)
            super().destroy()

    return DialogWindow


class _MobilePreviewDialog:
    def __init__(self, app, server, url):
        self.app = app
        self.server = server
        self.session = (server.port, server.token)
        self.window = self.address = self.qr = self.photo = None
        self.url = ''
        self.closed = False
        try:
            self._build()
            self.refresh(url)
        except BaseException:
            self.close()
            raise

    def _build(self):
        import customtkinter as ctk
        from WorkspaceLayout import fit_window

        window = self.window = _dialog_window_class(ctk.CTkToplevel)(self.app.root)
        window.bind('<Destroy>', self._destroyed, add='+')
        window.protocol('WM_DELETE_WINDOW', self.close)
        window.title('Mobile Preview')
        fit_window(window, preferred=(620, 610), minimum=(560, 520))
        window.transient(self.app.root)
        window.configure(fg_color='#101319')
        card = ctk.CTkFrame(window, fg_color='#1a202b', corner_radius=18)
        card.pack(fill='both', expand=True, padx=18, pady=18)
        ctk.CTkLabel(card, text='Mobile Preview', font=('Segoe UI', 24, 'bold'),
                    text_color='#f0f4fb').pack(anchor='w', padx=22, pady=(20, 3))
        ctk.CTkLabel(card,
            text='Live preview over your local Wi-Fi/LAN. No cloud, account, telemetry or external scripts.',
            font=('Segoe UI', 11), text_color='#a6b2c5', wraplength=550,
            justify='left').pack(anchor='w', padx=22, pady=(0, 12))
        self.address = ctk.CTkTextbox(card, height=64, fg_color='#101319',
            text_color='#98edce', font=('Consolas', 12), corner_radius=10)
        self.address.pack(fill='x', padx=22, pady=(0, 10))
        self.qr = ctk.CTkLabel(card, text='')
        self.qr.pack(pady=(4, 10))
        ctk.CTkLabel(card,
            text='Phone: connect to the same Wi-Fi/LAN, then scan the QR code or open the address. '
                 'If Windows asks, allow Image Draw Bot on Private networks only.',
            font=('Segoe UI', 11), text_color='#a6b2c5', wraplength=540,
            justify='left').pack(anchor='w', padx=22, pady=(0, 14))
        row = ctk.CTkFrame(card, fg_color='transparent')
        row.pack(fill='x', padx=22, pady=(0, 18))
        ctk.CTkButton(row, text='Copy address', command=self.copy_address,
            fg_color='#315c50', hover_color='#3e7465').pack(side='left')
        ctk.CTkButton(row, text='Open on this PC', command=self.open_local,
            fg_color='#252e3e', hover_color='#36445b').pack(side='left', padx=8)
        ctk.CTkButton(row, text='Stop Mobile Preview', command=self.stop,
            fg_color='#6b3030', hover_color='#814040').pack(side='right')

    def same_session(self, server):
        return (not self.closed and self.server is server and server.running
                and self.session == (server.port, server.token))

    def current(self):
        if (self.closed or getattr(self.app, 'closing', False)
                or getattr(self.app, '_mobile_preview_dialog', None) is not self
                or not self.same_session(getattr(self.app, 'mobile_preview_server', None))):
            return False
        try:
            return bool(self.window.winfo_exists())
        except (tk.TclError, RuntimeError):
            return False

    def _qr_photo(self, url):
        import qrcode
        from PIL import ImageTk

        code = qrcode.QRCode(version=None, box_size=5, border=2)
        code.add_data(url)
        code.make(fit=True)
        generated = code.make_image(fill_color='black', back_color='white')
        with closing(generated.get_image()) as bitmap, closing(bitmap.convert('RGB')) as rgb:
            with closing(rgb.resize((210, 210))) as pixels:
                return ImageTk.PhotoImage(pixels, master=self.window)

    def refresh(self, url):
        try:
            photo = self._qr_photo(url)
        except Exception:
            photo = None
        try:
            self.address.configure(state='normal')
            self.address.delete('1.0', 'end')
            self.address.insert('1.0', url)
            self.address.configure(state='disabled')
            self.qr.configure(image=photo, text='' if photo is not None else
                'QR code unavailable in this build. Copy the address above to your phone.',
                text_color='#a6b2c5', font=('Segoe UI', 11), wraplength=500)
        except BaseException:
            _release_photo(photo)
            raise
        previous = self.photo
        self.qr.image = self.photo = photo
        self.url = url
        _release_photo(previous)

    def copy_address(self):
        if self.current():
            return self.app._copy_mobile_preview_url()
        return False

    def open_local(self):
        if not self.current():
            return False
        try:
            import webbrowser
            return webbrowser.open(self.url)
        except Exception as error:
            self.app.status.set(f'Could not open Mobile Preview in browser: {error}')
            return False

    def stop(self):
        if not self.current():
            return False
        self.app.stop_mobile_preview()
        return True

    def _dispose(self):
        self.closed = True
        self.url = ''
        if self.qr is not None:
            self.qr.image = None
        _release_photo(self.photo)
        self.photo = self.qr = self.address = self.window = None
        if getattr(self.app, '_mobile_preview_dialog', None) is self:
            self.app._mobile_preview_dialog = None

    def _destroyed(self, event):
        if event.widget is self.window:
            self._dispose()

    def close(self):
        if self.closed:
            return
        window = self.window
        self._dispose()
        if window is not None:
            try:
                window.destroy()
            except (tk.TclError, RuntimeError):
                pass


def close_mobile_preview_dialog(app):
    dialog = getattr(app, '_mobile_preview_dialog', None)
    if dialog is not None:
        dialog.close()


def show_mobile_preview_dialog(app, server, url):
    """Refresh or replace only this app's current session panel; own no timers."""
    dialog = getattr(app, '_mobile_preview_dialog', None)
    try:
        if dialog is not None and dialog.current() and dialog.same_session(server):
            dialog.refresh(url)
            dialog.window.deiconify()
            dialog.window.lift()
            return dialog.window
        close_mobile_preview_dialog(app)
        if getattr(app, 'closing', False) or not server.running:
            return None
        dialog = _MobilePreviewDialog(app, server, url)
        app._mobile_preview_dialog = dialog
        if not dialog.current():
            dialog.close()
            return None
        return dialog.window
    except BaseException:
        close_mobile_preview_dialog(app)
        raise
