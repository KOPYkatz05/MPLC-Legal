"""Declarative definitions for printable document packets."""

from services.printing_models import PacketDefinition, PacketDocumentRule
from utils.constants import requires_fbi_document


INTERPOL_PACKET = PacketDefinition(
    key="INTERPOL",
    filename_prefix="interpol_packet",
    documents=(
        PacketDocumentRule("TAM"),
        PacketDocumentRule("PASSPORT", transform_key="interpol_passport"),
        PacketDocumentRule("FBI", condition=requires_fbi_document),
        PacketDocumentRule("PAGO_INTERPOL"),
        PacketDocumentRule("CONSTANCIA_DE_CITA_INTERPOL"),
    ),
)


PACKET_DEFINITIONS = {
    INTERPOL_PACKET.key: INTERPOL_PACKET,
}


def get_packet_definition(packet_key):
    key = str(packet_key or "").strip().upper()
    try:
        return PACKET_DEFINITIONS[key]
    except KeyError as error:
        raise ValueError(f"Unknown print packet: {packet_key}") from error

