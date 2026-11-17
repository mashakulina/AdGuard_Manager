from core.ui_scaling import grab_when_visible
import tkinter as tk
from tkinter import font as tkfont, ttk
from core.ui_scaling import snapshot
from ui.components.button_styler import create_hover_button
from ui.components.adaptive import AdaptivePage


def restore_parent_focus(parent, previous_focus):
    """Restore after the destroyed dialog has released the window-system focus."""
    pending = {}

    def cancel(event):
        if event.widget is parent and pending.get('after'):
            parent.after_cancel(pending.pop('after'))

    def restore():
        pending.pop('after', None)
        parent.unbind('<Destroy>', pending['binding'])
        if previous_focus.winfo_exists():
            previous_focus.focus_force()

    pending['binding'] = parent.bind('<Destroy>', cancel, add='+')
    pending['after'] = parent.after_idle(restore)


def _dialog(parent, title, message, question=False):
    previous_focus = parent.focus_get()
    previous_grab = parent.grab_current()
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.configure(bg='#182030')
    dialog.transient(parent)
    scale = snapshot(dialog)[4]
    font = tkfont.Font(root=dialog, family='Arial', size=11)
    text_width = max((font.measure(line) for line in message.splitlines()), default=0)
    preferred = max(320, min(560, round(text_width / scale) + 40))
    page = AdaptivePage(dialog, (preferred, 0), parent)
    if len(message) > 1200:
        message_frame = tk.Frame(page.body, bg='#182030')
        message_frame.pack(fill='both', expand=True)
        message_frame.grid_columnconfigure(0, weight=1)
        message_frame.grid_rowconfigure(0, weight=1)
        message_text = tk.Text(message_frame, font=('Arial', 11), bg='#182030', fg='white',
                               wrap='word', width=1, height=1, bd=0, highlightthickness=0,
                               padx=0, pady=0, cursor='arrow')
        message_text.insert('1.0', message)
        message_text.configure(state='disabled')
        message_text.grid(row=0, column=0, sticky='nsew')
        message_scrollbar = ttk.Scrollbar(message_frame, orient='vertical', command=message_text.yview)
        message_text.configure(yscrollcommand=message_scrollbar.set)
        page.text_block(message_text, message_scrollbar)
    else:
        message_label = tk.Label(page.body, text=message, font=('Arial', 11), bg='#182030',
                                fg='white', justify=tk.LEFT, anchor='w',
                                wraplength=max(40, round((preferred-40)*scale)))
        message_label.pack(fill='x')
        page.wrap(message_label)
    result = [False]

    def close(value=False):
        result[0] = value
        dialog.destroy()

    def restore(event):
        if event.widget is dialog:
            if previous_grab is not None and previous_grab.winfo_exists():
                previous_grab.grab_set()
            if previous_focus is not None and previous_focus.winfo_exists():
                restore_parent_focus(parent, previous_focus)

    dialog.bind('<Destroy>', restore, add='+')
    buttons = tk.Frame(page.footer, bg='#182030')
    buttons.pack(fill='x')
    style = dict(font=('Arial', 10), bg='#15354D', fg='white', bd=0,
                 padx=20, pady=8, width=10, highlightthickness=0, cursor='hand2')
    first = create_hover_button(buttons, text='Да' if question else 'OK', command=lambda: close(question), **style)
    first.pack(side='left')
    if question:
        create_hover_button(buttons, text='Нет', command=close, **style).pack(side='left')
    dialog.bind('<Return>', lambda e: close(question))
    dialog.bind('<Escape>', lambda e: close())
    dialog.protocol('WM_DELETE_WINDOW', close)
    page.responsive_row(buttons, gap=10)
    grab_when_visible(dialog)
    first.focus_set()
    return dialog, result


def show_message_dialog(parent, title, message, message_type='info'):
    _dialog(parent, title, message)


def show_question_dialog(parent, title, message):
    dialog, result = _dialog(parent, title, message, True)
    dialog.wait_window()
    return result[0]
