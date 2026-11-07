"""Local keyboard behavior for application buttons, selectors and switches.

Bindings belong to each button and end with its lifetime. A button is one Tab
stop; Return, keypad Enter and Space use its existing state-checked invoke().
Selectors share focus visibility and use their existing variable/command path.
Switches use CTk's ordinary toggle(), including its on/off values and command.
Sliders keep native value/variable callbacks with focused numeric key input.
"""
from __future__ import annotations

import tkinter as tk
import math
from weakref import WeakSet

import customtkinter as ctk


class _KeyboardFocusSupport:
    _focus_tag = 'imagedrawbot_keyboard_focus'

    def _keyboard_has_focus(self):
        try:
            widget = self.focus_get()
        except (tk.TclError, KeyError):
            return False
        while widget is not None:
            if widget is self:
                return True
            widget = getattr(widget, 'master', None)
        return False


    def _keyboard_scroll_frames(self):
        parent = getattr(self, 'master', None)
        while parent is not None:
            if isinstance(parent, ctk.CTkScrollableFrame):
                yield parent
            parent = getattr(parent, 'master', None)


    def _keyboard_reveal_focus(self):
        """Reveal a Tab target inside owned CTk scroll frames, inside out."""
        frames = tuple(self._keyboard_scroll_frames())
        if not frames:
            return
        try:
            position = [self.winfo_rootx(), self.winfo_rooty()]
            size = (self.winfo_width(), self.winfo_height())
            for frame in frames:
                canvas = frame._parent_canvas
                axis = 0 if frame._orientation == 'horizontal' else 1
                viewport_start = canvas.winfo_rootx() if axis == 0 else canvas.winfo_rooty()
                viewport_size = canvas.winfo_width() if axis == 0 else canvas.winfo_height()
                if viewport_size <= 1:
                    continue
                if (position[axis] >= viewport_start and
                        position[axis] + size[axis] <= viewport_start + viewport_size):
                    continue
                bounds = canvas.bbox(frame._create_window_id)
                if not bounds:
                    continue
                extent = bounds[axis + 2] - bounds[axis]
                if extent <= 0:
                    continue
                coordinate = canvas.canvasx if axis == 0 else canvas.canvasy
                origin = coordinate(0)
                # Centre the target so platform scroll increments have room
                # to round without leaving its label outside the viewport.
                desired = origin + position[axis] - viewport_start + (size[axis] - viewport_size) / 2
                fraction = max(0.0, min(1.0, (desired - bounds[axis]) / extent))
                (canvas.xview_moveto if axis == 0 else canvas.yview_moveto)(fraction)
                # Native child coordinates may update at idle. Project this
                # scroll now when revealing the target in an outer viewport.
                position[axis] -= coordinate(0) - origin
        except (tk.TclError, RuntimeError, AttributeError):
            return  # The activation guard still rejects a clipped/gone target.


    def _keyboard_in_view(self):
        """A mapped canvas child may still be completely scrolled out of view."""
        frames = tuple(self._keyboard_scroll_frames())
        if not frames:
            return True
        try:
            x = self.winfo_rootx() + self.winfo_width() / 2
            y = self.winfo_rooty() + self.winfo_height() / 2
            for frame in frames:
                canvas = frame._parent_canvas
                left, top = canvas.winfo_rootx(), canvas.winfo_rooty()
                if not (left <= x < left + canvas.winfo_width() and
                        top <= y < top + canvas.winfo_height()):
                    return False
            return True
        except (tk.TclError, RuntimeError, AttributeError):
            return False


    def focus_set(self):
        return tk.Misc.focus_set(self)


    focus = focus_set


    def focus_force(self):
        return tk.Misc.focus_force(self)


    def _keyboard_draw_focus(self):
        try:
            if not self._keyboard_focus_active or not self._keyboard_focusable():
                if self._keyboard_focus_displayed:
                    self._canvas.delete(self._focus_tag)
                    self._keyboard_focus_displayed = False
                return
            self._canvas.delete(self._focus_tag)
            self._keyboard_focus_displayed = False
            width, height = self._canvas.winfo_width(), self._canvas.winfo_height()
            inset = max(2, round(2 * self._get_widget_scaling()))
            if width > 2 * inset and height > 2 * inset:
                self._canvas.create_rectangle(inset, inset, width - inset, height - inset,
                    outline=self._keyboard_focus_color, width=inset, tags=(self._focus_tag,))
                self._canvas.tag_raise(self._focus_tag)
                self._keyboard_focus_displayed = True
        except (tk.TclError, RuntimeError):
            pass  # Destruction can occur between a focus event and its repaint.


