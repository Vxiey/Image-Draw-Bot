"""Small, explicit Win32 mouse backend.

Cursor movement defaults to SetCursorPos for compatibility, including during drags.
An explicit reliable mode can opt into absolute SendInput movement, but Image Draw Bot
never forces the more aggressive backend merely because Microsoft Paint is active.
"""
import ctypes
from functools import wraps
import sys
import threading
import time
from ctypes import wintypes

LONG = ctypes.c_int32
DWORD = ctypes.c_uint32
ULONG_PTR = ctypes.c_size_t


class Point(ctypes.Structure):
    _fields_ = [('x', LONG), ('y', LONG)]


class MouseInput(ctypes.Structure):
    _fields_ = [
        ('dx', LONG),
        ('dy', LONG),
        ('mouseData', DWORD),
        ('dwFlags', DWORD),
        ('time', DWORD),
        ('dwExtraInfo', ULONG_PTR),
    ]


class InputUnion(ctypes.Union):
    _fields_ = [('mi', MouseInput)]


class Input(ctypes.Structure):
    _anonymous_ = ('data',)
    _fields_ = [('type', DWORD), ('data', InputUnion)]


def normalize_position(x, y, rect):
    """Legacy helper kept for compatibility/tests and absolute-coordinate maths."""
    left, top, width, height = rect
    if width < 2 or height < 2 or not (left <= x < left + width and top <= y < top + height):
        raise ValueError('Mouse position is outside the desktop. Select the drawing area again.')
    return round((x-left)*65535/(width-1)), round((y-top)*65535/(height-1))


