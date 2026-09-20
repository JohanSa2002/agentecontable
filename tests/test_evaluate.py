from datetime import date
from decimal import Decimal

from agentecontable.evaluate import GroundTruth, InvoiceEval, summarize, values_match


def test_none_vs_none_coincide():
    assert values_match("discount", None, None)


def test_none_vs_valor_no_coincide():
    assert not values_match("total", Decimal("1.00"), None)
    assert not values_match("total", None, Decimal("1.00"))


def test_decimal_exacto():
    assert values_match("total", Decimal("107.00"), Decimal("107.00"))
    assert not values_match("total", Decimal("107.00"), Decimal("107.01"))


def test_fecha():
    assert values_match("issue_date", date(2026, 9, 15), date(2026, 9, 15))
    assert not values_match("issue_date", date(2026, 9, 15), date(2026, 9, 16))


def test_ruc_ignora_espacios_y_guiones():
    assert values_match("supplier_ruc", "155612345-2-2019", "155612345 - 2 - 2019")
    assert values_match("supplier_ruc", "8-123-4567", "81234567")
    assert not values_match("supplier_ruc", "8-123-4567", "8-123-4568")


def test_numero_factura_ignora_separadores_y_mayusculas():
    assert values_match("invoice_number", "F001-00123", "f001 00123")
    assert values_match("invoice_number", "F001-00123", "F001/00123")
    assert not values_match("invoice_number", "F001-00123", "F001-00124")


def test_texto_ignora_espacios_multiples_y_case():
    assert values_match(
        "supplier_name", "Restaurante  El Trapiche S.A.", "restaurante el trapiche s.a."
    )


def test_ground_truth_parsea_ejemplo_del_readme():
    gt = GroundTruth.model_validate(
        {
            "meta": {"source": "restaurante_propina"},
            "invoice": {
                "supplier_ruc": "155612345-2-2019",
                "invoice_number": "F001-00123",
                "issue_date": "2026-09-15",
                "subtotal": "100.00",
                "itbms": "7.00",
                "tip": "10.00",
                "total": "117.00",
                "items": [
                    {
                        "description": "Sancocho",
                        "quantity": "2",
                        "unit_price": "12.50",
                        "total": "25.00",
                    }
                ],
            },
        }
    )
    assert gt.invoice.total == Decimal("117.00")
    assert gt.invoice.expected_total() == Decimal("117.00")


def test_summarize_metricas_principales():
    ok = InvoiceEval(
        id="a",
        source="fe_qr",
        extraction_path="qr",
        fields_ok={"supplier_ruc": True, "invoice_number": True, "issue_date": True, "total": True},
    )
    mal = InvoiceEval(
        id="b",
        source="foto_celular",
        extraction_path="vision",
        fields_ok={
            "supplier_ruc": True,
            "invoice_number": False,
            "issue_date": True,
            "total": True,
        },
    )
    con_error = InvoiceEval(id="c", source="otro", extraction_path=None, error="boom")

    s = summarize([ok, mal, con_error])
    assert s["invoices_total"] == 3
    assert s["invoices_evaluated"] == 2
    assert s["invoices_with_error"] == 1
    assert s["approved_without_correction_pct"] == 50.0
    assert s["critical_fields_pct"] == 87.5  # 7 de 8
    assert s["by_extraction_path"]["qr"] == {"total": 1, "all_ok": 1}
    assert s["by_extraction_path"]["vision"] == {"total": 1}
    assert s["sources"] == {"fe_qr": 1, "foto_celular": 1, "otro": 1}
