"""UI-thread-only window hiding with idempotent restoration."""
class ScreenTaskWindow:
    def __init__(self,root):
        self.root=root;self.previous=None
    def hide(self):
        if self.root is None or self.previous is not None:return
        self.previous=self.root.state()
        try:
            self.root.iconify()
            self.root.update_idletasks()
        except Exception:
            self.restore();raise
    def restore(self):
        if self.previous is None:return
        previous=self.previous;self.previous=None
        try:
            if not self.root.winfo_exists():return
            if previous=='withdrawn':self.root.withdraw()
            elif previous=='iconic':self.root.iconify()
            else:
                self.root.deiconify()
                if previous=='zoomed':self.root.state('zoomed')
                self.root.lift()
        except Exception:pass

SCREEN_ACTIVITIES=frozenset(('calibration','exact-color-calibration','browser-auto-calibration',
    'browser-one-click-setup','paint-auto-calibration','one-click-verify','screen','record','result-recheck'))
