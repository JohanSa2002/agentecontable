import cv2
import numpy as np
import pymupdf
import pytest

from agentecontable.extraction.pipeline import extract
from agentecontable.extraction.router import route, sniff_mime
from agentecontable.models import ExtractionPath

QR_URL = "https://dgi-fep.mef.gob.pa/Consultas/FacturasPorCUFE?CUFE=FE0120000-TEST"


def _qr_png(text: str, size: int = 300) -> bytes:
    img = cv2.QRCodeEncoder.create().encode(text)
    img = cv2.resize(img, (size, size), interpolation=cv2.INTER_NEAREST)
    # margen blanco: el detector lo necesita
    img = cv2.copyMakeBorder(img, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=255)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


@pytest.fixture
def pdf_con_texto(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "FACTURA No. F001-00123\nRUC 155612345-2-2019\nTOTAL B/. 107.00")
    p = tmp_path / "texto.pdf"
    doc.save(p)
    return p


@pytest.fixture
def pdf_con_qr(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "FACTURA ELECTRONICA " * 5)
    page.insert_image(pymupdf.Rect(72, 120, 300, 348), stream=_qr_png(QR_URL))
    p = tmp_path / "qr.pdf"
    doc.save(p)
    return p


@pytest.fixture
def pdf_escaneado(tmp_path):
    # Solo una imagen gris, sin texto ni QR: simula un escaneo
    doc = pymupdf.open()
    page = doc.new_page()
    gris = np.full((200, 200, 3), 200, dtype=np.uint8)
    ok, buf = cv2.imencode(".png", gris)
    page.insert_image(pymupdf.Rect(72, 72, 272, 272), stream=buf.tobytes())
    p = tmp_path / "escaneado.pdf"
    doc.save(p)
    return p


@pytest.fixture
def foto_sin_qr(tmp_path):
    img = np.full((400, 300, 3), 230, dtype=np.uint8)
    p = tmp_path / "foto.jpg"
    cv2.imwrite(str(p), img)
    return p


@pytest.fixture
def foto_con_qr(tmp_path):
    p = tmp_path / "fe.png"
    p.write_bytes(_qr_png(QR_URL))
    return p


def test_mime_por_magic_bytes_no_por_extension(tmp_path, pdf_con_texto):
    disfrazado = tmp_path / "factura.jpg"
    disfrazado.write_bytes(pdf_con_texto.read_bytes())
    assert sniff_mime(disfrazado.read_bytes()) == "application/pdf"
    assert route(disfrazado).route == ExtractionPath.PDF_TEXT


def test_pdf_con_texto_va_por_pdf_text(pdf_con_texto):
    doc = route(pdf_con_texto)
    assert doc.route == ExtractionPath.PDF_TEXT
    assert "F001-00123" in doc.pdf_text
    assert doc.page_images == []


def test_pdf_con_qr_va_por_qr_aunque_tenga_texto(pdf_con_qr):
    doc = route(pdf_con_qr)
    assert doc.route == ExtractionPath.QR
    assert doc.qr_payload == QR_URL


def test_pdf_escaneado_va_por_vision_con_paginas(pdf_escaneado):
    doc = route(pdf_escaneado)
    assert doc.route == ExtractionPath.VISION
    assert len(doc.page_images) == 1


def test_foto_sin_qr_va_por_vision(foto_sin_qr):
    doc = route(foto_sin_qr)
    assert doc.route == ExtractionPath.VISION
    assert doc.mime == "image/jpeg"


def test_foto_con_qr_va_por_qr(foto_con_qr):
    doc = route(foto_con_qr)
    assert doc.route == ExtractionPath.QR
    assert doc.qr_payload == QR_URL


def test_archivo_no_soportado(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("hola")
    with pytest.raises(ValueError, match="no soportado"):
        route(p)


def test_extract_stub_devuelve_trazabilidad(pdf_con_texto):
    r = extract(pdf_con_texto)
    assert r.extraction_path == ExtractionPath.PDF_TEXT
    assert r.raw_extraction["stub"] is True
    assert r.processing_ms >= 0
