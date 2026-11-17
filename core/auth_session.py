"""Cancellable, bounded login process. No Tk calls or raw CLI diagnostics."""
from dataclasses import dataclass
import codecs
import os
import re
import selectors
import signal
import subprocess
import threading
import time
from urllib.parse import urlsplit
from core.auth_diagnostics import DiagnosticCollector, sanitize

_ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)')
_URL = re.compile(r'https://[^\s<>\x00-\x1f"\']+')


@dataclass(frozen=True)
class LoginResult:
    state: str
    returncode: int | None = None
    output: str = ''
    duration: float = 0.0
    start_error: str = ''


class AuthSession:
    def __init__(self, command=None, url_timeout=30, login_timeout=300):
        self.command = command or ['adguardvpn-cli', 'login']
        self.url_timeout = url_timeout
        self.login_timeout = login_timeout
        self.cancelled = threading.Event()
        self.process = None
        self._running = threading.Lock()

    def cancel(self):
        # Worker observes this within 50ms and performs terminate/wait itself.
        self.cancelled.set()

    def wait(self, timeout=None):
        """Acknowledge worker cleanup after cancel; call outside the Tk loop.

        A queued run that has not acquired the lock cannot spawn after cancel.
        """
        acquired = self._running.acquire() if timeout is None else self._running.acquire(timeout=timeout)
        if acquired:
            self._running.release()
        return acquired

    def _reap(self):
        process = self.process
        if process is None:
            return
        try:
            # Descendants may still own the output after the parent exits.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=0.4)
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        finally:
            for pipe in (process.stdin, process.stdout):
                if pipe:
                    pipe.close()

    def run(self, on_url):
        if not self._running.acquire(blocking=False):
            return LoginResult('busy')
        started = time.monotonic()
        collector = DiagnosticCollector()
        state, start_error = 'cancelled', ''
        self.process = None
        try:
            if not self.cancelled.is_set():
                try:
                    # Keep stdin open: EOF can cause a CLI console-read busy loop.
                    # Never send guessed answers or credentials automatically.
                    self.process = subprocess.Popen(self.command, stdin=subprocess.PIPE,
                                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                                    start_new_session=True, bufsize=0)
                except OSError as error:
                    state, start_error = 'start_error', sanitize(str(error), limit=1024)
                else:
                    try:
                        state = self._collect(on_url, collector)
                    except OSError as error:
                        state, start_error = 'read_error', sanitize(str(error), limit=1024)
        finally:
            try:
                self._reap()
                result = LoginResult(
                    state, self.process.returncode if self.process is not None else None,
                    collector.finish(), time.monotonic()-started, start_error)
            finally:
                self._running.release()
        return result

    def _collect(self, on_url, collector):
        start = last_data = time.monotonic()
        buffer = ''
        decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        emitted = None
        eof = False
        with selectors.DefaultSelector() as selector:
            os.set_blocking(self.process.stdout.fileno(), False)
            selector.register(self.process.stdout, selectors.EVENT_READ)
            while True:
                if self.cancelled.is_set():
                    return 'cancelled'
                now = time.monotonic()
                if now - start >= self.login_timeout or (emitted is None and now - start >= self.url_timeout):
                    return 'timeout'
                if not eof:
                    for key, _ in selector.select(0.05):
                        chunk = os.read(key.fd, 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            eof = True
                            break
                        decoded = decoder.decode(chunk)
                        collector.feed(decoded)
                        buffer = (buffer + decoded)[-131072:]
                        last_data = time.monotonic()
                else:
                    self.cancelled.wait(0.05)
                clean = _ANSI.sub('', buffer)
                matches = list(_URL.finditer(clean))
                if matches:
                    match = matches[-1]
                    candidate = match.group().rstrip('.,;)')
                    # With no newline, allow a short quiet period for split writes.
                    complete = match.end() < len(clean) or eof or time.monotonic() - last_data >= 0.35
                    try:
                        valid = bool(urlsplit(candidate).hostname)
                    except ValueError:
                        valid = False
                    if complete and valid and candidate != emitted:
                        emitted = candidate
                        on_url(candidate)
                if eof and self.process.poll() is not None:
                    return 'exited' if emitted else 'no_url'