class _KeyboardReleaseSupport(_KeyboardFocusSupport):
    """One local activation on key release, cancelled when its context changes."""

    def _keyboard_focus_in(self, _event=None):
        self._keyboard_focus_active = True
        self._keyboard_reveal_focus()
        self._keyboard_draw_focus()

    def _keyboard_focus_out(self, _event=None):
        self._keyboard_focus_active = False
        self._keyboard_cancel()
        self._keyboard_draw_focus()

    def _keyboard_pointer_focus(self, _event=None):
        self._keyboard_cancel()
        if self._keyboard_focusable():
            self.focus_set()

    @staticmethod
    def _keyboard_key(event):
        symbol = getattr(event, 'keysym', '')
        if symbol in ('Return', 'KP_Enter'):
            return 'Return'
        return 'space' if symbol == 'space' else None

    def _keyboard_key_press(self, event):
        key = self._keyboard_key(event)
        # Preserve modified shortcuts instead of treating them as activation.
        if key is None or (getattr(event, 'state', 0) or 0) & (4 | 8 | 128 | 0x20000):
            return None
        if not self._keyboard_has_focus() or not self._keyboard_focusable():
            return 'break'
        if self._keyboard_pressed == key:
            # X11 may deliver a release/press pair for autorepeat. Defer the
            # release to idle so that pair cannot repeatedly invoke the action.
            if self._keyboard_job is not None:
                self.after_cancel(self._keyboard_job)
                self._keyboard_job = None
        elif self._keyboard_pressed is None:
            self._keyboard_pressed = key
        return 'break'

    def _keyboard_key_release(self, event):
        key = self._keyboard_key(event)
        if key is None:
            return None
        if key == self._keyboard_pressed and self._keyboard_job is None:
            self._keyboard_job = self.after_idle(self._keyboard_activate)
        return 'break'

    def _keyboard_activate(self):
        self._keyboard_job = None
        pressed = self._keyboard_pressed
        self._keyboard_pressed = None
        if (pressed is not None and self._keyboard_has_focus() and
                self._keyboard_focusable() and self._keyboard_in_view()):
            # The original CTk action rechecks its live state; the existing
            # controller retains all option and drawing-permission decisions.
            return self._keyboard_invoke()
        return None

    def _keyboard_cancel(self, _event=None):
        self._keyboard_pressed = None
        job, self._keyboard_job = self._keyboard_job, None
        if job is not None:
            try:
                self.after_cancel(job)
            except (tk.TclError, RuntimeError, ValueError):
                pass


class KeyboardButton(_KeyboardReleaseSupport, ctk.CTkButton):
    _focus_tag = 'imagedrawbot_keyboard_focus'

    def __init__(self, *args, focus_color='#72e2bd', **kwargs):
        self._keyboard_ready = False
        self._keyboard_closed = False
        self._keyboard_pressed = None
        self._keyboard_job = None
        self._keyboard_focus_active = False
        self._keyboard_focus_displayed = False
        self._keyboard_nodes = WeakSet()
        self._keyboard_focus_color = focus_color
        super().__init__(*args, **kwargs)
        self._keyboard_ready = True
        # CTk forwards configure()/bind()/focus_set() to decorative children.
        # Native Frame operations give the logical button one traversal stop.
        tk.Frame.configure(self, takefocus=self._keyboard_focusable)
        for sequence, callback in (
                ('<FocusIn>', self._keyboard_focus_in),
                ('<FocusOut>', self._keyboard_focus_out),
                ('<KeyPress-Return>', self._keyboard_key_press),
                ('<KeyRelease-Return>', self._keyboard_key_release),
                ('<KeyPress-KP_Enter>', self._keyboard_key_press),
                ('<KeyRelease-KP_Enter>', self._keyboard_key_release),
                ('<KeyPress-space>', self._keyboard_key_press),
                ('<KeyRelease-space>', self._keyboard_key_release)):
            tk.Misc.bind(self, sequence, callback, add='+')
        self._keyboard_sync_children()

    def _keyboard_focusable(self, _path=None):
        try:
            return bool(not self._keyboard_closed and self.winfo_exists()
                        and self.winfo_ismapped() and self.cget('state') != 'disabled'
                        and callable(self.cget('command')))
        except (tk.TclError, RuntimeError):
            return False








    def _keyboard_sync_children(self):
        # CTk can replace text/image labels during configure(). Its persistent
        # canvas and each new label remain decorative rather than extra stops.
        for child in (self._canvas, self._text_label, self._image_label):
            if child is not None and child not in self._keyboard_nodes:
                child.configure(takefocus=0)
                child.bind('<ButtonPress-1>', self._keyboard_pointer_focus, add='+')
                self._keyboard_nodes.add(child)

    def _draw(self, *args, **kwargs):
        super()._draw(*args, **kwargs)
        if getattr(self, '_keyboard_ready', False) and not self._keyboard_closed:
            self._keyboard_sync_children()
            self._keyboard_draw_focus()


    def _keyboard_invoke(self):
        return self.invoke()

    def destroy(self):
        self._keyboard_closed = True
        self._keyboard_cancel()
        super().destroy()


