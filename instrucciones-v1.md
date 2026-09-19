# Agente Inteligente para Gestión de Facturas — V1 (revisada)

> **Principio fundamental:** la IA interpreta, el código valida, el humano aprueba.
> **Métrica que define el éxito:** no es extraer datos, es ahorrar tiempo al contador.

---

## 1. Objetivo de la V1

Convertir una factura no estructurada (foto o PDF) en información contable estructurada, validada, editable y almacenada, manteniendo al contador como responsable de la aprobación final.

### Criterios de éxito (definidos antes de empezar)

| Métrica | Meta V1 |
|---|---|
| Facturas aprobadas sin corregir ningún campo | ≥ 85 % |
| Tiempo medio de revisión y aprobación | ≤ 20 segundos |
| Exactitud en campos críticos (RUC, número, fecha, total) | ≥ 95 % |
| Facturas resueltas sin llamar al modelo (vía QR/CUFE) | medir y maximizar |
| Falsos positivos de validación (marca error en factura correcta) | ≤ 2 % |

Si la extracción no alcanza estos números, **no se avanza a construir pantallas**. Se ajusta el pipeline.

---

## 2. Cambio de orden: validar el riesgo primero

El riesgo real del proyecto está en la lectura de facturas, no en el CRUD. El orden de fases se reordena:

```
Fase 0  Dataset de evaluación        ← NUEVO, antes que nada
Fase 1  Pipeline de extracción       ← adelantado (sin UI, sin BD)
Fase 2  Configuración e infraestructura
Fase 3  Base de datos
Fase 4  Autenticación y empresas
Fase 5  Carga de documentos y storage
Fase 6  Validación
Fase 7  Revisión humana
Fase 8  Dashboard y consulta
Fase 9  Pruebas end-to-end y métricas
```

---

## 3. Fase 0 — Dataset de evaluación (primera tarea del proyecto)

Sin esto, cada cambio de prompt es a ciegas.

**Tareas**

- Recolectar 50–100 facturas panameñas reales o anonimizadas.
- Escribir a mano el JSON correcto de cada una (*ground truth*).
- Diversidad obligatoria: factura electrónica con QR, PDF con texto, foto de celular, foto inclinada, foto borrosa, ticket de supermercado, factura de restaurante con propina, nota de crédito, factura con descuento, factura con ítems exentos.
- Script `evaluate.py` que corre el pipeline sobre el dataset y reporta exactitud por campo.

**Resultado:** un número objetivo que sube o baja con cada cambio.

---

## 4. Fase 1 — Pipeline de extracción en cascada

**No todo va al modelo de IA.** Se resuelve por el camino más barato y exacto disponible.

```
Documento recibido
  │
  ├─ ¿Tiene QR / CUFE de factura electrónica?
  │     └─ Sí → parsear FE → datos exactos, costo cero, confianza 100 %
  │
  ├─ ¿Es PDF con capa de texto?
  │     └─ Sí → extraer texto → LLM sobre texto (barato, sin visión)
  │
  └─ Imagen o PDF escaneado
        └─ Visión / OCR (camino caro, último recurso)
```

**Decisión pendiente antes de codificar:** proveedor de OCR. Si se necesita confianza por campo nativa, usar Google Document AI, Azure Document Intelligence o AWS Textract. Si se usa modelo multimodal, la confianza se deriva (ver punto 5).

La capa de OCR se mantiene desacoplada tras una interfaz:

```python
class OCRProvider(Protocol):
    async def extract(self, file_path: str) -> RawExtraction: ...
```

---

## 5. Confianza derivada, no auto-reportada

Un LLM no sabe cuánta confianza tiene. Preguntarle produce números decorativos.

**Método:** dos extracciones con temperatura 0 y prompts distintos.

| Resultado | Confianza | Acción |
|---|---|---|
| Ambas pasadas coinciden | Alta | Campo en verde, no requiere atención |
| Discrepan | Baja | Campo en amarillo, cursor salta ahí |
| Campo vacío en ambas | Nula | Campo en rojo, obligatorio completar |

Si el proveedor de OCR entrega confianza nativa, se combina con este método.

Se guarda por factura: `field_confidence JSONB` con el nivel de cada campo.

---

