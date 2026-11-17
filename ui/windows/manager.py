from core.ui_tasks import TaskRunner
from utils.browser import open_url
from core.ui_scaling import place_popup, observe_window, snapshot
from types import SimpleNamespace
from math import gcd
import tkinter as tk
from tkinter import ttk, scrolledtext, PhotoImage
import subprocess
import threading
import time
import sys
import re
from datetime import datetime, date
from ui.windows.locations import LocationSelectionWindow
from ui.windows.settings import SettingsWindow
from ui.windows.updates import UpdateWindow
from core.uninstall import UninstallWindow
from ui.components.common import create_tooltip
from core.auth import ManagerAuthWindow
from core.utils import clean_ansi_codes, clean_location_output, check_if_connected
import os
from ui.components.dialogs import show_message_dialog, show_question_dialog
from ui.components.button_styler import create_hover_button, create_hover_button_for_manager
from ui.windows.license import LicenseWindow
from ui.windows.info_dialog import show_info_dialog
from ui.windows.donat import DonationWindow
_last_available_site = None
_last_check_time = 0

def get_available_site():
    """Возвращает доступный сайт с кэшированием на 5 минут"""
    global _last_available_site, _last_check_time

    import time
    current_time = time.time()

    # Если прошло меньше 5 минут, возвращаем кэшированный результат
    if _last_available_site and (current_time - _last_check_time) < 300:
        return _last_available_site

    sites = [
        "https://adguard-vpn.com",
        "https://adguard-vpn.work",
        "https://adguardvpn-help.net"
    ]

    # Используем улучшенную проверку
    for site in sites:
        if check_site_availability_improved(site):
            _last_available_site = site
            _last_check_time = current_time
            return site

    # Если ни один сайт не доступен, возвращаем основной
    _last_available_site = sites[0]
    _last_check_time = current_time
    return sites[0]

def check_site_availability_improved(url):
    """Улучшенная проверка доступности сайта"""
    try:
        import socket
        import ssl
        from urllib.parse import urlparse

        parsed = urlparse(url)
        domain = parsed.netloc
        port = 443  # HTTPS по умолчанию

        # Создаем socket с таймаутом
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3.0)  # 3 секунды таймаут

        # Пробуем подключиться
        sock.connect((domain, port))

        # Для HTTPS создаем SSL контекст
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        ssl_sock = context.wrap_socket(sock, server_hostname=domain)
        ssl_sock.close()

        return True

    except (socket.timeout, ConnectionRefusedError, ssl.SSLError, OSError):
        return False
    except Exception:
        return False