class KeyboardSwitch(_KeyboardReleaseSupport, ctk.CTkSwitch):
    """One Tab stop and deliberate local toggles through CTk's existing action."""

    def __init__(self, *args, focus_color='#72e2bd', **kwargs):
        self._keyboard_ready = False
        self._keyboard_closed = False
        self._keyboard_pressed = None
        self._keyboard_job = None
        self._keyboard_focus_active = False
        self._keyboard_focus_displayed = False
        self._keyboard_nodes = WeakSet()
        self._keyboard_focus_color = focus_color
        super().__init__(*args, **kwargs)
        self._keyboard_ready = True
        tk.Frame.configure(self, takefocus=self._keyboard_focusable)
        for sequence, callback in (
                ('<FocusIn>', self._keyboard_focus_in),
                ('<FocusOut>', self._keyboard_focus_out),
                ('<Unmap>', self._keyboard_cancel),
                ('<KeyPress-Return>', self._keyboard_key_press),
                ('<KeyRelease-Return>', self._keyboard_key_release),
                ('<KeyPress-KP_Enter>', self._keyboard_key_press),
                ('<KeyRelease-KP_Enter>', self._keyboard_key_release),
                ('<KeyPress-space>', self._keyboard_key_press),
                ('<KeyRelease-space>', self._keyboard_key_release)):
            tk.Misc.bind(self, sequence, callback, add='+')
        self._keyboard_sync_children()

    def _keyboard_focusable(self, _path=None):
        try:
            # A switch can still edit its variable without a command callback.
            return bool(not self._keyboard_closed and self.winfo_exists()
                        and self.winfo_ismapped() and self.cget('state') == 'normal')
        except (tk.TclError, RuntimeError):
            return False

    def _keyboard_sync_children(self):
        for child in (self._bg_canvas, self._canvas, self._text_label):
            if child not in self._keyboard_nodes:
                child.configure(takefocus=0)
                self._keyboard_nodes.add(child)

    def _draw(self, *args, **kwargs):
        super()._draw(*args, **kwargs)
        if getattr(self, '_keyboard_ready', False) and not self._keyboard_closed:
            self._keyboard_sync_children()
            self._keyboard_draw_focus()

    def _keyboard_invoke(self):
        return self.toggle()

    def toggle(self, event=None):
        # CTk toggles on ButtonPress, so cancel a pending keyboard release
        # before that existing callback can run (and possibly pump Tk events).
        if event is not None:
            self._keyboard_pointer_focus(event)
        else:
            self._keyboard_cancel()
        return super().toggle(event)

    def configure(self, *args, **kwargs):
        result = super().configure(*args, **kwargs)
        if getattr(self, '_keyboard_ready', False) and not self._keyboard_focusable():
            self._keyboard_cancel()
        return result

    def destroy(self):
        self._keyboard_closed = True
        self._keyboard_cancel()
        super().destroy()