## 6. Fase 6 — Validación con tolerancia

La regla `subtotal + tax = total` se rompe en la práctica. Corregir el modelo de datos y la lógica.

**Fórmula real:**

```python
TOLERANCIA = Decimal("0.02")
esperado = subtotal - descuento + itbms + propina + otros_cargos
if abs(esperado - total) > TOLERANCIA:
    warning("El total no cuadra")   # warning, NO error
```

**Campos nuevos requeridos en `invoices`:** `discount`, `tip`, `exempt_amount`, `isc`, `retencion_itbms`.

### Errores vs. warnings

| Tipo | Efecto | Ejemplos |
|---|---|---|
| **Error** (bloquea aprobación) | El contador debe corregir | Falta RUC, falta número de factura, fecha inválida, total negativo |
| **Warning** (solo resalta) | El contador puede aprobar igual | Totales no cuadran por centavos, proveedor nuevo, monto inusual |

Regla: **advertir, no bloquear.** Un sistema que declara incorrectas facturas correctas pierde la confianza del usuario en una semana.

---

## 7. Detección de duplicados en tres niveles

El duplicado real no es subir dos veces el mismo archivo, es fotografiar la misma factura dos veces.

| Nivel | Detección | Resultado |
|---|---|---|
| 1 | `sha256` idéntico | Mismo archivo → bloquear |
| 2 | `UNIQUE (company_id, supplier_ruc, invoice_number)` | Misma factura, otra foto → bloquear |
| 3 | Mismo proveedor + mismo total ± 3 días | Posible duplicado → warning |

---

## 8. Storage: original + derivado

**Nunca se descarta el archivo original.**

| Archivo | Uso |
|---|---|
| Original (JPG/PNG/PDF) | Respaldo fiscal, reproceso con versiones futuras del pipeline, consume el OCR |
| Derivado WebP (calidad 85, ancho máx. 2000 px) | Solo preview en el frontend |

```
companies/{company_id}/invoices/{año}/{mes}/
    ├── original/  {uuid}.jpg
    └── preview/   {uuid}.webp
```

---

## 9. Trazabilidad: guardar siempre el crudo

Barato de hacer ahora, imposible de recuperar después. Sin esto no se puede depurar una regresión al cambiar el prompt, ni construir el dataset de aprendizaje de la V2.

**Campos nuevos en `invoices`:**

```
raw_extraction      JSONB    -- respuesta completa del OCR/LLM
ocr_provider        TEXT
model_version       TEXT
prompt_version      TEXT
extraction_path     TEXT     -- 'qr' | 'pdf_text' | 'vision'
tokens_used         INTEGER
processing_ms       INTEGER
```

---

## 10. Fase 7 — Revisión humana orientada a velocidad

Esta pantalla decide si el sistema ahorra tiempo o no.

**Reglas de diseño**

- La cola de revisión se ordena por **confianza ascendente**, no cronológicamente.
- Al abrir una factura, el cursor salta **automáticamente al primer campo dudoso**.
- Campos de alta confianza se muestran en verde y colapsados; no se releen.
- Campos dudosos en amarillo, expandidos, con la zona correspondiente de la imagen resaltada si el proveedor entrega *bounding boxes*.
- Atajos de teclado: `Tab` siguiente campo dudoso, `Enter` aprobar, `Esc` rechazar.
- Aprobar debe ser posible **sin tocar el mouse**.

```
┌──────────────────────┬──────────────────────────────┐
│                      │ ✓ Proveedor    Empresa XYZ   │
│                      │ ✓ RUC          123456-1-...  │
│      FACTURA         │ ⚠ Número      [F001-00123 ]  │ ← cursor aquí
│   (zona resaltada)   │ ✓ Fecha        15/09/2026    │
│                      │ ✓ Subtotal     $100.00       │
│                      │ ✓ ITBMS        $7.00         │
│                      │ ✓ Total        $107.00       │
│                      │                              │
│                      │ [Enter] Aprobar  [Esc] Error │
└──────────────────────┴──────────────────────────────┘
```

---

## 11. Modelo de datos — cambios respecto al documento original

### `invoices` — campos añadidos

