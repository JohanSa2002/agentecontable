"""Decide por qué camino de la cascada se procesa un documento (spec §4).

Orden: QR de factura electrónica → PDF con capa de texto → visión.
Solo detecta y prepara la entrada; no llama a ningún modelo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import filetype
import numpy as np
import pymupdf

from agentecontable.models import ExtractionPath

# Un PDF "con texto" tiene que aportar algo más que ruido de OCR previo o metadatos.
MIN_TEXT_CHARS = 40
# DPI al rasterizar un PDF para buscar QR o mandarlo a visión.
RENDER_DPI = 150


@dataclass
class RoutedDocument:
    path: Path
    mime: str
    route: ExtractionPath
    qr_payload: str | None = None
    pdf_text: str | None = None
    # Imágenes (PNG bytes) por página, listas para visión. Vacío si la ruta no las necesita.
    page_images: list[bytes] = field(default_factory=list)


def sniff_mime(data: bytes) -> str | None:
    """MIME real por magic bytes, nunca por extensión (spec §13)."""
    kind = filetype.guess(data)
    return kind.mime if kind else None


def decode_qr(image_bgr: np.ndarray) -> str | None:
    """Devuelve el contenido del primer QR legible o None."""
    detector = cv2.QRCodeDetector()
    data, _points, _ = detector.detectAndDecode(image_bgr)
    if data:
        return data
    # Segundo intento sobre escala de gris con umbral: ayuda en fotos con sombra.
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    data, _points, _ = detector.detectAndDecode(thresh)
    return data or None


def _pdf_pages_to_images(doc: pymupdf.Document, dpi: int = RENDER_DPI) -> list[bytes]:
    return [page.get_pixmap(dpi=dpi).tobytes("png") for page in doc]


def _png_to_bgr(png: bytes) -> np.ndarray:
    arr = np.frombuffer(png, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def route(path: str | Path) -> RoutedDocument:
    path = Path(path)
    data = path.read_bytes()
    mime = sniff_mime(data)

    if mime == "application/pdf":
        doc = pymupdf.open(stream=data, filetype="pdf")
        text = "\n".join(page.get_text() for page in doc).strip()
        images = _pdf_pages_to_images(doc)

        for png in images:
            if payload := decode_qr(_png_to_bgr(png)):
                return RoutedDocument(
                    path,
                    mime,
                    ExtractionPath.QR,
                    qr_payload=payload,
                    pdf_text=text or None,
                    page_images=images,
                )

        if len(text) >= MIN_TEXT_CHARS:
            return RoutedDocument(path, mime, ExtractionPath.PDF_TEXT, pdf_text=text)

        return RoutedDocument(path, mime, ExtractionPath.VISION, page_images=images)

    if mime in ("image/jpeg", "image/png", "image/webp"):
        img = _png_to_bgr(data)  # imdecode acepta cualquier formato soportado
        if img is None:
            raise ValueError(f"No se pudo decodificar la imagen: {path}")
        if payload := decode_qr(img):
            return RoutedDocument(
                path, mime, ExtractionPath.QR, qr_payload=payload, page_images=[data]
            )
        return RoutedDocument(path, mime, ExtractionPath.VISION, page_images=[data])

    raise ValueError(f"Tipo de archivo no soportado ({mime}): {path}")
