"""Cancellable account check before the standalone authorization/manager roots."""
import os
import re
import signal
import subprocess
import threading
import time
import tkinter as tk

from core.ui_tasks import TaskRunner
from core.update_diagnostics import has_error
from ui.components.adaptive import AdaptivePage
from ui.components.button_styler import create_hover_button


def classify_license(result):
    """An identity is useful even when fetching its license failed."""
    if not isinstance(result, subprocess.CompletedProcess):
        return 'unknown'
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', result.stdout or '')
    combined = text + '\n' + re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', result.stderr or '')
    # Only explicit account/session errors override a cached identity. Do not
    # match an example command such as "adguardvpn-cli login", permission
    # errors, HTTP failures or a generic license/network retrieval failure.
    auth_negative = (
        r'\bnot (?:logged|signed) in\b|\bnot authenticated\b|\bnot authori[sz]ed\b|'
        r'\bplease (?:log|sign) ?in\b|'
        r'\bsession (?:has )?expired\b|\bunauthorized\b|\bauthentication required\b|'
        r'не авторизован|не выполнен вход|вход не выполнен|пожалуйста,? войдите|вы не вошли|'
        r'сессия истекла|сеанс ист[её]к|требуется (?:авторизация|аутентификация)'
    )
    if re.search(auth_negative, combined, re.IGNORECASE):
        return 'auth'
    if re.search(r'Logged in as\s+\S+', text, re.IGNORECASE):
        return 'known'
    if has_error(combined) or re.search(r'\b(?:timeout|timed out)\b', combined, re.IGNORECASE):
        return 'unknown'
    return 'auth' if result.returncode == 0 else 'unknown'


class StartupCheckWindow:
    def __init__(self, timeout=10):
        self.root = tk.Tk()
        self.root.title('AdGuard VPN Manager')
        self.root.configure(bg='#182030')
        icon_path = os.path.expanduser('~/AdGuard VPN Manager/ico/adguard.png')
        try:
            if os.path.isfile(icon_path):
                self._icon = tk.PhotoImage(master=self.root, file=icon_path)
                self.root.iconphoto(True, self._icon)
        except (OSError, tk.TclError):
            pass
        self.tasks = TaskRunner(self.root)
        self.timeout = timeout
        self.cancelled = threading.Event()
        self._query_done = threading.Event()
        self._query_done.set()
        self.result = ('cancel', None)
        self._closed = False
        self.root.protocol('WM_DELETE_WINDOW', self.cancel)
        self.root.bind('<Destroy>', self._destroyed, add='+')
        self.root.bind('<Escape>', lambda event: self.cancel())
        self.page = AdaptivePage(self.root, (470, 180))
        self.status = tk.StringVar(value='Проверка аккаунта…')
        label = tk.Label(self.page.body, textvariable=self.status, font=('Arial', 11),
                         bg='#182030', fg='white', justify=tk.LEFT)
        label.pack(fill=tk.X)
        self.page.wrap(label)
        style = dict(font=('Arial', 10), bg='#15354D', fg='white', bd=0,
                     padx=12, pady=8, highlightthickness=0, cursor='hand2')
        self.retry_button = create_hover_button(self.page.footer, text='Повторить', command=self.retry, **style)
        self.retry_button.pack(side=tk.LEFT)
        create_hover_button(self.page.footer, text='Войти', command=self.login, **style).pack(side=tk.LEFT)
        create_hover_button(self.page.footer, text='Отмена', command=self.cancel, **style).pack(side=tk.LEFT)
        self.page.responsive_row(self.page.footer, gap=10)
        self.page.request_fit()
        self.retry()

    @staticmethod
    def _stop(process):
        # This process alone created this session. Cleanup never targets an
        # existing VPN service, a global process name or an unrelated session.
        for sig, timeout in ((signal.SIGTERM, .2), (signal.SIGKILL, .5)):
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                pass
            try:
                process.communicate(timeout=timeout)
                return
            except subprocess.TimeoutExpired:
                pass

    def _query(self):
        if self.cancelled.is_set():
            return None
        process = subprocess.Popen(['adguardvpn-cli', 'license'], stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, start_new_session=True)
        deadline = time.monotonic() + self.timeout
        completed = False
        try:
            while not self.cancelled.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Account check timed out')
                try:
                    stdout, stderr = process.communicate(timeout=min(.1, remaining))
                    completed = True
                    return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
                except subprocess.TimeoutExpired:
                    pass
            return None
        finally:
            if not completed:
                self._stop(process)

    def retry(self):
        if self._closed:
            return
        done = threading.Event()
        def work():
            try:
                return self._query()
            finally:
                done.set()
        accepted = self.tasks.submit(work, self._checked, self._failed, key='account')
        if accepted:
            self._query_done = done
            # An interpreter exit must not abandon the daemon task's child.
            # No Tk calls here; normal close is acknowledged before run returns.
            threading.Thread(target=done.wait, daemon=False, name='startup-query-cleanup').start()
            self.status.set('Проверка аккаунта… Это может занять несколько секунд.')
            self.retry_button.configure(state=tk.DISABLED)

    def _checked(self, result):
        if self._closed:
            return
        state = classify_license(result)
        if state in ('known', 'auth'):
            self._finish(state, result if state == 'known' else None)
        else:
            self._failed(None)

    def _failed(self, error):
        if self._closed:
            return
        self.status.set('Не удалось проверить аккаунт. Повторите проверку или войдите вручную.')
        self.retry_button.configure(state=tk.NORMAL)
        self.page.request_fit()

    def _finish(self, state, result=None):
        if self._closed:
            return
        self.result = state, result
        self._closed = True
        self.cancelled.set()
        self.tasks.close()
        self.root.destroy()

    def _destroyed(self, event):
        if event.widget is self.root:
            self._closed = True
            self.cancelled.set()
            self.tasks.close()

    def login(self):
        self._finish('auth')

    def cancel(self):
        self._finish('cancel')

    def run(self):
        if not self._closed:
            self.root.mainloop()
        # The window is already gone; this bounded acknowledgement cannot freeze
        # Tk. Its cleanup guard also covers direct destroy or exceptional exits.
        if not self._query_done.wait(timeout=1.5):
            raise RuntimeError('Account-check cleanup has not finished')
        return self.result
