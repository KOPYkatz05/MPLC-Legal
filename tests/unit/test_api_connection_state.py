from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QThread

from services import api_connection_state as connection_state_module
from services.api_connection_state import ApiConnectionState


def test_worker_reports_are_applied_and_emitted_on_qt_owner_thread(qtbot):
    state = ApiConnectionState()
    unavailable_threads = []
    restored_threads = []
    details = []
    state.unavailable.connect(
        lambda detail: (
            details.append(detail),
            unavailable_threads.append(QThread.currentThread()),
        )
    )
    state.restored.connect(
        lambda: restored_threads.append(QThread.currentThread())
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(state.report_unavailable, "network down").result(
            timeout=3
        )

    # The worker only queues the transition; QObject state is not mutated from
    # the pool thread.
    assert state._available is True
    qtbot.waitUntil(lambda: details == ["network down"], timeout=3000)

    assert state._available is False
    assert unavailable_threads == [state.thread()]

    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(state.report_restored).result(timeout=3)

    assert state._available is False
    qtbot.waitUntil(lambda: len(restored_threads) == 1, timeout=3000)

    assert state._available is True
    assert restored_threads == [state.thread()]


def test_singleton_created_concurrently_is_unique_and_ui_affine(
    qapp,
    monkeypatch,
):
    monkeypatch.setattr(connection_state_module, "_connection_state", None)

    with ThreadPoolExecutor(max_workers=4) as executor:
        states = list(
            executor.map(
                lambda _index: connection_state_module.api_connection_state(),
                range(8),
            )
        )

    assert all(state is states[0] for state in states)
    assert states[0].thread() == qapp.thread()


def test_out_of_order_queued_transition_cannot_overwrite_newer_state(qapp):
    state = ApiConnectionState()
    unavailable = []
    restored = []
    state.unavailable.connect(unavailable.append)
    state.restored.connect(lambda: restored.append(True))

    state._apply_requested_state(2, False, "latest failure")
    state._apply_requested_state(1, True, "")

    assert state._available is False
    assert unavailable == ["latest failure"]
    assert restored == []
