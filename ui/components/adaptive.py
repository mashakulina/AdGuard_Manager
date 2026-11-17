"""Content-sized forms with explicitly declared wrapping and responsive groups."""
from fractions import Fraction
import tkinter as tk
from tkinter import ttk

from core.ui_scaling import descendants, observe_window, snapshot, window_position


def _pixels(widget, value):
    try:
        return widget.winfo_pixels(value)
    except (tk.TclError, ValueError, TypeError):
        return 0


def _insets(widget):
    return 2 * _pixels(widget, widget.cget('padx')) if 'padx' in widget.keys() else 0


class AdaptivePage:
    def __init__(self, window, size=(520, 400), parent=None, padding=(20, 15)):
        self.window = window
        self.outer = tk.Frame(window, bg='#182030')
        self.outer.pack(fill='both', expand=True)
        self.footer = tk.Frame(self.outer, bg='#182030', padx=padding[0])
        self.footer.pack(side='bottom', fill='x', pady=(0, 12))
        self.viewport = tk.Frame(self.outer, bg='#182030')
        self.viewport.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(self.viewport, bg='#182030', bd=0,
                                highlightthickness=0, width=1, height=1)
        self.canvas.pack(side='left', fill='both', expand=True)
        self.scrollbar = ttk.Scrollbar(self.viewport, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.body = tk.Frame(self.canvas, bg='#182030', padx=padding[0], pady=padding[1])
        self.item = self.canvas.create_window(0, 0, window=self.body, anchor='nw')
        self.rows, self.columns = [], []
        self._wraps, self._images = [], []
        self._text_blocks = []
        self._variable_traces = []
        self._wrap_heights = {}
        self._wrap_window_width = None
        self._changed_wraps = set()
        self._arranging = False
        self._measure_width = None
        self._image_scale = None
        self.canvas.bind('<Configure>', self._configure)
        self.body.bind('<Configure>', self._configure)
        for sequence in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
            window.bind(sequence, self._wheel, add='+')
        self.observer = observe_window(window, size, self.layout, parent, measure=self.measure)
        self.outer.bind('<Destroy>', self._destroy, add='+')

    def wrap(self, label, max_width=None, reserve=0):
        self._wraps.append((label, max_width, reserve))
        variable = str(label.cget('textvariable')) if 'textvariable' in label.keys() else ''
        if variable:
            command = self.window.register(lambda *args: self._text_changed(label))
            label.tk.call('trace', 'add', 'variable', variable, 'write', command)
            self._variable_traces.append((variable, command))
        return label

    def _text_changed(self, label):
        self._changed_wraps.add(label)
        self.observer.request()

    def _destroy(self, event):
        if event.widget is not self.outer:
            return
        for variable, command in self._variable_traces:
            try:
                self.window.tk.call('trace', 'remove', 'variable', variable, 'write', command)
                self.window.deletecommand(command)
            except tk.TclError:
                pass
        self._variable_traces.clear()
        self._changed_wraps.clear()
        self._wrap_heights.clear()

    def _grow_for_changed_text(self):
        """Grow for newly taller text; retain manual widths and shorter viewports."""
        heights = {label: label.winfo_reqheight() for label, _, _ in self._wraps}
        width = self.window.winfo_width()
        # A concurrent manual width change can itself add wrapped lines.
        taller = (width == self._wrap_window_width and
                  any(heights[label] > self._wrap_heights.get(label, heights[label])
                      for label in self._changed_wraps if label in heights))
        self._changed_wraps.clear()
        self._wrap_heights = heights
        self._wrap_window_width = width
        if taller:
            needed = self.body.winfo_reqheight() + self._footer_height()
            height = min(needed, max(1, self.window.winfo_screenheight() - 48))
            if height > self.window.winfo_height():
                x, y = window_position(self.window)
                y = max(0, min(y, self.window.winfo_screenheight()-height-24))
                self.window.geometry(f'{self.window.winfo_width()}x{height}+{x}+{y}')
                self.window.update_idletasks()

    def register_image(self, label, original_photo):
        self._images.append((label, original_photo))
        self._image_scale = None
        return label

    def text_block(self, text, scrollbar, preferred_lines=18):
        """A long selectable message scrolls inside a bounded Text viewport."""
        self._text_blocks.append((text, scrollbar, preferred_lines))

    def responsive_row(self, container, widgets=None, gap=10, align='center'):
        widgets = list(widgets or container.winfo_children())
        if container.winfo_manager() == 'pack':
            container.pack_configure(fill='x')
        for widget in widgets:
            if widget.master is not container:
                raise ValueError('Responsive row widgets must share their container')
            widget.pack_forget()
            widget.grid_forget()
        self.rows.append(dict(container=container, widgets=widgets, gap=gap,
                              align=align, narrow=None))
        return container

    def responsive_columns(self, container, columns, gap=20, *, equal_width=True, fit_width=False):
        if fit_width and container.master is not self.body:
            raise ValueError('Width-fitting columns must be direct children of page.body')
        for column in columns:
            column.pack_forget()
        container._adaptive_equal_columns = equal_width
        container._adaptive_fit_width = fit_width
        self.columns.append((container, tuple(columns), gap))

    def discover_rows(self):
        """Compatibility only: widget semantics must be registered explicitly."""

    def request_fit(self):
        self.observer.refit()

    def _wheel(self, event):
        if (event.widget.winfo_toplevel() is self.window and self.scrollbar.winfo_ismapped()
                and not isinstance(event.widget, (tk.Text, ttk.Treeview))):
            upward = getattr(event, 'num', 0) == 4 or getattr(event, 'delta', 0) > 0
            self.canvas.yview_scroll(-1 if upward else 1, 'units')

    def _configure(self, event=None):
        if not self._arranging:
            self.observer.request()

    def _inner_width(self, container):
        if self._measure_width is not None:
            current = container
            deductions = 0
            while current is not None and current is not self.footer:
                deductions += _insets(current)
                manager = current.winfo_manager()
                info = current.pack_info() if manager == 'pack' else current.grid_info() if manager == 'grid' else {}
                raw = info.get('padx', 0)
                parts = current.tk.splitlist(str(raw) if isinstance(raw, (int, float)) else raw)
                deductions += sum(_pixels(current, p) for p in parts) if len(parts) == 2 else 2 * _pixels(current, raw)
                current = current.master
            if current is self.footer:
                return max(1, self._measure_width - _insets(self.footer) - deductions)
        return max(1, container.winfo_width() - _insets(container))

    def _row_width(self, row):
        return sum(w.winfo_reqwidth() for w in row['widgets']) + row['gap'] * max(0, len(row['widgets']) - 1)

    def _column_width(self, column):
        width = column.winfo_reqwidth()
        for row in self.rows:
            parent = row['container']
            extra = 0
            while parent is not column and parent is not self.outer:
                extra += _insets(parent)
                parent = parent.master
                if parent is None:
                    break
            if parent is column:
                width = max(width, self._row_width(row) + extra + _insets(column))
        return width

    def _columns_width(self, container, columns, gap):
        widths = [self._column_width(column) for column in columns]
        content = (max(widths) * len(columns) if getattr(container, '_adaptive_equal_columns', True)
                   else sum(widths))
        return content + gap * (len(columns)-1)

    def _place_row(self, row, narrow):
        if row['narrow'] == narrow:
            return
        frame, widgets = row['container'], row['widgets']
        for widget in widgets:
            widget.grid_forget()
        for column in range(max(frame.grid_size()[0], len(widgets) + 2)):
            frame.grid_columnconfigure(column, weight=0, minsize=0, uniform='')
        for old_row in range(max(frame.grid_size()[1], len(widgets))):
            frame.grid_rowconfigure(old_row, weight=0, minsize=0)
        centered = row['align'] == 'center'
        if narrow:
            frame.grid_columnconfigure(0, weight=1 if centered else 0)
            for i, widget in enumerate(widgets):
                widget.grid(row=i, column=0, sticky='' if centered else 'w',
                            pady=(0, row['gap'] if i < len(widgets) - 1 else 0))
        else:
            if centered:
                frame.grid_columnconfigure(0, weight=1)
                frame.grid_columnconfigure(len(widgets) + 1, weight=1)
            for i, widget in enumerate(widgets):
                widget.grid(row=0, column=i + (1 if centered else 0), sticky='',
                            padx=(0, row['gap'] if i < len(widgets) - 1 else 0))
        row['narrow'] = narrow

    def _arrange(self, width, scale):
        self.canvas.itemconfigure(self.item, width=max(1, width))
        self.window.update_idletasks()
        for container, columns, gap in self.columns:
            available = self._inner_width(container)
            equal_width = getattr(container, '_adaptive_equal_columns', True)
            wide = available >= self._columns_width(container, columns, gap)
            for i, column in enumerate(columns):
                column.grid(row=0 if wide else i, column=i if wide else 0,
                            sticky='nsew', padx=(0, gap if wide and i < len(columns)-1 else 0),
                            pady=(0, gap if not wide and i < len(columns)-1 else 0))
            for i in range(len(columns)):
                minimum = (self._column_width(columns[i]) + (gap if i < len(columns)-1 else 0)
                           if wide and not equal_width else 0)
                container.grid_columnconfigure(i, weight=1 if wide or i == 0 else 0,
                                               uniform='sections' if wide and equal_width else '',
                                               minsize=minimum)
            container._column_count = len(columns) if wide else 1
        self.window.update_idletasks()
        for row in self.rows:
            self._place_row(row, self._row_width(row) > self._inner_width(row['container']))
        self.window.update_idletasks()
        for label, maximum, reserve in self._wraps:
            remaining = reserve() if callable(reserve) else reserve
            limit = max(40, self._inner_width(label.master) - remaining)
            if maximum is not None:
                limit = min(limit, round(maximum * scale))
            if int(float(label.cget('wraplength'))) != limit:
                label.configure(wraplength=limit)
        if self._image_scale != round(scale, 3):
            ratio = Fraction(scale).limit_denominator(16)
            for label, original in self._images:
                displayed = original.zoom(ratio.numerator).subsample(ratio.denominator)
                label.configure(image=displayed)
                label._adaptive_image = displayed
            self._image_scale = round(scale, 3)
        self.window.update_idletasks()
        for text, scrollbar, preferred_lines in self._text_blocks:
            linespace = int(text.tk.call('font', 'metrics', text.cget('font'), '-linespace'))
            available = (self.window.winfo_screenheight() - 48 - self._footer_height()
                         - 2 * _pixels(self.body, self.body.cget('pady')) - 8)
            count = text.count('1.0', 'end-1c', 'displaylines')
            lines = (int(count[0]) if count else 0) + 1
            height = min(preferred_lines, lines, max(1, available // max(1, linespace)))
            if int(text.cget('height')) != height:
                text.configure(height=height)
            if lines > height:
                scrollbar.grid(row=0, column=1, sticky='ns')
            else:
                scrollbar.grid_remove()
        self.window.update_idletasks()

    def _minimum_width(self):
        buttons = [w for w in descendants(self.outer) if isinstance(w, tk.Button)]
        return max([240] + [w.winfo_reqwidth() + _insets(self.body) + 20 for w in buttons])

    def _footer_height(self):
        return self.footer.winfo_reqheight() + 12

    def measure(self, scale):
        sw, sh = snapshot(self.window)[:2]
        fitting = [(container, columns, gap) for container, columns, gap in self.columns
                   if getattr(container, '_adaptive_fit_width', False)]
        preferred = round(self.observer.base_size[0] * scale)
        if fitting:
            self.window.update_idletasks()
            preferred = max(self._columns_width(container, columns, gap)
                            + _insets(container) + _insets(self.body)
                            for container, columns, gap in fitting)
        width = min(max(1, sw - 16), max(preferred, self._minimum_width()))
        self._arranging = True
        self._measure_width = width
        try:
            self.scrollbar.pack_forget()
            for _ in range(3):
                self._arrange(width, scale)
            height = self.body.winfo_reqheight() + self._footer_height()
            if height > sh - 48:
                self.scrollbar.pack(side='right', fill='y')
                self.window.update_idletasks()
                if fitting:
                    # Reserve room for the bar rather than stacking columns
                    # solely because it consumed their exact natural width.
                    width = min(max(1, sw-16), width+self.scrollbar.winfo_reqwidth())
                    self._measure_width = width
                for _ in range(2):
                    self._arrange(width - self.scrollbar.winfo_reqwidth(), scale)
                height = self.body.winfo_reqheight() + self._footer_height()
            return width, max(1, height)
        finally:
            self._measure_width = None
            self._arranging = False

    def layout(self):
        if self._arranging:
            return
        self._arranging = True
        try:
            scale = snapshot(self.window)[4]
            # Judge intrinsic overflow before a scrollbar can add wrapped lines.
            # A bar packed during an early, undersized WM allocation must not
            # sustain its own overflow once the requested geometry arrives.
            full_width = max(1, self.viewport.winfo_width())
            self._arrange(full_width, scale)
            self._grow_for_changed_text()
            overflow = self.body.winfo_reqheight() > self.canvas.winfo_height() + 2
            if overflow and not self.scrollbar.winfo_manager():
                self.scrollbar.pack(side='right', fill='y')
            elif not overflow and self.scrollbar.winfo_manager():
                self.scrollbar.pack_forget()
                self.canvas.yview_moveto(0)
            self.window.update_idletasks()
            self._arrange(max(1, self.canvas.winfo_width()), scale)
            self.canvas.configure(scrollregion=self.canvas.bbox('all'))
            sw, sh = snapshot(self.window)[:2]
            self.window.minsize(max(1, min(sw-16, self._minimum_width())),
                                max(1, min(sh-48, self._footer_height()+min(60, self.body.winfo_reqheight()))))
        finally:
            self._arranging = False
