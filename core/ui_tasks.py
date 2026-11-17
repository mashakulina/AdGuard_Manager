"""Deliver worker results to Tk without calling Tcl from worker threads."""
import queue
import threading
import tkinter as tk


def _detach_tracebacks(error):
    """Keep error identity while dropping worker frames that capture Tk owners."""
    pending, seen = [error], set()
    while pending:
        current = pending.pop()
        if not isinstance(current, BaseException) or id(current) in seen:
            continue
        seen.add(id(current))
        current.__traceback__ = None
        pending.extend((current.__cause__, current.__context__))
        # ExceptionGroup exists on Python 3.11+. Its immutable exceptions tuple
        # can contain further groups and chained exceptions.
        children = getattr(current, 'exceptions', ())
        if isinstance(children, tuple):
            pending.extend(children)
    return error


class TaskRunner:
    def __init__(self, root):
        self.root = root
        self._queue = queue.Queue()
        self._lock = threading.Lock()
        self._closed = False
        self._keys = set()
        self._poll_id = root.after(25, self._poll)
        root.bind('<Destroy>', self._destroyed, add='+')

    def _destroyed(self, event):
        if event.widget is self.root:
            self.close()

    def post(self, callback, *args):
        with self._lock:
            if self._closed:
                return False
            self._queue.put((None, callback, args))
        return True

    def submit(self, work, on_success=None, on_error=None, key=None):
        with self._lock:
            if self._closed or (key is not None and key in self._keys):
                return False
            if key is not None:
                self._keys.add(key)

        def run():
            try:
                value = work()
                callback = on_success
            except Exception as error:
                value, callback = _detach_tracebacks(error), on_error
            with self._lock:
                if not self._closed:
                    self._queue.put((key, callback, (value,)))
        threading.Thread(target=run, daemon=True).start()
        return True

    def _poll(self):
        self._poll_id = None
        try:
            # Bound each batch so a stream of results cannot starve Tk events.
            for _ in range(100):
                with self._lock:
                    if self._closed:
                        return
                    try:
                        key, callback, args = self._queue.get_nowait()
                    except queue.Empty:
                        break
                    self._keys.discard(key)
                if callback is not None:
                    try:
                        callback(*args)
                    except Exception:
                        import sys
                        self.root.report_callback_exception(*sys.exc_info())
        finally:
            if not self._closed:
                self._poll_id = self.root.after(25, self._poll)

    def close(self):
        """Close on the Tk thread; running daemon work may finish silently."""
        with self._lock:
            self._closed = True
            self._keys.clear()
            while not self._queue.empty():
                self._queue.get_nowait()
        if self._poll_id is not None:
            try:
                self.root.after_cancel(self._poll_id)
            except tk.TclError:
                pass
            self._poll_id = None
