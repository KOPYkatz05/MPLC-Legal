import threading

from PySide6.QtCore import QCoreApplication, QObject, Qt, Signal, Slot


class ApiConnectionState(QObject):
    unavailable = Signal(str)
    restored = Signal()
    _state_requested = Signal(int, bool, str)

    def __init__(self):
        super().__init__()
        self._available = True
        self._request_lock = threading.Lock()
        self._request_sequence = 0
        self._applied_sequence = 0
        self._state_requested.connect(
            self._apply_requested_state,
            Qt.QueuedConnection,
        )

    def report_unavailable(self, detail):
        self._request_state(False, str(detail))

    def report_restored(self):
        self._request_state(True, "")

    def _request_state(self, available, detail):
        with self._request_lock:
            self._request_sequence += 1
            sequence = self._request_sequence
        self._state_requested.emit(
            sequence,
            bool(available),
            str(detail),
        )

    @Slot(int, bool, str)
    def _apply_requested_state(self, sequence, available, detail):
        """Apply state only on this QObject's Qt-affinity thread."""

        if sequence <= self._applied_sequence:
            return
        self._applied_sequence = sequence
        if available == self._available:
            return
        self._available = available
        if available:
            self.restored.emit()
        else:
            self.unavailable.emit(detail)


_connection_state = None
_connection_state_lock = threading.Lock()


def api_connection_state():
    global _connection_state
    with _connection_state_lock:
        if _connection_state is None:
            state = ApiConnectionState()
            app = QCoreApplication.instance()
            if app is not None and state.thread() != app.thread():
                state.moveToThread(app.thread())
            _connection_state = state
        return _connection_state
