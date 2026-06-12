# ==========================================
# WORKFLOW STATUS OPTIONS
# ==========================================

WORKFLOW_STATUSES = [
    "NOT STARTED",
    "IN PROGRESS",
    "WAITING",
    "COMPLETED",
    "BLOCKED",
]


# ==========================================
# CORE WORKFLOW STAGES
# ==========================================

WORKFLOW_STAGES = [
    "INTERPOL",
    "CARNET DE EXTRANJERIA",
    "PRORROGA",
    "CANCELACION",
]


# ==========================================
# DOCUMENT TYPE DEFINITIONS
# ==========================================
#
# Structure:
#
# "DOCUMENT_CODE": {
#     "label": Human readable label,
#     "stage": Which workflow stage it belongs to,
#     "required": Whether required for completion,
#     "ocr_fields": Fields OCR should attempt to extract,
#     "auto_updates": Missionary fields automatically updated,
# }
#
# This structure is future-proofed for:
# - OCR
# - AI extraction
# - auto-complete workflows
# - dashboard statistics
# - validation rules
# - reminders
# - missing document detection
# - future APIs
#
# ==========================================

DOCUMENTS = {

    # ======================================
    # GENERAL
    # ======================================

    "PHOTO": {
        "label": "Missionary Photo",
        "stage": None,
        "required": False,
        "ocr_fields": [],
        "auto_updates": [],
    },

    "PASSPORT": {
        "label": "Passport",
        "stage": None,
        "required": True,
        "ocr_fields": [
            "passport_number",
            "full_name",
            "date_of_birth",
            "nationality",
            "passport_expiration",
        ],
        "auto_updates": [
            "passport_number",
            "nationality",
            "passport_expiration",
        ],
    },

    "FBI": {
        "label": "FBI",
        "stage": "INTERPOL",
        "required": False,
        "ocr_fields": [],
        "auto_updates": [],
    },

    "TAM": {
        "label": "TAM",
        "stage": "INTERPOL",
        "required": True,
        "ocr_fields": [
            "arrival_date",
        ],
        "auto_updates": [
            "arrival_date",
        ],
    },

    # ======================================
    # INTERPOL
    # ======================================

    "PAGO_INTERPOL": {
        "label": "Pago Interpol",
        "stage": "INTERPOL",
        "required": True,
        "ocr_fields": [],
        "auto_updates": [],
    },

    "CONSTANCIA_DE_CITA_INTERPOL": {
        "label": "Constancia de Cita Interpol",
        "stage": "INTERPOL",
        "required": True,
        "ocr_fields": [
            "interpol_appointment_date",
        ],
        "auto_updates": [
            "interpol_appointment_date",
        ],
    },

    "FICHA_DE_CANJE_INTERNACIONAL": {
        "label": "Ficha de Canje Internacional",
        "stage": "INTERPOL",
        "required": True,
        "ocr_fields": [],
        "auto_updates": [],
    },

    # ======================================
    # CARNET DE EXTRANJERIA
    # ======================================

    "PAGO_CARNE_DE_EXTRANJERIA": {
        "label": "Pago Carné de Extranjería",
        "stage": "CARNET DE EXTRANJERIA",
        "required": True,
        "ocr_fields": [],
        "auto_updates": [],
    },

    "CONSTANCIA_DE_CITA_BIOMETRICO": {
        "label": "Constancia de Cita Biométrico",
        "stage": "CARNET DE EXTRANJERIA",
        "required": True,
        "ocr_fields": [
            "biometric_appointment_date",
        ],
        "auto_updates": [
            "biometric_appointment_date",
        ],
    },

    "CONSTANCIA_DE_TRAMITE_CARNE_DE_EXTRANJERIA": {
        "label": (
            "Constancia de Trámite "
            "Carné de Extranjería"
        ),
        "stage": "CARNET DE EXTRANJERIA",
        "required": True,
        "ocr_fields": [
            "tramite_usuario",
            "tramite_contrasena",
        ],
        "auto_updates": [
            "tramite_usuario",
            "tramite_contrasena",
        ],
    },

    "CITA_RECOJO": {
        "label": "Cita Recojo",
        "stage": "CARNET DE EXTRANJERIA",
        "required": True,
        "ocr_fields": [
            "pickup_appointment_date",
        ],
        "auto_updates": [
            "pickup_appointment_date",
        ],
    },

    "CARNE_DE_EXTRANJERIA": {
        "label": "Carné de Extranjería",
        "stage": "CARNET DE EXTRANJERIA",
        "required": True,
        "ocr_fields": [
            "carnet_number",
            "carnet_issue_date",
        ],
        "auto_updates": [
            "carnet_issue_date",
        ],
    },

    # ======================================
    # PRORROGA
    # ======================================

    "PAGO_PRORROGA": {
        "label": "Pago Prórroga",
        "stage": "PRORROGA",
        "required": True,
        "ocr_fields": [],
        "auto_updates": [],
    },

    "CARTA_MINJUS": {
        "label": "Carta MINJUS",
        "stage": "PRORROGA",
        "required": True,
        "ocr_fields": [],
        "auto_updates": [],
    },

    "DECLARACION_JURADA": {
        "label": "Declaración Jurada",
        "stage": "PRORROGA",
        "required": True,
        "ocr_fields": [],
        "auto_updates": [],
    },

    "CONSTANCIA_DE_PRORROGA": {
        "label": "Constancia de Prórroga",
        "stage": "PRORROGA",
        "required": False,
        "ocr_fields": [],
        "auto_updates": [],
    },

    "APROBACION_DE_PRORROGA": {
        "label": "Aprobación de Prórroga",
        "stage": "PRORROGA",
        "required": True,
        "ocr_fields": [
            "prorroga_expiration",
        ],
        "auto_updates": [
            "prorroga_expiration",
        ],
    },

    # ======================================
    # CANCELACION
    # ======================================

    "PAGO_CANCELACION_DE_RESIDENCIA": {
        "label": "Pago Cancelación de Residencia",
        "stage": "CANCELACION",
        "required": True,
        "ocr_fields": [],
        "auto_updates": [],
    },

    "CONSTANCIA_CANCELACION": {
        "label": "Constancia Cancelación",
        "stage": "CANCELACION",
        "required": True,
        "ocr_fields": [
            "cancelacion_date",
        ],
        "auto_updates": [
            "cancelacion_date",
        ],
    },

    # ======================================
    # FALLBACK
    # ======================================

    "OTHER": {
        "label": "Other",
        "stage": None,
        "required": False,
        "ocr_fields": [],
        "auto_updates": [],
    },
}


