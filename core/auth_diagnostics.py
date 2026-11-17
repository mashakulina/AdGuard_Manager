"""Bounded, private login diagnostics; raw data never leaves this collector."""
import re
import unicodedata

MAX_OUTPUT = 16384
MAX_LINE = 8192
TRUNCATED = '\n[Вывод усечён]\n'
_ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)|\x1b[^\n]*$')
_URL = re.compile(r'(?i)\b(?:https?|wss?)://[^\s<>]*')
_EMAIL = re.compile(r'(?i)[\w.!#$%&\'*+/=?^`{|}~-]+@[^\s]*')
_SECRET = re.compile(r'(?i)\b(?:authorization|proxy[-_]authorization|(?:set[-_])?cookie|'
                     r'''(?:x[-_])?(?:api[-_])?key|code|sid|session_id|[\w-]*(?:token|secret|password|passwd|credential|auth_code|device_code)[\w-]*)["']?\s*(?:[:=]|,\s*["']|\s)\s*''')
_AUTH = re.compile(r'(?i)\b(?:Bearer|Basic)\s+[^\s,;]+')


def _clean(text):
    text = _ANSI.sub('', text)
    return ''.join(ch for ch in text if ch == '\n' or (not unicodedata.category(ch).startswith('C') and unicodedata.category(ch) not in ('Zl', 'Zp') and (ch == ' ' or unicodedata.category(ch) != 'Zs')))


def _redact(line):
    line = _clean(line)
    line = _URL.sub('[URL скрыт]', line)
    line = _EMAIL.sub('[email скрыт]', line)
    line = _AUTH.sub('[Авторизация скрыта]', line)
    match = _SECRET.search(line)
    if match:
        line = line[:match.end()] + '[скрыто]'
    return line


class DiagnosticCollector:
    """Keep complete raw lines until redaction, discard oversized lines whole.

    Keeping a raw suffix would reveal a URL/token cut across the capture limit.
    Only already redacted text is cropped into a bounded head and tail.
    """
    def __init__(self, limit=MAX_OUTPUT, line_limit=MAX_LINE):
        self.limit = max(128, limit)
        self.line_limit = max(128, line_limit)
        self._pending = ''
        self._dropping = False
        self._sensitive_block = False
        self._safe = ''
        self._truncated = False

    def _append(self, text):
        combined = self._safe + text
        capacity = self.limit - len(TRUNCATED)
        if len(combined) > capacity:
            half = capacity // 2
            self._safe = combined[:half] + combined[-(capacity-half):]
            self._truncated = True
        else:
            self._safe = combined

    def _line(self, line):
        clean = _clean(line)
        sensitive = bool(_SECRET.search(clean) or _URL.search(clean) or _EMAIL.search(clean)
                         or re.search(r'(?i)\b(?:Bearer|Basic)\b', clean))
        # CLI wrapping can split an arbitrary URL, email or header value over
        # several physical lines. Retain no unlabelled continuation until a
        # blank line; preserve only fixed known error phrases in that block.
        if not clean.strip():
            self._sensitive_block = False
            self._append('\n')
        elif self._sensitive_block:
            known = [phrase for phrase in ('Backend config was not fetched',
                     'Failed to get device auth', 'Failed to get auth link') if phrase.lower() in clean.lower()]
            self._append(('\n'.join(known) if known else '[Продолжение скрыто]') + '\n')
        else:
            self._append(_redact(clean) + '\n')
            self._sensitive_block = sensitive

    def feed(self, text):
        # Only LF terminates a log line. CR, tabs and Unicode separators are
        # removed before redaction, so they cannot expose a URL suffix.
        parts = text.split('\n')
        for index, part in enumerate(parts):
            ended = index < len(parts)-1
            if self._dropping:
                if ended:
                    self._dropping = False
                continue
            if len(self._pending) + len(part) > self.line_limit:
                self._pending = ''
                self._truncated = True
                self._append('[Слишком длинная строка скрыта]\n')
                self._dropping = not ended
                self._sensitive_block = True
                continue
            self._pending += part
            if ended:
                self._line(self._pending)
                self._pending = ''

    def finish(self):
        if self._pending:
            self._line(self._pending)
            self._pending = ''
        if self._truncated:
            half = (self.limit-len(TRUNCATED)) // 2
            return self._safe[:half] + TRUNCATED + self._safe[half:]
        return self._safe.rstrip('\n')


def sanitize(text, limit=MAX_OUTPUT):
    collector = DiagnosticCollector(limit=limit)
    collector.feed(str(text))
    return collector.finish()


def failure_summary(result):
    output = result.output.lower()
    if 'failed to get auth link' in output or 'failed to get device auth' in output:
        return ('CLI не смог получить ссылку авторизации. Возможна проблема соединения, '
                'маршрута, провайдера или сервера; точная причина неизвестна. Повторите попытку.')
    if result.state == 'timeout':
        return 'Время ожидания авторизации истекло. Проверьте соединение и повторите получение ссылки.'
    if result.state in ('read_error', 'worker_error'):
        return 'Не удалось прочитать результат авторизации CLI. Откройте подробности и повторите попытку.'
    if result.state == 'start_error':
        return 'Не удалось запустить CLI для авторизации. Откройте подробности и проверьте установку.'
    if not result.output.strip():
        return 'CLI завершился без ссылки и диагностического вывода. Повторите получение ссылки.'
    return 'CLI не получил ссылку или не завершил авторизацию. Откройте подробности и повторите попытку.'


def format_diagnostics(result):
    code = 'не получен' if result.returncode is None else str(result.returncode)
    return (f'Команда: adguardvpn-cli login\nСостояние: {result.state}\n'
            f'Код завершения: {code}\nДлительность: {result.duration:.2f} с\n\n'
            + (f'Ошибка запуска: {result.start_error}\n\n' if result.start_error else '')
            + 'Безопасный вывод CLI:\n' + (result.output or '[Вывод отсутствует]'))
