from PySide6.QtCore import QObject, Signal

TRANSLATIONS = {
    "en": {
        "app_title": "Mission Legal Tracker",
        "sidebar_dashboard": "  Dashboard",
        "sidebar_missionaries": "  Missionaries",
        "sidebar_office_work": "  Office Work",
        "sidebar_appointments": "  Appointments",
        "sidebar_reports": "  Reports",
        "sidebar_trash": "  Trash",
        "sidebar_settings": "  Settings",
        "settings_title": "Settings",
        "settings_language": "Language",
        "settings_language_hint": "Choose the language for secretary-facing screens.",
        "settings_storage_root": "Document storage folder",
        "settings_storage_root_hint": "Shared OneDrive folder used for ACTIVE, TRASH, and ARCHIVE.",
        "settings_browse": "Browse",
        "settings_saved": "Settings saved.",
        "settings_digest_title": "Daily Digest",
        "settings_digest_hint": "Show a compressed daily work summary on the dashboard and send it by email.",
        "settings_digest_email_enabled": "Send daily digest email",
        "settings_digest_recipient": "Recipient email",
        "settings_digest_time": "Digest time",
        "settings_digest_include_overdue": "Include overdue tasks",
        "settings_digest_detail": "Detail level",
        "settings_digest_detail_brief": "Brief",
        "settings_digest_detail_balanced": "Balanced",
        "settings_digest_detail_detailed": "Detailed",
        "settings_digest_smtp_host": "SMTP host",
        "settings_digest_smtp_port": "SMTP port",
        "settings_digest_tls": "Security",
        "settings_digest_tls_none": "None",
        "settings_digest_sender": "Sender email",
        "settings_digest_smtp_username": "SMTP username",
        "settings_digest_smtp_password": "SMTP password",
        "settings_digest_password_saved": "Saved password will be kept",
        "settings_digest_password_error": "Could not save the SMTP password to Windows Credential Manager.",
        "settings_digest_send_test": "Send test email",
        "settings_digest_install_task": "Install/Update Windows scheduled task",
        "settings_digest_test_sent": "Test digest email sent.",
        "settings_digest_test_failed": "Could not send the test digest email.",
        "settings_digest_missing_settings": "Missing email settings: {missing}",
        "settings_digest_task_installed": "Windows scheduled task installed.",
        "settings_digest_task_failed": "Could not install the Windows scheduled task.",
        "lang_english": "English",
        "lang_spanish": "Español",
        "ocr_review_title": "Review Extracted Data",
        "ocr_review_instructions": (
            "OCR has extracted the following data from your document. "
            "Please review and correct any errors before saving."
        ),
        "ocr_status_success": "All fields extracted successfully. Please verify.",
        "ocr_status_partial": "Some fields could not be read. Please fill in missing values.",
        "ocr_status_failed": "OCR could not read this document. Enter values manually.",
        "ocr_status_skipped": "No OCR fields for this document type.",
        "ocr_skip": "Skip (no OCR data)",
        "ocr_save": "Save Extracted Data",
        "ocr_initializing": "Initializing OCR engine...",
        "ocr_running": "Reading document text...",
        "save_dates": "Save Dates",
        "dates_saved": "Dates saved successfully.",
        "dates_save_failed": "Failed to save dates.",
        "upload_summary_title": "Upload Complete",
        "upload_summary_updated": "Updated fields:",
        "upload_summary_missing": "Still missing for current stage:",
        "upload_summary_none_missing": "All required documents for this stage are uploaded.",
        "upload_summary_calendar": "View in Appointments calendar?",
        "field_from_source": "From: {label}",
        "view_extracted_data": "View Extracted Data",
        "delete_document": "Delete Document",
        "delete_document_title": "Delete Document",
        "delete_document_confirm": (
            "Delete this uploaded document?\n\n"
            "This will permanently remove the file and its record."
        ),
        "delete_document_failed": "Failed to delete the document.",
        "extracted_data_title": "Extracted Data",
        "extracted_data_none": "No OCR data stored for this document.",
        "batch_run_ocr": "Run OCR for supported document types",
        "batch_uploaded_ocr": "Uploaded + OCR",
        "batch_uploaded": "Uploaded",
        "batch_ocr_skipped": "OCR skipped",
        "export_passport_exp": "Passport Expiration",
        "export_interpol_appt": "Interpol Appointment",
        "export_biometric_appt": "Biometric Appointment",
        "export_pickup_appt": "Pickup Appointment",
        "export_menu": "Export",
        "export_columns": "Export Columns",
        "export_full": "Full Export",
        "export_select_group_title": "Select Group",
        "export_select_group_message": "Choose a group before running a full export.",
        "export_full_dialog_title": "Full Export",
        "export_complete_title": "Export Complete",
        "export_failed_title": "Export Failed",
        "export_failed_message": "Failed to export. Check logs for details.",
        "export_full_complete_message": (
            "Exported {count} missionaries to:\n{path}"
        ),
        "export_full_missing_folders": (
            "These missionaries did not have a document folder to copy:"
        ),
        "passport_number": "Passport Number",
        "full_name": "Full Name",
        "date_of_birth": "Date of Birth",
        "nationality": "Nationality",
        "passport_expiration": "Passport Expiration",
        "arrival_date": "Arrival Date",
        "visa_expiration": "Visa Expiration",
        "tramite_usuario": "Trámite Usuario",
        "tramite_contrasena": "Trámite Contraseña",
        "interpol_appointment_date": "Interpol Appointment Date",
        "biometric_appointment_date": "Biometric Appointment Date",
        "pickup_appointment_date": "Pickup Appointment Date",
        "carnet_number": "Carnet Number",
        "carnet_issue_date": "Carnet Issue Date",
        "residency_expiration": "Residency Expiration",
        "prorroga_expiration": "Prórroga Expiration",
        "cancelacion_date": "Cancelación Date",
    },
    "es": {
        "app_title": "Seguimiento Legal Misional",
        "sidebar_dashboard": "  Panel",
        "sidebar_missionaries": "  Misioneros",
        "sidebar_office_work": "  Trabajo de Oficina",
        "sidebar_appointments": "  Citas",
        "sidebar_reports": "  Reportes",
        "sidebar_trash": "  Papelera",
        "sidebar_settings": "  Configuración",
        "settings_title": "Configuración",
        "settings_language": "Idioma",
        "settings_language_hint": "Elija el idioma para las pantallas de secretaría.",
        "settings_storage_root": "Carpeta de documentos",
        "settings_storage_root_hint": "Carpeta compartida de OneDrive usada para ACTIVE, TRASH y ARCHIVE.",
        "settings_browse": "Buscar",
        "settings_saved": "Configuración guardada.",
        "settings_digest_title": "Resumen diario",
        "settings_digest_hint": "Muestra un resumen comprimido del trabajo diario en el panel y lo envía por correo.",
        "settings_digest_email_enabled": "Enviar resumen diario por correo",
        "settings_digest_recipient": "Correo destinatario",
        "settings_digest_time": "Hora del resumen",
        "settings_digest_include_overdue": "Incluir tareas atrasadas",
        "settings_digest_detail": "Nivel de detalle",
        "settings_digest_detail_brief": "Breve",
        "settings_digest_detail_balanced": "Balanceado",
        "settings_digest_detail_detailed": "Detallado",
        "settings_digest_smtp_host": "Servidor SMTP",
        "settings_digest_smtp_port": "Puerto SMTP",
        "settings_digest_tls": "Seguridad",
        "settings_digest_tls_none": "Ninguna",
        "settings_digest_sender": "Correo remitente",
        "settings_digest_smtp_username": "Usuario SMTP",
        "settings_digest_smtp_password": "Contraseña SMTP",
        "settings_digest_password_saved": "Se conservará la contraseña guardada",
        "settings_digest_password_error": "No se pudo guardar la contraseña SMTP en Windows Credential Manager.",
        "settings_digest_send_test": "Enviar correo de prueba",
        "settings_digest_install_task": "Instalar/actualizar tarea programada",
        "settings_digest_test_sent": "Correo de prueba enviado.",
        "settings_digest_test_failed": "No se pudo enviar el correo de prueba.",
        "settings_digest_missing_settings": "Faltan configuraciones de correo: {missing}",
        "settings_digest_task_installed": "Tarea programada de Windows instalada.",
        "settings_digest_task_failed": "No se pudo instalar la tarea programada de Windows.",
        "lang_english": "English",
        "lang_spanish": "Español",
        "ocr_review_title": "Revisar datos extraídos",
        "ocr_review_instructions": (
            "El OCR extrajo los siguientes datos de su documento. "
            "Revise y corrija errores antes de guardar."
        ),
        "ocr_status_success": "Todos los campos se extrajeron. Verifique los datos.",
        "ocr_status_partial": "Algunos campos no se leyeron. Complete los valores faltantes.",
        "ocr_status_failed": "No se pudo leer el documento. Ingrese los valores manualmente.",
        "ocr_status_skipped": "Este tipo de documento no usa OCR.",
        "ocr_skip": "Omitir (sin datos OCR)",
        "ocr_save": "Guardar datos extraídos",
        "ocr_initializing": "Iniciando motor OCR...",
        "ocr_running": "Leyendo texto del documento...",
        "save_dates": "Guardar fechas",
        "dates_saved": "Fechas guardadas correctamente.",
        "dates_save_failed": "No se pudieron guardar las fechas.",
        "upload_summary_title": "Carga completada",
        "upload_summary_updated": "Campos actualizados:",
        "upload_summary_missing": "Aún faltan para la etapa actual:",
        "upload_summary_none_missing": "Todos los documentos requeridos de esta etapa están cargados.",
        "upload_summary_calendar": "¿Ver en el calendario de citas?",
        "field_from_source": "De: {label}",
        "view_extracted_data": "Ver datos extraídos",
        "delete_document": "Eliminar documento",
        "delete_document_title": "Eliminar documento",
        "delete_document_confirm": (
            "¿Eliminar este documento cargado?\n\n"
            "Esto eliminará permanentemente el archivo y su registro."
        ),
        "delete_document_failed": "No se pudo eliminar el documento.",
        "extracted_data_title": "Datos extraídos",
        "extracted_data_none": "No hay datos OCR guardados para este documento.",
        "batch_run_ocr": "Ejecutar OCR en tipos de documento compatibles",
        "batch_uploaded_ocr": "Cargado + OCR",
        "batch_uploaded": "Cargado",
        "batch_ocr_skipped": "OCR omitido",
        "export_passport_exp": "Vencimiento pasaporte",
        "export_interpol_appt": "Cita Interpol",
        "export_biometric_appt": "Cita biométrica",
        "export_pickup_appt": "Cita recojo",
        "export_menu": "Exportar",
        "export_columns": "Exportar columnas",
        "export_full": "Exportaci\u00f3n completa",
        "export_select_group_title": "Seleccionar grupo",
        "export_select_group_message": "Elija un grupo antes de hacer una exportaci\u00f3n completa.",
        "export_full_dialog_title": "Exportaci\u00f3n completa",
        "export_complete_title": "Exportaci\u00f3n completada",
        "export_failed_title": "Error de exportaci\u00f3n",
        "export_failed_message": "No se pudo exportar. Revise los registros para m\u00e1s detalles.",
        "export_full_complete_message": (
            "Se exportaron {count} misioneros a:\n{path}"
        ),
        "export_full_missing_folders": (
            "Estos misioneros no ten\u00edan una carpeta de documentos para copiar:"
        ),
        "passport_number": "Número de pasaporte",
        "full_name": "Nombre completo",
        "date_of_birth": "Fecha de nacimiento",
        "nationality": "Nacionalidad",
        "passport_expiration": "Vencimiento pasaporte",
        "arrival_date": "Fecha de llegada",
        "visa_expiration": "Vencimiento visa",
        "tramite_usuario": "Usuario del trámite",
        "tramite_contrasena": "Contraseña del trámite",
        "interpol_appointment_date": "Cita Interpol",
        "biometric_appointment_date": "Cita biométrica",
        "pickup_appointment_date": "Cita recojo",
        "carnet_number": "Número carnet",
        "carnet_issue_date": "Fecha emisión carnet",
        "residency_expiration": "Vencimiento residencia",
        "prorroga_expiration": "Vencimiento prórroga",
        "cancelacion_date": "Fecha cancelación",
    },
}


class I18nManager(QObject):
    language_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self._language = "en"

    def set_language(self, lang):
        if lang in TRANSLATIONS:
            self._language = lang
            self.language_changed.emit(lang)

    def get_language(self):
        return self._language

    def tr(self, key, **kwargs):
        text = TRANSLATIONS.get(self._language, TRANSLATIONS["en"]).get(
            key,
            TRANSLATIONS["en"].get(key, key),
        )
        if kwargs:
            try:
                return text.format(**kwargs)
            except (KeyError, ValueError):
                return text
        return text


_i18n = I18nManager()


def get_i18n():
    return _i18n


def tr(key, **kwargs):
    return _i18n.tr(key, **kwargs)


def field_label(field_key):
    return tr(field_key)
