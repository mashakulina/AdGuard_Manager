from core.ui_tasks import TaskRunner
from utils.browser import open_url
from ui.components.adaptive import AdaptivePage
import tkinter as tk
import subprocess
import urllib.parse
import re
import os
from urllib.request import urlopen
from ui.components.button_styler import create_hover_button
from config.manager_config import MANAGER_CONFIG
_last_available_site = None
_last_check_time = 0


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

def get_adguard_current_version():
    """Получает текущую версию AdGuard VPN"""
    try:
        result = subprocess.run(
            ['adguardvpn-cli', '-v'],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode == 0:
            # Очищаем вывод от ANSI кодов и лишних символов
            version_output = clean_ansi_codes(result.stdout).strip()

            # Ищем версию в формате vX.X.X или X.X.X
            version_match = re.search(r'v?(\d+\.\d+\.\d+)', version_output)
            if version_match:
                return f"{version_match.group(1)}"

            # Если не нашли через regex, возвращаем как есть (очищенное)
            return version_output if version_output else "Неизвестно"

        return "Неизвестно"
    except Exception as e:
        return "Неизвестно"

def get_manager_version():
    """Получает версию менеджера"""
    return MANAGER_CONFIG.get("current_version", "Неизвестно")

def clean_ansi_codes(text):
    """Очищает текст от ANSI escape sequences"""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

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

def check_site_availability_simple(url):
    """Простая проверка через HEAD запрос"""
    try:
        import urllib.request
        import ssl

        # Создаем контекст без проверки SSL (на случай проблем с сертификатами)
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        # Создаем запрос
        req = urllib.request.Request(url, method='HEAD')

        # Выполняем запрос с таймаутом
        response = urllib.request.urlopen(req, timeout=5, context=context)
        return response.getcode() == 200

    except Exception:
        return False

def show_info_dialog(parent):
    """Показывает диалоговое окно с информацией о AdGuard VPN"""
    dialog = tk.Toplevel(parent)
    tasks = TaskRunner(dialog)

    # Применяем настройки окна
    try:
        dialog.title("AdGuard VPN Manager")
        dialog.wm_class("AdGuardVPNManager")

        manager_dir = os.path.expanduser("~/AdGuard VPN Manager")
        icon_path = os.path.join(manager_dir, "ico/adguard.png")
        if os.path.exists(icon_path):
            icon = tk.PhotoImage(file=icon_path)
            dialog.iconphoto(True, icon)
    except Exception as e:
        print(f"Не удалось установить свойства окна: {e}")

    dialog.title("Информация о AdGuard VPN")

    dialog.configure(bg='#182030')
    dialog.transient(parent)

    page = AdaptivePage(dialog, (430, 470), parent)
    # Заголовок
    title_frame = tk.Frame(page.body, bg='#182030')
    title_frame.pack(fill=tk.X, pady=(0, 15))

    tk.Label(title_frame, text="Информация",
             font=("Arial", 14, "bold"), bg='#182030', fg='white').pack()

    # Основное содержимое
    content_frame = tk.Frame(page.body, bg='#182030')
    content_frame.pack(fill=tk.BOTH, expand=True)

    # Информационное сообщение
    info_text = (
        "AdGuard VPN Manager создан энтузиастом для упрощения работы с AdGuard VPN в Linux-окружении и не является официальным продуктом. По вопросам функционирования VPN-сервиса следует обращаться на официальный сайт разработчиков AdGuard"
    )

    info_frame = tk.Frame(content_frame, bg='#182030')
    info_frame.pack(fill=tk.X, pady=(0, 20))

    # Автоматический расчет wraplength
    window_width = 395
    padding = 50
    auto_wraplength = window_width - padding

    info_label = tk.Label(info_frame, text=info_text,
                        font=('Arial', 11),
                        bg='#182030',
                        fg='#ff9500',
                        wraplength=auto_wraplength,
                        justify=tk.CENTER
                        )
    info_label.pack(fill=tk.X)
    page.wrap(info_label)

    def browser_result(opened):
        if not opened:
            info_label.configure(text='Не удалось открыть браузер. Попробуйте ещё раз.')
            page.request_fit()

    def browser_error(error):
        browser_result(False)

    # Сначала объявляем функции для ссылок
    def open_official_page(event):
        tasks.submit(lambda: open_url(get_available_site()), browser_result, browser_error, key='browser')

    def open_knowledge_base(event):
        tasks.submit(lambda: open_url('https://adguard-vpn.com/kb/'), browser_result, browser_error, key='browser')

    def open_github_page(event):
        tasks.submit(lambda: open_url('https://github.com/mashakulina/AdGuard_Manager'), browser_result, browser_error, key='browser')

    # Функция для создания ссылки с разделенной иконкой и текстом
    def create_link_with_icon(parent, icon, text, command_func):
        link_frame = tk.Frame(parent, bg='#182030')
        link_frame.pack(anchor=tk.W, pady=(0, 8), fill=tk.X)

        # Иконка (без подчеркивания)
        icon_label = tk.Label(link_frame, text=icon, font=('Arial', 11),
                            bg='#182030', fg='#3CAA3C', cursor='hand2')
        icon_label.grid(row=0, column=0, sticky='nw', padx=(0, 8))
        icon_label.bind("<Button-1>", command_func)
        icon_label.bind("<Enter>", lambda e: (icon_label.config(fg='#4d8058'),
                                            text_label.config(fg='#4d8058', font=('Arial', 11, 'underline'))))
        icon_label.bind("<Leave>", lambda e: (icon_label.config(fg='#3CAA3C'),
                                            text_label.config(fg='#3CAA3C', font=('Arial', 11))))

        # Текст (с подчеркиванием при наведении)
        text_label = tk.Label(link_frame, text=text, font=('Arial', 11),
                            bg='#182030', fg='#3CAA3C', cursor='hand2', justify=tk.LEFT, anchor=tk.W)
        text_label.grid(row=0, column=1, sticky='ew')
        link_frame.grid_columnconfigure(1, weight=1)
        page.wrap(text_label, reserve=lambda: icon_label.winfo_reqwidth() + 8)
        text_label.bind("<Button-1>", command_func)
        text_label.bind("<Enter>", lambda e: (icon_label.config(fg='#4d8058'),
                                            text_label.config(fg='#4d8058', font=('Arial', 11, 'underline'))))
        text_label.bind("<Leave>", lambda e: (icon_label.config(fg='#3CAA3C'),
                                            text_label.config(fg='#3CAA3C', font=('Arial', 11))))

        return link_frame

    # Создаем ссылки с разделенными иконками и текстом
    create_link_with_icon(content_frame, "🌐", "Официальный сайт AdGuard VPN", open_official_page)
    create_link_with_icon(content_frame, "📚", "База знаний AdGuard VPN", open_knowledge_base)
    create_link_with_icon(content_frame, "💻", "Страница AdGuard VPN Manager на GitHub", open_github_page)

    # Отображаем версии в одну строку по центру
    versions_frame = tk.Frame(content_frame, bg='#182030')
    versions_frame.pack(fill=tk.X, pady=(10,0))

    # Версия AdGuard VPN и менеджера в одну строку
    vpn_version = 'Загрузка…'
    manager_version = get_manager_version()

    version_text = f"AdGuard VPN: {vpn_version} | AdGuard VPN Manager: {manager_version}"
    version_label = tk.Label(versions_frame, text=version_text,
                           font=("Arial", 9), fg='#5BA06A', bg='#182030')
    version_label.pack(fill=tk.X)
    page.wrap(version_label)
    def apply_version(version):
        version_label.configure(text=f'AdGuard VPN: {version} | AdGuard VPN Manager: {manager_version}')
        page.request_fit()
    tasks.submit(get_adguard_current_version, apply_version,
                 lambda error: apply_version('Неизвестно'), key='version')

    # Кнопка закрытия
    button_frame = tk.Frame(page.footer, bg='#182030')
    button_frame.pack(fill=tk.X, pady=(5, 0))

    close_style = {
        'font': ('Arial', 10),
        'bg': '#15354D',
        'fg': 'white',
        'bd': 0,
        'padx': 20,
        'pady': 8,
        'width': 10,
        'highlightthickness': 0,
        'cursor': 'hand2'
    }

    close_btn = create_hover_button(button_frame, text="Закрыть",
                                  command=dialog.destroy, **close_style)
    close_btn.pack()

    # Обработка клавиш
    dialog.bind('<Escape>', lambda e: dialog.destroy())
    dialog.bind('<Return>', lambda e: dialog.destroy())

    # Устанавливаем фокус на диалоговое окно
    dialog.focus_set()

    # Ждем закрытия окна
    page.request_fit()
    dialog.wait_window()
