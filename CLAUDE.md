# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Estado del repositorio

Proyecto en arranque: entorno y dependencias listos, sin lógica de negocio todavía. La especificación revisada de la V1 está en `instrucciones-v1.md`; léela antes de proponer o implementar cualquier cosa. Este archivo resume sus decisiones no negociables.

## Comandos

Gestor: `uv` con Python 3.13 (fijado en `.python-version`). Nunca usar `pip` directamente.

```bash
uv sync                          # crear .venv e instalar todo (incluye grupo dev)
uv add <paquete>                 # agregar dependencia (actualiza pyproject + uv.lock)
uv run pytest                    # todos los tests
uv run pytest tests/test_x.py::test_nombre   # un test
uv run ruff check . && uv run ruff format .  # lint y formato
uv run python -m agentecontable.<modulo>     # ejecutar un módulo
```

Credenciales: `ANTHROPIC_API_KEY` en `.env` (ver `.env.example`); `.env` está en `.gitignore`.

## Layout

- `src/agentecontable/` — paquete principal (layout `src/`, build con hatchling).
- `src/agentecontable/extraction/` — pipeline en cascada (Fase 1).
- `dataset/facturas/` — facturas reales del dataset de evaluación. **Ignorado por git**: nunca se suben facturas reales.
- `dataset/ground_truth/` — JSON correcto por factura, escrito a mano (Fase 0). Sí va al repo.
- `tests/` — pytest, `asyncio_mode = "auto"`.

## Stack elegido

| Necesidad | Librería | Por qué |
|---|---|---|
| LLM texto y visión | `anthropic` (SDK 1.x), modelo `claude-opus-5` | Extracción estructurada con `client.messages.parse(output_format=ModeloPydantic)` → `response.parsed_output` validado |
| Modelos / validación | `pydantic` v2, `pydantic-settings` | Config desde `.env` |
| PDF | `pymupdf` (`import pymupdf`, no `fitz`) | Capa de texto y render de páginas sin poppler |
| QR | `opencv-python-headless` (`cv2.QRCodeDetector`) | Sin dependencia de zbar en Windows |
| Imágenes | `pillow` | Preview WebP (soporte verificado) |
| MIME real | `filetype` | Magic bytes en puro Python |

FastAPI, PostgreSQL/Supabase y storage se agregan cuando llegue su fase (2+), no antes.

Notas del SDK `anthropic` 1.x: usa `httpx2` (no `httpx`); prefill de assistant está eliminado (usar structured outputs); `output_format=` en `messages.parse()`, `output_config={"format": ...}` en `messages.create()`; no usar `budget_tokens` (usar `thinking={"type": "adaptive"}` o omitir).

## Qué es el proyecto

Agente que convierte una factura panameña no estructurada (foto o PDF) en datos contables estructurados, validados y editables, con el contador como responsable de la aprobación final.

Principio rector: **la IA interpreta, el código valida, el humano aprueba.** La métrica de éxito no es extraer datos sino ahorrar tiempo al contador (≥ 85 % de facturas aprobadas sin corregir campos, ≤ 20 s de revisión, ≥ 95 % de exactitud en RUC/número/fecha/total, ≤ 2 % de falsos positivos de validación).

## Orden de trabajo (no reordenar)

El riesgo está en la lectura de facturas, no en el CRUD. Las fases son:

0. Dataset de evaluación (50–100 facturas con ground truth a mano + `evaluate.py` que reporta exactitud por campo)
1. Pipeline de extracción — **sin UI ni BD**
2. Configuración e infraestructura → 3. BD → 4. Auth y empresas → 5. Carga y storage → 6. Validación → 7. Revisión humana → 8. Dashboard → 9. E2E y métricas

**Si el pipeline no alcanza las métricas sobre el dataset, no se construyen pantallas; se ajusta el pipeline.** No propongas empezar por la UI o el modelo de datos.

## Arquitectura clave

