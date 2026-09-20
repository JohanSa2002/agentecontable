"""Corre el pipeline sobre el dataset y reporta exactitud por campo (spec §3).

Uso:
    uv run python -m agentecontable.evaluate            # todo el dataset
    uv run python -m agentecontable.evaluate --only foto # solo facturas cuyo nombre contenga "foto"

Convención del dataset:
    dataset/facturas/<id>.<jpg|png|pdf>      la factura
    dataset/ground_truth/<id>.json           su verdad, formato: {"meta": {...}, "invoice": {...}}

El resultado se imprime en consola y se guarda en dataset/results/<timestamp>.json
para poder comparar corridas entre cambios de prompt.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agentecontable.extraction.pipeline import extract
from agentecontable.models import Invoice

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "dataset"
FACTURAS = DATASET / "facturas"
GROUND_TRUTH = DATASET / "ground_truth"
RESULTS = DATASET / "results"

# Campos que se comparan uno a uno. `items` se compara aparte por cantidad de líneas.
SCALAR_FIELDS = [
    "document_type",
    "supplier_name",
    "supplier_ruc",
    "supplier_dv",
    "invoice_number",
    "issue_date",
    "cufe",
    "subtotal",
    "discount",
    "exempt_amount",
    "itbms",
    "isc",
    "tip",
    "other_charges",
    "retencion_itbms",
    "total",
]


class GroundTruthMeta(BaseModel):
    """Describe el origen para medir diversidad del dataset (spec §3)."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(
        description=(
            "fe_qr | pdf_texto | foto_celular | foto_inclinada | foto_borrosa | "
            "ticket_supermercado | restaurante_propina | nota_credito | con_descuento | "
            "items_exentos | otro"
        )
    )
    notes: str | None = None


class GroundTruth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meta: GroundTruthMeta
    invoice: Invoice


# --- Normalización para comparar -------------------------------------------------


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().casefold()


def _norm_ruc(s: str) -> str:
    # Los RUC se escriben con y sin espacios, a veces con guiones distintos
    return re.sub(r"[\s\-–]", "", s).upper()


def _norm_number(s: str) -> str:
    # "F001-00123" vs "F001 00123" vs "f001-00123": misma factura
    return re.sub(r"[\s\-_/]", "", s).upper()


def values_match(field_name: str, expected: Any, got: Any) -> bool:
    if expected is None and got is None:
        return True
    if expected is None or got is None:
        return False
    if isinstance(expected, Decimal):
        return expected == got
    if isinstance(expected, date):
        return expected == got
    e, g = str(expected), str(got)
    if field_name == "supplier_ruc":
        return _norm_ruc(e) == _norm_ruc(g)
    if field_name == "invoice_number":
        return _norm_number(e) == _norm_number(g)
    return _norm_text(e) == _norm_text(g)


# --- Evaluación ------------------------------------------------------------------


@dataclass
class InvoiceEval:
    id: str
    source: str
    extraction_path: str | None
    fields_ok: dict[str, bool] = field(default_factory=dict)
    items_expected: int = 0
    items_got: int = 0
    error: str | None = None
    processing_ms: int = 0

    @property
    def all_ok(self) -> bool:
        return (
            self.error is None
            and all(self.fields_ok.values())
            and (self.items_expected == self.items_got)
        )


def find_invoice_file(invoice_id: str) -> Path | None:
    for ext in ("pdf", "jpg", "jpeg", "png", "webp"):
        p = FACTURAS / f"{invoice_id}.{ext}"
        if p.exists():
            return p
    return None


def evaluate_one(gt_path: Path) -> InvoiceEval:
    gt = GroundTruth.model_validate_json(gt_path.read_text(encoding="utf-8"))
    invoice_id = gt_path.stem
    ev = InvoiceEval(id=invoice_id, source=gt.meta.source, extraction_path=None)

    file = find_invoice_file(invoice_id)
    if file is None:
        ev.error = "falta el archivo de la factura en dataset/facturas/"
        return ev

    try:
        result = extract(file)
    except Exception:
        ev.error = traceback.format_exc(limit=3)
        return ev

    ev.extraction_path = result.extraction_path.value
    ev.processing_ms = result.processing_ms
    got = result.invoice
    for f in SCALAR_FIELDS:
        ev.fields_ok[f] = values_match(f, getattr(gt.invoice, f), getattr(got, f))
    ev.items_expected = len(gt.invoice.items)
    ev.items_got = len(got.items)
    return ev


