"""Open an HTTP(S) URL without shell expansion or sensitive diagnostics.

Call from a worker: default browser discovery may block. True means that a
browser accepted the request (not that the remote page loaded).
"""
import shutil
import subprocess
import threading
import webbrowser
from urllib.parse import urlsplit

_NATIVE = ('firefox', 'firefox-esr', 'chromium', 'chromium-browser',
           'google-chrome', 'google-chrome-stable', 'brave-browser', 'vivaldi')
_FLATPAK = ('org.mozilla.firefox', 'org.chromium.Chromium',
            'com.google.Chrome', 'com.brave.Browser', 'com.vivaldi.Vivaldi')


def _launch(argv):
    try:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   start_new_session=True)
        try:
            return process.wait(timeout=0.2) == 0
        except subprocess.TimeoutExpired:
            threading.Thread(target=process.wait, daemon=True).start()
            return True
    except OSError:
        return False


def open_url(url):
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc or any(
                ord(ch) < 32 for ch in url):
            return False
    except (TypeError, ValueError):
        return False
    try:
        if webbrowser.open(url):
            return True
    except Exception:
        pass
    for name in _NATIVE:
        executable = shutil.which(name)
        if executable and _launch([executable, url]):
            return True
    flatpak = shutil.which('flatpak')
    if flatpak:
        try:
            result = subprocess.run([flatpak, 'list', '--app', '--columns=application'],
                                    capture_output=True, text=True, timeout=3)
            installed = set(result.stdout.splitlines()) if result.returncode == 0 else set()
            for app in _FLATPAK:
                if app in installed and _launch([flatpak, 'run', app, url]):
                    return True
        except (OSError, subprocess.TimeoutExpired):
            pass
    return False
