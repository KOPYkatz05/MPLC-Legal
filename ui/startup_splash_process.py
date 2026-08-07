"""Dedicated-process lifecycle for the animated startup splash."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

from PySide6.QtCore import QEventLoop, QObject, QProcess, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from utils.runtime_paths import is_frozen


SPLASH_CHILD_ARGUMENT = "--mission-legal-splash-child"


class StartupSplashProcess(QObject):
    """Parent-side controller for the independently animated splash."""

    fading = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process = QProcess(self)
        self._server = QLocalServer(self)
        self._socket = None
        self._buffer = ""
        self._statuses = set()
        self._dismissed = False
        self._server_name = f"mission-legal-splash-{uuid.uuid4().hex}"
        self._process.finished.connect(self._server.close)

    @property
    def running(self) -> bool:
        return self._process.state() != QProcess.NotRunning

    def start(self, *, timeout_ms: int = 5000) -> bool:
        if self.running:
            return True
        if not self._server.listen(self._server_name):
            return False

        if is_frozen():
            program = sys.executable
            arguments = [SPLASH_CHILD_ARGUMENT, self._server_name]
            working_directory = str(Path(sys.executable).resolve().parent)
        else:
            main_path = Path(__file__).resolve().parents[1] / "main.py"
            program = sys.executable
            arguments = [str(main_path), SPLASH_CHILD_ARGUMENT, self._server_name]
            working_directory = str(main_path.parent)

        self._process.setWorkingDirectory(working_directory)
        self._process.start(program, arguments)
        if not self._process.waitForStarted(timeout_ms):
            self._server.close()
            return False
        if not self._wait_for_connection(timeout_ms=timeout_ms):
            self.abort()
            return False
        return self._wait_for_status("SHOWN", timeout_ms=timeout_ms)

    def advance_to(
        self,
        value: int,
        *,
        wait: bool = False,
        timeout_ms: int = 1000,
    ):
        """Advance the child splash, optionally flushing the IPC write first."""
        self._send({"command": "progress", "value": int(value)})
        if wait and self._socket is not None:
            self._socket.waitForBytesWritten(timeout_ms)

    def finish_and_wait(self, *, timeout_ms: int = 6000):
        if not self.running:
            return
        self._send({"command": "finish"})
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        self._process.finished.connect(loop.quit)
        timer.timeout.connect(loop.quit)
        timer.start(timeout_ms)
        loop.exec()
        timer.stop()
        if self.running:
            self.abort()

    def dismiss(self):
        if self._dismissed:
            return
        self._dismissed = True
        self._send({"command": "close"}, allow_dismissed=True)
        if self.running and not self._process.waitForFinished(1200):
            self.abort()

    def abort(self):
        self._dismissed = True
        if self.running:
            self._process.kill()
            self._process.waitForFinished(1000)
        self._server.close()

    def _send(self, payload: dict, *, allow_dismissed: bool = False):
        if (self._dismissed and not allow_dismissed) or self._socket is None:
            return
        if self._socket.state() != QLocalSocket.ConnectedState:
            return
        data = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        self._socket.write(data)
        self._socket.flush()

    def _wait_for_connection(self, *, timeout_ms: int) -> bool:
        if self._server.hasPendingConnections():
            self._accept_connection()
            return True
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        self._server.newConnection.connect(loop.quit)
        self._process.finished.connect(loop.quit)
        timer.timeout.connect(loop.quit)
        timer.start(timeout_ms)
        loop.exec()
        timer.stop()
        if not self._server.hasPendingConnections():
            return False
        self._accept_connection()
        return True

    def _accept_connection(self):
        self._socket = self._server.nextPendingConnection()
        self._socket.readyRead.connect(self._read_messages)
        self._server.close()

    def _read_messages(self):
        if self._socket is None:
            return
        self._buffer += bytes(self._socket.readAll()).decode("utf-8", errors="replace")
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            status = line.strip()
            if not status:
                continue
            self._statuses.add(status)
            if status == "FADING":
                self.fading.emit()

    def _wait_for_status(self, expected: str, *, timeout_ms: int) -> bool:
        if expected in self._statuses:
            return True
        found = False
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)

        def inspect_messages():
            nonlocal found
            if self._socket is None:
                loop.quit()
                return
            self._buffer += bytes(self._socket.readAll()).decode(
                "utf-8", errors="replace"
            )
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                status = line.strip()
                if status:
                    self._statuses.add(status)
                    if status == "FADING":
                        self.fading.emit()
            if expected in self._statuses:
                found = True
                loop.quit()

        poll = QTimer()
        poll.setInterval(10)
        poll.timeout.connect(inspect_messages)
        timer.timeout.connect(loop.quit)
        self._process.finished.connect(loop.quit)
        poll.start()
        timer.start(timeout_ms)
        inspect_messages()
        if not found and self.running:
            loop.exec()
        poll.stop()
        timer.stop()
        return found


def run_splash_child(server_name: str) -> int:
    """Run the splash window and consume parent commands over a local socket."""
    from app_identity import configure_windows_app_identity
    from ui.dialogs.startup_splash import StartupSplash
    from utils.runtime_paths import resource_path

    configure_windows_app_identity()

    app = QApplication(sys.argv)
    app.setWindowIcon(
        QIcon(
            str(
                resource_path(
                    "assets", "icons", "mission_legal", "mission_legal_icon.ico"
                )
            )
        )
    )
    app.setQuitOnLastWindowClosed(True)
    socket = QLocalSocket()
    socket.connectToServer(server_name)
    if not socket.waitForConnected(5000):
        return 2

    splash = StartupSplash()
    splash.show_centered()
    buffer = ""

    def report(status: str):
        socket.write(f"{status}\n".encode("utf-8"))
        socket.flush()

    def begin_fade():
        report("FADING")
        splash.fade_out(duration_ms=480, wait=False)

    def finish():
        splash.advance_to(100)
        animation = splash._progress_animation
        if animation is None:
            begin_fade()
        else:
            animation.finished.connect(begin_fade)

    def read_commands():
        nonlocal buffer
        buffer += bytes(socket.readAll()).decode("utf-8", errors="replace")
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            try:
                command = json.loads(line)
            except (TypeError, ValueError):
                continue
            action = command.get("command")
            if action == "progress":
                splash.advance_to(command.get("value", 0))
            elif action == "finish":
                finish()
            elif action == "close":
                splash.dismiss()
                app.quit()
                return

    socket.readyRead.connect(read_commands)
    socket.disconnected.connect(app.quit)
    report("SHOWN")
    return app.exec()


__all__ = [
    "SPLASH_CHILD_ARGUMENT",
    "StartupSplashProcess",
    "run_splash_child",
]