def summarize(evals: list[InvoiceEval]) -> dict[str, Any]:
    valid = [e for e in evals if e.error is None]
    n = len(valid)

    per_field = {}
    for f in SCALAR_FIELDS:
        ok = sum(1 for e in valid if e.fields_ok.get(f))
        per_field[f] = {"ok": ok, "total": n, "pct": round(100 * ok / n, 1) if n else 0.0}

    critical_ok = sum(1 for e in valid for f in Invoice.CRITICAL_FIELDS if e.fields_ok.get(f))
    critical_total = n * len(Invoice.CRITICAL_FIELDS)

    by_path: dict[str, Counter] = defaultdict(Counter)
    for e in valid:
        by_path[e.extraction_path or "?"]["total"] += 1
        if e.all_ok:
            by_path[e.extraction_path or "?"]["all_ok"] += 1

    return {
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "invoices_total": len(evals),
        "invoices_evaluated": n,
        "invoices_with_error": len(evals) - n,
        # Métrica principal de la spec §1: ≥ 85 %
        "approved_without_correction_pct": round(100 * sum(1 for e in valid if e.all_ok) / n, 1)
        if n
        else 0.0,
        # Spec §1: ≥ 95 %
        "critical_fields_pct": round(100 * critical_ok / critical_total, 1)
        if critical_total
        else 0.0,
        "per_field": per_field,
        "by_extraction_path": {k: dict(v) for k, v in by_path.items()},
        "sources": dict(Counter(e.source for e in evals)),
        "avg_processing_ms": round(sum(e.processing_ms for e in valid) / n) if n else 0,
        "invoices": [asdict(e) | {"all_ok": e.all_ok} for e in evals],
    }


def print_report(s: dict[str, Any]) -> None:
    def bar(pct: float, width: int = 20) -> str:
        filled = round(width * pct / 100)
        return "█" * filled + "░" * (width - filled)

    print(f"\nDataset: {s['invoices_evaluated']}/{s['invoices_total']} facturas evaluadas", end="")
    if s["invoices_with_error"]:
        print(f"  ({s['invoices_with_error']} con error)", end="")
    print()

    aprobadas = s["approved_without_correction_pct"]
    print(f"\n  Aprobadas sin corrección   {aprobadas:5.1f} %   meta >= 85 %")
    print(f"  Campos críticos            {s['critical_fields_pct']:5.1f} %   meta >= 95 %")
    print(f"  Tiempo medio pipeline      {s['avg_processing_ms']:>5} ms")

    print("\n  Exactitud por campo")
    for f, v in s["per_field"].items():
        crit = "*" if f in Invoice.CRITICAL_FIELDS else " "
        print(f"   {crit} {f:<18} {bar(v['pct'])} {v['pct']:5.1f} %  ({v['ok']}/{v['total']})")
    print("   * campo crítico")

    if s["by_extraction_path"]:
        print("\n  Por camino de extracción")
        for path, c in sorted(s["by_extraction_path"].items()):
            print(f"    {path:<10} {c.get('all_ok', 0)}/{c['total']} sin corrección")

    if s["sources"]:
        print("\n  Diversidad del dataset")
        for src, c in sorted(s["sources"].items(), key=lambda kv: -kv[1]):
            print(f"    {src:<24} {c}")

    errors = [e for e in s["invoices"] if e["error"]]
    if errors:
        print("\n  Errores")
        for e in errors:
            print(f"    {e['id']}: {e['error'].strip().splitlines()[-1]}")
    print()


def main(argv: list[str] | None = None) -> int:
    # La consola de Windows arranca en cp1252 y no imprime las barras del reporte
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--only", help="evaluar solo facturas cuyo id contenga este texto")
    ap.add_argument(
        "--no-save", action="store_true", help="no guardar resultados en dataset/results/"
    )
    args = ap.parse_args(argv)

    gt_files = sorted(GROUND_TRUTH.glob("*.json"))
    if args.only:
        gt_files = [p for p in gt_files if args.only in p.stem]
    if not gt_files:
        print(
            "No hay ground truth en dataset/ground_truth/. Ver dataset/README.md.", file=sys.stderr
        )
        return 1

    evals = [evaluate_one(p) for p in gt_files]
    summary = summarize(evals)
    print_report(summary)

    if not args.no_save:
        RESULTS.mkdir(exist_ok=True)
        out = RESULTS / f"{summary['timestamp'].replace(':', '-')}.json"
        out.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
        )
        print(f"Resultados guardados en {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
