import json
import logging
import sys
import uuid

from PySide6.QtCore import QEventLoop, QObject, QProcess, QTimer, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog
from packaging.version import InvalidVersion, Version

from database.runtime import get_client_data_dir
from services.update_service import (
    ClientUpdateService,
    PreparedUpdate,
    installed_binary_dir,
)


logger = logging.getLogger(__name__)


def required_update_version_problem(candidate_version, required_version):
    """Return a user-facing problem when a release misses a server floor."""

    if not required_version:
        return ""
    try:
        candidate = Version(str(candidate_version))
        required = Version(str(required_version))
    except InvalidVersion:
        return "The update feed returned invalid release-version metadata."
    if candidate < required:
        return (
            f"The server requires Mission Legal {required} or newer, but the "
            f"latest update offered by this feed is {candidate}."
        )
    return ""


def _download_update_blocking(service, parent, message):
    """Run the isolated updater while a startup dialog owns the UI."""

    progress = QProgressDialog(
        message,
        "",
        0,
        100,
        parent,
    )
    progress.setWindowTitle("Mission Legal Update")
    progress.setCancelButton(None)
    progress.setWindowModality(Qt.ApplicationModal)
    progress.setMinimumDuration(0)
    progress.show()

    result = {"prepared": None, "error": ""}
    loop = QEventLoop()
    worker = _UpdateWorkerProcess(service)

    def finished(prepared):
        result["prepared"] = prepared
        loop.quit()

    def failed(error):
        result["error"] = error
        loop.quit()

    worker.progress.connect(progress.setValue)
    worker.finished.connect(finished)
    worker.failed.connect(failed)
    if worker.start():
        loop.exec()
    else:
        result["error"] = "The update worker could not be started."
    progress.close()
    return result


def offer_required_client_update(
    detail,
    parent=None,
    *,
    required_client_version=None,
):
    """Offer an update when API compatibility blocks normal app startup."""

    try:
        service = ClientUpdateService()
    except Exception as exc:
        QMessageBox.critical(
            parent,
            "Mission Legal Update Required",
            f"{detail}\n\nThe update configuration could not be loaded:\n{exc}",
        )
        return False

    if not service.enabled:
        QMessageBox.critical(
            parent,
            "Mission Legal Update Required",
            f"{detail}\n\nThis installation does not have an update source configured.",
        )
        return False

    prompt = QMessageBox(parent)
    prompt.setIcon(QMessageBox.Warning)
    prompt.setWindowTitle("Mission Legal Update Required")
    prompt.setText("This Mission Legal client must be updated before it can connect.")
    prompt.setInformativeText(str(detail))
    download = prompt.addButton("Download update", QMessageBox.AcceptRole)
    prompt.addButton("Exit", QMessageBox.RejectRole)
    prompt.exec()
    if prompt.clickedButton() is not download:
        return False

    result = _download_update_blocking(
        service,
        parent,
        "Checking for the latest Mission Legal update...",
    )

    if result["error"]:
        QMessageBox.critical(
            parent,
            "Mission Legal Update Failed",
            f"The update could not be downloaded.\n\n{result['error']}",
        )
        return False
    prepared = result["prepared"]
    if prepared is None:
        QMessageBox.critical(
            parent,
            "Mission Legal Update Required",
            "No newer client update is currently available from the configured source.",
        )
        return False

    version_problem = required_update_version_problem(
        prepared.version,
        required_client_version,
    )
    if version_problem:
        QMessageBox.critical(
            parent,
            "Required Mission Legal Update Is Not Available",
            f"{version_problem}\n\nContact the Mission Legal administrator before retrying.",
        )
        return False

    ready = QMessageBox(parent)
    ready.setIcon(QMessageBox.Information)
    ready.setWindowTitle("Mission Legal Update Ready")
    ready.setText(f"Mission Legal {prepared.version} is ready to install.")
    ready.setInformativeText("Choose Restart and update to continue.")
    restart = ready.addButton("Restart and update", QMessageBox.AcceptRole)
    ready.addButton("Exit", QMessageBox.RejectRole)
    ready.exec()
    if ready.clickedButton() is not restart:
        return False
    try:
        service.apply_prepared_update()
    except Exception as exc:
        QMessageBox.critical(
            parent,
            "Mission Legal Update Failed",
            f"The downloaded update could not be installed.\n\n{exc}",
        )
        return False
    return True


