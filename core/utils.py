import re
import subprocess
import os

def clean_ansi_codes(text):
    """Очищает текст от ANSI escape sequences"""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

def detect_os():
    """Определяет операционную систему"""
    import platform
    system = platform.system().lower()
    if system == "darwin":
        return "macOS (darwin)"
    elif system == "linux":
        return "Linux"
    else:
        return f"Неподдерживаемая ОС: {system}"

def detect_arch():
    """Определяет архитектуру процессора"""
    import platform
    machine = platform.machine().lower()
    if machine in ["x86_64", "amd64"]:
        return "x86_64"
    elif machine in ["i386", "i486", "i586", "i686"]:
        return "i386"
    elif machine in ["arm64", "aarch64"]:
        return "arm64"
    elif machine in ["armv7l", "armv8l"]:
        return "armv7"
    else:
        return f"Неподдерживаемая архитектура: {machine}"

CLI_RELEASE_API = 'https://api.github.com/repos/AdguardTeam/AdGuardVPNCLI/releases/latest'
CLI_RELEASE_MAX_BYTES = 1024 * 1024
CLI_RELEASE_TIMEOUT = 10


class ReleaseLookupError(ValueError):
    """Official release lookup failed; never silently select an older binary."""


def _latest_release():
    import json
    import urllib.error
    import urllib.request
    request = urllib.request.Request(CLI_RELEASE_API, headers={
        'Accept': 'application/vnd.github+json', 'User-Agent': 'AdGuard-VPN-Manager'})
    try:
        with urllib.request.urlopen(request, timeout=CLI_RELEASE_TIMEOUT) as response:
            raw = response.read(CLI_RELEASE_MAX_BYTES + 1)
    except urllib.error.HTTPError as error:
        raise ReleaseLookupError(f'{CLI_RELEASE_API}: HTTP {error.code}') from None
    except (OSError, urllib.error.URLError) as error:
        # Do not expose proxy URLs, credentials, or arbitrary exception text.
        kind = type(error.reason).__name__ if isinstance(error, urllib.error.URLError) else type(error).__name__
        raise ReleaseLookupError(f'{CLI_RELEASE_API}: {kind}') from None
    if len(raw) > CLI_RELEASE_MAX_BYTES:
        raise ReleaseLookupError(f'{CLI_RELEASE_API}: слишком большой ответ')
    try:
        release = json.loads(raw)
    except (ValueError, UnicodeError):
        raise ReleaseLookupError(f'{CLI_RELEASE_API}: некорректный JSON') from None
    if not isinstance(release, dict) or release.get('draft') is not False or release.get('prerelease') is not False:
        raise ReleaseLookupError(f'{CLI_RELEASE_API}: ответ не является стабильным релизом')
    tag = release.get('tag_name')
    match = re.fullmatch(r'v(\d+\.\d+\.\d+)(?:-release)?', tag) if isinstance(tag, str) else None
    if not match or not isinstance(release.get('assets'), list):
        raise ReleaseLookupError(f'{CLI_RELEASE_API}: некорректный tag/assets')
    return release, match.group(1)


def _release_asset(release, version, os_type, arch):
    system = str(os_type).lower()
    arch = {'amd64': 'x86_64', 'arm64': 'aarch64', 'armv7l': 'armv7',
            'armv8l': 'armv7'}.get(str(arch).lower(), str(arch).lower())
    if system == 'linux' and arch in ('x86_64', 'aarch64', 'armv7', 'mips', 'mipsel'):
        suffix = f'linux-{arch}'
    elif system in ('darwin', 'macos') and arch in ('x86_64', 'aarch64'):
        suffix = 'macos'
    else:
        raise ReleaseLookupError('Неподдерживаемая ОС или архитектура для CLI')
    name = f'adguardvpn-cli-{version}-{suffix}.tar.gz'
    matches = [item for item in release['assets'] if isinstance(item, dict) and item.get('name') == name]
    if len(matches) != 1:
        raise ReleaseLookupError(f'{CLI_RELEASE_API}: отсутствует однозначный пакет {name}')
    url = matches[0].get('browser_download_url')
    expected = f"https://github.com/AdguardTeam/AdGuardVPNCLI/releases/download/{release['tag_name']}/{name}"
    if url != expected:
        raise ReleaseLookupError(f'{CLI_RELEASE_API}: некорректный официальный URL пакета')
    return url, name


def resolve_cli_release(os_type, arch):
    """Resolve stable version and exact official package using one bounded request."""
    release, version = _latest_release()
    url, name = _release_asset(release, version, os_type, arch)
    return version, url, name


def get_latest_version():
    return _latest_release()[1]


def get_download_url(os_type, arch, version):
    release, actual = _latest_release()
    if version != actual:
        raise ReleaseLookupError(f'{CLI_RELEASE_API}: запрошенная версия не совпадает с релизом')
    return _release_asset(release, actual, os_type, arch)

def check_if_connected(text):
    """Точно проверяет, подключен ли VPN"""
    text_lower = text.lower()

    connected_indicators = [
        'connected to',
        'successfully connected',
        'you are connected',
        'подключен к',
        'running on tun',
        'tun mode'
    ]

    disconnected_indicators = [
        'not connected',
        'disconnected',
        'no connection',
        'не подключен',
        'отключен'
    ]

    for indicator in disconnected_indicators:
        if indicator in text_lower:
            return False

    for indicator in connected_indicators:
        if indicator in text_lower:
            return True

    return False

def clean_location_output(text):
    """Очищает вывод локации от лишних данных, включая ANSI коды"""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    clean_text = ansi_escape.sub('', text)

    patterns = [
        r'Connected to (.+?) in',
        r'connected to (.+?) in',
        r'Connected to (.+?)\n',
        r'Connected to (.+?)\.',
        r'Location: (.+)',
        r'подключен к (.+?) в',
        r'Подключено к (.+?) в',
        r'Successfully Connected to (.+)',
        r'You are connected to (.+?)\.'
    ]

    for pattern in patterns:
        match = re.search(pattern, clean_text, re.IGNORECASE)
        if match:
            location = match.group(1).strip()
            return location

    locations = {
        'frankfurt': 'Frankfurt',
        'london': 'London',
        'new york': 'New York',
        'singapore': 'Singapore',
        'tokyo': 'Tokyo',
        'amsterdam': 'Amsterdam',
        'paris': 'Paris',
        'moscow': 'Moscow'
    }

    clean_text_lower = clean_text.lower()
    for key, value in locations.items():
        if key in clean_text_lower:
            return value

    return ""