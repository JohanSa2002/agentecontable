"""Pipeline de extracción en cascada (spec §4).

Fase 0: solo enruta y devuelve una factura vacía con el camino elegido, para que
`evaluate.py` tenga algo que medir desde el día uno. Los extractores reales
(QR/CUFE, LLM sobre texto, visión) se implementan en la Fase 1.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentecontable.extraction.router import RoutedDocument, route
from agentecontable.models import ExtractionPath, Invoice


@dataclass
class ExtractionResult:
    invoice: Invoice
    extraction_path: ExtractionPath
    # Trazabilidad (spec §9): se guarda siempre, aunque sea un stub
    raw_extraction: dict[str, Any] = field(default_factory=dict)
    ocr_provider: str | None = None
    model_version: str | None = None
    prompt_version: str | None = None
    tokens_used: int = 0
    processing_ms: int = 0


def _extract_from_qr(doc: RoutedDocument) -> tuple[Invoice, dict[str, Any]]:
    # TODO Fase 1: parsear URL de DGI / CUFE y consultar la FE
    return Invoice(), {"stub": True, "qr_payload": doc.qr_payload}


def _extract_from_text(doc: RoutedDocument) -> tuple[Invoice, dict[str, Any]]:
    # TODO Fase 1: client.messages.parse(output_format=Invoice) sobre doc.pdf_text
    return Invoice(), {"stub": True, "text_chars": len(doc.pdf_text or "")}


def _extract_from_vision(doc: RoutedDocument) -> tuple[Invoice, dict[str, Any]]:
    # TODO Fase 1: visión sobre doc.page_images (dos pasadas para confianza derivada, §5)
    return Invoice(), {"stub": True, "pages": len(doc.page_images)}


_EXTRACTORS = {
    ExtractionPath.QR: _extract_from_qr,
    ExtractionPath.PDF_TEXT: _extract_from_text,
    ExtractionPath.VISION: _extract_from_vision,
}


def extract(path: str | Path) -> ExtractionResult:
    t0 = time.perf_counter()
    doc = route(path)
    invoice, raw = _EXTRACTORS[doc.route](doc)
    return ExtractionResult(
        invoice=invoice,
        extraction_path=doc.route,
        raw_extraction=raw,
        processing_ms=int((time.perf_counter() - t0) * 1000),
    )
