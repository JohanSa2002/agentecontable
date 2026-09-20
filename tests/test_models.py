from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from agentecontable.models import DocumentType, Invoice, InvoiceItem


def test_montos_se_normalizan_a_dos_decimales():
    inv = Invoice(subtotal="100", itbms=7, total="B/. 1,234.567")
    assert inv.subtotal == Decimal("100.00")
    assert inv.itbms == Decimal("7.00")
    assert inv.total == Decimal("1234.57")
    assert isinstance(inv.total, Decimal)


def test_float_no_arrastra_error_de_precision():
    inv = Invoice(total=0.1 + 0.2)
    assert inv.total == Decimal("0.30")


def test_monto_vacio_es_none_no_cero():
    inv = Invoice(discount="", tip=None)
    assert inv.discount is None
    assert inv.tip is None


def test_monto_invalido_falla():
    with pytest.raises(ValidationError):
        Invoice(total="ciento siete")


def test_expected_total_formula_real():
    inv = Invoice(
        subtotal="100.00", discount="10.00", itbms="6.30", tip="9.00", other_charges="0.50"
    )
    assert inv.expected_total() == Decimal("105.80")


def test_expected_total_sin_subtotal_es_none():
    assert Invoice(total="10.00").expected_total() is None


def test_nota_credito_en_negativo():
    inv = Invoice(
        document_type=DocumentType.NOTA_CREDITO, subtotal="-50.00", itbms="-3.50", total="-53.50"
    )
    assert inv.expected_total() == inv.total


def test_campos_desconocidos_se_rechazan():
    with pytest.raises(ValidationError):
        Invoice(total="1.00", campo_inventado=1)


def test_fecha_iso():
    inv = Invoice(issue_date="2026-09-15")
    assert inv.issue_date == date(2026, 9, 15)


def test_items():
    inv = Invoice(
        items=[{"description": "Sancocho", "quantity": "2", "unit_price": "12.5", "total": "25"}]
    )
    assert inv.items[0] == InvoiceItem(
        description="Sancocho",
        quantity=Decimal("2.00"),
        unit_price=Decimal("12.50"),
        total=Decimal("25.00"),
    )


def test_critical_fields_son_los_de_la_spec():
    assert set(Invoice.CRITICAL_FIELDS) == {"supplier_ruc", "invoice_number", "issue_date", "total"}