# ==========================================
# COMPATIBILITY HELPERS
# ==========================================
#
# These prevent you from having to rewrite
# older parts of your code immediately.
#
# You can gradually migrate everything
# to use DOCUMENTS later.
#
# ==========================================

DOCUMENT_TYPES = list(
    DOCUMENTS.keys()
)


WORKFLOW_REQUIREMENTS = {
    stage: [
        document_key
        for document_key, config
        in DOCUMENTS.items()
        if (
            config["stage"] == stage
            and config["required"]
        )
    ]
    for stage in WORKFLOW_STAGES
}


def is_usa_missionary(missionary):
    return (getattr(missionary, "nationality", None) or "").strip() == "USA"


def visible_document_keys_for_missionary(missionary):
    return [
        document_key
        for document_key in DOCUMENTS
        if document_key != "FBI" or is_usa_missionary(missionary)
    ]


def required_documents_for_missionary(stage, missionary):
    required = list(WORKFLOW_REQUIREMENTS.get(stage, []))
    if stage == "INTERPOL" and is_usa_missionary(missionary):
        required.append("FBI")
    return list(dict.fromkeys(required))


# ==========================================
# OCR FIELD DEFINITIONS
# ==========================================
#
# Central location for future OCR mapping.
#
# ==========================================

OCR_FIELDS = [
    "passport_number",
    "full_name",
    "date_of_birth",
    "nationality",
    "passport_expiration",
    "arrival_date",
    "interpol_appointment_date",
    "biometric_appointment_date",
    "pickup_appointment_date",
    "carnet_number",
    "carnet_issue_date",
    "residency_expiration",
    "prorroga_expiration",
    "cancelacion_date",
    "visa_expiration",
    "tramite_usuario",
    "tramite_contrasena",
]


# Date fields that OCR / manual save can update on Missionary
MISSIONARY_DATE_FIELDS = [
    "arrival_date",
    "visa_expiration",
    "passport_expiration",
    "residency_expiration",
    "prorroga_expiration",
    "carnet_issue_date",
    "cancelacion_date",
    "interpol_appointment_date",
    "biometric_appointment_date",
    "pickup_appointment_date",
]
