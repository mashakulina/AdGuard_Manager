from ui.components.adaptive import AdaptivePage
import tkinter as tk
from tkinter import ttk, scrolledtext
import subprocess
import os
import tempfile
import tarfile
import urllib.request
import platform
import threading
import shutil
from core.auth import AuthWindow
from core.utils import detect_os, detect_arch, resolve_cli_release
import sys
from ui.components.button_styler import create_hover_button, apply_hover_effect

class AdGuardVPNInstaller:
    def __init__(self, sudo_password):
        self.root = tk.Tk()
        self.setup_window_properties()
        self.root.title("Установка AdGuard VPN")
        self.root.configure(bg='#182030')

        try:
            from tkinter import ttk
            style = ttk.Style()
            style.theme_use('clam')  # или 'alt', 'classic' - простые темы
        except:
            pass

        self.sudo_password = sudo_password
        self.filesystem_unlocked = False
        self.installation_complete = False  # Флаг завершения установки
        self.setup_ui()

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
        # Основной фрейм
        self.page = AdaptivePage(self.root, (430, 470), getattr(self, 'parent', None))
        main_frame = self.page.body

        # Заголовок
        title_label = tk.Label(main_frame, text="AdGuard VPN Installer",
                              font=("Arial", 16, "bold"), fg='white', bg='#182030')
        title_label.pack(pady=10)

        # Информация о системе
        info_frame = tk.Frame(main_frame, bg='#182030')
        info_frame.pack(fill=tk.X, pady=5)

        try:
            os_info = detect_os()
            arch_info = detect_arch()
            sys_info = f"ОС: {os_info}, Архитектура: {arch_info}"
        except Exception as e:
            sys_info = f"Ошибка определения системы: {str(e)}"

        system_label = tk.Label(info_frame, text=sys_info, fg='white', bg='#182030', justify=tk.LEFT, anchor=tk.W)
        system_label.pack(fill=tk.X)
        self.page.wrap(system_label)
        path_label = tk.Label(info_frame, text="Будет установлено в: /opt/adguardvpn_cli",
                fg='white', bg='#182030', justify=tk.LEFT, anchor=tk.W)
        path_label.pack(fill=tk.X, pady=(5, 0))
        self.page.wrap(path_label)

        # Фрейм установки
        install_frame = tk.Frame(main_frame, bg='#182030')
        install_frame.pack(fill=tk.BOTH, expand=True, pady=(5, 0))

        instructions_label = tk.Label(install_frame,
                text="Нажмите 'Установить' для начала\nустановки AdGuard VPN",
                font=("Arial", 10), fg='white', bg='#182030', justify=tk.LEFT, anchor=tk.W)
        instructions_label.pack(fill=tk.X, pady=5)
        self.page.wrap(instructions_label)

        # Кнопки установки
        btn_frame = tk.Frame(self.page.footer, bg='#182030')
        btn_frame.pack(fill=tk.X, pady=5)

        button_style = {
            'font': ('Arial', 10),
            'bg': '#15354D',
            'fg': 'white',
            'bd': 0,
            'relief': tk.FLAT,
            'padx': 20,
            'pady': 5,
            'width': 10,
            'highlightthickness':0,
            'cursor': 'hand2'
        }

        install_btn = create_hover_button(btn_frame, text="Установить",
                 command=self.install_vpn, **button_style)
        install_btn.grid(row=0, column=1, padx=(0, 10))

        exit_btn = create_hover_button(btn_frame, text="Выход",
                                       command=self.close_app,**button_style)
        exit_btn.grid(row=0, column=2)

        # Центрируем весь фрейм с кнопками
        btn_frame.grid_columnconfigure(0, weight=1)
        btn_frame.grid_columnconfigure(1, weight=1)
        btn_frame.grid_columnconfigure(2, weight=1)
        btn_frame.grid_columnconfigure(3, weight=1)

        # Текстовое поле для логов
        log_frame = tk.Frame(install_frame, bg='#182030')
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

        self.log_text = tk.Text(log_frame, height=7, width=1,
                                                 wrap=tk.WORD, bg='#15354D', fg='white', highlightthickness=0,
                                                 font=("Courier", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)

        self.page.responsive_row(btn_frame)
        self.page.request_fit()

    def close_app(self):
        sys.exit()

    def log_message(self, message):
        # Проверяем, существует ли еще виджет log_text
        try:
            self.log_text.insert(tk.END, f"{message}\n")
            self.log_text.see(tk.END)
            self.root.update()
        except tk.TclError:
            # Если виджет уже уничтожен, просто игнорируем сообщение
            pass

    def unlock_filesystem(self):
        """Разблокировка файловой системы SteamOS"""
        try:
            self.log_message("Разблокировка файловой системы SteamOS...")
            cmd = f'echo "{self.sudo_password}" | sudo -S steamos-readonly disable'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

            if result.returncode == 0:
                self.filesystem_unlocked = True
                self.log_message("✅ Файловая система разблокирована")
                return True
            else:
                self.log_message(f"⚠️ Предупреждение: не удалось разблокировать файловую систему: {result.stderr}")
                return True  # Продолжаем установку
        except Exception as e:
            self.log_message(f"⚠️ Предупреждение: ошибка разблокировки: {str(e)}")
            return True

    def lock_filesystem(self):
        """Блокировка файловой системы SteamOS"""
        if not self.filesystem_unlocked or self.installation_complete:
            return

        try:
            self.log_message("Блокировка файловой системы SteamOS...")
            cmd = f'echo "{self.sudo_password}" | sudo -S steamos-readonly enable'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

            if result.returncode == 0:
                self.log_message("✅ Файловая система заблокирована")
            else:
                self.log_message(f"⚠️ Предупреждение: не удалось заблокировать файловую систему: {result.stderr}")
        except Exception as e:
            self.log_message(f"⚠️ Предупреждение: ошибка блокировки: {str(e)}")

    def install_vpn(self):
        thread = threading.Thread(target=self._install_vpn_thread)
        thread.daemon = True
        thread.start()

    def _install_vpn_thread(self):
        try:
            self.root.after(0, lambda: self.log_message("=== Начало установки AdGuard VPN ==="))

            # Resolve the official release before any privileged/system changes.
            os_type = platform.system().lower()
            arch = detect_arch()
            version, download_url, package_name = resolve_cli_release(os_type, arch)
            self.root.after(0, lambda: self.log_message(f"Версия: {version}"))
            self.root.after(0, lambda: self.log_message(f"ОС: {os_type}, Архитектура: {arch}"))

            if not self.unlock_filesystem():
                raise Exception("Не удалось разблокировать файловую систему")

            self.root.after(0, lambda: self.log_message(f"Пакет: {package_name}"))
            self.root.after(0, lambda: self.log_message(f"URL для скачивания: {download_url}"))

            # Скачиваем и устанавливаем
            success = self.download_and_install(download_url, package_name, version)

            if success:
                self.root.after(0, self._install_success)
            else:
                self.root.after(0, lambda: self._install_fail("Ошибка установки"))

        except Exception as e:
            self.root.after(0, lambda message=str(e): self._install_fail(f"Ошибка: {message}"))
        finally:
            # Всегда блокируем файловую систему обратно, если установка не завершена успешно
            if self.filesystem_unlocked and not self.installation_complete:
                self.lock_filesystem()

    def _install_fail(self, message):
        self.installation_complete = False
        self.log_message(f"❌ {message}")

    def download_and_install(self, download_url, package_name, version):
        try:
            # Создаем временную директорию для распаковки
            temp_dir = tempfile.mkdtemp()
            archive_path = os.path.join(temp_dir, package_name)
            extract_dir = os.path.join(temp_dir, "extracted")

            # Скачиваем файл
            self.root.after(0, lambda: self.log_message("📥 Скачивание архива..."))
            urllib.request.urlretrieve(download_url, archive_path)
            self.root.after(0, lambda: self.log_message("✅ Архив успешно скачан"))

            # Распаковываем tar.gz во временную директорию
            self.root.after(0, lambda: self.log_message("📦 Распаковка архива..."))
            os.makedirs(extract_dir, exist_ok=True)
            with tarfile.open(archive_path, 'r:gz') as tar:
                tar.extractall(extract_dir)
            self.root.after(0, lambda: self.log_message("✅ Архив распакован"))

            # Находим корневую папку с содержимым
            content_root = self.find_content_root(extract_dir)
            self.root.after(0, lambda: self.log_message(f"📁 Корневая папка с содержимым: {content_root}"))

            # Создаем целевую директорию
            install_dir = "/opt/adguardvpn_cli"

            self.root.after(0, lambda: self.log_message(f"🔧 Создание директории {install_dir}..."))

            # Создаем директорию с помощью sudo
            cmd = f'echo "{self.sudo_password}" | sudo -S mkdir -p {install_dir}'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if result.returncode != 0:
                raise Exception(f"Не удалось создать директорию: {result.stderr}")

            # Устанавливаем владельца
            user = os.getenv('USER')
            cmd = f'echo "{self.sudo_password}" | sudo -S chown {user}:{user} {install_dir}'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if result.returncode != 0:
                raise Exception(f"Не удалось изменить владельца: {result.stderr}")

            self.root.after(0, lambda: self.log_message("✅ Директория создана успешно"))

            # Копируем СОДЕРЖИМОЕ корневой папки в целевую директорию
            self.root.after(0, lambda: self.log_message("📋 Копирование файлов в целевую директорию..."))

            # Копируем все файлы и папки из content_root в install_dir
            for item in os.listdir(content_root):
                src_path = os.path.join(content_root, item)
                dst_path = os.path.join(install_dir, item)

                if os.path.isdir(src_path):
                    if os.path.exists(dst_path):
                        shutil.rmtree(dst_path)
                    shutil.copytree(src_path, dst_path)
                else:
                    shutil.copy2(src_path, dst_path)

            self.root.after(0, lambda: self.log_message("✅ Файлы скопированы в целевую директорию"))

            # Ищем бинарный файл в целевой директории
            binary_name = "adguardvpn-cli"
            binary_path = os.path.join(install_dir, binary_name)

            if not os.path.exists(binary_path):
                # Ищем в поддиректориях
                for root, dirs, files in os.walk(install_dir):
                    if binary_name in files:
                        binary_path = os.path.join(root, binary_name)
                        break

            if not os.path.exists(binary_path):
                # Покажем содержимое для отладки
                install_contents = []
                for root, dirs, files in os.walk(install_dir):
                    for item in dirs + files:
                        install_contents.append(os.path.relpath(os.path.join(root, item), install_dir))
                self.root.after(0, lambda: self.log_message(f"📂 Содержимое установленной директории: {install_contents}"))
                raise Exception(f"Бинарный файл {binary_name} не найден в установленной директории")

            self.root.after(0, lambda: self.log_message(f"🔍 Найден бинарный файл: {binary_path}"))

            # Устанавливаем права на бинарный файл
            os.chmod(binary_path, 0o755)
            self.root.after(0, lambda: self.log_message("✅ Права на выполнение установлены"))

            # Создаем символическую ссылку
            self.root.after(0, lambda: self.log_message("🔗 Создание символической ссылки..."))
            link_cmd = f'echo "{self.sudo_password}" | sudo -S ln -sf {binary_path} /usr/local/bin/adguardvpn-cli'
            result = subprocess.run(link_cmd, shell=True, capture_output=True, text=True)

            if result.returncode == 0:
                self.root.after(0, lambda: self.log_message("✅ Символическая ссылка создана: /usr/local/bin/adguardvpn-cli"))
            else:
                self.root.after(0, lambda: self.log_message(f"⚠️ Предупреждение: не удалось создать ссылку: {result.stderr}"))

            # Очистка временных файлов
            shutil.rmtree(temp_dir)
            self.root.after(0, lambda: self.log_message("🧹 Временные файлы очищены"))

            return True

        except urllib.error.HTTPError as e:
            self.root.after(0, lambda: self.log_message(f"❌ HTTP ошибка {e.code}: {e.reason}"))
            self.root.after(0, lambda: self.log_message(f"❌ URL был: {download_url}"))
            return False
        except Exception as e:
            self.root.after(0, lambda: self.log_message(f"❌ ОШИБКА: {str(e)}"))
            return False

    def find_content_root(self, extract_dir):
        """Находит корневую папку с содержимым внутри распакованного архива"""
        items = os.listdir(extract_dir)

        # Если в extract_dir только одна папка, используем ее как корневую
        if len(items) == 1 and os.path.isdir(os.path.join(extract_dir, items[0])):
            return os.path.join(extract_dir, items[0])

        # Иначе используем саму extract_dir как корневую
        return extract_dir

    def create_desktop_file(self):
        """Создает .desktop файл для AdGuard VPN Manager с проверкой существования"""
        try:
            # Путь к менеджеру
            manager_dir = os.path.expanduser("~/AdGuard VPN Manager")
            main_script = os.path.join(manager_dir, "main.py")
            icon_path = os.path.join(manager_dir, "ico/adguard.png")

            # Проверяем существование файлов менеджера
            if not os.path.exists(main_script):
                self.log_message("❌ Основной скрипт менеджера не найден")
                return False

            if not os.path.exists(icon_path):
                self.log_message("❌ Иконка менеджера не найдена")
                return False

            # Содержимое .desktop файла
            desktop_content = f"""[Desktop Entry]
    Encoding=UTF-8
    Version=1.0
    Type=Application
    Name=AdGuard VPN Manager
    GenericName=AdGuard VPN Manager
    Comment=GUI Manager for AdGuard VPN on Linux
    Exec=python3 "{main_script}"
    Icon={icon_path}
    Categories=Network;VPN;
    Keywords=vpn;adguard;security;privacy;
    Terminal=false
    StartupNotify=true
    StartupWMClass=AdGuardVPNManager
    MimeType=
    X-GNOME-UsesNotifications=true
    # Для KDE
    InitialPreference=9
    # Указываем что это GUI приложение
    OnlyShowIn=GNOME;XFCE;KDE;
    """

            # Определяем пути для проверки и создания
            desktop_paths = [
                os.path.expanduser("~/Рабочий стол/AdGuard_VPN_Manager.desktop"),  # Русский
                os.path.expanduser("~/Desktop/AdGuard_VPN_Manager.desktop"),       # Английский
            ]

            # Путь для меню приложений
            home_dir = os.path.expanduser("~")
            applications_path = os.path.join(home_dir, ".local/share/applications/AdGuard_VPN_Manager.desktop")

            # ПРОВЕРКА: уже существуют ли все ярлыки
            desktop_exists = False
            applications_exists = os.path.exists(applications_path)

            # Проверяем существование на рабочем столе
            for desktop_path in desktop_paths:
                if os.path.exists(desktop_path):
                    desktop_exists = True
                    break

            # Если все ярлыки уже существуют, просто выходим
            if desktop_exists and applications_exists:
                return True

            # СОЗДАНИЕ ЯРЛЫКОВ (только если они не существуют)

            # Создаем на рабочем столе (если не существует)
            desktop_created = False
            if not desktop_exists:
                for desktop_path in desktop_paths:
                    desktop_dir = os.path.dirname(desktop_path)

                    # Проверяем существует ли папка рабочего стола
                    if os.path.exists(desktop_dir):
                        try:
                            with open(desktop_path, 'w') as f:
                                f.write(desktop_content)
                            os.chmod(desktop_path, 0o755)
                            self.log_message(f"✅ Ярлык создан: {desktop_path}")
                            desktop_created = True
                            break
                        except Exception as e:
                            self.log_message(f"❌ Ошибка создания ярлыка {desktop_path}: {e}")

                if not desktop_created:
                    self.log_message("❌ Не удалось создать ярлык на рабочем столе")
            else:
                self.log_message("✅ Ярлык на рабочем столе уже существует")

            # Создаем в меню приложений (если не существует)
            if not applications_exists:
                try:
                    # Создаем директорию если не существует
                    applications_dir = os.path.dirname(applications_path)
                    os.makedirs(applications_dir, exist_ok=True)

                    # Создаем файл напрямую
                    with open(applications_path, 'w') as f:
                        f.write(desktop_content)

                    # Устанавливаем права (644 - чтение для всех, запись только для владельца)
                    os.chmod(applications_path, 0o644)

                    self.log_message(f"✅ Добавлено в меню приложений: {applications_path}")

                    # ОБНОВЛЯЕМ КЭШ DESKTOP
                    self.log_message("🔄 Обновление кэша меню приложений...")
                    update_result = subprocess.run(['update-desktop-database', applications_dir],
                                                capture_output=True, text=True)

                    if update_result.returncode == 0:
                        self.log_message("✅ Кэш меню приложений обновлен")
                    else:
                        self.log_message(f"⚠️ Не удалось обновить кэш: {update_result.stderr}")

                except Exception as e:
                    self.log_message(f"❌ Ошибка создания файла .desktop: {str(e)}")
            else:
                self.log_message("✅ Ярлык в меню приложений уже существует")

            return True

        except Exception as e:
            self.log_message(f"❌ Ошибка создания desktop файла: {e}")
            return False

    def _install_success(self):
        self.installation_complete = True  # Устанавливаем флаг завершения
        self.log_message("=== Установка завершена успешно ===")


        # Закрываем окно установки и открываем окно авторизации
        self.root.destroy()
        auth_window = AuthWindow()
        auth_window.run()

    def run(self):
        self.create_desktop_file()
        self.root.mainloop()
