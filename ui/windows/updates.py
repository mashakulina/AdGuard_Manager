from core.ui_scaling import grab_when_visible
from ui.components.adaptive import AdaptivePage
import os
import shutil
import tarfile
import tempfile
from math import ceil
import tkinter as tk
from tkinter import ttk, scrolledtext
import subprocess
import re
from ui.components.dialogs import show_question_dialog
from ui.components.button_styler import create_hover_button
from core.ui_tasks import TaskRunner
from core.update_diagnostics import (run_command, clean_output, check_status,
    update_succeeded, diagnostics, format_result, has_error)
from core.github_updater import GitHubUpdater
from config.manager_config import MANAGER_CONFIG


class UpdateWindow:
    def __init__(self, parent):
        self.parent = parent
        self.root = tk.Toplevel(parent)
        self.setup_window_properties()
        self.root.title("Обновление")

        self.root.configure(bg='#182030')
        self.root.transient(parent)
        grab_when_visible(self.root)

        try:
            from tkinter import ttk
            style = ttk.Style()
            style.theme_use('clam')
        except:
            pass

        # Флаг наличия обновления для AdGuard VPN
        self.update_available = False
        self.available_version = None

        # Флаг наличия обновления для менеджера
        self.manager_update_available = False
        self.latest_manager_version = None
        self.latest_release_data = None

        # Для менеджера
        self.manager_updater = GitHubUpdater(
            version_url=MANAGER_CONFIG["version_url"],
            current_version=MANAGER_CONFIG["current_version"]
        )
        self.latest_manager_version = None
        self.latest_release_data = None
        self.downloaded_update_path = os.path.expanduser("~/AdGuard VPN Manager")  # Путь к скачанному обновлению

        self.setup_manager_section()  # Добавьте этот вызов

        # Загружаем сохраненный канал или используем release по умолчанию
        self.tasks = TaskRunner(self.root)
        self._generation = 0
        self._channel_touched = False
        self._cli_busy = False
        self.update_channel = "release"
        self.setup_ui()

        # Устанавливаем начальное значение метки и радиокнопок
        self.update_channel_display()
        self.channel_var.trace_add('write', self._channel_selected)
        self.tasks.submit(lambda: (self.load_saved_channel(), self.get_adguard_current_version()),
                          self._initial_loaded, self._initial_error, key='initial')

    def _channel_selected(self, *_):
        self._channel_touched = True

    def _initial_error(self, error):
        self.log_message(f"Ошибка начальной загрузки: {error}")

    def _initial_loaded(self, values):
        channel, version = values
        if self._generation == 0:
            self.current_version_label.config(text=f"Версия: {version or 'Неизвестно'}")
            selected = self.channel_var.get() if self._channel_touched else None
            self.update_channel = channel
            self.update_channel_display()
            if selected is not None:
                self.channel_var.set(selected)

    def setup_window_properties(self):
        """Настройка свойств окна для корректного отображения"""
        self.root.title("AdGuard VPN Manager")

        # Устанавливаем WM_CLASS (БЕЗ ПРОБЕЛОВ!)
        try:
            manager_dir = os.path.expanduser("~/AdGuard VPN Manager")
            self.root.wm_class("AdGuardVPNManager")
        except:
            pass

        # Устанавливаем иконку
        try:
            icon_path = os.path.join(manager_dir, "ico/adguard.png")
            if os.path.exists(icon_path):
                # Для PNG файлов в tkinter
                icon = tk.PhotoImage(file=icon_path)
                self.root.iconphoto(True, icon)
        except Exception as e:
            print(f"Не удалось установить иконку: {e}")

    def load_saved_channel(self):
        """Загружает сохраненный канал обновления из конфига"""
        try:
            # Получаем текущую конфигурацию
            result = subprocess.run(
                ['adguardvpn-cli', 'config', 'show'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                config_output = result.stdout
                # Ищем строку с Update channel с помощью regex
                match = re.search(r'Update channel:\s*([^\n]+)', config_output, re.IGNORECASE)
                if match:
                    channel = match.group(1).strip().lower()
                    if 'beta' in channel:
                        return 'beta'
                    elif 'release' in channel:
                        return 'release'
                    return channel
        except Exception as e:
            print(f"Ошибка загрузки канала: {e}")

        return "release"  # По умолчанию

    def save_channel(self, channel):
        """Сохраняет выбранный канал только локально (не применяет в CLI)"""
        self.update_channel = channel

    def update_channel_display(self):
        """Обновляет отображение канала обновления на основе фактического значения"""
        # Устанавливаем радиокнопку
        self.channel_var.set(self.update_channel)

        # Обновляем текст метки
        if self.update_channel == "release":
            self.channel_label.config(text="Канал обновления: Release")
        else:
            self.channel_label.config(text="Канал обновления: Beta")

    def update_action_button(self):
        """Обновляет текст и команду кнопки действия в зависимости от наличия обновления"""
        if self.update_available:
            self.action_button.config(
                text="Обновиться",
                command=self.update_adguard,
                bg='#15354D'
            )
        else:
            self.action_button.config(
                text="Проверить обновление",
                command=self.check_adguard_update,
                bg='#15354D'
            )

    def setup_manager_section(self):
        """Настраивает элементы UI для обновления менеджера"""
        # Этот метод будет вызываться из setup_ui
        pass

    def get_adguard_current_version(self):
        """Compatibility hook for the initial background version lookup."""
        return self.get_current_version()

    def setup_ui(self):
        self.page = AdaptivePage(self.root, (690, 430), getattr(self, 'parent', None))
        main_frame = self.page.body

        tk.Label(main_frame, text="Обновление",
                font=("Arial", 14, "bold"), fg='white', bg='#182030').pack(anchor=tk.CENTER, pady=(0, 5))


        # Создаем контейнер для двух колонок
        columns_frame = tk.Frame(main_frame, bg='#182030')
        columns_frame.pack(fill=tk.X)

        # Левая колонка - Обновление менеджера (заглушка)
        left_column = tk.Frame(columns_frame, bg='#182030', relief=tk.GROOVE, bd=0)
        left_column.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))


        # Правая колонка - Обновление AdGuard VPN
        right_column = tk.Frame(columns_frame, bg='#182030', relief=tk.GROOVE, bd=0)
        right_column.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 0))


        self.page.responsive_columns(columns_frame, (left_column, right_column), gap=24,
                                     equal_width=False, fit_width=True)

        # === ЛЕВАЯ КОЛОНКА - ОБНОВЛЕНИЕ МЕНЕДЖЕРА ===
        left_content = tk.Frame(left_column, bg='#182030', padx=0, pady=0)
        left_content.pack(fill=tk.X)

        tk.Label(left_content, text="AdGuard VPN Manager",
                font=("Arial", 14, "bold"), fg='white', bg='#182030').pack(anchor=tk.CENTER, pady=(0, 10))

        # Текущая версия
        version_frame = tk.Frame(left_content, bg='#182030')
        version_frame.pack(anchor=tk.CENTER, pady=(0, 10))

        tk.Label(version_frame, text=f"Версия: {MANAGER_CONFIG['current_version']}",
                font=("Arial", 11), fg='#5BA06A', bg='#182030').pack(anchor=tk.CENTER)

        # Кнопка проверки и обновления менеджера
        manager_buttons_frame = tk.Frame(left_content, bg='#182030')
        manager_buttons_frame.pack(anchor=tk.CENTER, pady=(0, 16))

        self.manager_action_button = create_hover_button(
            manager_buttons_frame,
            text="Проверить обновление",
            command=self.check_manager_update,
            bg='#15354D', fg='white', font=('Arial', 10),
            width=0, bd=0, highlightthickness=0, padx=10, pady=5
        )
        self.manager_action_button.pack(side=tk.LEFT)

        # Область лога внизу основного окна
        log_frame = tk.Frame(left_content, bg='#182030')
        log_frame.pack(fill=tk.X, pady=(5, 0))

        log_header = tk.Frame(log_frame, bg='#182030')
        log_header.pack(fill=tk.X, pady=(0, 10))
        log_label = tk.Label(log_header, text="Информация:",
                             font=("Arial", 10), fg='white', bg='#182030')
        self.copy_log_button = create_hover_button(
            log_header, text="Копировать", command=self.copy_log,
            bg='#15354D', fg='white', font=('Arial', 9),
            bd=0, highlightthickness=0, padx=8, pady=3)
        self.page.responsive_row(log_header, (log_label, self.copy_log_button),
                                 gap=8, align='left')

        log_body = tk.Frame(log_frame, bg='#182030')
        log_body.pack(fill=tk.X)
        self.log_text = tk.Text(log_body, height=5, width=40, bg='#15354D',
                               highlightthickness=0, fg='white', wrap=tk.WORD,
                               font=("Courier", 9), state=tk.DISABLED)
        log_style = ttk.Style(self.root)
        log_style.configure('Update.Vertical.TScrollbar', background='#2A4466',
                            troughcolor='#0F1A2F', bordercolor='#182030', arrowcolor='white')
        log_style.map('Update.Vertical.TScrollbar', background=[('active', '#3A5A88')])
        self.log_scrollbar = ttk.Scrollbar(log_body, orient=tk.VERTICAL,
                                          command=self.log_text.yview, style='Update.Vertical.TScrollbar')
        self.log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=self.log_scrollbar.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # === ПРАВАЯ КОЛОНКА - ОБНОВЛЕНИЕ ADGUARD VPN ===
        right_content = tk.Frame(right_column, bg='#182030', padx=0, pady=0)
        right_content.pack(fill=tk.X)

        tk.Label(right_content, text="AdGuard VPN",
                font=("Arial", 14, "bold"), fg='white', bg='#182030').pack(anchor=tk.CENTER, pady=(0, 10))

        # Текущая версия - динамическая
        version_frame = tk.Frame(right_content, bg='#182030')
        version_frame.pack(fill=tk.X, pady=(0, 10))

        # Получаем текущую версию при инициализации
        current_version = "Загрузка…"

        self.current_version_label = tk.Label(version_frame,
                                            text=f"Версия: {current_version}",
                                            font=("Arial", 11), fg='#5BA06A', bg='#182030')
        self.current_version_label.pack(anchor=tk.CENTER)

        # Кнопка действия (проверка/обновление)
        buttons_frame = tk.Frame(right_content, bg='#182030')
        buttons_frame.pack(fill=tk.X, pady=(0, 16))


        self.action_button = create_hover_button(buttons_frame, text="Проверить обновление",
                command=self.check_adguard_update, bg='#15354D', fg='white', font=('Arial', 10),
                width=0, bd=0, highlightthickness=0, padx=10, pady=5)
        self.action_button.pack(anchor=tk.CENTER)

        # Выбор канала обновления
        channel_frame = tk.Frame(right_content, bg='#182030')
        channel_frame.pack(fill=tk.X, pady=(0, 15))

        # Изменяемая строка с текущим каналом
        self.channel_label = tk.Label(channel_frame, text="Канал обновления: Release",
                                    font=("Arial", 11), fg='#5BA06A', bg='#182030')
        # Reserve the full caption even if an early WM allocation wraps it.
        # Character units keep this minimum proportional to the actual font.
        caption_width = int(self.root.tk.call('font', 'measure', self.channel_label['font'],
                                              'Канал обновления: Release'))
        digit_width = max(1, int(self.root.tk.call('font', 'measure', self.channel_label['font'], '0')))
        self.channel_label.configure(width=ceil(caption_width / digit_width))
        self.channel_label.pack(fill=tk.X, pady=(0, 8))
        self.page.wrap(self.channel_label)

        # Фрейм для радиокнопок - на одной линии
        radio_frame = tk.Frame(channel_frame, bg='#182030')
        radio_frame.pack(fill=tk.X)

        self.channel_var = tk.StringVar(value="release")

        self.release_radio = tk.Radiobutton(radio_frame, text="Release",
                                        variable=self.channel_var, value="release",
                                        font=("Arial", 10), fg='white', bg='#182030',
                                        selectcolor='#15354D', activebackground='#182030',
                                        activeforeground='white',
                                        bd=0, highlightthickness=0)
        self.release_radio.pack(side=tk.LEFT, padx=(0, 20))

        self.beta_radio = tk.Radiobutton(radio_frame, text="Beta",
                                    variable=self.channel_var, value="beta",
                                    font=("Arial", 10), fg='white', bg='#182030',
                                        selectcolor='#15354D', activebackground='#182030',
                                        activeforeground='white',
                                        bd=0, highlightthickness=0)
        self.beta_radio.pack(side=tk.LEFT)

        self.page.responsive_row(radio_frame, (self.release_radio, self.beta_radio), gap=16)

        # Кнопка действия (проверка/обновление)
        buttons_frame = tk.Frame(right_content, bg='#182030')
        buttons_frame.pack(anchor=tk.CENTER)
        # Кнопка применения канала
        apply_btn = create_hover_button(buttons_frame, text="Применить", command=self.apply_update_channel,
                bg='#15354D', fg='white', font=('Arial', 10),
                bd=0, highlightthickness=0, padx=10, pady=5).pack(side=tk.LEFT, padx=(0, 5))


        # Кнопка закрытия
        btn_frame = tk.Frame(self.page.footer, bg='#182030')
        btn_frame.pack(fill=tk.X, pady=(8, 10))

        close_btn=create_hover_button(btn_frame, text="Закрыть", command=self.close_window,
                                      bg='#15354D', fg='white', font=('Arial', 10), width=15, bd=0, highlightthickness=0, padx=10, pady=5)
        close_btn.pack(anchor=tk.CENTER)

        self.page.wrap(self.current_version_label)
        self.page.request_fit()

    def update_manager_action_button(self):
        """Обновляет текст и команду кнопки действия менеджера в зависимости от наличия обновления"""
        if self.manager_update_available:
            self.manager_action_button.config(
                text="Обновиться",
                command=self.download_manager_update,
                bg='#15354D'
            )
        else:
            self.manager_action_button.config(
                text="Проверить обновление",
                command=self.check_manager_update,
                bg='#15354D'
            )

    def check_manager_update(self):
        """Проверяет обновления для менеджера"""
        self.manager_action_button.config(state=tk.DISABLED, text="Проверка...")

        self.tasks.submit(self.manager_updater.check_for_updates,
                          self._manager_checked, self._manager_check_error, key='manager')

    def _manager_checked(self, values):
        version, release = values
        self.latest_manager_version, self.latest_release_data = version, release
        self.manager_update_available = bool(version)
        self.log_message(f"📢 Доступно обновление AdGuard VPN Manager: {version}" if version
                         else "✅ Установлена последняя версия AdGuard VPN Manager")
        self.manager_action_button.config(state=tk.NORMAL)
        self.update_manager_action_button()

    def _manager_check_error(self, error):
        self.log_message(f"❌ Ошибка проверки обновлений менеджера: {clean_output(str(error))}")
        self.manager_action_button.config(state=tk.NORMAL)
        self.update_manager_action_button()

    def download_manager_update(self):
        """Скачивает обновление менеджера"""
        if not self.latest_release_data:
            return

        # Показываем диалог подтверждения ДО запуска потока
        if not show_question_dialog(self.root, "Обновление AdGuard VPN Manager",
                                "AdGuard VPN Manager будет обновлен. После скачивания:\n"
                                "1. Удалятся текущие файлы AdGuard VPN Manager\n"
                                "2. Будет установлена новая версия\n"
                                "3. AdGuard VPN Manager перезапустится\n\n"
                                "Продолжить?"):
            return

        self.manager_action_button.config(state=tk.DISABLED, text="Обновление...")
        release, version = dict(self.latest_release_data), self.latest_manager_version

        self.tasks.submit(lambda: self._download_manager_update_thread(release, version), key='manager')

    def _download_manager_update_thread(self, release, version):
        """Поток для скачивания и установки обновления менеджера"""
        try:
            download_url = self.manager_updater.get_download_url(release)
            if not download_url:
                raise Exception("URL для скачивания не найден")

            self.tasks.post( lambda: self.log_message("📥 Начало загрузки обновления AdGuard VPN Manager..."))

            # Создаем временный файл для загрузки
            temp_dir = tempfile.gettempdir()
            filename = f"manager_update_{version}.tar.gz"
            downloaded_file_path = os.path.join(temp_dir, filename)

            # Скачиваем файл с помощью urllib (стандартная библиотека)
            import urllib.request
            with urllib.request.urlopen(download_url, timeout=30) as response, open(downloaded_file_path, 'wb') as target:
                shutil.copyfileobj(response, target)

            self.tasks.post( lambda: self.log_message("✅ Архив скачан. Начинается установка..."))

            # Путь к папке менеджера
            manager_dir = os.path.expanduser("~/AdGuard VPN Manager")

            # Удаляем старую версию
            if os.path.exists(manager_dir):
                shutil.rmtree(manager_dir)
                self.tasks.post( lambda: self.log_message("🗑️ Старая версия удалена"))

            # Создаем папку заново
            os.makedirs(manager_dir, exist_ok=True)

            # Распаковываем tar.gz архив
            with tarfile.open(downloaded_file_path, 'r:gz') as tar_ref:
                tar_ref.extractall(manager_dir)

            self.tasks.post( lambda: self.log_message("✅ Файлы распакованы"))

            # Удаляем временный файл
            os.remove(downloaded_file_path)

            self.tasks.post( lambda: self.log_message(f"✅ Обновление AdGuard VPN Manager до версии {version} завершено!"))
            self.tasks.post( lambda: self.log_message("🔄 Перезапуск AdGuard VPN Manager..."))

            # После успешного обновления сбрасываем флаг
            self.tasks.post(setattr, self, "manager_update_available", False)

            # Перезапускаем менеджер через 2 секунды
            self.tasks.post(lambda: self.root.after(2000, self.restart_manager))

        except Exception as error:
            error_msg = str(error)
            self.tasks.post( lambda: self.log_message(f"❌ Ошибка установки обновления AdGuard VPN Manager: {error_msg}"))
        finally:
            self.tasks.post( lambda: self.manager_action_button.config(state=tk.NORMAL))
            self.tasks.post( self.update_manager_action_button)

    def restart_manager(self):
        """Перезапускает менеджер"""
        try:
            # Путь к основному скрипту
            manager_dir = os.path.expanduser("~/AdGuard VPN Manager")
            main_script = os.path.join(manager_dir, "main.py")

            if not os.path.exists(main_script):
                self.tasks.post( lambda: self.log_message("❌ Файл main.py не найден"))
                return

            # Закрываем текущие окна
            self.root.destroy()
            self.parent.destroy()

            # Перезапускаем менеджер
            import sys
            import subprocess

            # Запускаем main.py в новом процессе
            subprocess.Popen([sys.executable, main_script])

        except Exception as e:
            self.tasks.post( lambda message=str(e): self.log_message(f"❌ Ошибка при перезапуске: {message}"))

    def update_adguard_version_display(self):
        generation = self._generation
        self.tasks.submit(self.get_current_version,
            lambda version: self.current_version_label.config(text=f"Версия: {version or 'Неизвестно'}")
            if generation == self._generation else None, key='version')

    def _begin_cli(self, text):
        if self._cli_busy:
            return False
        self._cli_busy = True
        self._generation += 1
        self.action_button.config(state=tk.DISABLED, text=text)
        return True

    def _finish_cli(self, refresh=True):
        self._cli_busy = False
        self.action_button.config(state=tk.NORMAL)
        self.update_action_button()
        if refresh:
            self.update_adguard_version_display()

    def _cli_error(self, error):
        self.log_message(f"❌ Ошибка команды: {clean_output(str(error))}")
        self._finish_cli()

    def apply_update_channel(self):
        channel = self.channel_var.get()
        if self._cli_busy:
            return
        if channel == self.update_channel:
            self.log_message(f"Канал {channel} уже установлен")
            return
        if not self._begin_cli("Установка канала…"):
            return
        self.tasks.submit(lambda: run_command(
            ['adguardvpn-cli', 'config', 'set-update-channel', channel], timeout=10),
            lambda result: self._channel_done(channel, result), self._cli_error, key='cli')

    def _channel_done(self, channel, result):
        self.log_message(format_result(result, channel))
        if result.returncode == 0 and not result.timed_out and not has_error(result.output):
            self.update_channel = channel
            self.update_channel_display()
            self.update_available = False
            self.available_version = None
            self.log_message(f"✅ Канал изменён на {channel}")
        else:
            self.log_message("❌ Канал не изменён.\n" + diagnostics(result))
        self._finish_cli()

    def check_adguard_update(self):
        if not self._begin_cli("Проверка…"):
            return
        self.tasks.submit(lambda: run_command(['adguardvpn-cli', 'check-update'], timeout=15),
                          self._check_done, self._cli_error, key='cli')

    def _check_done(self, result):
        self.log_message(format_result(result, self.update_channel))
        status = check_status(result)
        if status == 'available':
            self.update_available = True
            self.available_version = self.extract_version(result.output)
            self.log_message(f"📢 Доступно обновление AdGuard VPN {self.available_version or ''}")
        elif status == 'latest':
            self.update_available = False
            self.available_version = None
            self.log_message("✅ Установлена последняя версия AdGuard VPN")
        else:
            self.log_message("❌ Проверка не определила актуальность версии.\n" + diagnostics(result))
        self._finish_cli()

    def get_current_version(self):
        try:
            result = run_command(['adguardvpn-cli', '-v'], timeout=5)
            return self.extract_version(result.output) if result.returncode == 0 and not result.timed_out and not has_error(result.output) else None
        except (OSError, subprocess.SubprocessError):
            return None

    def extract_version(self, text):
        match = re.search(r'(?<![\d.])(\d+\.\d+\.\d+)(?:[-+][\w.]+)?', text)
        return match.group(0) if match else None

    def update_adguard(self):
        if self._cli_busy:
            return
        if not show_question_dialog(self.root, "Обновление",
                "Вы уверены, что хотите обновиться?\n\n"
                "Если VPN подключен, CLI может отключить его до скачивания архива. При ошибке обновления VPN может остаться отключённым."):
            return
        if not self._begin_cli("Обновление…"):
            return
        channel = self.update_channel
        self.tasks.submit(self._update_work,
            lambda values: self._update_done(channel, values), self._cli_error, key='cli')

    def _update_work(self):
        before = self.get_current_version()
        result = run_command(['adguardvpn-cli', 'update'], timeout=60, input='y\n')
        after = self.get_current_version()
        return result, before, after

    def _update_done(self, channel, values):
        result, before, after = values
        self.log_message(format_result(result, channel, before, after))
        if update_succeeded(result, before, after):
            offered = self.available_version
            self.update_available = False
            self.available_version = None
            self.log_message(f"✅ Установлена версия {after} (до обновления: {before}).")
            if offered and self.extract_version(offered) != after:
                self.log_message(f"При проверке предлагалась {offered}; фактически установлена {after}.")
        else:
            self.update_available = True
            self.log_message("❌ Успешное обновление не подтверждено.\n" + diagnostics(result))
            self.log_message(self._update_failure_summary(result, before, after))
        self._finish_cli(refresh=False)
        self.current_version_label.config(text=f"Версия: {after or 'Неизвестно'}")

    def clean_ansi_codes(self, text):
        return clean_output(text)

    @staticmethod
    def _update_failure_summary(result, before, after):
        output = result.output.lower()
        if result.timed_out or re.search(r'timed? ?out|timeout', output):
            reason = 'истекло время ожидания'
        elif re.search(r'could not resolve|couldn.t resolve|name resolution|\bdns\b', output):
            reason = 'ошибка DNS'
        elif re.search(r'certificate|\bssl\b|\btls\b', output):
            reason = 'ошибка TLS/сертификата'
        elif re.search(r'\bhttp[^\n]*[45]\d\d|error: [45]\d\d', output):
            reason = 'ошибка HTTP'
        elif re.search(r'permission|denied|operation not permitted', output):
            reason = 'недостаточно прав'
        elif 'download' in output:
            reason = 'не удалось скачать архив'
        else:
            reason = 'результат не подтверждён'
        version = (f'Версия не изменилась: {after}.' if before and after and before == after
                   else f'Версия: {before or "неизвестно"} → {after or "неизвестно"}.')
        return f'❌ {reason[0].upper() + reason[1:]}.\n{version}\nМожно повторить обновление.'

    def copy_log(self):
        text = clean_output(self.log_text.get('1.0', 'end-1c'))
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    def log_message(self, message):
        """Append cleaned diagnostics while keeping the journal read-only."""
        self.log_text.configure(state=tk.NORMAL)
        try:
            self.log_text.insert(tk.END, clean_output(str(message)) + "\n")
            self.log_text.see(tk.END)
        finally:
            self.log_text.configure(state=tk.DISABLED)

    def close_window(self):
        self.tasks.close()
        self.root.destroy()

    def run(self):
        self.root.wait_window()
