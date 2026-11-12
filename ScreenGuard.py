"""Windows window/position checks before mouse input. No input on import."""
import ctypes
import math
import os
import time
from contextlib import contextmanager, nullcontext
from ctypes import wintypes

from DpiSupport import get_window_dpi_info


def _screen_point(point):
    """Validate before crossing the signed 32-bit Win32 coordinate boundary."""
    try:
        x, y = map(int, point)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError('Screen coordinates must be two finite integers.') from error
    if not all(-(2**31) <= value < 2**31 for value in (x, y)):
        raise ValueError('Screen coordinates are outside the Windows coordinate range.')
    return x, y


def _capture_box(box, *, max_pixels=64_000_000, max_side=32768):
    left, top, right, bottom = map(int, box)
    _screen_point((left, top)); _screen_point((right - 1, bottom - 1))
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0 or max(width, height) > max_side or width * height > max_pixels:
        raise ValueError('The screen capture area is empty or too large. Select a smaller visible area.')
    return left, top, right, bottom


def _grab_rgb(box):
    """Return one owned RGB image; release the original capture on conversion."""
    from PIL import ImageGrab
    box = _capture_box(box)
    captured = ImageGrab.grab(bbox=box, all_screens=True)
    try:
        if captured.size != (box[2] - box[0], box[3] - box[1]):
            raise InterruptedError('The screen capture size changed. Check display scaling and select the area again.')
        if captured.mode == 'RGB':
            result = captured
            captured = None
            return result
        return captured.convert('RGB')
    finally:
        if captured is not None:
            captured.close()


@contextmanager
def _sample_rgb(box):
    image = _grab_rgb(box)
    try:
        yield image
    finally:
        image.close()


