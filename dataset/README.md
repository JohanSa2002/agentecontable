# Dataset de evaluación (Fase 0)

Sin esto, cada cambio de prompt es a ciegas. Meta: 50–100 facturas panameñas.

## Convención

```
dataset/
  facturas/       <id>.jpg | .png | .pdf     ← la factura. IGNORADO POR GIT.
  ground_truth/   <id>.json                  ← la verdad, escrita a mano. Sí va al repo.
  results/        <timestamp>.json           ← salida de evaluate.py. Ignorado por git.
```

El `<id>` une factura y ground truth. Usar ids descriptivos: `001-fe-qr-supermercado`,
`002-foto-inclinada-restaurante`.

## Formato del ground truth

```json
{
  "meta": {
    "source": "restaurante_propina",
    "notes": "foto con sombra en la esquina inferior"
  },
  "invoice": {
    "document_type": "FACTURA",
    "supplier_name": "Restaurante El Trapiche S.A.",
    "supplier_ruc": "155612345-2-2019",
    "supplier_dv": "45",
    "invoice_number": "F001-00123",
    "issue_date": "2026-09-15",
    "cufe": null,
    "currency": "PAB",
    "subtotal": "100.00",
    "discount": null,
    "exempt_amount": null,
    "itbms": "7.00",
    "isc": null,
    "tip": "10.00",
    "other_charges": null,
    "retencion_itbms": null,
    "total": "117.00",
    "items": [
      {"description": "Sancocho", "quantity": "2", "unit_price": "12.50", "total": "25.00", "exempt": false}
    ]
  }
}
```

Reglas:
- Montos como **string** con dos decimales (`"107.00"`), nunca número JSON.
- Campo que no aparece en la factura → `null`. No inventar ceros.
- Notas de crédito: montos en **negativo**.
- Transcribir tal cual está impreso; la normalización (espacios, guiones, mayúsculas) la hace `evaluate.py`.
- `items` puede quedar vacío `[]` si la factura no detalla líneas; se compara solo la cantidad de líneas.

## Valores de `meta.source`

Cada uno debe estar representado al menos una vez (spec §3):

| source | qué es |
|---|---|
| `fe_qr` | factura electrónica con QR legible |
| `pdf_texto` | PDF con capa de texto |
| `foto_celular` | foto normal |
| `foto_inclinada` | foto en ángulo |
| `foto_borrosa` | foto desenfocada o con poca luz |
| `ticket_supermercado` | ticket térmico largo |
| `restaurante_propina` | con propina |
| `nota_credito` | montos negativos |
| `con_descuento` | descuento explícito |
| `items_exentos` | ítems sin ITBMS |
| `otro` | lo que no encaje |

## Correr la evaluación

```bash
uv run python -m agentecontable.evaluate
uv run python -m agentecontable.evaluate --only foto
```
