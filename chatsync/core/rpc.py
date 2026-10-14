"""Bounded JSON-RPC client; does not send model turns or approval responses."""
import collections
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import threading
import time

from .config import SyncError


class WindowsJob:
    """Contain this server and its helpers; closing the handle ends the entire tree."""
    def __init__(self, process):
        import ctypes
        from ctypes import wintypes as w

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", w.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", w.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", w.DWORD), ("SchedulingClass", w.DWORD)]

        class Counters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in ("ReadOperationCount", "WriteOperationCount",
                        "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", Counters),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = w.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        limits = Extended()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.handle or not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)) or not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            self.close()
            raise SyncError("Cannot contain Codex helper processes in a Windows job. No import was performed.")

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class Codex:
    def __init__(self, executable, home, timeout=90):
        self.executable = str(executable)
        self.home = str(home)
        self.timeout = timeout
        self.messages = queue.Queue()
        self.errors = collections.deque(maxlen=20)
        self.counter = 0
        self.process = None
        self.job = None

    def __enter__(self):
        env = dict(os.environ, CODEX_HOME=self.home)
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            self.process = subprocess.Popen(
                [self.executable, "app-server", "--stdio"], env=env,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", creationflags=flags,
                cwd=self.home, bufsize=1, start_new_session=os.name != "nt")
            if os.name == "nt":
                self.job = WindowsJob(self.process)
            self.readers = [threading.Thread(target=self._stdout, daemon=True),
                            threading.Thread(target=self._stderr, daemon=True)]
            for reader in self.readers:
                reader.start()
            self.initialized = self.call("initialize", {
                "clientInfo": {"name": "codex_chat_sync", "title": "Codex Chat Sync", "version": "0.1.0"},
                "capabilities": {"experimentalApi": True}})
            self._send({"method": "initialized"})
            return self
        except Exception:
            self.close()
            raise

    def _stdout(self):
        try:
            for line in self.process.stdout:
                try:
                    self.messages.put(json.loads(line))
                except ValueError:
                    continue
        finally:
            self.messages.put({"_closed": True})

    def _stderr(self):
        for line in self.process.stderr:
            self.errors.append(line.rstrip())

    def _send(self, message):
        try:
            self.process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
        except (OSError, ValueError) as exc:
            raise SyncError("Codex app-server closed unexpectedly.") from exc

    def call(self, method, params):
        self.counter += 1
        request_id = self.counter
        self._send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SyncError(f"Codex timed out on {method}. No existing chat was overwritten.")
            try:
                message = self.messages.get(timeout=remaining)
            except queue.Empty as exc:
                raise SyncError(f"Codex timed out on {method}.") from exc
            if message.get("_closed"):
                raise SyncError(f"Codex exited during {method}. Check executable/version and local configuration.")
            if "method" in message and "id" in message:
                self._send({"id": message["id"], "error": {"code": -32601, "message": "Migration client does not execute tools"}})
            if message.get("id") != request_id or "method" in message:
                continue
            if "error" in message:
                raise SyncError(f"{method}: {message['error'].get('message', 'Codex error')}")
            return message["result"]

    def pages(self, method, params=None):
        params = dict(params or {}, limit=100)
        seen = set()
        output = []
        while True:
            response = self.call(method, params)
            output.extend(response["data"])
            cursor = response.get("nextCursor")
            if not cursor:
                return output
            if cursor in seen:
                raise SyncError(f"Repeated pagination cursor from {method}")
            seen.add(cursor)
            params["cursor"] = cursor

    def turns(self, thread_id):
        return self.pages("thread/turns/list", {"threadId": thread_id, "itemsView": "full", "sortDirection": "asc"})

    def close(self):
        process = self.process
        if process is None:
            return
        if process.stdin:
            try:
                process.stdin.close()
            except OSError:
                pass
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if self.job:
            self.job.close()
        elif os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for reader in getattr(self, "readers", []):
            reader.join(timeout=2)
        for reader, stream in zip(getattr(self, "readers", []), (process.stdout, process.stderr)):
            # Never block closing a buffered pipe while another thread owns its lock.
            if stream and not reader.is_alive():
                stream.close()

    def __exit__(self, *args):
        self.close()


def executable_version(executable):
    try:
        result = subprocess.run([str(executable), "--version"], capture_output=True,
                                text=True, timeout=15, check=True)
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise SyncError("Cannot run the configured Codex executable.") from exc
