#!/usr/bin/env bash
# Bootstrap for the existing per-user Python GUI; never installs CLI or uses sudo.
set -euo pipefail
url='https://github.com/mashakulina/AdGuard_Manager/releases/latest/download/adguard_manager.tar.gz'
for dependency in python3 mktemp timeout; do
    command -v "$dependency" >/dev/null 2>&1 || { echo "Не найдена команда: $dependency" >&2; exit 127; }
done
work=$(mktemp -d "${TMPDIR:-/tmp}/adguard-manager-bootstrap.XXXXXXXX")
cleanup() { result=$?; rm -rf -- "$work"; exit "$result"; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
archive="$work/adguard_manager.tar.gz"
echo 'Скачивание AdGuard VPN Manager…'
downloaded=false
code=127
if command -v curl >/dev/null 2>&1; then
    if (ulimit -f 131072; curl --fail --location --silent --show-error --connect-timeout 15 --max-time 120 --max-filesize 134217728 --output "$archive" "$url"); then
        downloaded=true
    else code=$?; fi
fi
if [[ "$downloaded" == false ]] && command -v wget >/dev/null 2>&1; then
    if (ulimit -f 131072; timeout 120 wget -q --timeout=30 --tries=2 --max-redirect=10 -O "$archive" "$url"); then
        downloaded=true
    else code=$?; fi
fi
if [[ "$downloaded" == false ]]; then
    echo "Не удалось скачать архив менеджера (код $code). Текущая установка сохранена." >&2
    exit "$code"
fi
python3 -I - "$archive" <<'PY'
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile

if sys.version_info < (3, 10):
    raise SystemExit('Для менеджера требуется Python 3.10 или новее. Установка сохранена.')
try:
    import tkinter
except ImportError:
    raise SystemExit('Не найден tkinter для Python3. Установите его перед менеджером; установка сохранена.')

archive = Path(sys.argv[1])
target = Path(os.path.abspath(os.path.expanduser(os.environ.get(
    'ADGUARD_MANAGER_INSTALL_DIR', '~/AdGuard VPN Manager'))))
if target == Path(target.anchor) or target == Path.home() or target.is_symlink():
    raise SystemExit('Небезопасный путь установки; текущая установка сохранена.')
if target.exists() and not target.is_dir():
    raise SystemExit('Путь установки занят файлом; текущая установка сохранена.')
allowed = {'core', 'ui', 'utils', 'config', 'ico'}
root_files = {'main.py', 'README.md', 'version.txt', 'LICENSE', 'LICENSE.txt', 'LICENSE.md', 'COPYING'}
required = {'main.py', 'core/__init__.py', 'core/auth.py', 'ui/__init__.py',
            'ui/windows/manager.py', 'utils/__init__.py', 'config/manager_config.py',
            'utils/qr.png', 'ico/adguard.png'}
# Validate every member before writing to the existing installation.
try:
    with tarfile.open(archive, 'r:gz') as package:
        members, names, total = [], set(), 0
        for member in package:
            raw = member.name
            path = PurePosixPath(raw)
            if str(path) == '.' and member.isdir():
                continue
            if (path.is_absolute() or '\\' in raw or '..' in path.parts
                    or str(path) in ('', '.')
                    or (str(path) not in root_files and path.parts[0] not in allowed)
                    or (str(path) in root_files and not member.isfile())
                    or not (member.isdir() or member.isfile()) or member.issparse()
                    or str(path) in names):
                raise ValueError('Небезопасный состав архива')
            names.add(str(path))
            total += member.size
            if member.size > 32*1024*1024 or total > 256*1024*1024 or len(names) > 5000:
                raise ValueError('Архив превышает допустимый размер')
            members.append(member)
        files = {str(PurePosixPath(member.name)) for member in members if member.isfile()}
        if not required <= files:
            raise ValueError('В архиве отсутствуют обязательные файлы приложения')
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix='.adguard-manager-stage-', dir=target.parent))
        backup = None
        try:
            for member in members:
                destination = stage.joinpath(*PurePosixPath(member.name).parts)
                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                    destination.chmod(0o755)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with package.extractfile(member) as source, destination.open('xb') as output:
                        shutil.copyfileobj(source, output)
                    destination.chmod(0o644)
            if target.exists():
                backup = Path(tempfile.mkdtemp(prefix='.adguard-manager-backup-', dir=target.parent))
                backup.rmdir()
                target.rename(backup)
            try:
                stage.rename(target)
            except BaseException:
                if backup is not None:
                    backup.rename(target)
                raise
        finally:
            if stage.exists():
                shutil.rmtree(stage)
        if backup is not None:
            shutil.rmtree(backup)