def offer_optional_client_update(parent=None):
    """Check for an optional release before the client has been paired."""

    try:
        service = ClientUpdateService()
    except Exception as exc:
        QMessageBox.warning(
            parent,
            "Mission Legal Updates",
            f"The update configuration could not be loaded.\n\n{exc}",
        )
        return False

    if not service.enabled:
        QMessageBox.information(
            parent,
            "Mission Legal Updates",
            "Updates are not configured for this installation.",
        )
        return False

    result = _download_update_blocking(
        service,
        parent,
        "Checking for Mission Legal updates...",
    )
    if result["error"]:
        QMessageBox.warning(
            parent,
            "Mission Legal Update Check Failed",
            f"The update check could not be completed.\n\n{result['error']}",
        )
        return False

    prepared = result["prepared"]
    if prepared is None:
        QMessageBox.information(
            parent,
            "Mission Legal Updates",
            "Mission Legal is up to date. You can continue pairing this computer.",
        )
        return False

    ready = QMessageBox(parent)
    ready.setIcon(QMessageBox.Information)
    ready.setWindowTitle("Mission Legal Update Available")
    ready.setText(f"Mission Legal {prepared.version} is available.")
    ready.setInformativeText(
        "You can restart and update now, or continue pairing with this version."
    )
    if prepared.notes_markdown:
        ready.setDetailedText(prepared.notes_markdown[:12000])
    restart = ready.addButton("Restart and update", QMessageBox.AcceptRole)
    ready.addButton("Continue pairing", QMessageBox.RejectRole)
    ready.exec()
    if ready.clickedButton() is not restart:
        return False

    try:
        service.apply_prepared_update()
    except Exception as exc:
        QMessageBox.critical(
            parent,
            "Mission Legal Update Failed",
            f"The downloaded update could not be installed.\n\n{exc}",
        )
        return False
    return True


