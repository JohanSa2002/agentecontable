"""Modelo canónico de una factura.

Cumple tres funciones a la vez:
  1. Formato del ground truth en dataset/ground_truth/*.json
  2. `output_format` que se le pasa a Claude en la extracción
  3. Entrada de la validación aritmética (Fase 6)

Los nombres de campo coinciden con las columnas de `invoices` en la spec
(instrucciones-v1.md §11) para que el mapeo a BD sea directo.
Todos los montos son Decimal con 2 decimales. Nunca float.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Any, ClassVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

CENT = Decimal("0.01")


def _to_monto(v: Any) -> Decimal | None:
    """Acepta número, string ("107.00", "B/. 1,234.50") o None y devuelve Decimal a 2 decimales."""
    if v is None or v == "":
        return None
    if isinstance(v, float):
        # Un float ya perdió precisión; lo pasamos por str para no arrastrar 0.1+0.2
        v = repr(v)
    if isinstance(v, str):
        limpio = v.replace("B/.", "").replace("$", "").replace(",", "").replace(" ", "")
        if limpio == "":
            return None
        v = limpio
    try:
        return Decimal(v).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError) as e:
        raise ValueError(f"monto inválido: {v!r}") from e


Monto = Annotated[Decimal | None, BeforeValidator(_to_monto)]


class DocumentType(StrEnum):
    FACTURA = "FACTURA"
    NOTA_CREDITO = "NOTA_CREDITO"
    RECIBO = "RECIBO"


class ExtractionPath(StrEnum):
    QR = "qr"
    PDF_TEXT = "pdf_text"
    VISION = "vision"


class InvoiceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(description="Descripción del ítem tal como aparece")
    quantity: Monto = Field(default=None, description="Cantidad")
    unit_price: Monto = Field(default=None, description="Precio unitario sin impuesto")
    total: Monto = Field(default=None, description="Total de la línea")
    exempt: bool = Field(default=False, description="True si el ítem está exento de ITBMS")


class Invoice(BaseModel):
    """Datos contables de una factura panameña."""

    model_config = ConfigDict(extra="forbid")

    document_type: DocumentType = Field(default=DocumentType.FACTURA)

    # Proveedor
    supplier_name: str | None = Field(default=None, description="Razón social del emisor")
    supplier_ruc: str | None = Field(
        default=None, description="RUC del emisor, ej. 155612345-2-2019 o 8-123-4567"
    )
    supplier_dv: str | None = Field(default=None, description="Dígito verificador del RUC")

    # Identificación
    invoice_number: str | None = Field(default=None, description="Número de factura")
    issue_date: date | None = Field(default=None, description="Fecha de emisión")
    cufe: str | None = Field(default=None, description="CUFE si es factura electrónica")
    currency: str = Field(default="PAB", description="PAB o USD (en Panamá son equivalentes)")

    # Montos — en notas de crédito se registran en negativo
    subtotal: Monto = None
    discount: Monto = None
    exempt_amount: Monto = Field(default=None, description="Base exenta de ITBMS")
    itbms: Monto = None
    isc: Monto = Field(default=None, description="Impuesto selectivo al consumo")
    tip: Monto = Field(default=None, description="Propina (restaurantes)")
    other_charges: Monto = None
    retencion_itbms: Monto = None
    total: Monto = None

    items: list[InvoiceItem] = Field(default_factory=list)

    # Campos críticos según la spec (§1): exactitud ≥ 95 %
    CRITICAL_FIELDS: ClassVar[tuple[str, ...]] = (
        "supplier_ruc",
        "invoice_number",
        "issue_date",
        "total",
    )

    def expected_total(self) -> Decimal | None:
        """Fórmula real de la spec §6. None si no hay subtotal."""
        if self.subtotal is None:
            return None
        z = Decimal("0.00")
        return (
            self.subtotal
            - (self.discount or z)
            + (self.itbms or z)
            + (self.isc or z)
            + (self.tip or z)
            + (self.other_charges or z)
        )