except (OSError, ValueError, EOFError, tarfile.TarError) as error:
    print('Установка прервана: ' + str(error), file=sys.stderr)
    raise SystemExit(65)


def desktop_quote(value):
    # Exec has desktop-string escaping followed by Exec argument escaping.
    value = str(value).replace('%', '%%')
    quoted = '"' + ''.join('\\'+ch if ch in '\\"`$' else ch for ch in value) + '"'
    return quoted.replace('\\', '\\\\')


def desktop_value(value):
    return str(value).replace('\\', '\\\\').replace('\n', '\\n').replace('\r', '\\r')


content = ('[Desktop Entry]\nVersion=1.0\nType=Application\nName=AdGuard VPN Manager\n'
           'Comment=AdGuard VPN Manager\nExec=' + desktop_quote(sys.executable) + ' ' + desktop_quote(target/'main.py') + '\n'
           'Path=' + desktop_value(target) + '\nIcon=' + desktop_value(target/'ico/adguard.png') + '\n'
           'Terminal=false\nCategories=Network;\nStartupNotify=true\nStartupWMClass=AdGuardVPNManager\n')
applications = Path(os.environ.get('ADGUARD_MANAGER_APPLICATIONS_DIR',
                    str(Path(os.environ.get('XDG_DATA_HOME', str(Path.home()/'.local/share')))/'applications')))
desktop_override = os.environ.get('ADGUARD_MANAGER_DESKTOP_DIR')
if desktop_override is not None:
    desktop = Path(desktop_override) if desktop_override else None
else:
    desktop = next((path for path in (Path.home()/'Desktop', Path.home()/'Рабочий стол') if path.is_dir()), None)
try:
    applications.mkdir(parents=True, exist_ok=True)
    entries = [applications/'AdGuard_VPN_Manager.desktop']
    if desktop is not None:
        desktop.mkdir(parents=True, exist_ok=True)
        entries.append(desktop/'AdGuard_VPN_Manager.desktop')
    for entry in entries:
        # Refuse existing links rather than writing through them.
        if entry.is_symlink():
            raise OSError('Ярлык является символической ссылкой: '+str(entry))
        entry.write_text(content, encoding='utf-8')
        entry.chmod(0o755 if desktop is not None and entry.parent == desktop else 0o644)
except OSError as error:
    print('Приложение установлено, но ярлык создать не удалось: '+str(error), file=sys.stderr)
    raise SystemExit(1)
print('Установлено: '+str(target))
if os.environ.get('ADGUARD_MANAGER_SKIP_LAUNCH') != '1':
    try:
        process = subprocess.Popen([sys.executable, str(target/'main.py')], cwd=target,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            code = process.wait(timeout=.3)
        except subprocess.TimeoutExpired:
            print('Менеджер запущен (PID '+str(process.pid)+').')
        else:
            if code:
                print('Менеджер установлен, но запуск завершился с кодом '+str(code), file=sys.stderr)
                raise SystemExit(code)
    except OSError as error:
        print('Менеджер установлен, но не запущен: '+str(error), file=sys.stderr)
        raise SystemExit(1)
PY
