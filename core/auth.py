from core.ui_scaling import grab_when_visible
from ui.components.adaptive import AdaptivePage
from ui.components.touch_input import install_touch_support
import tkinter as tk
import subprocess
import re
import os
from ui.components.button_styler import create_hover_button
from core.ui_tasks import TaskRunner
from core.auth_session import AuthSession, LoginResult
from core.auth_diagnostics import sanitize, failure_summary, format_diagnostics
from dataclasses import replace
from utils.browser import open_url

class _AuthURLLabel(tk.Label):
    """Keep the optional authorization URL out of the layout until available."""
    def configure(self, cnf=None, **kwargs):
        result = super().configure(cnf, **kwargs)
        options = dict(cnf or {}) if isinstance(cnf, dict) else {}
        options.update(kwargs)
        if 'text' in options:
            if options['text']:
                self.pack(fill=tk.X, pady=(5, 0))
            else:
                self.pack_forget()
                self.master.configure(height=1)
            callback = getattr(self, '_request_fit', None)
            if callback is not None:
                callback()
        return result

    config = configure


class SudoAuthWindow:
    """Окно авторизации через sudo"""
    def __init__(self):
        self.root = tk.Tk()
        self.setup_window_properties()
        self.root.title("Аутентификация")
        self.root.configure(bg='#182030')

        try:
            from tkinter import ttk
            style = ttk.Style()
            style.theme_use('clam')  # или 'alt', 'classic' - простые темы
        except:
            pass

        self.sudo_password = None
        self.auth_success = False
        self.setup_ui()
        self.tasks = TaskRunner(self.root)
        self.root.protocol('WM_DELETE_WINDOW', self.cancel)
        self._touch_input = install_touch_support(self.root)

    def setup_window_properties(self):
        """Настройка свойств окна для корректного отображения"""
        self.root.title("AdGuard VPN Manager")

        # Устанавливаем WM_CLASS (БЕЗ ПРОБЕЛОВ!)
        try:
            self.root.wm_class("AdGuardVPNManager")
        except:
            pass

        # Устанавливаем иконку
        try:
            manager_dir = os.path.expanduser("~/AdGuard VPN Manager")
            icon_path = os.path.join(manager_dir, "ico/adguard.png")
            if os.path.exists(icon_path):
                # Для PNG файлов в tkinter
                icon = tk.PhotoImage(master=self.root, file=icon_path)
                self.root.iconphoto(True, icon)
        except Exception as e:
            print(f"Не удалось установить иконку: {e}")

    def setup_ui(self):
        self.page = AdaptivePage(self.root, (370, 360), getattr(self, 'parent', None))
        main_frame = self.page.body

        title_label = tk.Label(main_frame, text="Аутентификация",
                              font=("Arial", 16, "bold"), fg='white', bg='#182030')
        title_label.pack(fill=tk.X, pady=10)
        self.page.wrap(title_label)

        desc_label = tk.Label(main_frame,
                             text="Для установки AdGuard VPN\nтребуется права администратора",
                             font=("Arial", 10), fg='white', bg='#182030')
        desc_label.pack(fill=tk.X, pady=5)
        self.page.wrap(desc_label)

        sudo_frame = tk.Frame(main_frame, bg='#182030')
        sudo_frame.pack(fill=tk.X, pady=10)

        tk.Label(sudo_frame, text="Введите пароль:",
                fg='white', bg='#182030').pack(anchor=tk.W)

        self.sudo_entry = tk.Entry(sudo_frame, show="*", width=1, font=('Arial', 12),
                                  bg='#15354D', fg='white', insertbackground='white')
        self.sudo_entry.pack(fill=tk.X, pady=5)
        self.sudo_entry.bind('<Return>', self.verify_sudo)
        self.sudo_entry.focus()

        btn_frame = tk.Frame(self.page.footer, bg='#182030')
        btn_frame.pack(fill=tk.X, pady=5)

        button_style = {
            'font': ('Arial', 10),
            'bg': '#15354D',
            'fg': 'white',
            'bd': 0,
            'padx': 10,
            'pady': 5,
            'width': 15,
            'highlightthickness':0,
            'cursor': 'hand2'
        }

        continue_btn = create_hover_button(btn_frame, text="Продолжить",
                                           command=self.verify_sudo, **button_style)
        continue_btn.grid(row=0, column=0, padx=(0, 10))

        cancel_btn = create_hover_button(btn_frame, text="Отмена",
                                         command=self.cancel, **button_style)
        cancel_btn.grid(row=0, column=1)

        # Центрируем весь фрейм с кнопками
        btn_frame.grid_columnconfigure(0, weight=1)
        btn_frame.grid_columnconfigure(1, weight=1)

        self.status_var = tk.StringVar(value="Введите пароль")
        status_bar = tk.Label(main_frame, textvariable=self.status_var,
                             relief=tk.SUNKEN, anchor=tk.W, bg='#15354D', fg='white')
        status_bar.pack(fill=tk.X, pady=(5, 0))
        self.page.wrap(status_bar)

        self.page.responsive_row(btn_frame)
        self.page.request_fit()

    def verify_sudo(self, event=None):
        password = self.sudo_entry.get()
        if not password:
            self.status_var.set("❗Sudo пароль не введен")
            return

        self.status_var.set("🔐 Проверка пароля...")
        self.sudo_entry.config(state='disabled')

        self.tasks.submit(lambda: self._verify_sudo_thread(password),
                          lambda valid: self._sudo_result(password, valid),
                          lambda error: self._sudo_verified_fail('Ошибка проверки пароля'),
                          key='sudo')

    def _verify_sudo_thread(self, password):
        process = subprocess.Popen(
            ['sudo', '-S', 'echo', 'success'], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            process.communicate(input=password + '\n', timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            return False
        return process.returncode == 0

    def _sudo_result(self, password, valid):
        if valid:
            self.sudo_password = password
            self.auth_success = True
            self._sudo_verified_success()
        else:
            self._sudo_verified_fail('❌ Неверный пароль')

    def _sudo_verified_success(self):
        self.status_var.set("✅ Пароль подтвержден!")
        self.root.after(1000, self.close_and_proceed)

    def _sudo_verified_fail(self, error_msg):
        self.status_var.set(error_msg)
        self.sudo_entry.config(state='normal')
        self.sudo_entry.delete(0, tk.END)
        self.sudo_entry.focus()

    def close_and_proceed(self):
        self.tasks.close()
        self.root.destroy()

    def cancel(self):
        self.sudo_password = None
        self.auth_success = False
        self.tasks.close()
        self.root.destroy()

    def run(self):
        self.root.mainloop()
        return self.sudo_password, self.auth_success

class _AuthFlow:
    """Shared login state machine; all methods here run on the Tk thread."""
    def _init_auth_flow(self):
        self.tasks = TaskRunner(self.root)
        self._session = None
        self._closed = False
        self._tick_id = None
        self._generation = 0
        self._last_login_result = None
        self._details_window = None
        self.details_btn = create_hover_button(
            self.page.footer, text='Подробности', command=self.show_auth_details,
            font=('Arial', 10), bg='#15354D', fg='white', bd=0,
            padx=10, pady=5, highlightthickness=0, cursor='hand2')
        self.root.protocol('WM_DELETE_WINDOW', self.cancel)
        self.root.bind('<Destroy>', self._auth_destroyed, add='+')
        self.url_label.bind('<Button-1>', lambda event: self.copy_auth_url())

    def _auth_destroyed(self, event):
        if event.widget is self.root:
            self._stop_auth()
            self.tasks.close()
            self._closed = True

    def _stop_auth(self):
        self.monitoring = False
        if self._session is not None:
            self._session.cancel()
        if self._tick_id is not None:
            self.root.after_cancel(self._tick_id)
            self._tick_id = None

    def cancel(self):
        self._stop_auth()
        self.tasks.close()
        self._closed = True
        self.root.destroy()

    def close_app(self):
        self.cancel()

    def start_auth_process(self):
        if self._closed or self.auth_success:
            return
        session = AuthSession()
        if not self.tasks.submit(
                lambda: session.run(lambda url: self.tasks.post(self._session_url, session, url)),
                lambda result: self._login_done(session, result),
                lambda error: self._login_error(session, error), key='login'):
            return
        self._generation += 1
        self._clear_auth_diagnostics()
        self._session = session
        self.auth_url = None
        self.url_label.config(text='')
        self.browser_btn.config(state='disabled', text='Открыть в браузере')
        self.check_now_btn.config(state='disabled')
        self.status_var.set('Получение ссылки для авторизации...')

    def _session_url(self, session, url):
        if session is self._session and not self.auth_success and not session.cancelled.is_set():
            self._show_auth_url(url)

    def _show_auth_url(self, auth_url):
        self.auth_url = auth_url
        display_url = auth_url if len(auth_url) <= 60 else auth_url[:60] + '...'
        self.url_label.config(text=display_url)
        self.status_var.set('Ссылка получена. Нажмите её для копирования или откройте браузер.')
        self.browser_btn.config(state='normal', text='Открыть в браузере')
        self.check_now_btn.config(state='normal')
        if not self.monitoring:
            self.monitoring = True
            self.current_countdown = 20
            self._tick_id = self.root.after(1000, self._auth_tick)

    def _login_done(self, session, result):
        if self._closed or session is not self._session or self.auth_success or session.cancelled.is_set():
            return
        if result.state == 'exited' and result.returncode == 0:
            self.force_check_auth()
        elif result.state not in ('busy', 'cancelled'):
            self._auth_fail(failure_summary(result), result)

    def _login_error(self, session, error=None):
        if (not self._closed and session is self._session and not self.auth_success
                and not session.cancelled.is_set()):
            result = LoginResult('worker_error', start_error=sanitize(error or 'Ошибка фоновой задачи', limit=1024))
            self._auth_fail(failure_summary(result), result)

    def _clear_auth_diagnostics(self):
        self._last_login_result = None
        self.details_btn.pack_forget()
        if self._details_window is not None:
            if self._details_window.winfo_exists():
                self._details_window.destroy()
            self._details_window = None

    def _auth_fail(self, error_msg, result=None):
        self._stop_auth()
        self._generation += 1
        self._session = None
        self.browser_btn.config(state='normal', text='Получить ссылку')
        self.check_now_btn.config(state='normal' if self.auth_url else 'disabled')
        self.status_var.set(error_msg)
        if result is not None:
            self._last_login_result = replace(result, output=sanitize(result.output),
                                              start_error=sanitize(result.start_error, limit=1024))
            self.details_btn.pack(pady=5)

    def show_auth_details(self):
        """Show safe diagnostics and return the Toplevel (also used by renderers)."""
        if self._closed or self._last_login_result is None:
            return None
        if self._details_window is not None and self._details_window.winfo_exists():
            self._details_window.lift()
            return self._details_window
        dialog = tk.Toplevel(self.root)
        self._details_window = dialog
        dialog.title('Подробности авторизации')
        dialog.configure(bg='#182030')
        dialog.transient(self.root)
        page = AdaptivePage(dialog, (680, 420), self.root)
        frame = tk.Frame(page.body, bg='#182030')
        frame.pack(fill='both', expand=True)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)
        from tkinter import ttk
        text = tk.Text(frame, font=('Arial', 10), bg='#15354D', fg='white',
                       wrap='word', width=1, height=1, bd=0, highlightthickness=0,
                       padx=5, pady=5, cursor='arrow')
        content = failure_summary(self._last_login_result) + '\n\n' + format_diagnostics(self._last_login_result)
        text.insert('1.0', content)
        text.config(state='disabled')
        text.grid(row=0, column=0, sticky='nsew')
        scrollbar = ttk.Scrollbar(frame, orient='vertical', command=text.yview)
        text.config(yscrollcommand=scrollbar.set)
        page.text_block(text, scrollbar, preferred_lines=16)
        buttons = tk.Frame(page.footer, bg='#182030')
        buttons.pack(fill='x')
        def copy():
            dialog.clipboard_clear()
            dialog.clipboard_append(content)
        style = dict(font=('Arial', 10), bg='#15354D', fg='white', bd=0,
                     padx=12, pady=7, highlightthickness=0, cursor='hand2')
        create_hover_button(buttons, text='Копировать', command=copy, **style).pack(side='left')
        create_hover_button(buttons, text='Закрыть', command=dialog.destroy, **style).pack(side='left')
        page.responsive_row(buttons)
        dialog.protocol('WM_DELETE_WINDOW', dialog.destroy)
        dialog.auth_diagnostics_text = text
        dialog.auth_diagnostics_page = page
        page.request_fit()
        return dialog

    def open_auth_browser(self):
        if self._session is None:
            self.start_auth_process()
            return
        if not self.auth_url or self.auth_success:
            return
        url = self.auth_url
        self.status_var.set('Открываю браузер...')
        session = self._session
        self.tasks.submit(lambda: open_url(url),
                          lambda opened: self._browser_done(opened, session),
                          lambda error: self._browser_done(False, session), key='browser')

    def _browser_done(self, opened, session):
        if self.auth_success or session is not self._session:
            return
        self.status_var.set('Ожидание авторизации...' if opened else
                            'Не удалось открыть браузер. Нажмите ссылку для копирования и откройте её вручную.')
        self.browser_btn.config(state='normal')
        self.check_now_btn.config(state='normal')

    def copy_auth_url(self):
        if self.auth_url:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.auth_url)
            self.status_var.set('Ссылка скопирована в буфер обмена!')

    def _auth_tick(self):
        self._tick_id = None
        if not self.monitoring or self._closed:
            return
        self.current_countdown -= 1
        if self.current_countdown <= 0:
            self.force_check_auth()
            self.current_countdown = 20
        self._tick_id = self.root.after(1000, self._auth_tick)

    def force_check_auth(self):
        if self._closed or self.auth_success or not self.auth_url:
            return
        def check():
            result = subprocess.run(['adguardvpn-cli', 'license'],
                                    capture_output=True, text=True, timeout=10)
            clean = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', result.stdout)
            return result.returncode == 0 and bool(re.search(r'Logged in as\s+\S+', clean))
        session, generation = self._session, self._generation
        def current():
            return (not self._closed and generation == self._generation
                    and session is self._session
                    and (session is None or not session.cancelled.is_set()))
        if self.tasks.submit(check,
                             lambda success: self._checked(success) if current() else None,
                             lambda error: self._check_error() if current() else None, key='auth-check'):
            self.check_now_btn.config(state='disabled')
            self.status_var.set('Проверка авторизации...')
            self.current_countdown = 20

    def _check_failed(self, error_msg=None):
        """Apply a caller-provided check error on the Tk thread."""
        self.check_now_btn.config(state='normal')
        self.status_var.set(error_msg or 'Авторизация ещё не завершена. Повторная проверка через 20 секунд.')

    def _check_error(self):
        if not self.auth_success:
            self.check_now_btn.config(state='normal')
            self.status_var.set('Не удалось проверить авторизацию. Повторная проверка через 20 секунд.')

    def _checked(self, success):
        if self.auth_success:
            return
        if success:
            self._auth_success()
        else:
            self.check_now_btn.config(state='normal')
            self.status_var.set('Авторизация ещё не завершена. Повторная проверка через 20 секунд.')

    def _auth_success(self):
        self._stop_auth()
        self._clear_auth_diagnostics()
        self.auth_success = True
        self.status_var.set('✅ Авторизация успешна!')
        self.check_now_btn.config(state='disabled')
        self.browser_btn.config(state='disabled')
        self._tick_id = self.root.after(2000, self.cancel)


