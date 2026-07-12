from PySide6.QtCore import QObject, Signal


class ApiConnectionState(QObject):
    unavailable = Signal(str)
    restored = Signal()

    def __init__(self):
        super().__init__()
        self._available = True

    def report_unavailable(self, detail):
        if self._available:
            self._available = False
            self.unavailable.emit(str(detail))

    def report_restored(self):
        if not self._available:
            self._available = True
            self.restored.emit()


_connection_state = None


def api_connection_state():
    global _connection_state
    if _connection_state is None:
        _connection_state = ApiConnectionState()
    return _connection_state
