"""Data contracts shared by packet definitions and the printing pipeline."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable


class PrintOutputMode(str, Enum):
    OPEN_PREVIEW = "open_preview"
    SAVE_AS = "save_as"
    DIRECT_PRINT = "direct_print"


class PrintStatus(str, Enum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NOTHING_TO_PRINT = "nothing_to_print"
    PREPARATION_FAILED = "preparation_failed"
    OUTPUT_FAILED = "output_failed"


@dataclass(frozen=True)
class PacketDocumentRule:
    document_type: str
    required: bool = True
    condition: Callable[[object], bool] | None = None
    transform_key: str | None = None

    def applies_to(self, missionary) -> bool:
        return self.condition is None or bool(self.condition(missionary))


@dataclass(frozen=True)
class PacketDefinition:
    key: str
    filename_prefix: str
    documents: tuple[PacketDocumentRule, ...]


@dataclass(frozen=True)
class PreparedDocument:
    record: object
    document_type: str
    label: str
    local_path: Path
    transform_key: str | None = None


@dataclass
class PreparedPrintJob:
    job_name: str
    filename_prefix: str
    missionary: object | None = None
    documents: list[PreparedDocument] = field(default_factory=list)
    missing_documents: list[str] = field(default_factory=list)
    unavailable_documents: list[str] = field(default_factory=list)
    context: dict = field(default_factory=dict)


@dataclass
class PrintResult:
    status: PrintStatus
    output_path: Path | None = None
    missing_documents: tuple[str, ...] = ()
    unavailable_documents: tuple[str, ...] = ()
    error: Exception | None = None
