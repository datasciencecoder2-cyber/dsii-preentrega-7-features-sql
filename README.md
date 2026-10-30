# Data Science II — Pre-entrega 7
## Ingeniería de Features con SQL Analítico Avanzado

**Objetivo:** construir una tabla maestra para un futuro modelo de predicción de abandono (*churn*) en e-commerce. El resultado conserva **una fila por usuario** y calcula métricas **Recency, Frequency, Monetary y Trend** mediante SQL avanzado, con `GROUP BY`, `LEFT JOIN`, `COALESCE` y funciones de ventana (`LAG`, `AVG OVER`, `DENSE_RANK`).

> **Alcance:** ingeniería de variables, no entrenamiento ni evaluación de un modelo. Los datos de prueba son **100 % ficticios**, preparados para comprobar casos normales y extremos.

## 1. Estructura del repositorio

```text
.
├── .gitignore
├── README.md
├── ejecutar.py                   # Orquesta y valida, no contiene lógica SQL de las features
├── sql/
│   ├── 01_esquema.sql            # Usuarios, pedidos y detalles de pedido
│   └── 02_features_churn.sql     # Consulta SQL principal: RFM + Trend
├── datos/
│   └── datos_ejemplo.sql         # 12 usuarios, 46 pedidos y 59 líneas (datos sintéticos)
├── tests/
│   └── test_features.py          # 21 pruebas automatizadas
└── evidencia/
    ├── ejecucion_muestra.txt     # Resultado de ejecución verificado
    └── pruebas.txt              # Salida de unittest
```

El proyecto funciona con **SQLite en memoria** y no versiona una base de datos binaria. Toda la lógica analítica está en `sql/02_features_churn.sql`, ejecutada desde Python con un parámetro de fecha de corte.

## 2. Requisitos y ejecución

- Python **3.10 o superior**. No requiere paquetes externos ni `pip install`.
- SQLite viene incluido con Python mediante el módulo estándar `sqlite3`.
- Para reproducir exactamente los resultados del README, usar la fecha de corte `2026-10-01`.

Desde PowerShell, en la carpeta del proyecto:

```powershell
py ejecutar.py
py -m unittest discover -s tests -v
```

Opcionalmente, generar un CSV de features que queda excluido de Git por `.gitignore`:

```powershell
py ejecutar.py --exportar
```

Para generar features de otra fecha de corte (primer día de un mes, exclusivo):

```powershell
py ejecutar.py --fecha-corte 2026-11-01
```

El programa no descarga datos ni depende de conexiones de red. Se puede ejecutar desde otras carpetas porque identifica las rutas con `pathlib` a partir de la ubicación de `ejecutar.py`.

## 3. Escenario, ventana temporal y unidad de análisis

- **Unidad de análisis:** un usuario, identificado por `usuario_id`.
- **Tablas de entrada:** `usuarios` (datos de cuenta), `pedidos` (fecha y estado) y `detalles_pedido` (cantidad y precio por línea).
- **Fecha de corte exclusiva:** `2026-10-01`. Solo se usan pedidos hasta el **30/09/2026**. No se incorporan usuarios registrados a partir de esa fecha.
- **Pedidos incluidos:** solo `estado = 'completado'`, con fecha válida en formato `AAAA-MM-DD`, no anterior al alta del usuario y anterior a la fecha de corte.
- **Importe por pedido:** suma de `cantidad * precio_unitario` para todos sus detalles. Primero se consolida a **una fila por pedido** y luego se agrega por usuario: así un pedido con varios artículos cuenta una sola vez para Frequency.
- **Ventana de tendencia:** junio, julio, agosto y septiembre de 2026. Junio–agosto forman la referencia histórica de **tres meses cerrados**; septiembre es el último mes cerrado. Los meses sin pedidos contribuyen con gasto **cero**, en vez de desaparecer del promedio.

La selección temporal evita *data leakage*: no utilizamos compras ni registros de usuarios posteriores a la fecha en la que se generarían las predicciones. En un proyecto real, la etiqueta de churn se definiría **después** de este corte, en una ventana futura que nunca debería entrar en las features.

## 4. Diccionario de features