def _serialized_input(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        # Keep disarm a barrier: an already authorized command must finish
        # before disarm returns, and a later command must see the revoked arm.
        with self.input_transaction():
            return method(self, *args, **kwargs)
    return call


class WindowsMouse:
    def __init__(self):
        if sys.platform != 'win32':
            raise OSError('Mouse control requires Windows.')

        self.api = ctypes.WinDLL('user32', use_last_error=True)
        self._native_input_lock = threading.RLock()
        self.held = False
        # Input is opt-in. Merely creating Image Draw Bot or switching profiles can
        # never move/click the pointer. GuardedMouse arms input only after an
        # explicit Test mouse / Start drawing action has activated the target.
        self._input_armed = False
        self.configure_precision('High')
        self.drag_backend = 'cursor'

        self.api.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
        self.api.SendInput.restype = wintypes.UINT
        self.api.GetCursorPos.argtypes = [ctypes.POINTER(Point)]
        self.api.GetCursorPos.restype = wintypes.BOOL
        self.api.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        self.api.SetCursorPos.restype = wintypes.BOOL
        self.api.GetSystemMetrics.argtypes = [ctypes.c_int]
        self.api.GetSystemMetrics.restype = ctypes.c_int
        self.api.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self.api.GetAsyncKeyState.restype = ctypes.c_short

    def input_transaction(self):
        """Keep one compound native gesture inside the disarm barrier."""
        # Lazy creation also supports lightweight injected native test backends.
        lock = getattr(self, '_native_input_lock', None)
        if lock is None:
            lock = self.__dict__.setdefault('_native_input_lock', threading.RLock())
        return lock

    def configure_precision(self, level='High'):
        from Precision import profile
        cfg=profile(level)
        self.precision_level=level
        self.position_tolerance=int(cfg['cursor_tolerance_px'])
        self.position_attempts=int(cfg['cursor_attempts'])
        self.position_retry_after=int(cfg['cursor_retry_after'])


    def configure_drag_backend(self, backend='cursor'):
        backend=str(backend or 'cursor').strip().lower()
        if backend not in ('cursor','sendinput'):
            raise ValueError('Unknown drag backend.')
        self.drag_backend=backend

    @property
    def input_armed(self):
        return bool(getattr(self, '_input_armed', False))

    @_serialized_input
    def arm_input(self):
        self._input_armed = False
        # A failed prior LEFTUP still belongs to this backend. Retry that
        # cleanup before an explicit new action can authorize further input.
        self.release()
        down=self.buttons_down()
        if down:
            raise InterruptedError('Release all mouse buttons before starting mouse control: '+', '.join(down)+'.')
        self._check_modifiers()
        self._input_armed = True

    @_serialized_input
    def disarm_input(self):
        # If a drawing was interrupted while the button was held, release first.
        try:
            self.release()
        finally:
            self._input_armed = False

    def _require_input_armed(self):
        if not self.input_armed:
            raise PermissionError(
                'Mouse input is locked. Use Test mouse without clicking or Start drawing to arm it explicitly.'
            )

    def buttons_down(self):
        """Return physical/logical mouse buttons Windows currently reports down."""
        keys=((0x01,'left'),(0x02,'right'),(0x04,'middle'),(0x05,'x1'),(0x06,'x2'))
        return tuple(name for vk,name in keys if self.api.GetAsyncKeyState(vk)&0x8000)

    def _check_modifiers(self):
        """Do not turn an ordinary stroke/control click into a modified action.

        Shift can constrain strokes, Ctrl can change a canvas gesture, and Alt
        or Windows can redirect it into application/system commands. The bot
        never owns these held keys across a mouse gesture. In particular, do
        not send key-up events for keys which belong to the user.
        """
        read = getattr(getattr(self, 'api', None), 'GetAsyncKeyState', None)
        if not callable(read):
            # Older injected native backends may implement cursor input only.
            # Real user32 always exposes the function bound in __init__.
            return
        keys = ((0x10, 'Shift'), (0x11, 'Ctrl'), (0x12, 'Alt'),
                (0x5B, 'Left Windows'), (0x5C, 'Right Windows'))
        down = tuple(name for vk, name in keys if read(vk) & 0x8000)
        if down:
            raise InterruptedError('Stopped: release the held keyboard modifiers before mouse control: '
                                   + ', '.join(down) + '.')

    def desktop_rect(self):
        # SM_X/Y/CX/CYVIRTUALSCREEN = 76,77,78,79
        return tuple(int(self.api.GetSystemMetrics(i)) for i in (76, 77, 78, 79))

    def get_position(self):
        p = Point()
        ctypes.set_last_error(0)
        if not self.api.GetCursorPos(ctypes.byref(p)):
            code = ctypes.get_last_error()
            raise OSError(f'Windows could not read the mouse position (code {code}).')
        return int(p.x), int(p.y)

    def _send(self, flags):
        # Button events are relative and therefore use zero dx/dy.
        event = Input(type=0, mi=MouseInput(0, 0, 0, flags, 0, 0))
        ctypes.set_last_error(0)
        result = self.api.SendInput(1, ctypes.byref(event), ctypes.sizeof(Input))
        if result != 1:
            code = ctypes.get_last_error()
            raise OSError(
                f'Windows did not accept the mouse command (code {code}). '
                'Run Paint and Image Draw Bot at the same privilege level and make sure the desktop is unlocked.'
            )

    def _send_absolute_move(self, x, y):
        """Deliver one non-coalesced absolute move while a Image Draw Bot drag is held."""
        nx, ny = normalize_position(int(x), int(y), self.desktop_rect())
        # MOVE | MOVE_NOCOALESCE | VIRTUALDESK | ABSOLUTE
        flags = 0x0001 | 0x2000 | 0x4000 | 0x8000
        event = Input(type=0, mi=MouseInput(nx, ny, 0, flags, 0, 0))
        ctypes.set_last_error(0)
        result = self.api.SendInput(1, ctypes.byref(event), ctypes.sizeof(Input))
        if result != 1:
            code = ctypes.get_last_error()
            raise OSError(
                f'Windows did not accept the drag movement (code {code}). '
                'Run Paint and Image Draw Bot at the same privilege level and make sure the desktop is unlocked.'
            )

    @_serialized_input
    def move(self, x, y):
        self._require_input_armed()
        x, y = round(x), round(y)
        # Validate against the complete virtual desktop before calling user32.
        normalize_position(x, y, self.desktop_rect())
        def send_position():
            down = self.buttons_down()
            if self.held:
                # Recheck before every native send, including position retries.
                # Only the left button belongs to this drag; other buttons are
                # user input and may open a menu or navigate the target.
                down = tuple(button for button in down if button != 'left')
            if down:
                raise InterruptedError('Stopped: a mouse button is held ('+', '.join(down)+'). Release it before moving the pointer.')
            self._check_modifiers()
            if self.held and getattr(self, 'drag_backend', 'cursor') == 'sendinput':
                self._send_absolute_move(x, y)
                return
            ctypes.set_last_error(0)
            if not self.api.SetCursorPos(x, y):
                code = ctypes.get_last_error()
                raise OSError(
                    f'Windows could not move the pointer to {x},{y} (code {code}). '
                    'Check permissions, Remote Desktop and that the screen is unlocked.'
                )

        send_position()
        actual = self.get_position()
        tolerance=int(getattr(self,'position_tolerance',1))
        attempts=max(1,int(getattr(self,'position_attempts',10)))
        retry_after=max(0,int(getattr(self,'position_retry_after',0)))
        for attempt in range(attempts):
            if max(abs(actual[0]-x), abs(actual[1]-y)) <= tolerance:
                return
            if retry_after and attempt>=retry_after and (attempt-retry_after)%2==0:
                send_position()
            time.sleep(.004 if tolerance==0 else .005)
            actual = self.get_position()
        raise OSError(
            f'The mouse did not reach the target {x},{y}; Windows reports {actual}. '
            'Select the area again and check Windows display scaling.'
        )

    @_serialized_input
    def press(self):
        self._require_input_armed()
        down=self.buttons_down()
        if down:
            raise InterruptedError('Stopped: release all mouse buttons before Image Draw Bot presses the brush.')
        self._check_modifiers()
        self._send(0x0002)  # MOUSEEVENTF_LEFTDOWN
        self.held = True

    @_serialized_input
    def release(self):
        if getattr(self, 'held', False):
            try:
                self._send(0x0004)  # MOUSEEVENTF_LEFTUP
            except BaseException:
                self._input_armed = False
                raise
            # SendInput failure does not release the button. Preserve ownership
            # until an accepted LEFTUP so the next cleanup step can retry it.
            self.held = False

    @_serialized_input
    def click(self):
        # Keep cleanup attached to this press. Otherwise disarm/rearm could
        # start another drag during the pause and this LEFTUP would release it.
        try:
            self.press()
            time.sleep(.02)
        finally:
            self.release()

    def diagnostics(self):
        return {
            'pointer_bits': ctypes.sizeof(ctypes.c_void_p) * 8,
            'input_size': ctypes.sizeof(Input),
            'desktop_rect': self.desktop_rect(),
            'cursor': self.get_position(),
            'input_armed': self.input_armed,
            'precision': getattr(self,'precision_level','High'),
            'position_tolerance_px': getattr(self,'position_tolerance',0),
            'drag_move_backend': ('SendInput absolute' if getattr(self,'drag_backend','cursor')=='sendinput' else 'SetCursorPos compatible'),
        }