def _box_probes(box):
    left, top, right, bottom = box
    return ((left, top), (right - 1, top), (left, bottom - 1),
            (right - 1, bottom - 1), ((left + right) // 2, (top + bottom) // 2))


def _nearest_rgb_scalar(image, bounds, stride, expected, rgb_error, best):
    left, top, right, bottom = bounds
    for y in range(top, bottom, stride):
        for x in range(left, right, stride):
            rgb = image.getpixel((x, y))
            error = rgb_error(rgb, expected)
            if best is None or error < best[0]:
                best = (error, x, y, rgb)
    return best


def _nearest_rgb_grid(image, bounds, stride, expected, rgb_error, best=None):
    """Search the existing sample grid in bounded strips, preserving scalar ties.

    Byte RGB distances have exact integer weights 30/59/11. Only colours tied
    at that minimum need the original floating-point metric: its rounding can
    distinguish mathematical ties. Preserve their first row-major occurrence,
    including the coarse winner supplied to the refinement pass.
    """
    left, top, right, bottom = bounds
    columns = len(range(left, right, stride))
    sample_rows = len(range(top, bottom, stride))
    if not columns or not sample_rows:
        return best
    if (columns * sample_rows <= 256 or len(expected) != 3
            or any(value < 0 or value > 255 for value in expected)):
        # Small fields/refinement patches need no NumPy allocation. Keep the
        # legacy behaviour for non-byte callers too; Paint uses validated RGB.
        return _nearest_rgb_scalar(image, bounds, stride, expected, rgb_error, best)

    import numpy as np
    # Bound both the native crop and NumPy scratch arrays, including very narrow
    # grids and a caller-requested stride larger than the capture itself.
    rows = max(1, min(64 // stride, 16384 // columns))
    pixels = samples = delta = scores = indices = tied = packed = first = None
    try:
        for y in range(top, bottom, rows * stride):
            end = min(bottom, y + (rows - 1) * stride + 1)
            with image.crop((left, y, right, end)) as strip:
                pixels = np.asarray(strip, dtype=np.uint8)
                samples = pixels[::stride, ::stride].reshape(-1, 3)
                delta = samples.astype(np.int32) - np.asarray(expected, dtype=np.int32)
                scores = (delta[:, 0] * delta[:, 0] * 30
                          + delta[:, 1] * delta[:, 1] * 59
                          + delta[:, 2] * delta[:, 2] * 11)
                indices = np.flatnonzero(scores == scores.min())
                tied = samples[indices]
                packed = (tied[:, 0].astype(np.uint32) << 16
                          | tied[:, 1].astype(np.uint32) << 8
                          | tied[:, 2].astype(np.uint32))
                first = np.unique(packed, return_index=True)[1]
                for candidate in np.sort(first):
                    index = int(indices[candidate])
                    rgb = tuple(map(int, samples[index]))
                    error = rgb_error(rgb, expected)
                    if best is None or error < best[0]:
                        best = (error, left + (index % columns) * stride,
                                y + (index // columns) * stride, rgb)
        return best
    except MemoryError:
        # This numeric fast path is optional. Its already captured pixels can
        # still be searched exactly by the constant-space scalar implementation.
        pass
    finally:
        # Diagnostic tracebacks must not retain the private screen-pixel exports.
        pixels = samples = delta = scores = indices = tied = packed = first = None
    return _nearest_rgb_scalar(image, bounds, stride, expected, rgb_error, best)


class WindowMonitor:
    def __init__(self):
        # Explicit signatures reduce the chance of ctypes using an incorrect
        # default integer ABI on 64-bit Windows.
        self.api=ctypes.WinDLL('user32', use_last_error=True)
        self.api.WindowFromPoint.argtypes=[wintypes.POINT]
        self.api.WindowFromPoint.restype=wintypes.HWND
        self.api.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT]
        self.api.GetAncestor.restype=wintypes.HWND
        self.api.GetWindow.argtypes=[wintypes.HWND,wintypes.UINT]
        self.api.GetWindow.restype=wintypes.HWND
        self.api.GetForegroundWindow.argtypes=[]
        self.api.GetForegroundWindow.restype=wintypes.HWND
        self.api.SetForegroundWindow.argtypes=[wintypes.HWND]
        self.api.SetForegroundWindow.restype=wintypes.BOOL
        self.api.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
        self.api.GetWindowRect.restype=wintypes.BOOL
        self.api.GetClientRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
        self.api.GetClientRect.restype=wintypes.BOOL
        self.api.ClientToScreen.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.POINT)]
        self.api.ClientToScreen.restype=wintypes.BOOL
        self.api.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
        self.api.GetWindowThreadProcessId.restype=wintypes.DWORD
        self.api.IsWindow.argtypes=[wintypes.HWND]
        self.api.IsWindow.restype=wintypes.BOOL
        self.api.IsWindowVisible.argtypes=[wintypes.HWND]
        self.api.IsWindowVisible.restype=wintypes.BOOL
        self.api.IsIconic.argtypes=[wintypes.HWND]
        self.api.IsIconic.restype=wintypes.BOOL
        try:
            self.api.GetDpiForWindow.argtypes=[wintypes.HWND]
            self.api.GetDpiForWindow.restype=wintypes.UINT
        except AttributeError:
            pass

    def _validate_handle(self,handle):
        if not handle or not self.api.IsWindow(handle):
            raise InterruptedError('The target window no longer exists. Select the drawing area again.')
        if not self.api.IsWindowVisible(handle):
            raise InterruptedError('The target window is not visible. Restore it and select the drawing area again.')
        bound = getattr(self, '_locked_target_identity', None)
        if bound is not None and handle == bound[0]:
            if self._process_identity(handle) != bound[1:]:
                raise InterruptedError('Stopped: the target window identity changed. Select the drawing area again.')
        return handle

    def _process_identity(self, handle):
        pid = wintypes.DWORD()
        thread = self.api.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        if not thread or not pid.value:
            raise InterruptedError('The target window identity could not be verified. Select the drawing area again.')
        return int(pid.value), int(thread)

    def lock_target(self, target):
        """Bind input to the owner observed before foreground activation.

        HWND values are reusable. Matching foreground/geometry alone must not
        authorize a replacement process or UI thread midway through a draw.
        An existing binding is checked before it can be refreshed, so rearming
        the same guard cannot silently adopt a recycled target.
        """
        handle, rectangle = target
        if self.rectangle(handle) != rectangle:
            raise InterruptedError('The target window moved or changed size. Select the drawing area again.')
        identity = self._process_identity(handle)
        self._locked_target_identity = (handle, *identity)
        # Catch replacement during the initial read before any activation.
        self._validate_handle(handle)

    def at(self,point):
        handle=self.api.WindowFromPoint(wintypes.POINT(*_screen_point(point)))
        return self.api.GetAncestor(handle,2) if handle else None

    def rectangle(self,handle):
        self._validate_handle(handle)
        rect=wintypes.RECT()
        ctypes.set_last_error(0)
        if not self.api.GetWindowRect(handle,ctypes.byref(rect)):
            code=ctypes.get_last_error()
            raise InterruptedError(f'Windows could not read the target window position (code {code}). Select the drawing area again.')
        return rect.left,rect.top,rect.right,rect.bottom

    def client_rectangle(self,handle):
        """Return the drawable client rectangle in physical screen coordinates."""
        self._validate_handle(handle)
        rect=wintypes.RECT()
        if not self.api.GetClientRect(handle,ctypes.byref(rect)):
            code=ctypes.get_last_error()
            raise InterruptedError(f'Windows could not read the target client area (code {code}).')
        origin=wintypes.POINT(0,0)
        if not self.api.ClientToScreen(handle,ctypes.byref(origin)):
            code=ctypes.get_last_error()
            raise InterruptedError(f'Windows could not map the target client area (code {code}).')
        return origin.x,origin.y,origin.x+(rect.right-rect.left),origin.y+(rect.bottom-rect.top)

    def in_client_area(self,handle,point):
        left,top,right,bottom=self.client_rectangle(handle)
        x,y=map(int,point)
        return left<=x<right and top<=y<bottom

    def dpi_info(self,handle):
        self._validate_handle(handle)
        return get_window_dpi_info(handle, user32=self.api)

    def dpi(self,handle):
        return int(self.dpi_info(handle).dpi)

    def capture(self,area,excluded_pids=()):
        x,y,w,h=map(int,area)
        if w < 10 or h < 10:
            raise ValueError('The drawing area is too small. Select at least 10 × 10 pixels.')
        _capture_box((x,y,x+w,y+h))
        handle=self.at((x+w//2,y+h//2))
        pid=wintypes.DWORD()
        if not handle:raise ValueError('No window was found under the drawing area.')
        if not self.api.GetWindowThreadProcessId(handle,ctypes.byref(pid)) or not pid.value:
            raise ValueError('The target window disappeared before its process could be verified. Select the area again.')
        excluded={int(value) for value in excluded_pids if value is not None}
        if pid.value==os.getpid() or pid.value in excluded:
            raise ValueError('You selected the Image Draw Bot window. Move it aside and select the target application.')
        # Probe points slightly inside the rectangle. Borders, resize handles and
        # shadows can belong to another HWND even though the drawing surface is
        # entirely inside the intended top-level window.
        inset_x=min(2,max(0,w//4));inset_y=min(2,max(0,h//4))
        points=_box_probes((x+inset_x,y+inset_y,x+w-inset_x,y+h-inset_y))
        if any(self.at(p)!=handle for p in points):
            raise ValueError('The drawing area is covered by different windows. Select it again in the target application.')
        left,top,right,bottom=self.client_rectangle(handle)
        if any(not (left<=px<right and top<=py<bottom) for px,py in points):
            raise ValueError('The drawing area touches the title bar/window border. Select only the drawable client area.')
        return handle,self.rectangle(handle)

    def activate(self,target):
        handle,rectangle=target
        if self.rectangle(handle)!=rectangle:
            raise InterruptedError('The target window moved or changed size. Select the drawing area again.')
        if self.api.IsIconic(handle):
            raise InterruptedError('The target window is minimized. Restore it and try again.')
        ctypes.set_last_error(0)
        return bool(self.api.SetForegroundWindow(handle))

    def active(self,target):
        handle,rectangle=target
        if self.rectangle(handle)!=rectangle:
            raise InterruptedError('The target window moved or changed size. Select the drawing area again.')
        return self.api.GetForegroundWindow()==handle

    def color(self,point):
        from Colors import sample_screen_color
        return tuple(sample_screen_color(*point))

    def colors(self,points):
        from Colors import sample_screen_colors
        return sample_screen_colors(points)

    def colors_near(self,point,radius=2):
        """Sample a small screen patch around a rendered stroke.

        Modern Paint can anti-alias or slightly offset a freehand stroke, so the
        verifier samples a bounded neighborhood instead of trusting one pixel.
        """
        from Colors import sample_screen_colors
        x,y=map(int,point);radius=max(0,min(6,int(radius)))
        points=[(x+dx,y+dy) for dy in range(-radius,radius+1) for dx in range(-radius,radius+1)]
        return sample_screen_colors(points)

    def colors_near_many(self, points, radius=2):
        from ScreenPixelSampling import sample_screen_color_groups
        radius = max(0, min(6, int(radius)))
        groups = []
        for point in points:
            x, y = _screen_point(point)
            groups.append([(x + dx, y + dy)
                           for dy in range(-radius, radius + 1)
                           for dx in range(-radius, radius + 1)])
        return sample_screen_color_groups(groups)

    def verify(self,target,point):
        handle,rectangle=target
        if self.api.GetForegroundWindow()!=handle:
            raise InterruptedError('Stopped: the wrong window is active. Switch to the target application and start again manually.')
        if self.rectangle(handle)!=rectangle:
            raise InterruptedError('Stopped: the target window moved or changed size. Select the drawing area again.')
        if self.at(point)!=handle:
            raise InterruptedError('Stopped: another window covers the click position.')
        if not self.in_client_area(handle,point):
            raise InterruptedError('Stopped: the pointer would enter the title bar/window border. Select only the drawable client area.')

    def verify_modal(self,target,point):
        """Allow the locked window or its owned foreground dialog, never a stranger."""
        handle,rectangle=target
        if self.rectangle(handle)!=rectangle:
            raise InterruptedError('Stopped: target window geometry changed while the custom-color dialog was open.')
        foreground=self.api.GetForegroundWindow()
        self._validate_handle(foreground)
        owner=foreground
        visited=set()
        for _ in range(32):
            if owner==handle:
                break
            if not owner or owner in visited:
                raise InterruptedError('Stopped: the active color dialog does not belong to the locked target window.')
            visited.add(owner)
            owner=self.api.GetWindow(owner,4)  # GW_OWNER; bounded against stale/cyclic HWNDs.
        else:
            raise InterruptedError('Stopped: the color dialog ownership could not be verified.')
        if self.api.IsIconic(foreground) or self.at(point)!=foreground or not self.in_client_area(foreground,point):
            raise InterruptedError('Stopped: the calibrated color control is covered or outside the active target dialog.')


class GuardedMouse:
    def __init__(self,mouse,monitor,target,palette_colors=None,live_target_check=None):
        self.mouse,self.monitor,self.target=mouse,monitor,target
        self.last=None
        self.palette_colors=palette_colors or {}
        self.last_palette_check=0
        self.palette_verified=False
        self.tracking_tolerance=4
        self.precision_level='High'
        # v1.0.25: optional live setup/fingerprint monitor supplied by DrawBot.
        # GuardedMouse remains generic; the callback may check DPI, client rect,
        # drawing-area lock, palette/tool fingerprint and other app-specific gates.
        self.live_target_check=live_target_check
        self.manual_movement_confirm_seconds=0.014
        self.transient_cover_retry_seconds=0.08

    def configure_precision(self,level='High'):
        from Precision import profile
        cfg=profile(level)
        self.precision_level=level
        self.tracking_tolerance=int(cfg['tracking_tolerance_px'])
        if hasattr(self.mouse,'configure_precision'):
            self.mouse.configure_precision(level)

    def configure_drag_backend(self, backend='cursor'):
        if hasattr(self.mouse,'configure_drag_backend'):
            self.mouse.configure_drag_backend(backend)

    def prepare_target(self,stop,wait,report):
        # Activation may be denied by Windows. Wait without moving/clicking.
        self._stop_event = stop
        if stop.is_set():raise InterruptedError()
        lock_target = getattr(self.monitor, 'lock_target', None)
        if callable(lock_target):
            lock_target(self.target)
        if stop.is_set():raise InterruptedError()
        self.monitor.activate(self.target)
        for attempt in range(81):
            if stop.is_set():raise InterruptedError()
            if self.monitor.active(self.target):
                if stop.is_set():raise InterruptedError()
                # This is the only transition that arms the native mouse backend,
                # and prepare_target is called only by explicit test/draw actions.
                if hasattr(self.mouse,'arm_input'):self.mouse.arm_input()
                self.reset_tracking();return
            if attempt==80:break
            if attempt%4==0:
                report('status',f'Waiting for the target window ({20-attempt//4} s). Select Paint/the target app with Alt+Tab. Esc cancels.')
            wait(.25)
        raise InterruptedError('The target window did not become active within 20 seconds. Select the drawing area in the correct window and try again.')

    def reset_tracking(self):
        self.last=None

    def _check_stop(self):
        stop = getattr(self, '_stop_event', None)
        if stop is not None and stop.is_set():
            raise InterruptedError('Mouse operation cancelled.')

    def _wait(self, seconds):
        """Wake verification/settling waits immediately when this draw stops."""
        stop = getattr(self, '_stop_event', None)
        wait = getattr(stop, 'wait', None)
        if not callable(wait):
            # Existing embedders may supply an is_set-only cancellation token.
            self._check_stop()
            time.sleep(seconds)
            self._check_stop()
        elif wait(seconds):
            raise InterruptedError('Mouse operation cancelled.')

    def disarm_input(self):
        if hasattr(self.mouse,'disarm_input'):self.mouse.disarm_input()
        self.last=None

    def check(self,point=None):
        self._check_stop()
        current=self.mouse.get_position()
        if self.live_target_check is not None:
            self.live_target_check(self.monitor,self.target,current if point is None else point)
            current=self.mouse.get_position()
        verify_point=current if point is None else point
        try:
            self.monitor.verify(self.target,verify_point)
        except InterruptedError as error:
            # Tooltips/transient overlays can momentarily own WindowFromPoint even
            # though Paint is still foreground. Retry once before treating a cover
            # as a real safety failure. Geometry/foreground failures still stop
            # immediately because their messages do not match this branch.
            if 'another window covers the click position' not in str(error):
                raise
            self._wait(float(getattr(self,'transient_cover_retry_seconds',0.08)))
            current=self.mouse.get_position()
            verify_point=current if point is None else point
            if self.live_target_check is not None:
                self.live_target_check(self.monitor,self.target,verify_point)
                current=self.mouse.get_position()
                verify_point=current if point is None else point
            self.monitor.verify(self.target,verify_point)
        # Palette geometry/color is verified once before any UI click. Rechecking
        # it after selecting a color can false-trigger because Paint may draw a
        # selection indicator around the active swatch.
        if self.palette_colors and not self.palette_verified:
            self.verify_palette_layout()
            current=self.mouse.get_position()
            self.monitor.verify(self.target,current if point is None else point)
        if self.last is not None:
            tolerance=max(1,int(getattr(self,'tracking_tolerance',4)))
            delta=max(abs(current[i]-self.last[i]) for i in (0,1))
            if delta>tolerance:
                # A single cursor read can catch the tail of our own Windows move.
                # Confirm the deviation once before declaring manual takeover.
                self._wait(float(getattr(self,'manual_movement_confirm_seconds',0.014)))
                confirmed=self.mouse.get_position()
                confirmed_delta=max(abs(confirmed[i]-self.last[i]) for i in (0,1))
                if confirmed_delta>tolerance:
                    raise InterruptedError(
                        f'Stopped: the mouse was moved manually (delta {confirmed_delta}px). No automatic restart.'
                    )
                self.monitor.verify(self.target,confirmed if point is None else point)
        self._check_stop()

    def verify_palette_layout(self):
        if not self.palette_colors:
            self.palette_verified=True;return
        handle,rectangle=self.target
        if self.monitor.rectangle(handle)!=rectangle:
            raise InterruptedError('Stopped before input: the target window changed geometry. Select the drawing area again.')
        mismatches=[]
        entries=tuple(self.palette_colors.items())
        if hasattr(self.monitor,'colors'):
            actual_colors=self.monitor.colors([position for position,_ in entries])
            if len(actual_colors)!=len(entries):
                raise InterruptedError('Stopped before input: the entire calibrated palette could not be sampled.')
        else:
            actual_colors=[self.monitor.color(position) for position,_ in entries]
        for (position,rgb),actual in zip(entries,actual_colors):
            error=max(abs(int(actual[i])-int(rgb[i])) for i in (0,1,2))
            if error>45:mismatches.append((position,tuple(rgb),tuple(actual),error))
        if mismatches:
            pos,expected,actual,error=max(mismatches,key=lambda row:row[3])
            raise InterruptedError(
                f'Stopped before input: the calibrated color palette no longer matches the selected drawing application at {pos}. '
                f'Expected {expected}, saw {actual}. Keep the target application at the calibrated window size with its palette/tool UI visible, then recalibrate colors. '
                'No mouse input was sent.')
        self.palette_verified=True;self.last_palette_check=time.monotonic()

    def move(self,x,y):
        self.check((x,y));self.mouse.move(x,y)
        # Track the actual Windows cursor endpoint rather than the requested point.
        # This avoids treating a harmless one-pixel rounding/settling difference as
        # user takeover on the next guarded move.
        self.last=self.mouse.get_position()

    def click(self):
        # Keep button-down visible to event loops; release even on cancellation/errors.
        self.check()
        self._click_with_settle()

    def _click_with_settle(self):
        transaction = getattr(self.mouse, 'input_transaction', None)
        # The native backend owns the complete gesture, including its release.
        # Other injected backends retain their established press/release API.
        with transaction() if callable(transaction) else nullcontext():
            try:
                self.mouse.press();self._wait(.015)
            finally:self.mouse.release()

    def _check_modal_geometry(self,point=None):
        """Keep modal color-picker sampling tied to the originally locked target."""
        self._check_stop()
        handle,rectangle=self.target
        if self.monitor.rectangle(handle)!=rectangle:
            raise InterruptedError('Stopped: target window geometry changed while the custom-color dialog was open.')
        if point is not None:
            verifier=getattr(self.monitor,'verify_modal',None) or getattr(self.monitor,'verify',None)
            if not callable(verifier):
                raise InterruptedError('Stopped: this screen monitor cannot verify the calibrated color dialog.')
            verifier(self.target,_screen_point(point))

    @staticmethod
    def _rgb_error(actual, expected):
        # Weighted RGB is inexpensive and tracks visual error better than raw max-channel
        # distance for the rendered picker spectrum. Exact stroke verification still
        # happens later on the canvas.
        ar,ag,ab=map(int,actual);er,eg,eb=map(int,expected)
        return ((ar-er)**2*0.30+(ag-eg)**2*0.59+(ab-eb)**2*0.11) ** .5

    def calibrated_modal_nearest_color_rect(self, corner_a, corner_b, expected, max_samples=70000):
        """Read a calibrated 2-D color spectrum and return its nearest visible RGB point.

        The picker may be a separate modal HWND. Its ownership and visible control
        bounds are checked against the locked target before reading any pixels.
        """
        import math
        self._check_modal_geometry()
        x0,y0=_screen_point(corner_a);x1,y1=_screen_point(corner_b)
        left,right=sorted((x0,x1));top,bottom=sorted((y0,y1))
        width=max(1,right-left+1);height=max(1,bottom-top+1)
        if width>1800 or height>1800 or width*height>2_000_000:
            raise ValueError('The calibrated custom color spectrum is too large. Recalibrate only the visible color field.')
        box=(left,top,right+1,bottom+1)
        for point in _box_probes(box):self._check_modal_geometry(point)
        expected=tuple(map(int,expected))
        stride=max(1,int(math.ceil(math.sqrt((width*height)/max(1,int(max_samples))))))
        best=None
        with _sample_rgb(box) as shot:
            best=_nearest_rgb_grid(shot,(0,0,width,height),stride,expected,self._rgb_error)
            if best is None:raise ValueError('Could not read the calibrated color spectrum.')
            _,bx,by,_=best
            radius=max(2,stride+1)
            best=_nearest_rgb_grid(shot,(max(0,bx-radius),max(0,by-radius),
                min(width,bx+radius+1),min(height,by+radius+1)),1,
                expected,self._rgb_error,best)
        err,bx,by,rgb=best
        return (left+bx,top+by),tuple(map(int,rgb)),float(err)

    def calibrated_modal_nearest_color_line(self, point_a, point_b, expected, samples=320):
        """Find the closest rendered color along a calibrated brightness/value scale."""
        self._check_modal_geometry()
        x0,y0=_screen_point(point_a);x1,y1=_screen_point(point_b);expected=tuple(map(int,expected))
        left,right=sorted((x0,x1));top,bottom=sorted((y0,y1))
        pad=2
        box=_capture_box((left-pad,top-pad,right+pad+1,bottom+pad+1),max_pixels=2_000_000,max_side=1804)
        for point in (point_a,point_b):self._check_modal_geometry(point)
        best=None;n=max(2,min(1200,int(samples)))
        with _sample_rgb(box) as shot:
            for i in range(n):
                t=i/(n-1);sx=round(x0+(x1-x0)*t);sy=round(y0+(y1-y0)*t)
                px=max(0,min(shot.width-1,sx-(left-pad)));py=max(0,min(shot.height-1,sy-(top-pad)))
                rgb=shot.getpixel((px,py));err=self._rgb_error(rgb,expected)
                if best is None or err<best[0]:best=(err,sx,sy,rgb)
        if best is None:raise ValueError('Could not read the calibrated brightness scale.')
        err,sx,sy,rgb=best
        return (sx,sy),tuple(map(int,rgb)),float(err)

    def calibrated_modal_color(self, point, radius=2):
        """Read a calibrated preview swatch robustly using the local median RGB.

        A single pixel can land on an antialiased border/cursor. Sampling a tiny
        patch around the captured swatch point makes exact-color verification much
        less likely to accept or reject the wrong RGB because of one bad pixel.
        """
        import numpy as np
        self._check_modal_geometry(point);x,y=_screen_point(point);r=max(0,min(6,int(radius)))
        with _sample_rgb((x-r,y-r,x+r+1,y+r+1)) as shot:
            arr=np.asarray(shot,dtype=np.uint8).reshape(-1,3)
            return tuple(int(v) for v in np.median(arr,axis=0))

    def calibrated_modal_click(self, point):
        """Click one explicitly calibrated modal-dialog control safely.

        The foreground dialog must belong to the locked target. Recheck after
        moving the cursor, since focus or an overlay can change during movement.
        """
        self._check_modal_geometry(point)
        current=self.mouse.get_position()
        if self.last is not None and max(abs(current[i]-self.last[i]) for i in (0,1))>getattr(self,'tracking_tolerance',4):
            raise InterruptedError('Stopped: the mouse was moved manually while selecting an exact color.')
        self.mouse.move(*_screen_point(point));self.last=self.mouse.get_position()
        self._check_modal_geometry(self.last)
        self._click_with_settle()

    def press(self):
        self.check();self.mouse.press()

    def check_keyboard(self,modal_point=None):
        """Revalidate focus immediately before a keyboard command or RGB write."""
        if modal_point is None:
            self.check()
        else:
            self._check_modal_geometry(modal_point)
        check_modifiers=getattr(self.mouse,'_check_modifiers',None)
        if callable(check_modifiers):check_modifiers()
        self._check_stop()

    def release(self):
        self.mouse.release()

    @staticmethod
    def _ink_probe_points(start,end):
        x1,y1=map(int,start);x2,y2=map(int,end)
        if (x1,y1)==(x2,y2):return [(x1,y1)]
        # Avoid only sampling the endpoints: the cursor and Paint's rounded caps
        # can make endpoint pixels less representative than the middle section.
        return [(round(x1+(x2-x1)*t),round(y1+(y2-y1)*t)) for t in (.2,.35,.5,.65,.8)]

    def inspect_ink_segment(self,start,end,expected,brush_px=1,tolerance=48):
        """Measure the rendered color of one stroke without deciding recovery policy.

        v1.0.35 uses this for one verification per color batch.  The caller can
        retry a different color-selection method and overwrite the same probe
        stroke instead of aborting the entire drawing immediately.
        """
        expected=tuple(map(int,expected));tolerance=max(1,min(120,int(tolerance)))
        points=self._ink_probe_points(start,end)
        for point in points:self.check(point)
        radius=max(2,min(6,int(round(max(1,int(brush_px))/2))+2))
        best_error=999;best=None;sample_count=0
        for settle in (0.0,0.08,0.18,0.32):
            if settle:
                self._wait(settle)
                for point in points:self.check(point)
            sample_many = getattr(self.monitor, 'colors_near_many', None)
            if callable(sample_many):
                samples = sample_many(points, radius)
            else:
                samples=[]
                for point in points:
                    try:samples.extend(self.monitor.colors_near(point,radius))
                    except AttributeError:samples.append(self.monitor.color(point))
            # A capture can yield to another application just like a settle
            # delay. Never accept matching pixels under stale focus evidence.
            for point in points:self.check(point)
            if not samples:continue
            sample_count+=len(samples)
            scored=[(max(abs(int(actual[i])-expected[i]) for i in range(3)),tuple(map(int,actual))) for actual in samples]
            error,color=min(scored,key=lambda item:item[0])
            if error<best_error:best_error,best=error,color
            if best_error<=tolerance:break
        if best is None:
            best=tuple(map(int,self.monitor.color(points[len(points)//2])))
            self.check(points[len(points)//2])
            best_error=max(abs(best[i]-expected[i]) for i in range(3))
            sample_count+=1
        confidence=max(0.0,min(100.0,100.0*(1.0-float(best_error)/255.0)))
        expected_luma=sum(expected)/3;best_luma=sum(best)/3
        # Do not infer transparency/opacity from a single failed RGB probe. A light
        # sample can also be unchanged canvas/background, a missed stroke, a stale
        # palette coordinate, or a probe that landed beside a very thin Pencil line.
        # The verifier reports only what it can actually observe; recovery policy is
        # decided by DrawBot after trying the available safe color selectors.
        if expected_luma<80 and best_luma>180:
            failure_kind='stroke-or-selection-mismatch'
            reason=('The expected dark ink was not found in the sampled stroke area. '
                    'The sample may still be canvas/background, the stroke may not have been delivered, '
                    'or Paint may have selected a different color.')
        elif expected_luma<80 and 20<best_luma<=180:
            failure_kind='weak-dark-ink'
            reason=('Paint produced dark ink, but it was much lighter than the requested color. '
                    'If Brush is selected, verify the solid preset and 100% opacity; otherwise re-check the selected color.')
        else:
            failure_kind='color-mismatch'
            reason='The rendered stroke color does not match the requested color closely enough.'
        return {'matched':best_error<=tolerance,'expected':expected,'actual':best,'error':int(best_error),
                'confidence':confidence,'sample_count':sample_count,'reason':reason,'failure_kind':failure_kind}

    @staticmethod
    def _ink_site_sample_indices(points,radius):
        """Assign each physical sample pixel to its nearest distinct site once."""
        owners={}
        for site,(x,y) in enumerate(points):
            offset=0
            for dy in range(-radius,radius+1):
                for dx in range(-radius,radius+1):
                    pixel=(x+dx,y+dy);distance=dx*dx+dy*dy
                    previous=owners.get(pixel)
                    if previous is None or distance<previous[0]:
                        owners[pixel]=(distance,site,offset)
                    offset+=1
        indices=[[] for _ in points]
        for _distance,site,offset in owners.values():indices[site].append(offset)
        return indices

    def inspect_ink_coverage(self,start,end,expected,brush_px=1,tolerance=48):
        """Require ink in a majority of distinct sites on the delivered segment.

        A nearest color anywhere is useful for Paint color selection, but does
        not confirm that a browser delivered the rest of a long stroke. Keep
        that existing API separate. Matches from different settling attempts
        never accumulate, and overlapping patches cannot count one physical
        pixel for several sites. Sparse/cross-monitor capture fallbacks observe
        sites successively; this is a static-ink sampling heuristic, not proof
        of one atomic display frame or an exact pixel-accuracy score.
        """
        expected=tuple(map(int,expected));tolerance=max(1,min(120,int(tolerance)))
        points=tuple(dict.fromkeys(self._ink_probe_points(start,end)))
        radius=max(2,min(6,int(round(max(1,int(brush_px))/2))+2))
        patch_size=(2*radius+1)**2
        site_indices=self._ink_site_sample_indices(points,radius)
        required=max(1,math.ceil(len(points)*.6))
        best=None;sample_count=0
        for settle in (0.0,.08,.18,.32):
            if settle:self._wait(settle)
            for point in points:self.check(point)
            sample_many=getattr(self.monitor,'colors_near_many',None)
            if callable(sample_many):
                samples=sample_many(points,radius)
                # Native grouped reads have a fixed square-patch contract. An
                # incomplete response must not shift colors into another site.
                complete=len(samples)==len(points)*patch_size
                sample_count+=len(samples)
                groups=[[samples[i*patch_size+j] for j in indices]
                        for i,indices in enumerate(site_indices)] if complete else []
            else:
                sample_point=getattr(self.monitor,'color',None)
                if not callable(sample_point):
                    # Preserve the established color-only API for injected
                    # providers which cannot identify physical sample sites.
                    result=self.inspect_ink_segment(start,end,expected,brush_px,tolerance)
                    result['coverage_unavailable']='provider has no located pixel samples'
                    return result
                groups=[]
                for point in points:
                    self._check_stop()
                    groups.append([sample_point(point)])
                    sample_count+=1
                complete=all(bool(group) for group in groups)
            for point in points:self.check(point)
            matched=0;closest=None;closest_error=999
            for group in groups:
                error=999
                for actual in group:
                    actual=tuple(map(int,actual))
                    distance=max(abs(actual[i]-expected[i]) for i in range(3))
                    error=min(error,distance)
                    if distance<closest_error:closest_error,closest=distance,actual
                matched+=error<=tolerance
            payload={'matched':bool(complete and matched>=required),
                     'expected':expected,'actual':closest,'error':closest_error,
                     'confidence':100.0*matched/len(points),
                     'matched_sites':matched,'tested_sites':len(points),'required_sites':required,
                     'sample_count':sample_count,'failure_kind':'partial-stroke',
                     'reason':(f'Expected ink found at {matched}/{len(points)} sampled stroke sites '
                               f'({required} required).' if complete else 'Incomplete stroke-neighborhood capture.')}
            if best is None or matched>best['matched_sites'] or (
                    matched==best['matched_sites'] and closest_error<best['error']):
                best=payload
            self._check_stop()
            if payload['matched']:return payload
        best['sample_count']=sample_count
        self._check_stop()
        return best

    def verify_ink_segment(self,start,end,expected,brush_px=1):
        """Backward-compatible strict verifier used by older callers/plugins."""
        result=self.inspect_ink_segment(start,end,expected,brush_px)
        if result['matched']:return result
        raise InterruptedError(
            f"Stopped: the first stroke did not get the expected color {result['expected']}. "
            f"Closest rendered RGB was {result['actual']} after sampling {result['sample_count']} pixels along the stroke. "
            f"{result['reason']} Re-check the palette/tool calibration and retry the small test. "
            'Adaptive color verification could not confirm this stroke.')

    def snapshot_colors(self,points):
        """Capture bounded guard pixels before a risky fill operation."""
        values=[]
        for point in points:
            self.check(point)
            values.append(tuple(map(int,self.monitor.color(point))))
        return values

    def verify_unchanged(self,points,before,tolerance=65):
        """Stop if a Fill appears to have escaped a closed region."""
        if len(points)!=len(before):
            raise ValueError('Fill guard snapshot length mismatch.')
        for point,expected in zip(points,before):
            self.check(point)
            actual=tuple(map(int,self.monitor.color(point)))
            if max(abs(actual[i]-int(expected[i])) for i in range(3))>int(tolerance):
                raise InterruptedError(
                    f'Stopped: Auto Fill appears to have changed pixels outside the planned region near {point}. '
                    'The Fill pass was stopped before continuing with detail strokes. Use Conservative Auto Fill or turn Auto Fill off.'
                )

    def verify_fill(self,point,expected):
        """Verify a bucket/base fill without assuming Microsoft Paint."""
        expected=tuple(map(int,expected));self.check(point)
        best=None;best_error=999
        for settle in (0.0,.10,.22,.38):
            if settle:
                self._wait(settle)
                self.check(point)
            try:samples=self.monitor.colors_near(point,4)
            except AttributeError:samples=[self.monitor.color(point)]
            self.check(point)
            for actual in samples or []:
                actual=tuple(map(int,actual));error=max(abs(actual[i]-expected[i]) for i in range(3))
                if error<best_error:best_error,best=error,actual
            if best_error<=52:return
        if best is None:
            best=self.monitor.color(point)
            self.check(point)
            if max(abs(int(best[i])-expected[i]) for i in range(3))<=52:return
        raise InterruptedError(
            f'Stopped: the Fill tool did not produce the expected color {expected}. Closest rendered RGB was {best}. '
            'Recalibrate the Fill tool/color palette, confirm the canvas is blank, and retry with the target application at the same window size.')


    def snapshot_canvas(self, area):
        """Capture the selected canvas after verifying it still belongs to the target.

        This is read-only: no cursor movement, clicking, pressing or arming occurs.
        The four inset corners and center are checked against the locked target
        before PIL reads the pixels.
        """
        x, y, w, h = map(int, area)
        if w < 2 or h < 2:
            raise ValueError('The drawing area is too small to verify visually.')
        box=_capture_box((x,y,x+w,y+h))
        inset_x = min(4, max(0, w // 5)); inset_y = min(4, max(0, h // 5))
        points = ((x + inset_x, y + inset_y), (x + w - 1 - inset_x, y + inset_y),
                  (x + inset_x, y + h - 1 - inset_y), (x + w - 1 - inset_x, y + h - 1 - inset_y),
                  (x + w // 2, y + h // 2))
        for point in points:
            self.monitor.verify(self.target, point)
        image=_grab_rgb(box)
        try:
            for point in points:
                self.monitor.verify(self.target,point)
        except BaseException:
            image.close()
            raise
        return image

    def snapshot_canvas_with_margin(self, area, margin=24):
        """Capture a read-only canvas neighborhood for edge verification.

        The capture is clipped to the target client area.  The returned selected
        box is relative to the screenshot, so deterministic edge detection can
        compare the saved drawing rectangle against visible canvas borders
        without moving or clicking the mouse.
        """
        x, y, w, h = map(int, area)
        if w < 2 or h < 2:
            raise ValueError('The drawing area is too small to verify visually.')
        _capture_box((x,y,x+w,y+h))
        pad = max(0, min(96, int(round(float(margin)))))
        handle = self.target[0]
        client_left, client_top, client_right, client_bottom = self.monitor.client_rectangle(handle)
        if x<client_left or y<client_top or x+w>client_right or y+h>client_bottom:
            raise InterruptedError('The selected canvas extends outside the target client area. Select the drawing area again.')
        left = max(client_left, x - pad); top = max(client_top, y - pad)
        right = min(client_right, x + w + pad); bottom = min(client_bottom, y + h + pad)
        if right <= left or bottom <= top:
            raise ValueError('The edge-verification capture area is empty.')
        probe_points = _box_probes((left,top,right,bottom))
        for point in probe_points:
            self.monitor.verify(self.target, point)
        image = _grab_rgb((left,top,right,bottom))
        try:
            for point in probe_points:
                self.monitor.verify(self.target,point)
        except BaseException:
            image.close()
            raise
        selected_box = (x - left, y - top, w, h)
        return image, selected_box, (left, top, right, bottom)

    def verify_ink(self,point,expected):
        # Backward-compatible single-point API used by older tests/plugins.
        return self.verify_ink_segment(point,point,expected,1)