**Pipeline en cascada** — resolver por el camino más barato y exacto disponible, en este orden:
1. QR / CUFE de factura electrónica → parsear, costo cero, confianza 100 %
2. PDF con capa de texto → extraer texto → LLM sobre texto (sin visión)
3. Imagen o PDF escaneado → visión/OCR (último recurso)

El proveedor de OCR va detrás de una interfaz `OCRProvider(Protocol)` con `async def extract(file_path) -> RawExtraction`. La elección de proveedor (Document AI / Azure DI / Textract vs. modelo multimodal) es una decisión pendiente; no la asumas.

**Confianza derivada, nunca auto-reportada** — no pedirle al LLM su confianza. Se hacen dos extracciones a temperatura 0 con prompts distintos: coinciden → alta (verde), discrepan → baja (amarillo), vacío en ambas → nula (rojo). Se guarda en `invoices.field_confidence JSONB`. Si el OCR entrega confianza nativa, se combina.

**Validación aritmética con tolerancia** — `subtotal + tax = total` no se cumple en la práctica. Fórmula: `subtotal - discount + itbms + tip + otros_cargos`, tolerancia `Decimal("0.02")`. Un descuadre es **warning, no error**.
- Error (bloquea aprobación): falta RUC, falta número, fecha inválida, total negativo.
- Warning (solo resalta): totales no cuadran por centavos, proveedor nuevo, monto inusual.
- Regla: advertir, no bloquear.

**Duplicados en tres niveles**: (1) `sha256` idéntico → bloquear; (2) `UNIQUE (company_id, supplier_ruc, invoice_number)` → bloquear; (3) mismo proveedor + mismo total ± 3 días → warning.

**Storage** — nunca descartar el original. Ruta `companies/{company_id}/invoices/{año}/{mes}/original/{uuid}.ext` + `preview/{uuid}.webp` (calidad 85, ancho máx. 2000 px, solo para preview).

**Trazabilidad** — toda factura procesada guarda `raw_extraction JSONB`, `ocr_provider`, `model_version`, `prompt_version`, `extraction_path` (`'qr' | 'pdf_text' | 'vision'`), `tokens_used`, `processing_ms`.

**Aislamiento multi-empresa** — el filtro por `company_id` va en la capa de datos (RLS si Supabase Auth, dependencia FastAPI que inyecta `company_id` si JWT propio), **nunca depende del frontend**. La elección Supabase Auth vs. JWT propio debe tomarse antes de tocar la BD.

**Revisión humana** — cola ordenada por confianza ascendente (no cronológica); cursor salta al primer campo dudoso; campos verdes colapsados; atajos `Tab` / `Enter` / `Esc`; aprobar sin mouse.

## Reglas de modelo de datos

- Todos los montos son `NUMERIC(12,2)`. **Nunca `float`.** En Python usar `Decimal`.
- Notas de crédito se registran en negativo (`document_type`: `FACTURA | NOTA_CREDITO | RECIBO`).
- `invoices` incluye `discount`, `tip`, `exempt_amount`, `isc`, `retencion_itbms`, `cufe`.
- `audit_logs` registra `entity_type`, `entity_id`, `field_name`, `old_value`, `new_value`.
- `processing_jobs` lleva `retry_count` y `last_heartbeat`; un barrido periódico marca `FAILED` los jobs sin heartbeat (los `BackgroundTasks` de FastAPI mueren al reiniciar).

## Validación de archivos

MIME por magic bytes (no por extensión); máx. 10 MB por archivo y 20 páginas por PDF; rechazar PDFs con JavaScript embebido; sanitizar el nombre original.

## Fuera de alcance en V1

Monolito modular. Nada de LangGraph, Celery, Redis, Kubernetes, microservicios, modelo propio, vector DB, RAG ni multi-agente. Tampoco reproceso masivo histórico, conciliación de notas de crédito contra factura original, ni reglas de validación configurables por empresa. No introduzcas estas piezas aunque parezcan convenientes.