class KeyboardOptionMenu(_KeyboardFocusSupport, ctk.CTkOptionMenu):
    """One Tab stop, bounded arrows, and a keyboard-opened native Tk menu."""

    def __init__(self, *args, focus_color='#72e2bd', **kwargs):
        self._keyboard_ready = False
        self._keyboard_closed = False
        self._keyboard_focus_active = False
        self._keyboard_focus_displayed = False
        self._keyboard_focus_color = focus_color
        super().__init__(*args, **kwargs)
        self._keyboard_ready = True
        tk.Frame.configure(self, takefocus=self._keyboard_focusable)
        for sequence, callback in (('<FocusIn>', self._keyboard_focus_in),
                                   ('<FocusOut>', self._keyboard_focus_out),
                                   ('<KeyPress>', self._keyboard_key_press)):
            tk.Misc.bind(self, sequence, callback, add='+')
        self._dropdown_menu.bind('<Unmap>', self._keyboard_popup_unmapped, add='+')
        self._keyboard_sync_children()

    def _keyboard_focusable(self, _path=None):
        try:
            return bool(not self._keyboard_closed and self.winfo_exists()
                        and self.winfo_ismapped() and self.cget('state') != 'disabled'
                        and self.cget('values'))
        except (tk.TclError, RuntimeError):
            return False

    def _keyboard_sync_children(self):
        for child in (self._canvas, self._text_label):
            child.configure(takefocus=0)

    def _draw(self, *args, **kwargs):
        super()._draw(*args, **kwargs)
        if getattr(self, '_keyboard_ready', False) and not self._keyboard_closed:
            self._keyboard_sync_children()
            self._keyboard_draw_focus()

    def _keyboard_focus_in(self, _event=None):
        self._keyboard_focus_active = True
        self._keyboard_reveal_focus()
        self._keyboard_draw_focus()

    def _keyboard_focus_out(self, _event=None):
        self._keyboard_focus_active = False
        self._keyboard_draw_focus()

    def _keyboard_popup_unmapped(self, _event=None):
        self._close_on_next_click = False

    def _keyboard_close_popup(self):
        self._close_on_next_click = False
        try:
            self._dropdown_menu.unpost()
            if self._dropdown_menu.grab_current() is self._dropdown_menu:
                self._dropdown_menu.grab_release()
        except (tk.TclError, RuntimeError, KeyError):
            pass

    def _keyboard_open_popup(self):
        values = self.cget('values')
        if not self._keyboard_focusable() or not self._keyboard_has_focus() or not self._keyboard_in_view():
            return
        if self._close_on_next_click:
            self._keyboard_close_popup()
            return
        try:
            selected = values.index(self.get())
        except ValueError:
            selected = 0
        self._close_on_next_click = True
        try:
            # tk_popup handles menu arrows/Return/Escape and focus restoration.
            # Selecting the current entry preserves the native menu's semantics.
            self._dropdown_menu.tk_popup(self.winfo_rootx(),
                self.winfo_rooty() + self.winfo_height(), selected)
        except (tk.TclError, RuntimeError):
            self._keyboard_close_popup()

    def _keyboard_key_press(self, event):
        key = getattr(event, 'keysym', '')
        state = getattr(event, 'state', 0) or 0
        modified = state & (4 | 8 | 128 | 0x20000)
        alt_down = key == 'Down' and bool(state & (8 | 0x20000)) and not state & (4 | 128)
        if modified and not alt_down:
            return None
        if key not in ('Up','Down','Left','Right','Home','End','Return','KP_Enter','space','F4','Escape'):
            return None
        if not self._keyboard_has_focus() or not self._keyboard_focusable() or not self._keyboard_in_view():
            return 'break'
        if key == 'Escape':
            self._keyboard_close_popup()
        elif alt_down or key in ('Return','KP_Enter','space','F4'):
            self._keyboard_open_popup()
        else:
            values = list(self.cget('values'))
            current = self.get()
            try:
                index = values.index(current)
            except ValueError:
                index = -1 if key in ('Down','Right','Home') else len(values)
            if key == 'Home': index = 0
            elif key == 'End': index = len(values)-1
            else: index += 1 if key in ('Down','Right') else -1
            value = values[max(0,min(len(values)-1,index))]
            if value != current:
                self._dropdown_callback(value)
        return 'break'

    def _dropdown_callback(self, value):
        self._close_on_next_click = False
        if self._keyboard_focusable() and value in self.cget('values'):
            return super()._dropdown_callback(value)

    def _clicked(self, event=0):
        if self._keyboard_focusable():
            self.focus_set()
            return super()._clicked(event)

    def configure(self, *args, **kwargs):
        result = super().configure(*args, **kwargs)
        if getattr(self, '_keyboard_ready', False) and not self._keyboard_focusable():
            self._keyboard_close_popup()
        return result

    def destroy(self):
        self._keyboard_closed = True
        self._keyboard_close_popup()
        super().destroy()


