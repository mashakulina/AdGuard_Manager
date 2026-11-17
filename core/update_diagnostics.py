"""CLI update execution and conservative, copyable diagnostics (no Tk dependencies)."""
from dataclasses import dataclass
import os
import re
import shlex
import signal
import subprocess
import time

RELEASES = 'https://github.com/AdguardTeam/AdGuardVPNCLI/releases'


def clean_output(value):
    if isinstance(value, bytes):
        value = value.decode('utf-8', 'replace')
    value = re.sub(r'\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\)|[@-_])', '', value or '')
    value = re.sub(r'(https?://)[^/\s@]+@', r'\1[REDACTED]@', value)
    return re.sub(r'(?i)([?&](?:[^=&\s]*(?:token|secret|password|signature|key|auth)[^=&\s]*)=)[^&\s]+', r'\1[REDACTED]', value)


@dataclass
class CommandResult:
    command: list
    returncode: int | None
    stdout: str
    stderr: str
    duration: float
    timed_out: bool = False

    @property
    def output(self):
        return clean_output(self.stdout) + ('\n' if self.stdout and self.stderr else '') + clean_output(self.stderr)


def _signal_tree(process, sig):
    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        pass


def run_command(command, timeout=15, input=None):
    started = time.monotonic()
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, start_new_session=True)
    timed_out = False
    try:
        out, err = process.communicate(input=input, timeout=timeout)
    except subprocess.TimeoutExpired as expired:
        timed_out = True
        _signal_tree(process, signal.SIGTERM)
        try:
            out, err = process.communicate(timeout=1)
        except subprocess.TimeoutExpired:
            _signal_tree(process, signal.SIGKILL)
            out, err = process.communicate()
        finally:
            # A descendant can close pipes and remain alive after its parent exits.
            _signal_tree(process, signal.SIGKILL)
        out = out or expired.output or ''
        err = err or expired.stderr or ''
    return CommandResult(list(command), process.returncode, clean_output(out), clean_output(err),
                         time.monotonic() - started, timed_out)


def has_error(text):
    return bool(re.search(r'\b(error|failed|failure|unavailable|cannot|denied)\b|ошиб|не удалось', text, re.I))


def _is_check_update(result):
    return (len(result.command) == 2
            and os.path.basename(result.command[0]) == 'adguardvpn-cli'
            and result.command[1] == 'check-update')


def check_status(result):
    # CLI 1.8.3 also uses 17 for an affirmative check-update "latest" result.
    known_check_code = result.returncode == 17 and _is_check_update(result)
    if result.timed_out or (result.returncode != 0 and not known_check_code) or has_error(result.output):
        return 'error'
    available = latest = False
    # Classify status assertions independently of the accompanying update instructions.
    # Split sentences without splitting the dots inside version numbers.
    for line in re.split(r'[\n;]+|(?<=[.!])\s+', result.output):
        line = line.strip(' >\t•').lower().rstrip('.!')
        if re.match(r'you can update\b|to update\b|run\b|для обновления\b', line):
            continue
        if re.fullmatch(
                r'you are (?:already )?using the latest version(?:\s+.*)?'
                r'|(?:your (?:version|software)|adguard vpn) is up[ -]to[ -]date'
                r'|up[ -]to[ -]date'
                r'|no (?:new )?updates? (?:is |are )?available'
                r'|(?:ваша |текущая )?версия актуальна'
                r'|установлена последняя версия(?:\s+.*)?', line):
            latest = True
        if re.search(r'\bnot (?:now )?available\b|\bno (?:new )?(?:version|update)[^\n]*available', line):
            continue
        if re.search(r'\bis (?:now )?available\b|\bupdate available\b'
                     r'|доступно обновление|можно обновиться', line):
            available = True
    if known_check_code:
        return 'latest' if latest and not available else 'error'
    if available and latest:
        return 'unknown'
    if available:
        return 'available'
    return 'latest' if latest else 'unknown'


def update_succeeded(result, before, after):
    if not all(re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][\w.]+)?', version or '') for version in (before, after)):
        return False
    return (not result.timed_out and result.returncode == 0 and not has_error(result.output)
            and bool(before and after) and before != after)


def diagnostics(result):
    text = result.output.lower()
    reasons = []
    for pattern, label in [
        (r'could not resolve|couldn.t resolve|name resolution|\bdns\b', 'Ошибка DNS: не удалось разрешить имя сервера.'),
        (r'certificate|\bssl\b|\btls\b', 'Ошибка TLS/сертификата.'),
        (r'\bhttp[^\n]*[45]\d\d|error: [45]\d\d', 'Сервер вернул ошибку HTTP.'),
        (r'timed? ?out|timeout', 'Истекло время ожидания.'),
        (r'permission|denied|operation not permitted', 'Недостаточно прав доступа.'),
    ]:
        if re.search(pattern, text):
            reasons.append(label)
    if result.timed_out:
        reasons.append('Таймаут: дерево процессов остановлено, частичный вывод сохранён.')
    if re.search(r'failed to download[^\n]*: 0\b', text):
        reasons.append('": 0" — дефект сообщения upstream install.sh: $? после if ! curl инвертирован; это не HTTP-статус.')
    network = result.timed_out or bool(re.search(
        r'curl|download|resolve|dns|ssl|tls|certificate|http|connect|network|timed? ?out|timeout', text))
    if network:
        reasons.extend([
            'Возможна недоступность маршрута, сети провайдера или сервера AdGuard/GitHub; вывод не доказывает блокировку.',
            'Повторите попытку; проверьте исходную ошибку curl в выводе или попробуйте другую сеть.',
            'Официальные пакеты: ' + RELEASES,
            'Сайт покупки подписки и сервер загрузки пакетов — разные адреса. Официальный установщик использует GitHub Releases.',
            'В историческом issue #62 описано отключение VPN до загрузки при update; поведение вашей версии нужно проверить: '
            'https://github.com/AdguardTeam/AdGuardVPNCLI/issues/62',
        ])
    elif not reasons:
        if _is_check_update(result):
            reasons.append('Проверка не определила актуальность версии. Проверьте полный вывод команды и повторите проверку.')
        else:
            reasons.append('Проверьте полный вывод команды и версии до/после. Нулевой код без подтверждённого изменения версии не доказывает обновление.')
    return '\n'.join(reasons)



def format_result(result, channel=None, before=None, after=None):
    return (f'Команда: {shlex.join(result.command)}\nКод возврата: {result.returncode}; '
            f'длительность: {result.duration:.2f} с; таймаут: {result.timed_out}\n'
            f'Канал: {channel or "—"}; версия до: {before or "неизвестно"}; '
            f'после: {after or "неизвестно"}\nstdout:\n{clean_output(result.stdout)}\n'
            f'stderr:\n{clean_output(result.stderr)}')