```
document_type       TEXT      -- FACTURA | NOTA_CREDITO | RECIBO
discount            NUMERIC(12,2)
tip                 NUMERIC(12,2)
exempt_amount       NUMERIC(12,2)
isc                 NUMERIC(12,2)
retencion_itbms     NUMERIC(12,2)
cufe                TEXT      -- si vino de factura electrónica
field_confidence    JSONB
raw_extraction      JSONB
ocr_provider        TEXT
model_version       TEXT
prompt_version      TEXT
extraction_path     TEXT
tokens_used         INTEGER
processing_ms       INTEGER
```

- Todos los montos son `NUMERIC(12,2)`. **Nunca `float`.**
- Las notas de crédito se registran en negativo.

### `audit_logs` — campos faltantes

```
entity_type    TEXT     -- 'invoice' | 'invoice_item' | ...
entity_id      UUID
field_name     TEXT     -- faltaba; el ejemplo del documento lo usa
old_value      TEXT
new_value      TEXT
```

### `processing_jobs` — campos añadidos

```
retry_count      INTEGER DEFAULT 0
last_heartbeat   TIMESTAMPTZ
```

Más un barrido periódico que marca como `FAILED` los jobs sin heartbeat por más de N minutos. Con `BackgroundTasks` de FastAPI los jobs mueren si se reinicia el proceso; esto los recupera.

---

## 12. Autenticación: decidir ahora, no después

El documento deja abierta la opción entre Supabase Auth y JWT propio. **La decisión cambia cómo se implementa el aislamiento por empresa y no se puede posponer.**

| Opción | Aislamiento |
|---|---|
| Supabase Auth | Row Level Security en PostgreSQL |
| JWT propio | Dependencia de FastAPI que inyecta `company_id` en toda consulta |

En ambos casos: el filtro por `company_id` se aplica en la capa de datos, **nunca depende del frontend**.

---

## 13. Validación de contenido de archivos

- Verificar MIME real leyendo los *magic bytes*, no la extensión.
- Límite: 10 MB por archivo, 20 páginas por PDF.
- Rechazar PDFs con JavaScript embebido.
- Sanitizar el nombre original antes de almacenarlo.

---

## 14. Proceso de trabajo

**Involucrar a un contador real desde la semana uno**, no al final para probar. Que use versiones incompletas y diga qué le estorba. Es la diferencia entre un sistema que funciona y uno que la gente usa.

Ciclo sugerido: cada viernes, el contador procesa 10 facturas reales y cronometra. Se registra el tiempo y el porcentaje sin corrección. Esos dos números son el tablero del proyecto.

---

## 15. Criterios de aceptación de la V1

### Funcionales

- [ ] Registro, login y logout.
- [ ] Crear y seleccionar empresa.
- [ ] Subir JPG, PNG y PDF.
- [ ] Se almacena el original y se genera el preview WebP.
- [ ] El pipeline en cascada resuelve por QR cuando existe.
- [ ] Extracción estructurada validada con Pydantic.
- [ ] Validación aritmética con tolerancia, separando errores de warnings.
- [ ] Confianza por campo visible en la interfaz.
- [ ] Duplicados detectados en los tres niveles.
- [ ] Edición, aprobación y registro en PostgreSQL.
- [ ] Auditoría con campo modificado, valor anterior y nuevo.
- [ ] Consulta con búsqueda, filtros y orden.
- [ ] Dashboard básico.
- [ ] Un usuario no puede ver datos de otra empresa (verificado con prueba automatizada).
- [ ] Se guarda `raw_extraction` en toda factura procesada.

### De rendimiento

- [ ] ≥ 85 % de facturas aprobadas sin corrección sobre el dataset de evaluación.
- [ ] Tiempo medio de revisión ≤ 20 segundos, medido con un contador real.
- [ ] ≤ 2 % de falsos positivos de validación.

---

## 16. Lo que sigue fuera de alcance

Sin cambios respecto al documento original: nada de LangGraph, Celery, Redis, Kubernetes, microservicios, modelo propio, vector database, RAG ni multi-agente. La V1 es un monolito modular.

Se añade a la lista de exclusiones:

- Reproceso masivo de facturas históricas.
- Conciliación de notas de crédito contra la factura original.
- Reglas de validación configurables por empresa.
