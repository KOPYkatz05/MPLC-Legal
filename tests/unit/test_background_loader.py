import threading

from PySide6.QtCore import QThread

from ui.foundation.background_loader import LatestRequestLoader


class InlineThreadPool:
    def start(self, task):
        task.run()


def test_inline_pool_is_a_deterministic_test_fallback(qapp):
    results = []
    loader = LatestRequestLoader(thread_pool=InlineThreadPool())

    generation = loader.request(lambda: {"ready": True}, on_success=results.append)

    assert generation == 1
    assert results == [{"ready": True}]
    assert loader.busy is False


def test_only_latest_queued_request_is_delivered_on_ui_thread(qtbot):
    first_started = threading.Event()
    release_first = threading.Event()
    operations = []
    delivered = []
    callback_threads = []
    loader = LatestRequestLoader()

    def first():
        operations.append("first")
        first_started.set()
        assert release_first.wait(timeout=3)
        return "stale"

    def second():
        operations.append("second")
        return "replaced"

    def third():
        operations.append("third")
        return "latest"

    loader.request(first, on_success=delivered.append)
    qtbot.waitUntil(first_started.is_set, timeout=3000)
    loader.request(second, on_success=delivered.append)
    loader.request(
        third,
        on_success=lambda result: (
            callback_threads.append(QThread.currentThread()),
            delivered.append(result),
        ),
    )
    release_first.set()

    qtbot.waitUntil(lambda: not loader.busy, timeout=3000)

    assert operations == ["first", "third"]
    assert delivered == ["latest"]
    assert callback_threads == [loader.thread()]


def test_cancel_suppresses_in_flight_result(qtbot):
    started = threading.Event()
    release = threading.Event()
    delivered = []
    loader = LatestRequestLoader()

    def operation():
        started.set()
        assert release.wait(timeout=3)
        return "ignored"

    loader.request(operation, on_success=delivered.append)
    qtbot.waitUntil(started.is_set, timeout=3000)
    cancelled_generation = loader.cancel()
    release.set()

    qtbot.waitUntil(lambda: not loader.busy, timeout=3000)

    assert cancelled_generation == 2
    assert delivered == []


def test_failure_callback_receives_original_exception_on_ui_thread(qtbot):
    errors = []
    callback_threads = []
    loader = LatestRequestLoader()
    failure = ValueError("broken snapshot")

    def operation():
        raise failure

    loader.request(
        operation,
        on_error=lambda error: (
            callback_threads.append(QThread.currentThread()),
            errors.append(error),
        ),
    )

    qtbot.waitUntil(lambda: not loader.busy, timeout=3000)

    assert errors == [failure]
    assert callback_threads == [loader.thread()]