class KeyboardSlider(_KeyboardFocusSupport, ctk.CTkSlider):
    """One focused numeric control; wheel/keys obey the same live busy state."""

    def __init__(self, *args, keyboard_step=.01, reset_value=None,
                 value_changed=None, focus_color='#72e2bd', **kwargs):
        self._keyboard_step=float(keyboard_step)
        if not math.isfinite(self._keyboard_step) or self._keyboard_step<=0:
            raise ValueError('Slider keyboard step must be finite and positive.')
        self._keyboard_reset=None if reset_value is None else float(reset_value)
        if self._keyboard_reset is not None and not math.isfinite(self._keyboard_reset):
            raise ValueError('Slider reset value must be finite.')
        self._keyboard_ready=False
        self._keyboard_closed=False
        self._keyboard_focus_active=False
        self._keyboard_focus_displayed=False
        self._keyboard_focus_color=focus_color
        self._keyboard_value_callback=value_changed
        self._keyboard_display_value=None
        super().__init__(*args, **kwargs)
        self._keyboard_ready=True
        self._canvas.configure(takefocus=0)
        # CTk's global click handler focuses event.widget after local handlers.
        # Its decorative canvas must return focus to the same logical owner
        # without swallowing the click or replacing application bindings.
        for method in ('focus','focus_set','focus_force'):
            setattr(self._canvas,method,getattr(self,method))
        tk.Frame.configure(self,takefocus=self._keyboard_focusable)
        for sequence, callback in (('<FocusIn>',self._keyboard_focus_in),
                                   ('<FocusOut>',self._keyboard_focus_out),
                                   ('<KeyPress>',self._keyboard_key_press)):
            tk.Misc.bind(self,sequence,callback,add='+')
        self._keyboard_refresh_value()

    def _keyboard_focusable(self, _path=None):
        try:
            return bool(not self._keyboard_closed and self.winfo_exists()
                        and self.winfo_ismapped() and self.cget('state')!='disabled')
        except (tk.TclError,RuntimeError):
            return False

    def _keyboard_focus_in(self, _event=None):
        self._keyboard_focus_active=True
        self._keyboard_reveal_focus()
        self._keyboard_draw_focus()

    def _keyboard_focus_out(self, _event=None):
        self._keyboard_focus_active=False
        self._keyboard_draw_focus()

    def _keyboard_refresh_value(self):
        callback=self._keyboard_value_callback
        value=self.get()
        if callable(callback) and value!=self._keyboard_display_value:
            try:callback(value)
            except (tk.TclError,RuntimeError):return
            self._keyboard_display_value=value

    def _draw(self, *args, **kwargs):
        super()._draw(*args, **kwargs)
        if getattr(self,'_keyboard_ready',False) and not self._keyboard_closed:
            self._keyboard_draw_focus()
            self._keyboard_refresh_value()

    def _keyboard_select(self, value):
        low,high=sorted((float(self._from_),float(self._to)))
        if not all(math.isfinite(number) for number in (low,high,value)) or low==high:
            return False
        value=self._round_to_step_size(max(low,min(high,round(value,12))))
        if value==self.get():return False
        # CTk's own input path updates its value, draws, writes the linked Tk
        # variable, then invokes the existing command, exactly as a pointer does.
        self._update_value((value-self._from_)/(self._to-self._from_))
        return True

    def _keyboard_step_value(self, direction, *, large=False):
        current=float(self.get())
        if not math.isfinite(current):return False
        # Join the documented numeric grid after an arbitrary pointer position.
        index=round((current-self._from_)/self._keyboard_step)
        index+=direction*(10 if large else 1)
        return self._keyboard_select(self._from_+index*self._keyboard_step)

    def _keyboard_key_press(self, event):
        key=getattr(event,'keysym','')
        state=getattr(event,'state',0) or 0
        if state & (4|8|128|0x20000):return None
        keys=('Left','Right','Up','Down','Prior','Next','Home','End')
        if key not in keys and not (key=='BackSpace' and self._keyboard_reset is not None):return None
        if not self._keyboard_focusable() or not self._keyboard_has_focus() or not self._keyboard_in_view():return 'break'
        if key=='Home':self._keyboard_select(self._from_)
        elif key=='End':self._keyboard_select(self._to)
        elif key=='BackSpace':self._keyboard_select(self._keyboard_reset)
        else:
            direction=1 if key in ('Right','Up','Prior') else -1
            self._keyboard_step_value(direction,large=bool(state&1) or key in ('Prior','Next'))
        return 'break'

    def _keyboard_owns_wheel(self):
        return bool(self._keyboard_focusable() and self._keyboard_has_focus()
                    and self._keyboard_in_view())

    def _mouse_scroll_event(self, event):
        # CTk's raw wheel handler ignores state='disabled'. Leave ordinary
        # panel scrolling alone until the user deliberately focuses this slider.
        if ((getattr(event,'state',0) or 0) & (4|8|128|0x20000) or
                not self._keyboard_owns_wheel()):return None
        number=getattr(event,'num',None)
        delta=getattr(event,'delta',0) or 0
        if not delta and number not in (4,5):return None
        self._keyboard_step_value(-1 if delta<0 or number==5 else 1,
                                  large=bool((getattr(event,'state',0) or 0)&1))
        return 'break'

    def _clicked(self, event=None):
        if self._keyboard_focusable():
            self.focus_set()
            return super()._clicked(event)

    def destroy(self):
        self._keyboard_closed=True
        self._keyboard_value_callback=None
        super().destroy()


