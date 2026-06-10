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
        "passport_number": "Passport Number",
        "full_name": "Full Name",
        "date_of_birth": "Date of Birth",
        "nationality": "Nationality",
        "passport_expiration": "Passport Expiration",
        "arrival_date": "Arrival Date",
        "visa_expiration": "Visa Expiration",
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
        "passport_number": "Número de pasaporte",
        "full_name": "Nombre completo",
        "date_of_birth": "Fecha de nacimiento",
        "nationality": "Nacionalidad",
        "passport_expiration": "Vencimiento pasaporte",
        "arrival_date": "Fecha de llegada",
        "visa_expiration": "Vencimiento visa",
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