class AuthWindow(_AuthFlow):
    """Окно авторизации после установки"""
    def __init__(self):
        self.root = tk.Tk()
        self.setup_window_properties()
        self.root.title("AdGuard VPN - Авторизация")

        self.root.configure(bg='#182030')

        try:
            from tkinter import ttk
            style = ttk.Style()
            style.theme_use('clam')
        except:
            pass

        self.auth_success = False
        self.auth_url = None
        self.monitoring = False
        self.current_countdown = 20
        self.check_count = 0
        self.countdown_running = False
        self.setup_ui()
        self._init_auth_flow()
        self._touch_input = install_touch_support(self.root)

    def setup_window_properties(self):
        """Настройка свойств окна для корректного отображения"""
        self.root.title("AdGuard VPN Manager")

        try:
            self.root.wm_class("AdGuardVPNManager")
        except:
            pass

        try:
            manager_dir = os.path.expanduser("~/AdGuard VPN Manager")
            icon_path = os.path.join(manager_dir, "ico/adguard.png")
            if os.path.exists(icon_path):
                icon = tk.PhotoImage(master=self.root, file=icon_path)
                self.root.iconphoto(True, icon)
        except Exception as e:
            print(f"Не удалось установить иконку: {e}")

    def setup_ui(self):
        self.page = AdaptivePage(self.root, (460, 360), getattr(self, 'parent', None))
        main_frame = self.page.body

        title_label = tk.Label(main_frame, text="AdGuard VPN - Авторизация",
                              font=("Arial", 16, "bold"), fg='white', bg='#182030')
        title_label.pack(fill=tk.X, pady=10)
        self.page.wrap(title_label)

        # Фрейм для ссылки
        self.url_frame = tk.Frame(main_frame, bg='#182030')
        self.url_frame.pack(fill=tk.X)

        self.url_label = _AuthURLLabel(self.url_frame, text="", font=("Arial", 9),
                                 wraplength=400, justify=tk.LEFT,
                                 fg='#0a84ff', bg='#182030', cursor="hand2")
        self.page.wrap(self.url_label)
        self.url_label._request_fit = self.page.request_fit

        # Фрейм для инструкций
        instructions_frame = tk.Frame(main_frame, bg='#182030')
        instructions_frame.pack(fill=tk.X, pady=10)

        instructions_text = (
            "1. Нажмите 'Открыть в браузере' для автоматического открытия\n"
            "2. Следуйте инструкциям на сайте\n"
            "3. Дождитесь завершения авторизации\n"
            "4. Для ускоренной проверки нажмите 'Проверить сейчас'"
        )
        instructions_label = tk.Label(instructions_frame, text=instructions_text, font=("Arial", 9),
                fg='white', bg='#182030', justify=tk.LEFT, anchor=tk.W)
        instructions_label.pack(fill=tk.X)
        self.page.wrap(instructions_label)

        # Кнопки основного действия
        btn_frame = tk.Frame(self.page.footer, bg='#182030')
        btn_frame.pack(fill=tk.X, pady=5)

        button_style = {
            'font': ('Arial', 10),
            'bg': '#15354D',
            'fg': 'white',
            'bd': 0,
            'padx': 10,
            'pady': 5,
            'width': 20,
            'highlightthickness':0,
            'cursor': 'hand2'
        }

        self.browser_btn = create_hover_button(btn_frame, text="Открыть в браузере",
                                    command=self.open_auth_browser, **button_style)
        self.browser_btn.grid(row=0, column=0, padx=(0, 10))

        exit_btn = create_hover_button(btn_frame, text="Выход",
                                       command=self.close_app, **button_style)
        exit_btn.grid(row=0, column=1)

        # Центрируем основной фрейм с кнопками
        btn_frame.grid_columnconfigure(0, weight=1)
        btn_frame.grid_columnconfigure(1, weight=1)

        # Кнопка для ускоренной проверки
        self.check_now_btn = create_hover_button(self.page.footer, text="🔄 Проверить сейчас", command=self.force_check_auth, ** button_style)
        self.check_now_btn.pack(pady=5)
        self.check_now_btn.config(state='disabled')  # Изначально неактивна

        # Статус
        self.status_var = tk.StringVar(value="Нажмите кнопку для получения ссылки")
        status_bar = tk.Label(main_frame, textvariable=self.status_var,
                             relief=tk.SUNKEN, anchor=tk.W, bg='#15354D', fg='white')
        status_bar.pack(fill=tk.X, pady=(5, 0))
        self.page.wrap(status_bar)

        # Изначально скрываем кнопки до получения ссылки
        self.browser_btn.config(state='disabled')

        self.page.responsive_row(btn_frame)
        self.page.request_fit()

    def run(self):
        self.start_auth_process()
        try:
            self.root.mainloop()
        finally:
            self._stop_auth()
            if self._session is not None and not self._session.wait(timeout=1.5):
                # An exceptional slow cleanup must still prevent interpreter
                # exit from abandoning this standalone login's child process.
                import threading
                threading.Thread(target=self._session.wait, daemon=False,
                                 name='standalone-auth-cleanup').start()
                raise RuntimeError('Authorization cleanup has not finished')
        return self.auth_success