class _UpdateWorkerProcess(QObject):
    """Run Velopack network work outside the GUI process.

    The worker may be stopped when the desktop app exits without terminating a
    Qt/Python thread in the middle of native Velopack code. Velopack stages only
    verified packages, so an interrupted temporary download is safe to retry.
    """

    progress = Signal(int)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, service, parent=None, *, check_only=False):
        super().__init__(parent)
        self.service = service
        self.check_only = bool(check_only)
        self._process = None
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._poll_state)
        self._state_path = None
        self._last_progress = -1
        self._done = False

    @property
    def running(self):
        return (
            self._process is not None
            and self._process.state() != QProcess.NotRunning
        )

    def start(self):
        if self.running:
            return False

        state_root = get_client_data_dir() / "Updates" / "Worker"
        state_root.mkdir(parents=True, exist_ok=True)
        self._state_path = state_root / f"update-{uuid.uuid4().hex}.json"
        self._last_progress = -1
        self._done = False

        process = QProcess(self)
        process.setWorkingDirectory(str(installed_binary_dir()))
        if getattr(sys, "frozen", False):
            program = installed_binary_dir() / "MissionLegalUpdateWorker.exe"
            if not program.is_file():
                self.failed.emit(
                    "The installed update worker is missing. Reinstall Mission Legal."
                )
                self._done = True
                self._cleanup_state()
                return False
            arguments = ["--state-file", str(self._state_path)]
        else:
            program = sys.executable
            arguments = [
                str(installed_binary_dir() / "client_update_worker.py"),
                "--state-file",
                str(self._state_path),
            ]
        if self.check_only:
            arguments.append("--check-only")

        process.finished.connect(self._process_finished)
        process.errorOccurred.connect(self._process_error)
        self._process = process
        self._timer.start()
        process.start(str(program), arguments)
        return True

    def _read_state(self):
        if self._state_path is None or not self._state_path.is_file():
            return None
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    @Slot()
    def _poll_state(self):
        payload = self._read_state()
        if not payload or payload.get("status") != "downloading":
            return
        try:
            value = max(0, min(100, int(payload.get("progress", 0))))
        except (TypeError, ValueError):
            return
        value = max(self._last_progress, value)
        if value != self._last_progress:
            self._last_progress = value
            self.progress.emit(value)

    @Slot(int, QProcess.ExitStatus)
    def _process_finished(self, exit_code, _exit_status):
        if self._done:
            return
        self._done = True
        self._timer.stop()
        payload = self._read_state() or {}
        status = str(payload.get("status") or "")
        try:
            if exit_code == 0 and status == "current":
                self.finished.emit(None)
                return
            if exit_code == 0 and status == "ready":
                prepared = self.service.load_pending_update()
                if prepared is None:
                    raise RuntimeError(
                        "The update worker finished, but no verified update was staged."
                    )
                worker_version = str(payload.get("version") or "")
                if worker_version and prepared.version != worker_version:
                    raise RuntimeError(
                        "The staged update version did not match the worker result."
                    )
                self.finished.emit(prepared)
                return
            if exit_code == 0 and status == "available":
                self.finished.emit(
                    PreparedUpdate(
                        version=str(payload.get("version") or ""),
                        notes_markdown=str(payload.get("notes_markdown") or ""),
                        size=int(payload.get("size") or 0),
                    )
                )
                return
            detail = str(payload.get("error") or "").strip()
            if not detail:
                detail = f"The update worker exited with code {exit_code}."
            self.failed.emit(detail)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self._cleanup_state()

    @Slot(QProcess.ProcessError)
    def _process_error(self, error):
        if self._done or error != QProcess.FailedToStart:
            return
        self._done = True
        self._timer.stop()
        self.failed.emit("The update worker process could not be started.")
        self._cleanup_state()

    def stop(self):
        self._done = True
        self._timer.stop()
        process = self._process
        if process is not None and process.state() != QProcess.NotRunning:
            process.terminate()
            if not process.waitForFinished(2000):
                process.kill()
                process.waitForFinished(5000)
        self._cleanup_state()

    def _cleanup_state(self):
        if self._state_path is not None:
            try:
                self._state_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                logger.debug(
                    "Could not remove update-worker state %s",
                    self._state_path,
                    exc_info=True,
                )