class AdGuardVPNManager:
    def __init__(self, root, initial_license=None):
        self.root = root
        self.tasks = TaskRunner(root)
        self._main_thread = threading.get_ident()
        self._closed = False
        self._refresh_generation = 0
        self._license_text = ""
        self._license_partial = False
        self._auth_known = False
        self._auth_error = False
        self._last_license_refresh = float("-inf")
        self._status_timer = None
        self.setup_window_properties()
        self.root.title("AdGuard VPN Manager")
        self.window_height_hidden = 210  # Высота когда лог скрыт
        self.window_height_visible = 355  # Высота когда лог показан
        self.window_width = 570
        self.root.geometry("570x210")
        self.root.configure(bg='#182030')


        try:
            from tkinter import ttk
            style = ttk.Style()
            style.theme_use('clam')  # или 'alt', 'classic' - простые темы
        except:
            pass

        self.sudo_password = None
        self.current_location = ""
        self.is_connected = False

        self.is_logged_in = False


        # Флаг для отслеживания состояния выпадающего меню
        self.account_menu_open = False
        self.settings_menu_open = False

        # Bind событий фокус
        self.root.bind("<FocusIn>", self.on_focus_in)
        self.root.bind("<FocusOut>", self.on_focus_out)
        self.root.bind("<Destroy>", self._cancel_menu_focus_check, add="+")
        self.root.bind("<Destroy>", self._on_destroy, add="+")
        self.root.protocol("WM_DELETE_WINDOW", self.close_app)

        self.setup_gui()
        if initial_license is not None:
            self._apply_refresh(self._refresh_generation, {'license': initial_license})
            self._last_license_refresh = time.monotonic()
        self.update_status()
        self.update_ui_for_auth_status()
        self.schedule_status_update()
        self.hide_log()
        self.log_visible = False

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
                icon = tk.PhotoImage(file=icon_path)
                self.root.iconphoto(True, icon)
        except Exception as e:
            print(f"Не удалось установить иконку: {e}")

    def on_focus_in(self, event):
        """Обрабатывает получение фокуса окном"""
        pass  # Можно добавить логику при необходимости

    def on_focus_out(self, event):
        """Debounce X focus handoffs between the owner and its popup windows."""
        pending = getattr(self, '_menu_focus_after', None)
        if pending is not None:
            self.root.after_cancel(pending)
        self._menu_focus_after = self.root.after(80, self._close_menus_if_unfocused)

    def _close_menus_if_unfocused(self):
        self._menu_focus_after = None
        focused = self.root.focus_get()
        if focused is not None:
            owner = focused.winfo_toplevel()
            if owner in (self.root, getattr(self, 'account_menu', None), getattr(self, 'settings_menu', None)):
                return
        self.close_all_menus()

    def _cancel_menu_focus_check(self, event):
        if event.widget is self.root and getattr(self, '_menu_focus_after', None):
            self.root.after_cancel(self._menu_focus_after)
            self._menu_focus_after = None

    def check_initial_login_status(self):
        return self.refresh_state()

    def setup_gui(self):
        # Основной контейнер
        self.main_container = main_container = tk.Frame(self.root, bg='#182030', padx=20, pady=14)
        main_container.pack(fill=tk.BOTH, expand=True)
        self.page = SimpleNamespace(body=main_container, footer=main_container)

        # Верхняя панель с логотипом и статусом
        header_frame = tk.Frame(main_container, bg='#182030')
        header_frame.pack(fill=tk.X)

        # Верхняя строка: логотип + иконки
        top_row_frame = tk.Frame(header_frame, bg='#182030')
        top_row_frame.pack(fill=tk.X)
        self.top_row_frame = top_row_frame
        top_row_frame.grid_columnconfigure(0, weight=1)

        left_icons_frame = tk.Frame(top_row_frame, bg='#182030')
        left_icons_frame.grid(row=0, column=0, sticky="ew")
        self.account_frame = left_icons_frame

        # Иконка личного кабинета
        self.account_icon = tk.Label(left_icons_frame, text="👤", font=("Arial", 16),
                                fg='#0a84ff', bg='#182030', cursor="hand2")
        self.account_icon.pack(side=tk.LEFT, padx=(0, 15))
        self.account_icon.bind("<Enter>", lambda e: self.account_icon.config(fg='#30d158'))
        self.account_icon.bind("<Leave>", lambda e: self.account_icon.config(fg='#0a84ff'))
        self.account_icon.bind("<Button-1>", self.toggle_account_menu)
        create_tooltip(self.account_icon, "Личный кабинет")

        # Email пользователя (рядом с иконкой)
        self.account_text_frame = tk.Frame(left_icons_frame, bg='#182030')
        self.account_text_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.email_label = tk.Label(self.account_text_frame, text="",
                            font=("Arial", 11), fg='#8e8e93', bg='#182030',
                            justify=tk.LEFT, anchor=tk.W)
        self.email_label.pack(fill=tk.X)
        self.account_status_label = tk.Label(self.account_text_frame, text="",
                            font=("Arial", 10), fg='#8e8e93', bg='#182030',
                            justify=tk.LEFT, anchor=tk.W)

        self.update_email_display()

        # Логотип и заголовок по центру
        logo_container = tk.Frame(header_frame, bg='#182030')
        logo_container.pack(fill=tk.X, pady=(10, 16))

        # Центрирующий фрейм
        center_frame = tk.Frame(logo_container, bg='#182030')
        center_frame.pack()
        self.title_frame = center_frame

        try:
            # Загрузка изображения
            manager_dir = os.path.expanduser("~/AdGuard VPN Manager")
            logo_path = os.path.join(manager_dir, "ico/logo.png")
            self.logo_image = tk.PhotoImage(file=logo_path)
            logo_icon = tk.Label(center_frame, image=self.logo_image, bg='#182030')
            logo_icon.pack(side=tk.LEFT, padx=(0, 10))
            self.logo_icon = logo_icon
            self.logo_original = self.logo_image

        except Exception as e:
            print(f"Не удалось загрузить логотип: {e}")
            logo_icon = tk.Label(center_frame, text="🛡️", font=("Arial", 24),
                            fg='white', bg='#182030')
            logo_icon.pack(side=tk.LEFT, padx=(0, 10))

        title_label = tk.Label(center_frame, text="AdGuard VPN",
                            font=("Arial", 24, "bold"),
                            fg='white', bg='#182030')
        title_label.pack(side=tk.LEFT)

        # Иконки справа
        icons_frame = tk.Frame(top_row_frame, bg='#182030')
        icons_frame.grid(row=0, column=1, sticky="e", padx=(12, 0))
        self.toolbar_frame = icons_frame

        # Статус подключения
        self.status_label = tk.Label(icons_frame, text="🔴", font=("Arial", 12),
                                    fg='#ff3b30', bg='#182030')
        self.status_label.pack(side=tk.LEFT, padx=(0, 15))
        self.status_label.bind("<Enter>", lambda e: self.status_label.config(fg='#30d158'))
        self.status_label.bind("<Leave>", lambda e: self.status_label.config(fg='#0a84ff'))
        create_tooltip(self.status_label, "Статус подключения к VPN")

        # Иконка глаза для скрытия/показа лога
        self.eye_icon = tk.Label(icons_frame, text="📝", font=("Arial", 14),
                                    fg='#0a84ff', bg='#182030', cursor="hand2")
        self.eye_icon.pack(side=tk.LEFT, padx=(0, 15))
        self.eye_icon.bind("<Enter>", lambda e: self.eye_icon.config(fg='#30d158'))
        self.eye_icon.bind("<Leave>", lambda e: self.eye_icon.config(fg='#0a84ff'))
        self.eye_icon.bind("<Button-1>", self.toggle_log_visibility)
        create_tooltip(self.eye_icon, "Показать/скрыть лог")

        # Иконка шестеренки (настройки)
        self.settings_icon = tk.Label(icons_frame, text="⚙️", font=("Arial", 22),
                                    fg='#0a84ff', bg='#182030', cursor="hand2")
        self.settings_icon.pack(side=tk.LEFT, padx=(0, 15))
        self.settings_icon.bind("<Enter>", lambda e: self.settings_icon.config(fg='#30d158'))
        self.settings_icon.bind("<Leave>", lambda e: self.settings_icon.config(fg='#0a84ff'))
        self.settings_icon.bind("<Button-1>", self.toggle_settings_menu)
        create_tooltip(self.settings_icon, "Настройки")

        # Иконка информации
        self.info_icon = tk.Label(icons_frame, text="🛈︎", font=("Arial", 16),
                                fg='#0a84ff', bg='#182030', cursor="hand2")
        self.info_icon.pack(side=tk.LEFT, padx=(0, 15))
        self.info_icon.bind("<Enter>", lambda e: self.info_icon.config(fg='#30d158'))
        self.info_icon.bind("<Leave>", lambda e: self.info_icon.config(fg='#0a84ff'))
        self.info_icon.bind("<Button-1>", lambda e: show_info_dialog(self.root))

        # Иконка доната
        self.donate_icon = tk.Label(icons_frame, text="💸", font=("Arial", 14),
                                fg='#ffcc00', bg='#182030', cursor="hand2")
        self.donate_icon.pack(side=tk.LEFT)
        self.donate_icon.bind("<Enter>", lambda e: self.donate_icon.config(fg='#ffdd44'))
        self.donate_icon.bind("<Leave>", lambda e: self.donate_icon.config(fg='#ffcc00'))
        self.donate_icon.bind("<Button-1>", self.open_donate_link)

        # Добавляем подсказки
        create_tooltip(self.settings_icon, "Список настроек")
        create_tooltip(self.info_icon, "Открыть справку AdGuard VPN")
        create_tooltip(self.donate_icon, "Поддержать разработку")

        # Основная область контента
        content_frame = tk.Frame(main_container, bg='#182030')
        content_frame.pack(fill=tk.BOTH, expand=True)

        # Кнопки
        btn_frame = tk.Frame(content_frame, bg='#182030')
        btn_frame.pack(pady=(0, 0))
        self.action_frame = btn_frame

        self.connect_button = tk.Button(btn_frame, text="Подключиться",
                                        command=self.connect_vpn, font=('Arial', 11), bg='#5BA06A', fg='white', bd=0, padx=12, pady=12, width=18, anchor='center',
                                        highlightthickness=0, cursor='hand2',
                                        activebackground='#5BA06A', activeforeground='white', takefocus=0)
        self.connect_button.grid(row=0, column=0, sticky="ew")


        self.location_button = location_button = create_hover_button_for_manager(btn_frame, "Выбрать локацию", self.select_location)
        location_button.grid(row=0, column=2, sticky="ew")

        btn_frame.grid_columnconfigure(0, weight=1, uniform="actions")
        btn_frame.grid_columnconfigure(1, minsize=12)
        btn_frame.grid_columnconfigure(2, weight=1, uniform="actions")

        # Фрейм для лога (изначально скрыт)
        self.log_frame = tk.Frame(content_frame, bg='#182030')
        self.log_frame.pack(fill=tk.BOTH, pady=(14, 0), expand=True)

        tk.Label(self.log_frame, text="Логи:",
                font=("Arial", 11), fg='white', bg='#182030').pack(anchor=tk.W, pady=(0, 5))

        self.log_text = tk.Text(self.log_frame, height=7, width=1, bg='#15354D', highlightthickness=0, wrap=tk.WORD,
                            fg='#00ff00', font=("Courier", 9))
        log_scrollbar = ttk.Scrollbar(self.log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=log_scrollbar.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.log_text.config(state=tk.DISABLED)

        self.log_visible = False
        self.page.observer = observe_window(self.root, (570, 210),
                                            layout=self._layout_main, measure=self._measure_main)
        self.page.request_fit = self.page.observer.refit

    def log_message(self, message):
        """Добавление сообщения в лог"""
        if threading.get_ident() != self._main_thread:
            self.tasks.post(self.log_message, message)
            return
        if self._closed:
            return
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"{message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def toggle_log_visibility(self, event=None):
        """Переключает видимость лога"""
        if self.log_visible:
            self.hide_log()
        else:
            self.show_log()

    def show_log(self):
        """Показывает лог"""
        self.log_frame.pack(fill=tk.BOTH, pady=(14, 0), expand=True)
        self.eye_icon.config(text="🚫")
        self.log_visible = True
        create_tooltip(self.eye_icon, "Скрыть лог")
        self.page.observer.refit()

    def hide_log(self):
        """Скрывает лог, сохраняя его содержимое и положение окна."""
        self.log_frame.pack_forget()
        self.eye_icon.config(text="📝")
        self.log_visible = False
        create_tooltip(self.eye_icon, "Показать лог")
        self.page.observer.refit()

    def _layout_main(self, width=None):
        width = self.root.winfo_width() if width is None else width
        scale = snapshot(self.root)[4]
        self.main_container.configure(padx=round(20 * scale), pady=round(14 * scale))
        if hasattr(self, 'logo_original'):
            factor = max(1, round(scale * 100))
            if getattr(self, '_logo_scale', None) != factor:
                divisor = gcd(factor, 100)
                self.logo_image = self.logo_original.zoom(factor // divisor).subsample(100 // divisor)
                self.logo_icon.configure(image=self.logo_image)
                self._logo_scale = factor
        available_actions = max(1, width - round(40 * scale))
        needed_actions = self.connect_button.winfo_reqwidth() + self.location_button.winfo_reqwidth() + 12
        narrow = needed_actions > available_actions
        if getattr(self, '_actions_narrow', None) != narrow:
            self.connect_button.grid_configure(row=0, column=0, padx=0,
                                               pady=(0, 10) if narrow else 0)
            self.location_button.grid_configure(row=1 if narrow else 0, column=0 if narrow else 2)
            self.action_frame.grid_columnconfigure(1, minsize=0 if narrow else 12)
            self.action_frame.grid_columnconfigure(2, weight=0 if narrow else 1, uniform="" if narrow else "actions")
            self._actions_narrow = narrow
        # Account text gets the width actually left after its icon, margins and
        # toolbar. A long login takes priority over keeping the toolbar inline.
        inner_width = max(1, width - 2 * int(self.main_container.cget('padx')))
        icon_width = self.account_icon.winfo_reqwidth() + 15
        inline_width = inner_width - self.toolbar_frame.winfo_reqwidth() - 12 - icon_width
        login_width = self._login_text_width()
        stacked = login_width > inline_width
        if getattr(self, '_account_stacked', None) != stacked:
            self.account_frame.grid_configure(row=0, column=0, columnspan=2 if stacked else 1,
                                              sticky='ew')
            self.toolbar_frame.grid_configure(row=1 if stacked else 0,
                                               column=0 if stacked else 1,
                                               columnspan=2 if stacked else 1,
                                               padx=0 if stacked else (12, 0),
                                               pady=(8, 0) if stacked else 0)
            self._account_stacked = stacked
        text_width = max(1, (inner_width - icon_width) if stacked else inline_width)
        for label in (self.email_label, self.account_status_label):
            insets = 2 * (label.winfo_pixels(label.cget('padx'))
                          + label.winfo_pixels(label.cget('borderwidth'))
                          + label.winfo_pixels(label.cget('highlightthickness')))
            label.configure(wraplength=max(1, text_width - insets))
        minimum_width = max(self.toolbar_frame.winfo_reqwidth(), self.title_frame.winfo_reqwidth(),
                            self.connect_button.winfo_reqwidth(), self.location_button.winfo_reqwidth())
        # Wrapping the login or moving the toolbar adds height during an ordinary
        # user resize too. Keep the actions visible without resetting that width.
        self.main_container.update_idletasks()
        minimum_height = min(max(1, self.root.winfo_screenheight()-48),
                             self.main_container.winfo_reqheight())
        self.root.minsize(min(self.root.winfo_screenwidth()-16, minimum_width+round(40*scale)),
                          minimum_height)

    def _login_text_width(self):
        text = self.email_label.cget('text')
        width = max((int(self.root.tk.call('font', 'measure', self.email_label.cget('font'), line))
                     for line in text.splitlines()), default=0)
        return width + 2 * (self.email_label.winfo_pixels(self.email_label.cget('padx'))
                            + self.email_label.winfo_pixels(self.email_label.cget('borderwidth'))
                            + self.email_label.winfo_pixels(self.email_label.cget('highlightthickness')))

    def _measure_main(self, scale):
        self._layout_main(max(round(570 * scale), self.root.winfo_width()))
        self.root.update_idletasks()
        toolbar = self.toolbar_frame.winfo_reqwidth()
        account = self.account_icon.winfo_reqwidth() + 15 + self._login_text_width()
        header_width = toolbar + 12 + account + round(40 * scale)
        width = max(round(570 * scale), min(header_width, self.root.winfo_screenwidth()-16),
                    self.title_frame.winfo_reqwidth() + round(40 * scale),
                    self.action_frame.winfo_reqwidth() + round(40 * scale))
        self._layout_main(min(width, self.root.winfo_screenwidth() - 16))
        self.root.update_idletasks()
        return width, self.main_container.winfo_reqheight()

    def update_login_button(self):
        """Обновляет текст и цвет кнопки входа/выхода"""
        pass

    def toggle_account_menu(self, event=None):
        """Открывает/закрывает меню личного кабинета"""
        if self.account_menu_open:
            self.close_account_menu()
        else:
            self.open_account_menu()

    def open_account_menu(self):
        """Открывает меню личного кабинета"""
        if self.account_menu_open:
            return

        if hasattr(self, 'settings_menu_open') and self.settings_menu_open:
            self.close_settings_menu()

        self.account_menu_open = True

        # Создаем выпадающее меню
        menu_x = self.account_icon.winfo_rootx()
        menu_y = self.account_icon.winfo_rooty() + self.account_icon.winfo_height()

        self.account_menu = tk.Toplevel(self.root)
        self.account_menu.wm_overrideredirect(True)

        # Получаем тип лицензии для определения текста кнопки
        license_type = self.get_license_type() if self.is_logged_in else "Free"

        # Динамически рассчитываем высоту меню
        if self.is_logged_in:
            # Для авторизованных: тип лицензии + инфо о лицензии + купить/продлить + выход
            menu_height = 165
        else:
            # Для неавторизованных: только вход
            menu_height = 40


        self.account_menu.configure(bg='#15354D', relief=tk.RAISED, bd=1)

        # Стиль для кнопок меню
        menu_button_style = {
            'font': ('Arial', 11),
            'bg': '#15354D',
            'fg': 'white',
            'bd': 0,
            'relief': tk.FLAT,
            'padx': 12,
            'pady': 10,
            'anchor': tk.W,
            'width': 0,
            'highlightthickness':0,
            'cursor': 'hand2'
        }

        # Стиль для текстовой информации
        text_style = {
            'font': ('Arial', 10),
            'bg': '#15354D',
            'fg': '#8e8e93',
            'bd': 0,
            'padx': 12,
            'pady': 5,
            'anchor': tk.W
        }

        # Отображаем тип лицензии (только для авторизованных пользователей)
        if self.is_logged_in:
            license_text = f"Тип лицензии: {license_type}"

            license_label = tk.Label(self.account_menu, text=license_text, **text_style)
            license_label.pack(fill=tk.X)

            # Разделитель
            separator = tk.Frame(self.account_menu, height=1, bg='#1e4a6a')
            separator.pack(fill=tk.X, padx=5, pady=2)

            # Кнопка "Инфо о лицензии"
            license_info_button = create_hover_button_for_manager(self.account_menu, text="Инфо о лицензии",
                                        command=self.check_license, **menu_button_style)
            license_info_button.pack(fill=tk.X)

            # Bind событий для hover эффекта
            license_info_button.bind("<Enter>", lambda e: license_info_button.config(bg='#1e4a6a'))
            license_info_button.bind("<Leave>", lambda e: license_info_button.config(bg='#15354D'))

            # Разделитель
            separator = tk.Frame(self.account_menu, height=1, bg='#1e4a6a')
            separator.pack(fill=tk.X, padx=5, pady=2)

            # Кнопка "Купить лицензию" или "Продлить лицензию" в зависимости от типа
            if license_type == "Free":
                renew_button_text = "Купить лицензию"
            else:
                renew_button_text = "Продлить лицензию"

            renew_button = create_hover_button_for_manager(self.account_menu, text=renew_button_text,
                                command=self.renew_license, **menu_button_style)
            renew_button.pack(fill=tk.X)

            # Bind событий для hover эффекта
            renew_button.bind("<Enter>", lambda e: renew_button.config(bg='#1e4a6a'))
            renew_button.bind("<Leave>", lambda e: renew_button.config(bg='#15354D'))

            # Разделитель перед кнопкой выхода
            separator2 = tk.Frame(self.account_menu, height=1, bg='#1e4a6a')
            separator2.pack(fill=tk.X, padx=5, pady=2)

        # Кнопка входа/выхода
        auth_text = "Выйти из аккаунта" if self.is_logged_in else "Войти в аккаунт"
        self.menu_auth_button = create_hover_button_for_manager(self.account_menu, text=auth_text,
                                        command=self.handle_menu_auth, **menu_button_style)
        self.menu_auth_button.pack(fill=tk.X)

        # Bind событий для hover эффекта
        self.menu_auth_button.bind("<Enter>", lambda e: self.menu_auth_button.config(bg='#1e4a6a'))
        self.menu_auth_button.bind("<Leave>", lambda e: self.menu_auth_button.config(bg='#15354D'))

        place_popup(self.account_menu, menu_x, menu_y)
        self.account_menu.focus_force()

        # Bind событие клика вне меню для закрытия
        self.account_menu.bind("<FocusOut>", self.on_focus_out)
        self.root.bind("<Button-1>", self.check_close_account_menu)

    def close_account_menu(self):
        """Закрывает меню личного кабинета"""
        if hasattr(self, 'account_menu') and self.account_menu:
            try:
                self.account_menu.destroy()
            except:
                pass  # Если окно уже уничтожено
        self.account_menu_open = False
        try:
            self.root.unbind("<Button-1>")
        except:
            pass

    def check_close_account_menu(self, event):
        """Проверяет, нужно ли закрыть меню при клике вне его области"""
        if (hasattr(self, 'account_menu') and self.account_menu and
            self.account_menu.winfo_exists()):

            # Проверяем, был ли клик на самом меню или иконке
            menu_widget = event.widget
            while menu_widget:
                if menu_widget == self.account_menu:
                    return  # Клик внутри меню - не закрываем
                menu_widget = menu_widget.master

            # Если клик был не в меню и не на иконке - закрываем
            if (event.widget != self.account_icon and
                not self.is_event_in_widget(event, self.account_icon)):
                self.close_account_menu()

    def is_event_in_widget(self, event, widget):
        """Проверяет, находится ли событие в области виджета"""
        try:
            x, y, width, height = (widget.winfo_rootx(), widget.winfo_rooty(),
                                widget.winfo_width(), widget.winfo_height())
            return (x <= event.x_root <= x + width and
                y <= event.y_root <= y + height)
        except:
            return False

    def handle_menu_auth(self):
        self.close_account_menu()
        self.toggle_auth()

    def renew_license(self):
        self.close_account_menu()
        self.tasks.submit(lambda: open_url(get_available_site()),
                          self._browser_result, self._browser_error, key='browser')

    def _browser_result(self, opened):
        self.log_message('🔗 Страница открыта' if opened else '❌ Не удалось открыть браузер')

    def _browser_error(self, error):
        self.log_message(f'❌ Не удалось открыть браузер: {error}')

    def toggle_settings_menu(self, event=None):
        """Открывает/закрывает меню настроек"""
        if hasattr(self, 'settings_menu_open') and self.settings_menu_open:
            self.close_settings_menu()
        else:
            self.open_settings_menu()

    def open_settings_menu(self):
        """Открывает меню настроек"""
        if hasattr(self, 'settings_menu_open') and self.settings_menu_open:
            return

        # Закрываем другие меню перед открытием
        if self.account_menu_open:
            self.close_account_menu()

        self.settings_menu_open = True

        # Создаем выпадающее меню
        menu_x = self.settings_icon.winfo_rootx()
        menu_y = self.settings_icon.winfo_rooty() + self.settings_icon.winfo_height()

        self.settings_menu = tk.Toplevel(self.root)
        self.settings_menu.wm_overrideredirect(True)

        self.settings_menu.configure(bg='#15354D', relief=tk.RAISED, bd=1)

        # Стиль для кнопок меню
        menu_button_style = {
            'font': ('Arial', 11),
            'bg': '#15354D',
            'fg': 'white',
            'bd': 0,
            'relief': tk.FLAT,
            'padx': 12,
            'pady': 10,
            'anchor': tk.W,
            'width': 0,
            'highlightthickness':0,
            'cursor': 'hand2'
        }

        # Кнопка "Основные настройки"
        settings_button = create_hover_button_for_manager(self.settings_menu, text="Основные настройки",
                                command=self.handle_settings, **menu_button_style)
        settings_button.pack(fill=tk.X)
        settings_button.bind("<Enter>", lambda e: settings_button.config(bg='#1e4a6a'))
        settings_button.bind("<Leave>", lambda e: settings_button.config(bg='#15354D'))

        # Разделитель
        separator = tk.Frame(self.settings_menu, height=1, bg='#1e4a6a')
        separator.pack(fill=tk.X, padx=5, pady=2)

        # Кнопка "Обновление"
        update_button = create_hover_button_for_manager(self.settings_menu, text="Обновление",
                                command=self.handle_update, **menu_button_style)
        update_button.pack(fill=tk.X)
        update_button.bind("<Enter>", lambda e: update_button.config(bg='#1e4a6a'))
        update_button.bind("<Leave>", lambda e: update_button.config(bg='#15354D'))

        # Разделитель
        separator = tk.Frame(self.settings_menu, height=1, bg='#1e4a6a')
        separator.pack(fill=tk.X, padx=5, pady=2)

        # Кнопка "Удалить AdGuard VPN"
        uninstall_button = create_hover_button_for_manager(self.settings_menu, text="Удалить AdGuard VPN",
                                command=self.handle_uninstall, **menu_button_style)
        uninstall_button.pack(fill=tk.X)
        uninstall_button.bind("<Enter>", lambda e: uninstall_button.config(bg='#1e4a6a'))
        uninstall_button.bind("<Leave>", lambda e: uninstall_button.config(bg='#15354D'))

        place_popup(self.settings_menu, menu_x, menu_y)
        self.settings_menu.focus_force()

        # Bind событие клика вне меню для закрытия
        self.settings_menu.bind("<FocusOut>", self.on_focus_out)
        self.root.bind("<Button-1>", self.check_close_settings_menu)

    def close_settings_menu(self):
        """Закрывает меню настроек"""
        if hasattr(self, 'settings_menu') and self.settings_menu:
            try:
                self.settings_menu.destroy()
            except:
                pass  # Если окно уже уничтожено
        self.settings_menu_open = False
        try:
            self.root.unbind("<Button-1>")
        except:
            pass

    def check_close_settings_menu(self, event):
        """Проверяет, нужно ли закрыть меню настроек при клике вне его области"""
        if (hasattr(self, 'settings_menu') and self.settings_menu and
            self.settings_menu.winfo_exists()):

            # Проверяем, был ли клик на самом меню или иконке
            menu_widget = event.widget
            while menu_widget:
                if menu_widget == self.settings_menu:
                    return  # Клик внутри меню - не закрываем
                menu_widget = menu_widget.master

            # Если клик был не в меню и не на иконке - закрываем
            if (event.widget != self.settings_icon and
                not self.is_event_in_widget(event, self.settings_icon)):
                self.close_settings_menu()

    def close_all_menus(self):
        """Закрывает все открытые выпадающие меню"""
        if self.account_menu_open:
            self.close_account_menu()
        if hasattr(self, 'settings_menu_open') and self.settings_menu_open:
            self.close_settings_menu()

    def handle_settings(self):
        """Обрабатывает клик по Основные настройки"""
        self.close_settings_menu()
        self.open_settings()

    def handle_update(self):
        """Обрабатывает клик по Обновление"""
        self.close_settings_menu()
        self.check_update()

    def handle_uninstall(self):
        """Обрабатывает клик по Удалить AdGuard VPN"""
        self.close_settings_menu()
        self.uninstall()

    def open_info_link(self, event=None):
        """Открывает ссылку на справку AdGuard VPN"""
        self.tasks.submit(lambda: open_url("https://adguard-vpn.com/kb/ru/"),
                          self._browser_result, self._browser_error, key="browser")
        self.log_message("🛈︎ Открыта справка AdGuard VPN")

    def open_donate_link(self, event=None):
        """Показывает окно доната"""
        donation_window = DonationWindow(self.root)
        donation_window.run()

    def open_settings(self):
        """Открывает окно настроек"""
        settings_window = SettingsWindow(self.root)
        settings_window.run()

    def update_status(self):
        if threading.get_ident() != self._main_thread:
            return self.tasks.post(self.update_status)
        return self.refresh_state(include_license=False)

    def refresh_state(self, include_license=True):
        if self._closed or getattr(self, "_logout_pending", False):
            return False
        generation = self._refresh_generation
        include_license = include_license or time.monotonic() - self._last_license_refresh >= 30
        def work():
            values = {}
            for command in (('status', 'license') if include_license else ('status',)):
                try:
                    values[command] = subprocess.run(['adguardvpn-cli', command],
                        capture_output=True, text=True, timeout=10)
                except Exception as error:
                    values[command] = error
            return values
        accepted = self.tasks.submit(work, lambda values: self._apply_refresh(generation, values),
                                     key='refresh')
        if accepted and include_license:
            self._last_license_refresh = time.monotonic()
        return accepted

    def _apply_refresh(self, generation, values):
        if self._closed:
            return
        if generation != self._refresh_generation:
            if getattr(self, "_refresh_after_pending", False):
                self._refresh_after_pending = False
                self.refresh_state()
            return
        license_result = values.get('license')
        if 'license' in values:
            self._auth_error = True
        if isinstance(license_result, subprocess.CompletedProcess):
            email = self.parse_user_email(license_result.stdout)
            if email:
                # Identity can be present even when license retrieval fails.
                # Retain full facts only when they belong to the same account.
                if license_result.returncode == 0:
                    self._license_text = license_result.stdout
                    self._license_partial = False
                    self._auth_error = False
                elif email != self.get_user_email():
                    self._license_text = f'Logged in as {email}'
                    self._license_partial = True
                self.is_logged_in = True
                self._auth_known = True
        result = values.get('status')
        if isinstance(result, subprocess.CompletedProcess) and result.returncode == 0:
            self.is_connected = check_if_connected(clean_ansi_codes(result.stdout))
            self.current_location = (clean_location_output(result.stdout) or 'Подключено') if self.is_connected else ''
        self.update_ui_for_auth_status()
        self.status_label.config(text='🟢' if self.is_connected else '🔴')
        color = '#ff3b30' if self.is_connected else '#5BA06A'
        self.connect_button.config(text='Отключиться' if self.is_connected else 'Подключиться',
                                   bg=color if self.is_logged_in else '#2a4d6a', activebackground=color)
        self.update_email_display()

    def get_user_email(self):
        return self.parse_user_email(self._license_text) if self._license_text else None

    def parse_user_email(self, license_text):
        """Парсит email пользователя из вывода adguardvpn-cli license"""
        try:
            # Очищаем ANSI коды
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            clean_text = ansi_escape.sub('', license_text)

            lines = clean_text.split('\n')

            for line in lines:
                line_clean = line.strip()

                # Ищем email в строке "Logged in as"
                if "Logged in as" in line_clean:
                    email_match = re.search(r'Logged in as (.+)$', line_clean)
                    if email_match:
                        email = email_match.group(1).strip()
                        # Убираем скобки если есть
                        email = email.replace('(', '').replace(')', '')
                        return email

            return None

        except Exception as e:
            return None

    def update_email_display(self):
        """Обновляет отображение email пользователя и информации о лицензии"""
        status = ""
        email = ""
        if self.is_logged_in:
            email = self.get_user_email()
            license_type = self.get_license_type()

            if email:
                # Для Free версии показываем трафик
                if license_type == "Free":
                    traffic = self.get_traffic_left()
                    if traffic:
                        status = f"Трафик: {traffic}"

                # Для Premium версий показываем дни до окончания
                elif license_type in ["Premium"]:
                    expiry_date = self.get_license_expiry()
                    if expiry_date:
                        days_left = self.get_days_until_expiry(expiry_date)
                        if days_left is not None:
                            if days_left == 0:
                                status = "Лицензия истекает сегодня"
                            elif days_left == 1:
                                status = "До окончания лицензии остался 1 день"
                            else:
                                days_text = self.get_days_text(days_left)
                                status = f"Лицензия истекает через {days_left} {days_text}"
                        else:
                            status = f"Лицензия действует до {expiry_date}"

        login = (email or "Авторизован") if self.is_logged_in else ("Не авторизован" if self._auth_known else ("Не удалось проверить аккаунт" if self._auth_error else "Проверка аккаунта…"))
        changed = (self.email_label.cget('text') != login
                   or self.account_status_label.cget('text') != status)
        self.email_label.configure(text=login,
                                   fg='#5BA06A' if self.is_logged_in else '#8e8e93')
        self.account_status_label.configure(text=status)
        if status:
            self.account_status_label.pack(fill=tk.X)
        else:
            self.account_status_label.pack_forget()
        observer = getattr(self.root, '_scale_observer', None)
        if changed and observer is not None:
            observer.refit()

    def get_traffic_left(self):
        return self.parse_traffic_left(self._license_text) if self._license_text else None

    def parse_traffic_left(self, license_text):
        """Парсит оставшийся трафик из вывода adguardvpn-cli license"""
        try:
            # Очищаем ANSI коды
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            clean_text = ansi_escape.sub('', license_text)

            lines = clean_text.split('\n')

            for line in lines:
                line_clean = line.strip()

                # Ищем оставшийся трафик в разных форматах
                if "GB left" in line_clean or "MB left" in line_clean:
                    # Паттерн для "You have X.XX GB left" или подобных
                    traffic_match = re.search(r'(\d+\.?\d*)\s*(GB|MB)\s*left', line_clean, re.IGNORECASE)
                    if traffic_match:
                        amount = traffic_match.group(1)
                        unit = traffic_match.group(2)
                        return f"{amount} {unit}"

                # Альтернативный паттерн
                if "left" in line_clean.lower():
                    traffic_match = re.search(r'(\d+\.?\d*)\s*(GB|MB)', line_clean, re.IGNORECASE)
                    if traffic_match:
                        amount = traffic_match.group(1)
                        unit = traffic_match.group(2)
                        return f"{amount} {unit}"

            return None

        except Exception as e:
            return None

    def get_license_type(self):
        if self.parse_license_expiry(self._license_text):
            return 'Premium'
        if self._license_partial:
            return 'Неизвестно'
        return self.parse_license_type(self._license_text) if self._license_text else 'Free'

    def parse_license_type(self, license_text):
        """Парсит тип лицензии из вывода adguardvpn-cli license"""
        try:
            # Очищаем ANSI коды
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            clean_text = ansi_escape.sub('', license_text)

            lines = clean_text.split('\n')

            for line in lines:
                line_clean = line.strip()

                # Ищем тип лицензии
                if "FREE version" in line_clean:
                    return "Free"
                elif "PREMIUM" in line_clean.upper():
                    return "Premium"

            # Если не нашли явного указания, считаем Free
            return "Free"

        except Exception as e:
            return "Неизвестно"

    def parse_license_info(self, license_text):
        """Парсит информацию о лицензии из вывода adguardvpn-cli license"""
        try:
            # Очищаем ANSI коды
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            clean_text = ansi_escape.sub('', license_text)

            lines = clean_text.split('\n')
            license_type = "Неизвестно"
            devices = ""
            traffic_left = ""
            email = ""

            for line in lines:
                line_clean = line.strip()

                # Ищем тип лицензии
                if "FREE version" in line_clean:
                    license_type = "Free"
                elif "PREMIUM" in line_clean.upper():
                    license_type = "Premium"

                # Ищем информацию об устройствах
                if "devices simultaneously" in line_clean:
                    devices_match = re.search(r'Up to (\d+) devices', line_clean)
                    if devices_match:
                        devices = f", {devices_match.group(1)} устройств"

                # Ищем оставшийся трафик
                if "GB left" in line_clean or "MB left" in line_clean:
                    traffic_match = re.search(r'(\d+\.?\d*)\s*(GB|MB)\s*left', line_clean)
                    if traffic_match:
                        traffic_left = f", {traffic_match.group(1)} {traffic_match.group(2)}"

                # Ищем email
                if "Logged in as" in line_clean:
                    email_match = re.search(r'Logged in as (.+)$', line_clean)
                    if email_match:
                        email = email_match.group(1)
                        # Сокращаем email для отображения
                        if len(email) > 20:
                            email = email[:15] + "..."
                        email = f" ({email})"

            # Формируем финальную строку
            if license_type != "Неизвестно":
                return f"Лицензия: {license_type}{devices}{traffic_left}{email}"
            else:
                # Если не нашли явного указания типа, но есть другие данные
                if devices or traffic_left:
                    return f"Лицензия: Free{devices}{traffic_left}{email}"
                else:
                    return "Лицензия: Free"

        except Exception as e:
            return "Лицензия: Ошибка парсинга"


    def get_license_expiry(self):
        return self.parse_license_expiry(self._license_text) if self._license_text else None

    def parse_license_expiry(self, license_text):
        """Парсит дату окончания лицензии из вывода adguardvpn-cli license"""
        try:
            # Очищаем ANSI коды
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            clean_text = ansi_escape.sub('', license_text)

            lines = clean_text.split('\n')

            for line in lines:
                line_clean = line.strip()

                # Ищем дату окончания в разных форматах
                if "subscription will be renewed on" in line_clean:
                    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', line_clean)
                    if date_match:
                        return date_match.group(1)

                # Альтернативные форматы
                elif "expires on" in line_clean.lower():
                    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', line_clean)
                    if date_match:
                        return date_match.group(1)

                elif "valid until" in line_clean.lower():
                    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', line_clean)
                    if date_match:
                        return date_match.group(1)

            return None

        except Exception as e:
            return None

    def get_days_text(self, days):
        """Возвращает правильное склонение слова 'день' в зависимости от числа"""
        if days % 10 == 1 and days % 100 != 11:
            return "день"
        elif days % 10 in [2, 3, 4] and days % 100 not in [12, 13, 14]:
            return "дня"
        else:
            return "дней"

    def get_days_until_expiry(self, expiry_date_str):
        """Рассчитывает количество дней до окончания лицензии"""
        try:
            from datetime import datetime, date

            # Парсим дату окончания
            expiry_date = datetime.strptime(expiry_date_str, '%Y-%m-%d').date()

            # Получаем текущую дату
            current_date = date.today()

            # Рассчитываем разницу в днях
            days_left = (expiry_date - current_date).days + 1

            return max(0, days_left)  # Возвращаем 0 если лицензия уже истекла

        except Exception as e:
            return None

    def update_ui_for_auth_status(self):
        """Обновляет состояние UI в зависимости от статуса авторизации"""
        if self.is_logged_in and not getattr(self, "_connection_pending", False):
            # Разблокировать кнопки
            self.connect_button.config(state=tk.NORMAL, bg='#15354D')
            # Найти кнопку "Выбрать локацию" (вторая кнопка в left_panel)
            for widget in self.connect_button.master.winfo_children():
                if isinstance(widget, tk.Button) and widget.cget('text') == "Выбрать локацию":
                    widget.config(state=tk.NORMAL, bg='#15354D')
                    break
        else:
            # Заблокировать кнопки
            self.connect_button.config(state=tk.DISABLED, bg='#2a4d6a')
            # Найти кнопку "Выбрать локацию"
            for widget in self.connect_button.master.winfo_children():
                if isinstance(widget, tk.Button) and widget.cget('text') == "Выбрать локацию":
                    widget.config(state=tk.DISABLED, bg='#2a4d6a')
                    break

    def schedule_status_update(self):
        if self._closed:
            return
        self.refresh_state(include_license=False)
        self._status_timer = self.root.after(3000, self.schedule_status_update)

    def check_connection_status(self):
        """Called by the connection worker; publish state through refresh only."""
        try:
            result = subprocess.run(['adguardvpn-cli', 'status'], capture_output=True,
                                    text=True, timeout=5)
            return result.returncode == 0 and check_if_connected(clean_ansi_codes(result.stdout))
        except Exception:
            return False

    def get_current_location(self):
        """Получает текущую локацию через детальную команду"""
        try:
            result = subprocess.run(
                ['adguardvpn-cli', 'status', '--verbose'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                output = result.stdout
                location_patterns = [
                    r'Location:\s*(.+)',
                    r'Server:\s*(.+)',
                    r'Endpoint:\s*(.+)',
                    r'Connected to:\s*(.+)'
                ]

                for pattern in location_patterns:
                    match = re.search(pattern, output, re.IGNORECASE)
                    if match:
                        location = match.group(1).strip()
                        return location

            result = subprocess.run(
                ['adguardvpn-cli', 'status'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                text = result.stdout
                if 'connected to' in text.lower():
                    parts = text.split()
                    for i, part in enumerate(parts):
                        if part.lower() == 'connected' and i + 2 < len(parts) and parts[i + 1].lower() == 'to':
                            location = parts[i + 2]
                            return location

            return None

        except Exception as e:
            return None

    def connect_vpn(self):
        """Подключается к VPN через внешнюю консоль"""
        if getattr(self, "_connection_pending", False):
            self.log_message("Подключение уже выполняется. Дождитесь завершения.")
            return
        if self.is_connected:
            self.disconnect_vpn()
            return

        # Запускаем в отдельном потоке, чтобы GUI не блокировался
        self._submit_connection(self._connect_vpn_thread)

    def _connect_vpn_thread(self):
        self.log_message("🔗 Запуск подключения в терминале...")
        try:
            # Запускаем подключение в отдельном терминале (konsole для KDE)
            command = 'konsole -e bash -c "(echo y; echo y; echo y) | adguardvpn-cli connect && echo Успешно подключено, терминал автоматически закроется! && sleep 1 || echo Ошибка подключения && sleep 2"'

            process = subprocess.Popen(
                command,
                shell=True
            )

            time.sleep(10)

            # Проверяем статус подключения
            max_attempts = 5
            for attempt in range(max_attempts):
                if self._closed:
                    return
                self.log_message(f"🔍 Проверка подключения... ({attempt + 1}/{max_attempts})")

                if self.check_connection_status():
                    current_location = self.get_current_location()
                    location_text = f" к {current_location}" if current_location else ""
                    self.log_message(f"✅ VPN успешно подключен!")
                    return

                time.sleep(3)
                self.update_status()

            self.log_message("⚠️ Проверьте терминал - возможно требуется дополнительное время")

        except Exception as e:
            self.log_message(f"❌ Ошибка при запуске подключения: {str(e)}")

    def select_location(self):
        """Подключение к выбранной локации через внешнюю консоль"""
        if getattr(self, "_connection_pending", False):
            self.log_message("Подключение уже выполняется. Дождитесь завершения.")
            return
        location_window = LocationSelectionWindow(self.root)
        selected_location = location_window.run()

        if not selected_location:
            return

        # Запускаем в отдельном потоке
        self._submit_connection(lambda: self._select_location_thread(selected_location))

    def _submit_connection(self, work):
        def done(result):
            self._connection_pending = False
            self.update_ui_for_auth_status()
            self.update_status()
        def failed(error):
            self.log_message(f'❌ Ошибка подключения: {error}')
            done(None)
        accepted = self.tasks.submit(work, done, failed, key='connect')
        if accepted:
            self._connection_pending = True
            self.update_ui_for_auth_status()
        else:
            self.log_message('Подключение уже выполняется. Дождитесь завершения.')
        return accepted

    def _select_location_thread(self, selected_location):
        """Поток для подключения к выбранной локации с автоматическими ответами"""
        try:
            self.log_message(f"🔗 Подключение к {selected_location} через терминал...")

            # Запускаем подключение к конкретной локации в терминале
            command = f'konsole -e bash -c "(echo y; echo y; echo y) | adguardvpn-cli connect -l \\"{selected_location}\\" && echo Успешно подключено, терминал автоматически закроется! && sleep 3 || echo Ошибка подключения && sleep 5"'

            process = subprocess.Popen(
                command,
                shell=True
            )

            time.sleep(10)

            # Проверяем статус
            max_attempts = 5
            connected = False

            for attempt in range(max_attempts):
                if self._closed:
                    return
                self.update_status()
                if self.check_connection_status():
                    connected = True
                    break
                time.sleep(3)

            if connected:
                current_location = self.get_current_location()
                display_location = current_location if current_location else selected_location
                self.log_message(f"✅ VPN успешно подключен!")
            else:
                time.sleep(2)
                self.update_status()

        except Exception as e:
            self.log_message(f"❌ Ошибка при подключении: {str(e)}")

    def check_update(self):
        """Открывает окно проверки обновлений"""
        update_window = UpdateWindow(self.root)
        update_window.run()

    def check_license(self):
        """Проверка лицензии"""
        self.close_account_menu()
        license_window = LicenseWindow(self.root)
        license_window.run()

    def disconnect_vpn(self):
        self.log_message('🔒 Отключение VPN...')
        self.tasks.submit(lambda: subprocess.run(['adguardvpn-cli', 'disconnect'],
            capture_output=True, text=True, timeout=10), self._disconnect_done,
            lambda error: self.log_message(f'❌ Ошибка отключения: {error}'), key='disconnect')

    def _disconnect_done(self, result):
        self.log_message('✅ VPN отключен' if result.returncode == 0 else '❌ Не удалось отключить VPN')
        self.refresh_state()

    def logout(self):
        if show_question_dialog(self.root, 'Подтверждение', 'Вы уверены, что хотите выйти из аккаунта?'):
            self._refresh_generation += 1
            self._logout_pending = True
            connected = self.is_connected
            def work():
                if connected:
                    subprocess.run(['adguardvpn-cli', 'disconnect'], capture_output=True, text=True, timeout=10)
                return subprocess.run(['adguardvpn-cli', 'logout'], capture_output=True, text=True, timeout=10)
            self.tasks.submit(work, lambda result: self._logout_success() if result.returncode == 0 else self._logout_failed(),
                              lambda error: self._logout_error(str(error)), key='logout')

    def _logout_thread(self):
        self.tasks.post(self.logout)

    def _logout_success(self):
        """Обновляет GUI после успешного выхода"""
        self._refresh_generation += 1
        self._logout_pending = False
        self._auth_known = True
        self._refresh_after_pending = False
        self._license_text = ""
        self._license_partial = False
        self.is_connected = False
        self.is_logged_in = False
        self.update_email_display()
        self.update_ui_for_auth_status()
        self.log_message("✅ Успешный выход из аккаунт")

        # Сбрасываем состояние интерфейса
        self.current_location = ""
        self.status_label.config(text="🔴", fg='#ff3b30')
        self.connect_button.config(text="Подключиться", bg='#2a4d6a', state=tk.DISABLED)

    def _logout_failed(self):
        """Обновляет GUI после неудачного выхода"""
        self._logout_pending = False
        self.log_message("❌ Не удалось выйти из аккаунта")

    def _logout_error(self, error_msg):
        """Обновляет GUI при ошибке выхода"""
        self._logout_pending = False
        self.log_message(f"❌ Ошибка при выходе: {error_msg}")

    def toggle_auth(self):
        if self.is_logged_in:
            self.logout()
        else:
            self._login_thread()

    def _login_thread(self):
        if threading.get_ident() != self._main_thread:
            self.tasks.post(self._login_thread)
            return
        if getattr(self, '_login_open', False):
            return
        self._login_open = True
        self._refresh_generation += 1
        try:
            window = ManagerAuthWindow(self.root)
            if window.run() and not self._closed:
                self._login_success()
            else:
                self._login_failed()
        except Exception as error:
            self._login_error(str(error))
        finally:
            self._login_open = False

    def _login_success(self):
        self._refresh_generation += 1
        self._refresh_after_pending = True
        self._last_license_refresh = float("-inf")
        self.is_logged_in = True
        self._auth_known = True
        self.update_email_display()
        self.update_ui_for_auth_status()
        self.refresh_state()
        self.log_message('✅ Успешный вход в аккаунт')

    def _login_failed(self):
        """Обновляет GUI после неудачной авторизации"""
        self.log_message("❌ Авторизация не удалась")

    def _login_error(self, error_msg):
        """Обновляет GUI при ошибке авторизации"""
        self.log_message(f"❌ Ошибка авторизации: {error_msg}")

    def uninstall(self):
        """Удаление AdGuard VPN"""
        uninstall_window = UninstallWindow(self.root)
        uninstall_window.run()

    def close_app(self):
        self._closed = True
        self._refresh_generation += 1
        if self._status_timer is not None:
            self.root.after_cancel(self._status_timer)
            self._status_timer = None
        self.tasks.close()
        self.close_all_menus()
        self.root.destroy()

    def _on_destroy(self, event):
        if event.widget is self.root:
            self._closed = True
            self._refresh_generation += 1
            if self._status_timer is not None:
                self.root.after_cancel(self._status_timer)
                self._status_timer = None
            self.tasks.close()

    def run(self):
        self.root.mainloop()
