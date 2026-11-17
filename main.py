#!/usr/bin/env python3
import tkinter as tk
import os
import sys
import subprocess
import gc
from core.auth import SudoAuthWindow, AuthWindow
from core.installer import AdGuardVPNInstaller
from core.startup import StartupCheckWindow
from ui.windows.manager import AdGuardVPNManager

def is_adguard_installed():
    return os.path.exists("/usr/local/bin/adguardvpn-cli")

def is_logged_in():
    """Проверяет, авторизован ли пользователь"""
    try:
        result = subprocess.run(
            ['adguardvpn-cli', 'list-locations'],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0
    except:
        return False

def main():
    if os.geteuid() == 0:
        print("Не запускайте скрипт напрямую от root!")
        sys.exit(1)

    # Сначала проверяем установлен ли AdGuard VPN
    if not is_adguard_installed():
        print("AdGuard VPN не установлен, запуск установки...")
        # Только для установки запрашиваем sudo пароль
        auth_window = SudoAuthWindow()
        sudo_password, auth_success = auth_window.run()

        if not auth_success or not sudo_password:
            print("Sudo аутентификация отменена")
            sys.exit(0)

        installer = AdGuardVPNInstaller(sudo_password)
        installer.run()
        # После установки продолжаем

    state, initial_license = StartupCheckWindow().run()
    # Destroyed Tk roots/pages can retain cycles. Collect them on the GUI
    # thread after cleanup completes, before another root starts CLI workers.
    gc.collect()
    if state == 'cancel':
        return
    if state == 'auth':
        auth_success = AuthWindow().run()
        gc.collect()
        if not auth_success:
            return
        initial_license = None

    root = tk.Tk()
    app = (AdGuardVPNManager(root, initial_license=initial_license)
           if initial_license is not None else AdGuardVPNManager(root))
    app.run()

if __name__ == "__main__":
    main()
