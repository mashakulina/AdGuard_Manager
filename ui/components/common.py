import tkinter as tk
from core.ui_scaling import center_window, place_popup, snapshot


def create_tooltip(widget, text):
    """Create a tooltip constrained to this widget's display."""
    def on_leave(event=None):
        tooltip = getattr(widget, 'tooltip', None)
        if tooltip is not None:
            if tooltip.winfo_exists():
                tooltip.destroy()
            widget.tooltip = None

    def on_enter(event):
        on_leave()
        tooltip = tk.Toplevel(widget)
        tooltip.wm_overrideredirect(True)
        label = tk.Label(tooltip, text=text, background='#ffffe0', relief='solid',
                         borderwidth=1, font=('Arial', 9))
        label.pack()
        def update_wrap():
            label.configure(wraplength=max(40, min(round(400*snapshot(widget)[4]),
                                                   widget.winfo_screenwidth()-40)))
        update_wrap()
        widget.tooltip = tooltip
        observer = place_popup(tooltip, event.x_root+10, event.y_root+10)
        place = observer.layout
        def layout():
            update_wrap()
            place()
        observer.layout = layout

    widget.bind('<Enter>', on_enter)
    widget.bind('<Leave>', on_leave)
    widget.bind('<Destroy>', on_leave, add='+')
