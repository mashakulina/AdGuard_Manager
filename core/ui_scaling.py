"""Screen bounded Tk geometry and one lifecycle-managed observer per window.

Pixel dimensions start from logical (96 DPI) bases. Font points and character
widths remain Tk units. No display settings or external commands are changed.
"""
import ctypes
from functools import lru_cache
import math
import os
import re
import tkinter as tk
from tkinter import font as tkfont, ttk


def finite_number(value, fallback):
    try:
        value = float(value)
        return value if math.isfinite(value) and value > 0 else fallback
    except (ValueError, TypeError, OverflowError):
        return fallback


@lru_cache(maxsize=1)
def _x11_library():
    """Load optional Xlib without library discovery's external commands."""
    try:
        lib = ctypes.CDLL('libX11.so.6')
        signatures = {
            'XOpenDisplay': ([ctypes.c_char_p], ctypes.c_void_p),
            'XDefaultRootWindow': ([ctypes.c_void_p], ctypes.c_ulong),
            'XInternAtom': ([ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int], ctypes.c_ulong),
            'XGetWindowProperty': ([ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
                                   ctypes.c_long, ctypes.c_long, ctypes.c_int, ctypes.c_ulong,
                                   ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
                                   ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
                                   ctypes.POINTER(ctypes.c_void_p)], ctypes.c_int),
            'XFree': ([ctypes.c_void_p], ctypes.c_int),
            'XCloseDisplay': ([ctypes.c_void_p], ctypes.c_int),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(lib, name)
            function.argtypes, function.restype = arguments, result
        return lib
    except (OSError, AttributeError):
        return None


def _parse_xft_dpi(resources):
    for line in resources.splitlines():
        name, separator, value = line.partition(':')
        if separator and name.strip() == 'Xft.dpi':
            return finite_number(value.strip(), None)
    return None


def read_xft_dpi(display=None):
    """Read current root resources, avoiding Xlib's cached resource string.

    Open/close each time so RESOURCE_MANAGER changes are visible to polling.
    Bound the property read to 1 MiB and ignore missing or malformed resources.
    """
    display = os.environ.get('DISPLAY') if display is None else display
    if not display:
        return None
    lib = _x11_library()
    if lib is None:
        return None
    connection = None
    data = ctypes.c_void_p()
    try:
        connection = lib.XOpenDisplay(display.encode())
        if not connection:
            return None
        atom = lib.XInternAtom(connection, b'RESOURCE_MANAGER', True)
        if not atom:
            return None
        actual_type, count, remaining = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_ulong()
        actual_format = ctypes.c_int()
        status = lib.XGetWindowProperty(
            connection, lib.XDefaultRootWindow(connection), atom, 0, 262144,
            False, 31, ctypes.byref(actual_type), ctypes.byref(actual_format),
            ctypes.byref(count), ctypes.byref(remaining), ctypes.byref(data))
        # XA_STRING = 31; XGetWindowProperty counts items, not bytes.
        if (status != 0 or actual_type.value != 31 or actual_format.value != 8
                or remaining.value or count.value > 1048576 or not data.value):
            return None
        return _parse_xft_dpi(ctypes.string_at(data, count.value).decode('latin-1'))
    except (OSError, ValueError, TypeError, AttributeError, ctypes.ArgumentError):
        return None
    finally:
        if data.value:
            lib.XFree(data)
        if connection:
            lib.XCloseDisplay(connection)


def scale_factor(dpi=96, tk_scaling=None, environ=None, xft_dpi=None):
    values = [finite_number(dpi, 96) / 96]
    if tk_scaling is not None:
        values.append(finite_number(tk_scaling, 4 / 3) * 72 / 96)
    if xft_dpi is not None:
        values.append(finite_number(xft_dpi, 0) / 96)
    for name in ('GDK_SCALE', 'QT_SCALE_FACTOR', 'ELM_SCALE', 'WINIT_HIDPI_FACTOR'):
        hint = finite_number((os.environ if environ is None else environ).get(name), 0)
        if .25 <= hint <= 4:
            values.append(hint)
    return max(.5, min(4., max(values)))


def bounded_geometry(size, screen, position=None, parent=None, margin=(16, 48)):
    sw, sh = (max(1, int(n)) for n in screen)
    aw, ah = max(1, sw - margin[0]), max(1, sh - margin[1])
    w, h = min(aw, max(1, int(size[0]))), min(ah, max(1, int(size[1])))
    if position is None:
        px, py, pw, ph = parent or (0, 0, sw, sh)
        position = (px + (pw - w) // 2, py + (ph - h) // 2)
    x, y = position
    return w, h, max(0, min(sw-w, int(x))), max(0, min(sh-h-margin[1]//2, int(y)))


def window_position(window):
    """Read the coordinates accepted by wm geometry, excluding WM decoration.

    On a decorated X11 window winfo_x/y describe the client origin. Feeding
    them back to geometry adds the frame border and titlebar on every resize.
    Negative-gravity coordinates do not describe an absolute origin, so retain
    the previous fallback for that uncommon case instead of clamping to zero.
    """
    try:
        match = re.fullmatch(r'\d+x\d+\+(\d+)\+(\d+)', window.wm_geometry())
        if match:
            return tuple(map(int, match.groups()))
    except (AttributeError, tk.TclError):
        pass
    return window.winfo_x(), window.winfo_y()


def snapshot(window):
    try:
        dpi = finite_number(window.winfo_fpixels('1i'), 96)
        scaling = finite_number(window.tk.call('tk', 'scaling'), 4/3)
        xft_dpi = (read_xft_dpi(window.winfo_screen())
                   if window.tk.call('tk', 'windowingsystem') == 'x11' else None)
        return (window.winfo_screenwidth(), window.winfo_screenheight(),
                round(dpi, 3), round(scaling, 5), scale_factor(dpi, scaling, xft_dpi=xft_dpi), xft_dpi)
    except tk.TclError:
        return 800, 600, 96, 4/3, 1, None


def descendants(widget):
    for child in widget.winfo_children():
        if not isinstance(child, tk.Toplevel):
            yield child
            yield from descendants(child)


def font_parameters(window, specification):
    """Read declared points, avoiding Font(font=...)'s stale `font actual` copy."""
    if str(specification) in window.tk.splitlist(window.tk.call('font', 'names')):
        values = window.tk.splitlist(window.tk.call('font', 'configure', specification))
        return {str(values[i]).lstrip('-'): values[i+1] for i in range(0, len(values), 2)}
    parts = window.tk.splitlist(specification)
    if len(parts) >= 2:
        try:
            size = int(parts[1])
        except (TypeError, ValueError):
            pass
        else:
            options = set(str(p) for p in parts[2:])
            return dict(family=parts[0], size=size, weight='bold' if 'bold' in options else 'normal',
                        slant='italic' if 'italic' in options else 'roman',
                        underline=int('underline' in options), overstrike=int('overstrike' in options))
    return tkfont.Font(root=window, font=specification).configure()


def capture_style_fonts(window):
    root = window._root()
    if not any(isinstance(w, ttk.Treeview) for w in descendants(window)):
        return
    if not hasattr(root, '_adaptive_style_bases'):
        style = ttk.Style(window)
        root._adaptive_style_bases = {
            name: font_parameters(window, style.lookup(name, 'font') or 'TkDefaultFont')
            for name in ('Treeview', 'Treeview.Heading')
        }


def refresh_fonts(window):
    # Tk caches existing fonts across `tk scaling` changes. New font instances
    # preserve the original points and invalidate stale metrics.
    for widget in descendants(window):
        if 'font' in widget.keys():
            base = getattr(widget, '_adaptive_font_base', None)
            if base is None:
                base = font_parameters(window, widget.cget('font'))
                widget._adaptive_font_base = base
            fresh = tkfont.Font(root=window, **base)
            widget.configure(font=fresh)
            widget._adaptive_font = fresh
    capture_style_fonts(window)
    root = window._root()
    root._adaptive_style_fonts = {}
    for name, base in getattr(root, '_adaptive_style_bases', {}).items():
        fresh = tkfont.Font(root=window, **base)
        ttk.Style(window).configure(name, font=fresh)
        root._adaptive_style_fonts[name] = fresh


def center_window(window, parent=None):
    window.update_idletasks()
    p = None
    if parent is not None and parent.winfo_viewable():
        p = (parent.winfo_rootx(), parent.winfo_rooty(), parent.winfo_width(), parent.winfo_height())
    w, h, x, y = bounded_geometry((window.winfo_width(), window.winfo_height()), snapshot(window)[:2], parent=p)
    window.geometry(f'{w}x{h}+{x}+{y}')


class WindowObserver:
    def __init__(self, window, base_size, layout=None, parent=None, measure=None):
        self.window, self.base_size, self.layout, self.parent = window, base_size, layout, parent
        self.measure = measure
        self._force_fit = True
        self.pending = self.polling = None
        self.closed = False
        self.last = None
        self.first = True
        self.bindings = []
        for event in ('<Map>', '<FocusIn>', '<Configure>'):
            self.bindings.append((event, window.bind(event, self._event, add='+')))
        self.bindings.append(('<Destroy>', window.bind('<Destroy>', self._destroy, add='+')))
        self.request()
        self.polling = window.after(500, self._poll)

    def _event(self, event):
        if event.widget is self.window:
            self.request()

    def request(self):
        if not self.closed and self.pending is None:
            self.pending = self.window.after(60, self._apply)

    def _poll(self):
        self.polling = None
        if not self.closed:
            if snapshot(self.window) != self.last:
                self.request()
            self.polling = self.window.after(500, self._poll)

    def _apply(self):
        self.pending = None
        if self.closed:
            return
        win = self.window
        state = snapshot(win)
        changed = state != self.last
        if self.last is not None and state[3] != self.last[3]:
            refresh_fonts(win)
        self.last = state
        if self.first:
            capture_style_fonts(win)
            for widget in descendants(win):
                if 'font' in widget.keys():
                    widget._adaptive_font_base = font_parameters(win, widget.cget('font'))
        if self.first or changed or self._force_fit:
            scale = state[4]
            if self.measure is not None:
                width, height = self.measure(scale)
            elif self.base_size is None:
                win.update_idletasks()
                width, height = win.winfo_reqwidth(), win.winfo_reqheight()
            else:
                width, height = (round(n * scale) for n in self.base_size)
            p = None
            if self.parent is not None and self.parent.winfo_viewable():
                p = (self.parent.winfo_rootx(), self.parent.winfo_rooty(), self.parent.winfo_width(), self.parent.winfo_height())
            pos = None if self.first else window_position(win)
            w, h, x, y = bounded_geometry((width, height), state[:2], pos, p)
            win.minsize(min(240, w), min(100, h))
            win.maxsize(max(1, state[0]-16), max(1, state[1]-48))
            win.geometry(f'{w}x{h}+{x}+{y}')
            # Layout must see the newly allocated viewport, not the previous
            # one-pixel canvas (which would spuriously enable scrolling).
            win.update_idletasks()
            self.first = False
            self._force_fit = False
        if self.layout:
            self.layout()

    def refit(self, base_size=None):
        if base_size:
            self.base_size = base_size
        self._force_fit = True
        self.request()

    def _destroy(self, event):
        if event.widget is self.window:
            self.closed = True
            for name in ('pending', 'polling'):
                token = getattr(self, name)
                if token:
                    self.window.after_cancel(token)
                    setattr(self, name, None)


def grab_when_visible(window):
    """Acquire modal input after the WM has actually mapped the window."""
    if window.winfo_viewable():
        window.grab_set()
        return
    bindings = {}

    def mapped(event):
        if event.widget is window and window.winfo_viewable():
            for sequence, identifier in bindings.items():
                window.unbind(sequence, identifier)
            bindings.clear()
            window.grab_set()

    # A child can be mapped while its ancestor is still hidden. Visibility also
    # covers its later appearance. Destroy removes these window-owned bindings.
    for sequence in ('<Map>', '<Visibility>'):
        bindings[sequence] = window.bind(sequence, mapped, add='+')


def observe_window(window, base_size=(520, 400), layout=None, parent=None, measure=None):
    current = getattr(window, '_scale_observer', None)
    if current is None or current.closed:
        current = window._scale_observer = WindowObserver(window, base_size, layout, parent, measure)
    return current


def _place_popup(window, x, y):
    window.update_idletasks()
    w, h, x, y = bounded_geometry((window.winfo_reqwidth(), window.winfo_reqheight()), snapshot(window)[:2], (x, y), margin=(8, 8))
    window.geometry(f'{w}x{h}+{x}+{y}')


class PopupObserver(WindowObserver):
    def _apply(self):
        self.pending = None
        if self.closed:
            return
        state = snapshot(self.window)
        if self.first:
            for widget in descendants(self.window):
                if 'font' in widget.keys():
                    widget._adaptive_font_base = font_parameters(self.window, widget.cget('font'))
        elif self.last is not None and state[3] != self.last[3]:
            refresh_fonts(self.window)
        self.last = state
        self.first = False
        self.layout()


def place_popup(window, x, y):
    """Measure popup content now and on later display/DPI snapshots."""
    _place_popup(window, x, y)
    observer = getattr(window, '_scale_observer', None)
    if observer is None or observer.closed:
        window._scale_observer = PopupObserver(window, None, lambda: _place_popup(window, x, y))
    return window._scale_observer
