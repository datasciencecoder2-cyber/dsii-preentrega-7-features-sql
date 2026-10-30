-- PRE-ENTREGA 7 | Tabla maestra de features RFM + Trend (una fila por usuario).
-- Parámetro requerido: :fecha_corte = primer día del mes posterior al último
-- mes COMPLETO analizado. Ejemplo: 2026-10-01 analiza hasta 2026-09-30.
-- No se admiten pedidos futuros, pendientes, cancelados o anteriores al alta.
-- Todas las métricas de tendencia usan meses CALENDARIO completos, incluso en 0.

WITH RECURSIVE
meses(n, mes) AS (
    -- Cuatro meses cerrados: tres meses de referencia y el último mes.
    SELECT 0, DATE(:fecha_corte, 'start of month', '-4 months')
    UNION ALL
    SELECT n + 1, DATE(mes, '+1 month')
    FROM meses
    WHERE n < 3
),
usuarios_elegibles AS (
    -- Evita fuga temporal: no crear features para usuarios registrados después del corte.
    SELECT usuario_id, nombre, ciudad, fecha_alta
    FROM usuarios
    WHERE DATE(fecha_alta) = fecha_alta
      AND DATE(fecha_alta) < DATE(:fecha_corte)
),
importe_por_pedido AS (
    -- Una fila por pedido, aunque tenga múltiples detalles: evita duplicar COUNT.
    SELECT
        detalle.pedido_id,
        ROUND(SUM(detalle.cantidad * detalle.precio_unitario), 2) AS importe_pedido
    FROM detalles_pedido AS detalle
    GROUP BY detalle.pedido_id
),
pedidos_validos AS (
    SELECT
        pedido.pedido_id,
        pedido.usuario_id,
        DATE(pedido.fecha) AS fecha,
        importe.importe_pedido
    FROM pedidos AS pedido
    JOIN importe_por_pedido AS importe
        ON importe.pedido_id = pedido.pedido_id
    JOIN usuarios_elegibles AS usuario
        ON usuario.usuario_id = pedido.usuario_id
    WHERE pedido.estado = 'completado'
      AND DATE(pedido.fecha) IS NOT NULL
      AND DATE(pedido.fecha) = pedido.fecha -- El formato debe ser ISO válido: AAAA-MM-DD.
      AND DATE(pedido.fecha) >= DATE(usuario.fecha_alta)
      AND DATE(pedido.fecha) < DATE(:fecha_corte)
),
resumen_usuario AS (
    -- LEFT JOIN conserva a toda la base de usuarios, incluso sin pedidos.
    SELECT
        usuario.usuario_id,
        usuario.nombre,
        usuario.ciudad,
        COUNT(DISTINCT pv.pedido_id) AS frequency_pedidos,
        ROUND(COALESCE(SUM(pv.importe_pedido), 0), 2) AS monetary_total,
        COALESCE(
            CAST(
                JULIANDAY(DATE(:fecha_corte, '-1 day'))
                - JULIANDAY(MAX(pv.fecha))
                AS INTEGER
            ),
            -1
        ) AS recency_dias,
        CASE WHEN COUNT(pv.pedido_id) = 0 THEN 1 ELSE 0 END AS sin_compras
    FROM usuarios_elegibles AS usuario
    LEFT JOIN pedidos_validos AS pv
        ON pv.usuario_id = usuario.usuario_id
    GROUP BY usuario.usuario_id, usuario.nombre, usuario.ciudad
),
ventas_por_mes AS (
    SELECT
        pv.usuario_id,
        DATE(pv.fecha, 'start of month') AS mes,
        ROUND(SUM(pv.importe_pedido), 2) AS gasto_mes
    FROM pedidos_validos AS pv
    WHERE pv.fecha >= DATE(:fecha_corte, 'start of month', '-4 months')
    GROUP BY pv.usuario_id, DATE(pv.fecha, 'start of month')
),
grilla_mensual AS (
    -- 4 meses x cada usuario: falta de compras equivale a gasto 0, no a mes ausente.
    SELECT
        u.usuario_id,
        m.mes,
        COALESCE(v.gasto_mes, 0.0) AS gasto_mes
    FROM usuarios_elegibles AS u
    CROSS JOIN meses AS m
    LEFT JOIN ventas_por_mes AS v
        ON v.usuario_id = u.usuario_id
       AND v.mes = m.mes
),
ventanas_mensuales AS (
    SELECT
        usuario_id,
        mes,
        gasto_mes,
        -- Ventana 1: gasto del mes precedente, por usuario.
        LAG(gasto_mes, 1, 0) OVER (
            PARTITION BY usuario_id
            ORDER BY mes
        ) AS gasto_mes_anterior,
        -- Ventana 2: promedio de los TRES meses anteriores (no incluye mes actual).
        AVG(gasto_mes) OVER (
            PARTITION BY usuario_id
            ORDER BY mes
            ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING
        ) AS promedio_historico_3m
    FROM grilla_mensual
),
ultimo_mes AS (
    SELECT *
    FROM ventanas_mensuales
    WHERE mes = DATE(:fecha_corte, 'start of month', '-1 month')
),
features AS (
    SELECT
        r.usuario_id,
        r.nombre,
        r.ciudad,
        r.recency_dias,
        r.frequency_pedidos,
        r.monetary_total,
        r.sin_compras,
        ROUND(u.gasto_mes, 2) AS gasto_ultimo_mes,
        ROUND(u.gasto_mes_anterior, 2) AS gasto_mes_anterior,
        ROUND(u.promedio_historico_3m, 2) AS promedio_historico_3m,
        -- Trend: diferencia entre último mes cerrado y promedio previo de 3 meses.
        ROUND(u.gasto_mes - u.promedio_historico_3m, 2) AS trend_delta_3m,
        ROUND(u.gasto_mes - u.gasto_mes_anterior, 2) AS delta_vs_mes_anterior
    FROM resumen_usuario AS r
    JOIN ultimo_mes AS u ON u.usuario_id = r.usuario_id
)
SELECT
    *,
    -- Ventana 3: ranking contextual del valor monetario dentro de cada ciudad.
    DENSE_RANK() OVER (
        PARTITION BY ciudad ORDER BY monetary_total DESC
    ) AS ranking_monetary_ciudad
FROM features
ORDER BY ciudad, ranking_monetary_ciudad, usuario_id;
