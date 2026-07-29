from client_bootstrap import run_client_bootstrap


# Velopack install/update hooks must run before argument parsing, Qt creation,
# logging, database imports, or any other application startup work.
run_client_bootstrap()

import sys
import argparse

from utils.pycache_cleanup import cleanup_pycache
from utils.runtime_paths import is_frozen, resource_path


def load_stylesheet(app):
    theme_path = resource_path("assets", "styles", "theme.qss")

    if theme_path.exists():
        with open(theme_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())


def main():
    import os

    # Source runs historically use the repository as their working directory.
    # A frozen app lives under Program Files, so it must never rely on that
    # read-only directory for logs, configuration, or other runtime output.
    if not is_frozen():
        os.chdir(resource_path())

    parser = argparse.ArgumentParser(
        description=(
            "Mission Legal App"
        )
    )

    parser.add_argument(
        "--clean-pycache",
        action="store_true",
        help=(
            "Remove stale __pycache__ folders and exit."
        ),
    )

    parser.add_argument(
        "--pycache-root",
        default=".",
        help=(
            "Root directory to scan when using "
            "--clean-pycache."
        ),
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Show which __pycache__ folders would be removed "
            "without deleting them."
        ),
    )
    parser.add_argument(
        "--send-daily-digest",
        action="store_true",
        help="Send the configured daily digest email and exit.",
    )
    parser.add_argument(
        "--ocr-worker",
        nargs=argparse.REMAINDER,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--package-smoke-test",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--installed-update-smoke-test",
        nargs=2,
        metavar=("EXPECTED_VERSION", "RESULT_FILE"),
        help=argparse.SUPPRESS,
    )

    args = parser.parse_args()

    if args.ocr_worker is not None:
        os.environ["MISSION_LEGAL_LOG_ROLE"] = "ocr-worker"
        from services.ocr_worker import main as ocr_worker_main

        return ocr_worker_main(args.ocr_worker)

    if args.package_smoke_test:
        from utils.package_smoke import run_client_package_smoke_test

        return run_client_package_smoke_test()

    if args.installed_update_smoke_test is not None:
        from utils.installed_update_smoke import run_installed_update_smoke_test

        return run_installed_update_smoke_test(*args.installed_update_smoke_test)

    if args.clean_pycache:
        removed = cleanup_pycache(
            args.pycache_root,
            dry_run=args.dry_run,
        )

        action = "Would remove" if args.dry_run else "Removed"

        print(
            f"{action} {len(removed)} stale __pycache__ "
            f"folder(s)."
        )

        return

    if args.send_daily_digest:
        if (
            is_frozen()
            and os.environ.get("MISSION_LEGAL_ALLOW_LOCAL_DATABASE") != "1"
        ):
            print(
                "Daily digest jobs must run from the Mission Legal server package."
            )
            return 2
        os.environ["MISSION_LEGAL_SERVER_PROCESS"] = "1"
        from database.models.missionary import Missionary  # noqa: F401
        from database.models.workflow import WorkflowStage  # noqa: F401
        from database.models.document import Document  # noqa: F401
        from database.models.stage_history import StageHistory  # noqa: F401
        from database.models.appointment import Appointment  # noqa: F401
        from database.models.secretary_work import SecretaryTask  # noqa: F401
        from database.db import init_db
        from services.email_digest_service import EmailDigestService

        init_db()
        result = EmailDigestService().send_daily_digest()
        if result.get("sent"):
            print("Daily digest email sent.")
            return
        print(f"Daily digest email not sent: {result.get('reason')}")
        return

    from PySide6.QtCore import QCoreApplication, QTimer
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
    from app_identity import APP, ORG
    from version import APP_VERSION

    QCoreApplication.setOrganizationName(ORG)
    QCoreApplication.setApplicationName(APP)
    QCoreApplication.setApplicationVersion(APP_VERSION)

    app = QApplication(sys.argv)

    from ui.dialogs.startup_splash import StartupSplash

    startup_splash = StartupSplash()
    startup_splash.show_centered()
    app.processEvents()

    from services.api_client import (
        ApiCompatibilityError,
        MissionLegalApiClient,
        connection_configuration_diagnostics,
    )
    from services.client_pairing_service import (
        ClientPairingRecoveryError,
        recover_configured_server_address,
        recover_interrupted_pairing,
    )

    try:
        recover_interrupted_pairing()
        startup_splash.advance_to(10)
    except ClientPairingRecoveryError as exc:
        startup_splash.dismiss()
        QMessageBox.critical(
            None,
            "Mission Legal Pairing Recovery Required",
            str(exc),
        )
        return

    client_update_scheduled = object()

    def pair_installed_client():
        from ui.dialogs.client_pairing_dialog import ClientPairingDialog

        startup_splash.dismiss()
        load_stylesheet(app)
        pairing_dialog = ClientPairingDialog()
        if pairing_dialog.exec() != QDialog.Accepted:
            return None
        if pairing_dialog.update_scheduled:
            return client_update_scheduled
        paired_client = MissionLegalApiClient.from_environment()
        if paired_client is None:
            QMessageBox.critical(
                None,
                "Mission Legal Pairing Was Not Saved",
                "Windows did not retain the new server connection. Reopen "
                "Mission Legal and pair this computer again.",
            )
        return paired_client

    api_client = MissionLegalApiClient.from_environment()
    print(
        "Mission Legal connection configuration: "
        f"{connection_configuration_diagnostics()}",
        flush=True,
    )
    startup_splash.advance_to(25)
    if (
        api_client is None
        and is_frozen()
        and os.environ.get("MISSION_LEGAL_ALLOW_LOCAL_DATABASE") != "1"
    ):
        api_client = pair_installed_client()
        if api_client is client_update_scheduled:
            return
        if api_client is None:
            return

    if api_client is None:
        # IMPORTANT: import models before creating or migrating local tables.
        from database.models.missionary import Missionary  # noqa: F401
        from database.models.workflow import WorkflowStage  # noqa: F401
        from database.models.document import Document  # noqa: F401
        from database.models.stage_history import StageHistory  # noqa: F401
        from database.db import init_db
        from database.runtime import get_database_path
        from services.database_backup_service import DatabaseBackupService

        if get_database_path().exists():
            DatabaseBackupService().create_snapshot(reason="pre-migration")
        init_db()
        startup_splash.advance_to(65)
    else:
        # Modules imported by the UI expose both local and remote services. Mark
        # this process before importing them so database.db cannot create a
        # writable client-side SQLite database as an import side effect.
        os.environ["MISSION_LEGAL_REMOTE_CLIENT"] = "1"
        while True:
            try:
                health = api_client.health()
                api_client.validate_compatibility(health)
                session = api_client.session()
                api_client.validate_compatibility(session)
                startup_splash.advance_to(65)
                break
            except ApiCompatibilityError as exc:
                if exc.client_update_required:
                    from ui.update_coordinator import offer_required_client_update

                    offer_required_client_update(
                        str(exc),
                        required_client_version=exc.required_client_version,
                    )
                else:
                    title = (
                        "Mission Legal Server Update Required"
                        if exc.reason == ApiCompatibilityError.SERVER_UPDATE_REQUIRED
                        else "Mission Legal Compatibility Error"
                    )
                    QMessageBox.critical(
                        None,
                        title,
                        f"{exc}\n\n"
                        "Update or repair Mission Legal Server on the main "
                        "computer, then reopen this app.",
                    )
                return
            except Exception as exc:
                if recover_configured_server_address():
                    refreshed_client = MissionLegalApiClient.from_environment()
                    if refreshed_client is not None:
                        api_client = refreshed_client
                        continue
                startup_splash.dismiss()
                dialog = QMessageBox()
                dialog.setIcon(QMessageBox.Warning)
                dialog.setWindowTitle("Mission Legal Server Unavailable")
                dialog.setText("Waiting for the main Mission Legal computer.")
                dialog.setInformativeText(
                    f"The server could not be reached or authenticated.\n\n{exc}\n\n"
                    "Start the main computer and server, then choose Retry."
                )
                retry = dialog.addButton("Retry", QMessageBox.AcceptRole)
                change_connection = None
                change_connection = dialog.addButton(
                    "Change connection",
                    QMessageBox.ActionRole,
                )
                dialog.addButton("Exit", QMessageBox.RejectRole)
                dialog.exec()
                clicked = dialog.clickedButton()
                if clicked is change_connection:
                    api_client = pair_installed_client()
                    if api_client is client_update_scheduled:
                        return
                    if api_client is None:
                        return
                    continue
                if clicked is not retry:
                    return

    from ui.main_window import MainWindow

    load_stylesheet(app)

    from utils.window_diagnostics import install_window_diagnostics

    install_window_diagnostics(app)

    window = MainWindow()
    startup_splash.advance_to(90)
    startup_splash.dismiss()

    if api_client is not None:
        from services.api_connection_state import api_connection_state
        from ui.dialogs.server_wait_dialog import ServerWaitDialog

        wait_dialog = None

        def show_server_wait(detail):
            nonlocal wait_dialog
            if wait_dialog is None:
                wait_dialog = ServerWaitDialog(api_client, detail, window)
            else:
                wait_dialog.set_detail(detail)
            wait_dialog.show()
            wait_dialog.raise_()
            wait_dialog.activateWindow()

        api_connection_state().unavailable.connect(show_server_wait)

    window.showMaximized()

    try:
        from ui.update_coordinator import ClientUpdateCoordinator

        window.update_coordinator = ClientUpdateCoordinator(window)
        window.settings_page.bind_update_coordinator(window.update_coordinator)
        if window.update_coordinator.enabled:
            QTimer.singleShot(
                2500,
                window.update_coordinator.start_automatic_check,
            )
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "Client automatic updates could not be initialized"
        )

    exit_code = app.exec()

    # A SQLite online backup remains consistent even if WAL mode was active.
    # Dispose pooled connections first so a clean desktop exit also checkpoints
    # and releases the authoritative database before the snapshot is mirrored.
    if api_client is None:
        try:
            from database.db import engine
            from services.database_backup_service import DatabaseBackupService

            engine.dispose()
            backup_service = DatabaseBackupService()
            backup_service.create_snapshot(reason="clean-exit")
            backup_service.prune(keep=48, mirror_keep=30)
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "Could not create the clean-exit database backup"
            )

    sys.exit(exit_code)


if __name__ == "__main__":
    result = main()
    if isinstance(result, int):
        raise SystemExit(result)