| Columna | Tipo | Interpretación y utilidad para churn |
|---|---|---|
| `usuario_id` | entero | Identificador único de la fila; no es una variable predictora por sí mismo. |
| `nombre` | texto | Referencia descriptiva; debe excluirse del entrenamiento. |
| `ciudad` | texto | Contexto territorial; puede codificarse si es pertinente. |
| `recency_dias` | entero | Días desde la última compra hasta el último día observado. Valores altos pueden indicar desenganche. `-1` significa **nunca compró**, no compra reciente. |
| `frequency_pedidos` | entero | Cantidad de pedidos completados **distintos** antes del corte. `0` para usuarios sin compras. |
| `monetary_total` | decimal | Gasto histórico total calculado desde detalles, sin duplicaciones. `0` si no compró. |
| `sin_compras` | entero (0/1) | Flag explícito que acompaña `recency_dias=-1` para distinguir usuarios nuevos o sin historial. |
| `gasto_ultimo_mes` | decimal | Gasto del último mes cerrado (septiembre 2026). |
| `gasto_mes_anterior` | decimal | Gasto del mes precedente (agosto 2026), obtenido con `LAG() OVER`. |
| `promedio_historico_3m` | decimal | Promedio de junio, julio y agosto, usando `AVG() OVER ... ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING`. |
| `trend_delta_3m` | decimal | **Trend = gasto último mes − promedio de los tres meses anteriores.** Negativo significa caída relativa; positivo, aumento. |
| `delta_vs_mes_anterior` | decimal | Diferencia entre los dos últimos meses cerrados, útil para captar cambios bruscos. |
| `ranking_monetary_ciudad` | entero | Posición por gasto histórico dentro de cada ciudad con `DENSE_RANK() OVER(PARTITION BY ciudad ...)`; los empates comparten posición. |

**Precisión conceptual:** `recency_dias = -1` es un valor centinela documentado. No se utiliza `0` para usuarios sin compras porque `0` significaría que compraron en el último día observado. Todos los importes se expresan en **unidades monetarias ficticias** y se redondean a dos decimales.

## 5. Diseño de SQL y decisiones de calidad

1. `importe_por_pedido`: agrega cada línea de pedido antes del JOIN final para no inflar el número de compras.
2. `pedidos_validos`: restringe estado, fecha y existencia de usuario anterior al corte.
3. `resumen_usuario`: `LEFT JOIN` desde la población de usuarios elegibles; `GROUP BY` por ID, nombre y ciudad; `COUNT(DISTINCT pedido_id)` y `COALESCE(SUM(...), 0)`.
4. `meses` + `grilla_mensual`: genera cuatro meses calendario por usuario, incluidos los meses con importe cero.
5. `ventanas_mensuales`: calcula `LAG` y `AVG OVER` por usuario sin reducir filas prematuramente.
6. `ultimo_mes`: conserva únicamente la ventana del último mes cerrado y calcula las diferencias.
7. Consulta final: `DENSE_RANK` por ciudad y una fila ordenada por usuario.

Las consultas utilizan nombres descriptivos, CTE, fechas parametrizadas y comentarios que explican la finalidad analítica. No se hace un `WHERE` sobre un alias de ventana en el mismo nivel.

## 6. Resultados auditados (dataset ficticio)

La ejecución de ejemplo, con corte en `2026-10-01`, produce:

| Indicador | Valor |
|---|---:|
| Usuarios conservados | 12 |
| Usuarios sin compras | 3 |
| Pedidos completados válidos | 39 |
| Gasto total | 2.840,00 |
| Pruebas automatizadas correctas | 21 / 21 |

**Ejemplos de interpretación:**

- **Ana:** 7 pedidos, gasto total 570; septiembre 225, promedio junio–agosto 95; `trend_delta_3m = +130`.
- **Bruno:** 3 pedidos históricos, pero septiembre = 0 y `recency_dias = 166`: inactividad reciente, no falta de información.
- **Jorge:** septiembre = 0 y promedio histórico 50; `trend_delta_3m = -50`. Se excluye un pedido cancelado.
- **Carla, Gina y Karen:** no registran compras completadas antes del corte; aparecen con `frequency_pedidos = 0`, `monetary_total = 0`, `recency_dias = -1` y `sin_compras = 1`.

Los resultados y el registro de las 21 pruebas están en `evidencia/`. Los casos de prueba incluyen pedidos con múltiples artículos, operaciones canceladas, compras futuras, fechas inválidas, ausencia de actividad y un usuario registrado después de la fecha de corte.

## 7. Consideraciones para un modelo real de churn

Esta tabla es una **base de entrenamiento potencial**, no un modelo predictivo. Antes de entrenar habría que definir la etiqueta de churn y su horizonte (por ejemplo, ausencia de compra en los 60 días siguientes), generar varios cortes históricos sin mezclar períodos, analizar el sesgo de supervivencia y dividir entrenamiento/prueba temporalmente. Toda imputación estadística aprendida de datos debe ajustarse solo al entrenamiento. Como referencia inicial debe existir un modelo *baseline* frente al cual medir mejoras.

## 8. Cómo publicar el repositorio

Crear un repositorio público sugerido `dsii-preentrega-7-features-sql`, mantener las carpetas y subir los archivos. Para evitar publicar `__pycache__`, seleccionar `.gitignore` de Python al crear el repositorio en GitHub si el archivo del ZIP no se muestra en el cargador, y comprobar que se ignore también `resultados/`. Conservar commits claros y descriptivos, por ejemplo: `feat: estructura SQL y datos`, `feat: features RFM y tendencia`, `test: validar casos limite`, `docs: explicar variables y resultados`.

**Licencia de datos:** todas las observaciones son sintéticas y se utilizan exclusivamente con fines educativos.