class ManagerAuthWindow(_AuthFlow):
    """Окно авторизации через менеджер"""
    def __init__(self, parent):
        self.parent = parent
        self.root = tk.Toplevel(parent)
        self.setup_window_properties()
        self.root.title("AdGuard VPN - Авторизация")

        self.root.configure(bg='#182030')

        # Явно позиционируем относительно родительского окна
        self.root.transient(parent)  # Связываем с родителем
        grab_when_visible(self.root)         # Делаем модальным

        try:
            from tkinter import ttk
            style = ttk.Style()
            style.theme_use('clam')
        except:
            pass

        self.auth_success = False
        self.auth_url = None
        self.monitoring = False
        self.current_countdown = 20
        self.check_count = 0
        self.countdown_running = False
        self.setup_ui()
        self._init_auth_flow()

    def setup_window_properties(self):
        """Настройка свойств окна для корректного отображения"""
        self.root.title("AdGuard VPN Manager")

        # Устанавливаем WM_CLASS (БЕЗ ПРОБЕЛОВ!)
        try:
            self.root.wm_class("AdGuardVPNManager")
        except:
            pass

        # Устанавливаем иконку
        try:
            manager_dir = os.path.expanduser("~/AdGuard VPN Manager")
            icon_path = os.path.join(manager_dir, "ico/adguard.png")
            if os.path.exists(icon_path):
                # Для PNG файлов в tkinter
                icon = tk.PhotoImage(master=self.root, file=icon_path)
                self.root.iconphoto(True, icon)
        except Exception as e:
            print(f"Не удалось установить иконку: {e}")

    def setup_ui(self):
        self.page = AdaptivePage(self.root, (460, 360), getattr(self, 'parent', None))
        main_frame = self.page.body

        title_label = tk.Label(main_frame, text="AdGuard VPN - Авторизация",
                              font=("Arial", 16, "bold"), fg='white', bg='#182030')
        title_label.pack(fill=tk.X, pady=10)
        self.page.wrap(title_label)

        # Фрейм для ссылки
        self.url_frame = tk.Frame(main_frame, bg='#182030')
        self.url_frame.pack(fill=tk.X)

        self.url_label = _AuthURLLabel(self.url_frame, text="", font=("Arial", 9),
                                 wraplength=400, justify=tk.LEFT,
                                 fg='#0a84ff', bg='#182030', cursor="hand2")
        self.page.wrap(self.url_label)
        self.url_label._request_fit = self.page.request_fit

        # Фрейм для инструкций
        instructions_frame = tk.Frame(main_frame, bg='#182030')
        instructions_frame.pack(fill=tk.X, pady=10)

        instructions_text = (
            "1. Нажмите 'Открыть в браузере' для автоматического открытия\n"
            "2. Следуйте инструкциям на сайте\n"
            "3. Дождитесь завершения авторизации\n"
            "4. Для ускоренной проверки нажмите 'Проверить сейчас'"
        )
        instructions_label = tk.Label(instructions_frame, text=instructions_text, font=("Arial", 9),
                fg='white', bg='#182030', justify=tk.LEFT, anchor=tk.W)
        instructions_label.pack(fill=tk.X)
        self.page.wrap(instructions_label)

        # Кнопки основного действия
        btn_frame = tk.Frame(self.page.footer, bg='#182030')
        btn_frame.pack(fill=tk.X, pady=5)

        button_style = {
            'font': ('Arial', 10),
            'bg': '#15354D',
            'fg': 'white',
            'bd': 0,
            'padx': 10,
            'pady': 5,
            'width': 20,
            'highlightthickness':0,
            'cursor': 'hand2'
        }

        self.browser_btn = create_hover_button(btn_frame, text="Открыть в браузере",
                                    command=self.open_auth_browser, **button_style)
        self.browser_btn.grid(row=0, column=0, padx=(0, 10))

        self.cancel_btn = create_hover_button(btn_frame, text="Отмена",
                                              command=self.cancel, **button_style)
        self.cancel_btn.grid(row=0, column=1)

        # Центрируем основной фрейм с кнопками
        btn_frame.grid_columnconfigure(0, weight=1)
        btn_frame.grid_columnconfigure(1, weight=1)

        # Кнопка для ускоренной проверки
        self.check_now_btn = create_hover_button(self.page.footer, text="🔄 Проверить сейчас", command=self.force_check_auth, ** button_style)
        self.check_now_btn.pack(pady=5)
        self.check_now_btn.config(state='disabled')

        # Статус
        self.status_var = tk.StringVar(value="Получение ссылки для авторизации...")
        status_bar = tk.Label(main_frame, textvariable=self.status_var,
                             relief=tk.SUNKEN, anchor=tk.W, bg='#15354D', fg='white')
        status_bar.pack(fill=tk.X, pady=(5, 0))
        self.page.wrap(status_bar)

        # Изначально скрываем кнопки до получения ссылки
        self.browser_btn.config(state='disabled')

        self.page.responsive_row(btn_frame)
        self.page.request_fit()

    def run(self):
        self.start_auth_process()
        self.root.wait_window()
        return self.auth_success