class KeyboardPreviewCanvas(_KeyboardFocusSupport, tk.Canvas):
    """Inspect the local preview with one Tab stop and bounded keyboard panning."""

    def __init__(self, *args, get_zoom, set_zoom, step_zoom, on_pan,
                 available=lambda: True, focus_color='#72e2bd', **kwargs):
        self._keyboard_closed = False
        self._get_preview_zoom = get_zoom
        self._set_preview_zoom = set_zoom
        self._step_preview_zoom = step_zoom
        self._preview_pan_changed = on_pan
        self._preview_available = available
        kwargs.setdefault('highlightthickness', 2)
        kwargs.setdefault('highlightbackground', kwargs.get('bg', '#101319'))
        kwargs.setdefault('highlightcolor', focus_color)
        super().__init__(*args, **kwargs)
        self.configure(takefocus=self._keyboard_focusable)
        self.bind('<FocusIn>', self._keyboard_focus_in, add='+')
        self.bind('<ButtonPress-1>', self._keyboard_pointer_focus, add='+')
        self.bind('<KeyPress>', self._keyboard_key_press, add='+')

    def _keyboard_focusable(self, _path=None):
        try:
            return bool(not self._keyboard_closed and self.winfo_exists()
                        and self.winfo_ismapped() and self.cget('state') == 'normal'
                        and getattr(self, '_preview_image_size', None)
                        and self._preview_available())
        except (tk.TclError, RuntimeError):
            return False

    def _keyboard_focus_in(self, _event=None):
        if self._keyboard_focusable():
            self._keyboard_reveal_focus()

    def _keyboard_pointer_focus(self, _event=None):
        if self._keyboard_focusable():
            self.focus_set()

    def _keyboard_key_press(self, event):
        from PreviewNavigation import pan_by, reset_pan
        key = getattr(event, 'keysym', '')
        state = getattr(event, 'state', 0) or 0
        if state & (4 | 8 | 128 | 0x20000):
            return None
        if key not in ('Left', 'Right', 'Up', 'Down', 'Prior', 'Next', 'Home',
                       'plus', 'equal', 'KP_Add', 'minus', 'KP_Subtract', '0', 'KP_0', '1', 'KP_1'):
            return None
        if not self._keyboard_focusable() or not self._keyboard_has_focus() or not self._keyboard_in_view():
            return 'break'
        if key in ('plus', 'equal', 'KP_Add'):
            self._step_preview_zoom(.25)
        elif key in ('minus', 'KP_Subtract'):
            self._step_preview_zoom(-.25)
        elif key in ('0', 'KP_0', '1', 'KP_1'):
            self._set_preview_zoom(0.0 if key in ('0', 'KP_0') else 1.0)
        elif key == 'Home':
            changed = getattr(self, '_preview_pan', (0, 0)) != (0, 0)
            reset_pan(self)
            if changed:
                self._preview_pan_changed()
        else:
            step = 160 if state & 1 else 32
            dx, dy = {'Left': (-step, 0), 'Right': (step, 0),
                      'Up': (0, -step), 'Down': (0, step),
                      'Prior': (0, -self._preview_viewport_size[1] * .8),
                      'Next': (0, self._preview_viewport_size[1] * .8)}[key]
            if pan_by(self, dx, dy, self._get_preview_zoom()):
                self._preview_pan_changed()
        return 'break'

    def destroy(self):
        self._keyboard_closed = True
        super().destroy()
