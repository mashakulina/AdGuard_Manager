from core.ui_scaling import grab_when_visible
from core.ui_tasks import TaskRunner
from ui.components.adaptive import AdaptivePage
import tkinter as tk
import subprocess
import re
import os
from ui.components.button_styler import create_hover_button, apply_hover_effect
import platform

class SettingsWindow:
    def __init__(self, parent):
        self.parent = parent
        self.root = tk.Toplevel(parent)
        self.setup_window_properties()
        self.root.title("Настройки AdGuard VPN")

        self.root.configure(bg='#182030')
        self.root.transient(parent)
        grab_when_visible(self.root)

        try:
            from tkinter import ttk
            style = ttk.Style()
            style.theme_use('clam')  # или 'alt', 'classic' - простые темы
        except:
            pass

        self.tasks = TaskRunner(self.root)
        self._load_generation = 0
        self.setup_ui()
        self.load_current_settings()

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

    def setup_ui(self):
        self.page = AdaptivePage(self.root, (690, 560), getattr(self, 'parent', None))
        main_frame = self.page.body

        title_label = tk.Label(main_frame, text="Настройки AdGuard VPN",
                              font=("Arial", 16, "bold"), fg='white', bg='#182030')
        title_label.pack(pady=(0, 20))

        # Создаем контейнер для двух колонок
        columns_frame = tk.Frame(main_frame, bg='#182030')
        columns_frame.pack(fill=tk.X)

        # Левая колонка - Основные настройки
        left_column = tk.Frame(columns_frame, bg='#182030')
        left_column.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))


        # Правая колонка - Дополнительные настройки
        right_column = tk.Frame(columns_frame, bg='#182030')
        right_column.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))


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

        self.page.responsive_columns(columns_frame, (left_column, right_column), gap=20,
                                     equal_width=False, fit_width=True)

        # === ЛЕВАЯ КОЛОНКА - ОСНОВНЫЕ НАСТРОЙКИ ===

        # Настройка режима VPN
        mode_frame = tk.Frame(left_column, bg='#182030', relief=tk.GROOVE, bd=0, padx=0, pady=0)
        mode_frame.pack(fill=tk.X, pady=(0, 16))

        tk.Label(mode_frame, text="Режим VPN:",
                font=("Arial", 12, "bold"), fg='white', bg='#182030').pack(anchor=tk.W)

        # Фрейм для кнопок режима
        mode_buttons_frame = tk.Frame(mode_frame, bg='#182030')
        mode_buttons_frame.pack(fill=tk.X, pady=10)

        self.mode_var = tk.StringVar(value="TUN")

        self.tun_btn = tk.Radiobutton(mode_buttons_frame, text="TUN режим",
                                    variable=self.mode_var, value="TUN",
                                    font=("Arial", 10), fg='white', bg='#182030',
                                    selectcolor='#15354D', activebackground='#182030',
                                    activeforeground='white', bd=0, highlightthickness=0, cursor="hand2")
        self.tun_btn.pack(side=tk.LEFT, padx=(0, 20))

        self.socks_btn = tk.Radiobutton(mode_buttons_frame, text="SOCKS5 режим",
                                       variable=self.mode_var, value="SOCKS",
                                       font=("Arial", 10), fg='white', bg='#182030',
                                       selectcolor='#15354D', activebackground='#182030',
                                       activeforeground='white', bd=0, highlightthickness=0, cursor="hand2")
        self.socks_btn.pack(side=tk.LEFT)

        self.page.responsive_row(mode_buttons_frame, (self.tun_btn, self.socks_btn), gap=12, align="left")

        # Кнопка применения режима
        apply_btn = create_hover_button(mode_frame, text="Применить",
                                        command=self.apply_mode, **button_style)
        apply_btn.pack(anchor=tk.W, pady=(6, 0))

        # Настройка DNS-адреса
        dns_frame = tk.Frame(left_column, bg='#182030', relief=tk.GROOVE, bd=0, padx=0, pady=0)
        dns_frame.pack(fill=tk.X, pady=(0, 16))

        tk.Label(dns_frame, text="DNS-настройки:",
                font=("Arial", 12, "bold"), fg='white', bg='#182030').pack(anchor=tk.W)

        # Фрейм для ввода порта
        dns_input_frame = tk.Frame(dns_frame, bg='#182030')
        dns_input_frame.pack(fill=tk.X, pady=10)

        tk.Label(dns_input_frame, text="DNS сервер:",
                font=("Arial", 10), fg='white', bg='#182030').pack(side=tk.LEFT)

        self.dns_entry = tk.Entry(dns_input_frame, width=10, font=('Arial', 10),
                                bg='#15354D', fg='white', highlightthickness=0, cursor="hand2")
        self.dns_entry.pack(side=tk.LEFT, padx=(10, 20))
        self.dns_entry.insert(0, "1.1.1.1")  # Пример порта по умолчанию

        # Кнопки для DNS
        dns_buttons_frame = tk.Frame(dns_frame, bg='#182030')
        dns_buttons_frame.pack(fill=tk.X, pady=(6, 0))

        apply_dns_btn = create_hover_button(dns_buttons_frame, text="Применить DNS",
                                            command=self.set_dns, **button_style)
        apply_dns_btn.pack(side=tk.LEFT, padx=(0, 10))

        # Кнопка для возврата к настройкам по умолчанию
        default_btn = create_hover_button(dns_buttons_frame, text="Сбросить",
                                          command=self.set_default_dns, **button_style)
        default_btn.pack(side=tk.LEFT, padx=(0, 10))


        self.page.responsive_row(dns_buttons_frame, (apply_dns_btn, default_btn), gap=10, align="left")

        # === ПРАВАЯ КОЛОНКА - ДОПОЛНИТЕЛЬНЫЕ НАСТРОЙКИ ===
        # Настройка режима маршрутизации VPN-туннеля
        routing_frame = tk.Frame(right_column, bg='#182030', relief=tk.GROOVE, bd=0, padx=0, pady=0)
        routing_frame.pack(fill=tk.X, pady=(0, 16))

        tk.Label(routing_frame, text="Режим VPN-туннеля:",
                font=("Arial", 12, "bold"), fg='white', bg='#182030').pack(anchor=tk.W)

        # Фрейм для кнопок режима маршрутизации
        routing_buttons_frame = tk.Frame(routing_frame, bg='#182030')
        routing_buttons_frame.pack(fill=tk.X, pady=10)

        self.routing_var = tk.StringVar(value="NONE")

        self.routing_none_btn = tk.Radiobutton(routing_buttons_frame, text="NONE",
                                              variable=self.routing_var, value="NONE",
                                              font=("Arial", 10), fg='white', bg='#182030',
                                              selectcolor='#15354D', activebackground='#182030',
                                              activeforeground='white', bd=0, highlightthickness=0, cursor="hand2")
        self.routing_none_btn.pack(side=tk.LEFT, padx=(0, 20))

        self.routing_auto_btn = tk.Radiobutton(routing_buttons_frame, text="AUTO",
                                              variable=self.routing_var, value="AUTO",
                                              font=("Arial", 10), fg='white', bg='#182030',
                                              selectcolor='#15354D', activebackground='#182030',
                                              activeforeground='white', bd=0, highlightthickness=0, cursor="hand2")
        self.routing_auto_btn.pack(side=tk.LEFT)

        self.page.responsive_row(routing_buttons_frame, (self.routing_none_btn, self.routing_auto_btn), gap=12, align="left")

        # Кнопка применения режима маршрутизации
        apply_tun_btn = create_hover_button(routing_frame, text="Применить",
                                            command=self.apply_routing_mode, **button_style)
        apply_tun_btn.pack(anchor=tk.W, pady=(6, 0))

        # Настройка порта SOCKS5
        port_frame = tk.Frame(right_column, bg='#182030', relief=tk.GROOVE, bd=0, padx=0, pady=0)
        port_frame.pack(fill=tk.X, pady=(0, 10))

        tk.Label(port_frame, text="Порт SOCKS5:",
                font=("Arial", 12, "bold"), fg='white', bg='#182030').pack(anchor=tk.W)

        # Фрейм для ввода порта
        port_input_frame = tk.Frame(port_frame, bg='#182030')
        port_input_frame.pack(fill=tk.X, pady=10)

        tk.Label(port_input_frame, text="Номер порта:",
                font=("Arial", 10), fg='white', bg='#182030').pack(side=tk.LEFT)

        self.port_entry = tk.Entry(port_input_frame, width=10, font=('Arial', 10),
                                bg='#15354D', fg='white', highlightthickness=0, cursor="hand2")
        self.port_entry.pack(side=tk.LEFT, padx=(10, 0))
        self.port_entry.insert(0, "1080")  # Пример порта по умолчанию

        # Кнопка установки порта
        apply_port_btn = create_hover_button(port_frame, text="Установить порт",
                                             command=self.set_socks_port, **button_style)
        apply_port_btn.pack(anchor=tk.W, pady=(6, 0))

        # # Пустое пространство для выравнивания
        # spacer_frame = tk.Frame(right_column, bg='#182030')
        # spacer_frame.pack(fill=tk.BOTH, expand=True)


        # Информационная рамка
        info_frame = tk.Frame(main_frame, bg='#182030', relief=tk.GROOVE, bd=0, padx=0, pady=0)
        info_frame.pack(fill=tk.X, pady=(0, 0))

        tk.Label(info_frame, text="Справка:",
                font=("Arial", 11, "bold"), fg='white', bg='#182030').pack(anchor=tk.W)

        info_text = (
            "• TUN: Полное VPN-подключение\n"
            "• SOCKS5: Прокси-режим через порт\n"
            "• NONE: Без маршрутизации\n"
            "• AUTO: Автоматическая маршрутизация\n"
            "• DNS: Укажите свой"
        )

        info_label = tk.Label(info_frame, text=info_text, font=("Arial", 10),
                             fg='#8e8e93', bg='#182030', justify=tk.LEFT, anchor=tk.W)
        info_label.pack(fill=tk.X, pady=0)
        self.page.wrap(info_label)

        # Статус бар внизу основного окна
        self.status_var = tk.StringVar(value="Готов к настройке")
        status_bar = tk.Label(main_frame, textvariable=self.status_var,
                             relief=tk.SUNKEN, anchor=tk.W, bg='#15354D', fg='white', highlightthickness=0)
        status_bar.pack(fill=tk.X, pady=(16, 0))
        self.page.wrap(status_bar)

        # Кнопка закрытия - по центру
        btn_frame = tk.Frame(self.page.footer, bg='#182030')
        btn_frame.pack(fill=tk.X, pady=(8, 10))

        close_btn = create_hover_button(btn_frame, text="Закрыть",
                                        command=self.close_window, **button_style)
        close_btn.pack(anchor=tk.CENTER)

        self.page.request_fit()

    def load_current_settings(self):
        self._load_generation += 1
        generation = self._load_generation
        initial = (self.mode_var.get(), self.port_entry.get(), self.dns_entry.get(), self.routing_var.get())
        def work():
            values = {}
            for name in ('get-mode', 'get-socks-port', 'get-dns', 'get-tun-routing-mode'):
                result = subprocess.run(['adguardvpn-cli', 'config', name], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    values[name] = result.stdout.strip()
            return values
        def apply(values):
            if generation != self._load_generation:
                return
            if self.mode_var.get() == initial[0] and 'get-mode' in values:
                self.mode_var.set('SOCKS' if 'SOCKS' in values['get-mode'].upper() else 'TUN')
            for entry, old, name in ((self.port_entry, initial[1], 'get-socks-port'), (self.dns_entry, initial[2], 'get-dns')):
                if entry.get() == old and name in values:
                    entry.delete(0, tk.END)
                    entry.insert(0, values[name])
            if self.routing_var.get() == initial[3] and 'get-tun-routing-mode' in values:
                self.routing_var.set('NONE' if 'NONE' in values['get-tun-routing-mode'].upper() else 'AUTO')
            self.status_var.set('Настройки загружены')
        self.status_var.set('Загрузка настроек…')
        self.tasks.submit(work, apply, lambda error: self.status_var.set(f'❌ Ошибка загрузки настроек: {error}'), key='load')

    def apply_mode(self):
        """Применяет выбранный режим VPN"""
        selected_mode = self.mode_var.get()

        if selected_mode == "SOCKS":
            command = ['adguardvpn-cli', 'config', 'set-mode', 'SOCKS']
        else:
            command = ['adguardvpn-cli', 'config', 'set-mode', 'TUN']

        self._apply_setting_thread(command, f"Режим {selected_mode} успешно установлен")

    def set_socks_port(self):
        """Устанавливает порт SOCKS5"""
        port_text = self.port_entry.get().strip()

        if not port_text:
            self.status_var.set(f"❌ Ошибка. Введите номер порта")
            return

        if not port_text.isdigit():
            self.status_var.set(f"❌ Ошибка. Номер порта должен быть числом")
            return

        port = int(port_text)
        if port < 1 or port > 65535:
            self.status_var.set(f"❌ Ошибка. Номер порта должен быть в диапазоне 1-65535")
            return

        command = ['adguardvpn-cli', 'config', 'set-socks-port', str(port)]

        self._apply_setting_thread(command, f"Порт SOCKS5 изменен на {port}")

    def set_dns(self):
        """Устанавливает DNS-сервер"""
        dns_address = self.dns_entry.get().strip()

        if not dns_address:
            self.status_var.set(f"❌ Ошибка. Введите DNS-адрес")
            return

        # Простая валидация DNS-адреса
        if not re.match(r'^([0-9]{1,3}\.){3}[0-9]{1,3}$', dns_address):
            self.status_var.set(f"❌ Ошибка. Введите корректный IP-адрес DNS-сервера")
            return

        command = ['adguardvpn-cli', 'config', 'set-dns', dns_address]

        self._apply_setting_thread(command, f"DNS-сервер изменен на {dns_address}")

    def set_default_dns(self):
        """Возвращает DNS настройки к значениям по умолчанию"""
        default_dns = "default"

        # Обновляем поле ввода
        self.dns_entry.delete(0, tk.END)
        self.dns_entry.insert(0, default_dns)

        # Применяем настройку
        command = ['adguardvpn-cli', 'config', 'set-dns', default_dns]

        self._apply_setting_thread(command, f"DNS восстановлен по умолчанию: {default_dns}")

    def apply_routing_mode(self):
        """Применяет выбранный режим маршрутизации"""
        selected_routing = self.routing_var.get()

        command = ['adguardvpn-cli', 'config', 'set-tun-routing-mode', selected_routing]

        self._apply_setting_thread(command, f"Режим маршрутизации изменен на {selected_routing}")

    def _apply_setting_thread(self, command, success_message):
        self._load_generation += 1
        if not hasattr(self, '_setting_pending'):
            self._setting_pending = {}
            self._setting_active = set()
        key = command[2]
        self._setting_pending[key] = (list(command), success_message)
        if key in self._setting_active:
            self.status_var.set(f'Ожидание применения {key}…')
            return
        self._start_setting(key)

    def _start_setting(self, key):
        command, success_message = self._setting_pending.pop(key)
        self._setting_active.add(key)
        self.status_var.set(f'Установка {key}…')
        def finish(result=None, error=None):
            self._setting_active.discard(key)
            if key in self._setting_pending:
                self._start_setting(key)
                return
            if error is not None:
                message = f'❌ Ошибка изменения настройки: {error}'
            elif result.returncode == 0:
                message = f'✅ {success_message}'
            else:
                message = f'❌ Не удалось изменить настройку: {result.stderr}'
            self.status_var.set(message)
        self.tasks.submit(lambda: subprocess.run(command, capture_output=True, text=True, timeout=10),
                          finish, lambda error: finish(error=error), key=key)

    def close_window(self):
        self._load_generation += 1
        self.tasks.close()
        self.root.destroy()

    def run(self):
        self.root.wait_window()