class ClientUpdateCoordinator(QObject):
    status_changed = Signal(str)
    progress_changed = Signal(int)
    update_ready = Signal(str)

    def __init__(self, main_window, service=None):
        super().__init__(main_window)
        self.main_window = main_window
        self.service = service or ClientUpdateService()
        self._worker = None
        self._manual = False
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    @property
    def enabled(self):
        return self.service.enabled

    def start_automatic_check(self):
        settings = getattr(self.main_window, "settings_service", None)
        if settings is not None and not settings.get_automatic_updates_enabled():
            self.status_changed.emit("disabled")
            return False
        return self.check_for_updates(manual=False)

    def check_for_updates(self, manual=True):
        if not self.enabled:
            self.status_changed.emit("not-configured")
            if manual:
                QMessageBox.information(
                    self.main_window,
                    "Mission Legal Updates",
                    "This installation does not have an update source configured.",
                )
            return False
        if self._worker is not None:
            return False

        self._manual = bool(manual)
        self.status_changed.emit("checking")
        worker = _UpdateWorkerProcess(self.service, self, check_only=True)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        self._worker = worker
        if not worker.start():
            if self._worker is worker:
                self._worker = None
                worker.deleteLater()
            return False
        return True

    @Slot(int)
    def _on_progress(self, progress):
        self.status_changed.emit("downloading")
        self.progress_changed.emit(progress)

    @Slot(object)
    def _on_finished(self, prepared):
        self._clear_worker()
        if prepared is None:
            self.status_changed.emit("current")
            if self._manual:
                QMessageBox.information(
                    self.main_window,
                    "Mission Legal Updates",
                    "Mission Legal is up to date.",
                )
            return

        if prepared._native is not None:
            self.status_changed.emit("ready")
            self.update_ready.emit(prepared.version)
            QTimer.singleShot(0, lambda: self._offer_restart(prepared))
            return

        self.status_changed.emit("available")
        QTimer.singleShot(0, lambda: self._offer_download(prepared))

    @Slot(str)
    def _on_failed(self, detail):
        self._clear_worker()
        self.status_changed.emit("failed")
        if self._manual:
            QMessageBox.warning(
                self.main_window,
                "Mission Legal Updates",
                f"The update check could not be completed.\n\n{detail}",
            )
        else:
            logger.warning("Automatic update check failed: %s", detail)

    def _clear_worker(self):
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()

    def _offer_download(self, available):
        if QApplication.activeModalWidget() is not None:
            QTimer.singleShot(1500, lambda: self._offer_download(available))
            return

        dialog = QMessageBox(self.main_window)
        dialog.setIcon(QMessageBox.Information)
        dialog.setWindowTitle("Mission Legal Update Available")
        dialog.setText(f"Mission Legal {available.version} is available.")
        dialog.setInformativeText("Would you like to download this update now?")
        if available.notes_markdown:
            dialog.setDetailedText(available.notes_markdown[:12000])
        download = dialog.addButton("Download update", QMessageBox.AcceptRole)
        dialog.addButton("Later", QMessageBox.RejectRole)
        dialog.exec()
        if dialog.clickedButton() is not download:
            self.status_changed.emit("available")
            return

        self.status_changed.emit("downloading")
        worker = _UpdateWorkerProcess(self.service, self)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_download_finished)
        worker.failed.connect(self._on_failed)
        self._worker = worker
        if not worker.start() and self._worker is worker:
            self._worker = None
            worker.deleteLater()

    @Slot(object)
    def _on_download_finished(self, prepared):
        self._clear_worker()
        if prepared is None:
            self.status_changed.emit("current")
            return
        self.status_changed.emit("ready")
        self.update_ready.emit(prepared.version)
        QTimer.singleShot(0, lambda: self._offer_restart(prepared))

    @Slot()
    def shutdown(self):
        worker = self._worker
        self._worker = None
        if worker is None:
            return
        if worker.running:
            logger.info("Stopping the isolated client update worker during shutdown")
        worker.stop()

    def _offer_restart(self, prepared):
        if QApplication.activeModalWidget() is not None:
            QTimer.singleShot(1500, lambda: self._offer_restart(prepared))
            return

        dialog = QMessageBox(self.main_window)
        dialog.setIcon(QMessageBox.Information)
        dialog.setWindowTitle("Mission Legal Update Ready")
        dialog.setText(f"Mission Legal {prepared.version} is ready to install.")
        dialog.setInformativeText(
            "Save any work, then restart Mission Legal to finish the update."
        )
        if prepared.notes_markdown:
            dialog.setDetailedText(prepared.notes_markdown[:12000])
        restart = dialog.addButton("Restart and update", QMessageBox.AcceptRole)
        dialog.addButton("Later", QMessageBox.RejectRole)
        dialog.exec()
        if dialog.clickedButton() is not restart:
            return

        self.status_changed.emit("applying")
        try:
            self.service.apply_prepared_update()
        except Exception as exc:
            self.status_changed.emit("failed")
            QMessageBox.critical(
                self.main_window,
                "Mission Legal Update Failed",
                f"The downloaded update could not be installed.\n\n{exc}",
            )
            return
        QApplication.quit()
