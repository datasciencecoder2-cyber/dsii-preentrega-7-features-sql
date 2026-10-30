"""Ejecutor reproducible de la Pre-entrega 7. Solo usa la biblioteca estándar."""

from __future__ import annotations

import argparse
import csv
from datetime import date
from pathlib import Path
import sqlite3

RAIZ = Path(__file__).resolve().parent
ESQUEMA = RAIZ / "sql" / "01_esquema.sql"
DATOS = RAIZ / "datos" / "datos_ejemplo.sql"
CONSULTA = RAIZ / "sql" / "02_features_churn.sql"


def validar_fecha_corte(valor: str) -> str:
    """Obliga a cortar al principio del mes para no mezclar meses parciales."""
    try:
        fecha = date.fromisoformat(valor)
    except ValueError as error:
        raise ValueError("La fecha de corte debe ser AAAA-MM-01, por ejemplo 2026-10-01.") from error
    if fecha.strftime("%Y-%m-%d") != valor or fecha.day != 1:
        raise ValueError("La fecha de corte debe ser el primer día de un mes: AAAA-MM-01.")
    return valor


def conectar_y_cargar() -> sqlite3.Connection:
    """Prepara el esquema y los datos de demostración en memoria; no crea .db."""
    conexion = sqlite3.connect(":memory:")
    conexion.row_factory = sqlite3.Row
    conexion.execute("PRAGMA foreign_keys = ON")
    conexion.executescript(ESQUEMA.read_text(encoding="utf-8"))
    conexion.executescript(DATOS.read_text(encoding="utf-8"))
    return conexion


def obtener_features(conexion: sqlite3.Connection, fecha_corte: str = "2026-10-01") -> list[dict]:
    """Ejecuta la consulta principal con parámetro de corte; retorna una fila por usuario."""
    validar_fecha_corte(fecha_corte)
    consulta = CONSULTA.read_text(encoding="utf-8")
    return [dict(fila) for fila in conexion.execute(consulta, {"fecha_corte": fecha_corte})]


def validar_resultado(conexion: sqlite3.Connection, filas: list[dict], fecha_corte: str = "2026-10-01") -> None:
    """Control estructural sin asumir importes específicos de la muestra."""
    ids_usuarios = {
        fila[0]
        for fila in conexion.execute(
            "SELECT usuario_id FROM usuarios WHERE DATE(fecha_alta) = fecha_alta "
            "AND DATE(fecha_alta) < DATE(?)", (fecha_corte,)
        )
    }
    ids_resultado = [f["usuario_id"] for f in filas]
    if len(filas) != len(ids_usuarios) or set(ids_resultado) != ids_usuarios:
        raise ValueError("La tabla maestra no conserva exactamente una fila por usuario.")
    if len(ids_resultado) != len(set(ids_resultado)):
        raise ValueError("Hay usuarios duplicados en la tabla maestra.")
    columnas = (
        "recency_dias", "frequency_pedidos", "monetary_total", "sin_compras",
        "gasto_ultimo_mes", "gasto_mes_anterior", "promedio_historico_3m",
        "trend_delta_3m", "delta_vs_mes_anterior", "ranking_monetary_ciudad"
    )
    for f in filas:
        if any(f[col] is None for col in columnas):
            raise ValueError(f"Features con nulos en usuario {f['usuario_id']}.")
        if f["frequency_pedidos"] == 0 and not (f["recency_dias"] == -1 and f["sin_compras"] == 1):
            raise ValueError("La codificación de usuarios sin compras es incoherente.")
        if f["frequency_pedidos"] > 0 and (f["recency_dias"] < 0 or f["sin_compras"] != 0):
            raise ValueError("Recency incompatible con compras existentes.")
    print("VALIDACIONES DE FEATURES: OK")


def exportar_csv(filas: list[dict], ruta: Path) -> None:
    """Salida OPCIONAL derivada; se excluye del repositorio mediante .gitignore."""
    if not filas:
        raise ValueError("No hay filas para exportar.")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=list(filas[0]))
        escritor.writeheader()
        escritor.writerows(filas)


def main() -> None:
    parser = argparse.ArgumentParser(description="Features RFM y Trend para predicción de abandono")
    parser.add_argument("--fecha-corte", default="2026-10-01", help="AAAA-MM-01, exclusivo")
    parser.add_argument("--exportar", action="store_true", help="Guardar CSV en resultados/")
    argumentos = parser.parse_args()
    fecha_corte = validar_fecha_corte(argumentos.fecha_corte)

    with conectar_y_cargar() as con:
        filas = obtener_features(con, fecha_corte)
        validar_resultado(con, filas, fecha_corte)
        print(f"Fecha de corte exclusiva: {fecha_corte}")
        print(f"Usuarios conservados: {len(filas)}")
        print(f"Usuarios sin compras: {sum(f['sin_compras'] for f in filas)}")
        print(f"Pedidos confirmados: {sum(f['frequency_pedidos'] for f in filas)}")
        print(f"Gasto confirmado: {sum(f['monetary_total'] for f in filas):.2f}")
        print("\nEjemplo de features:")
        for fila in filas[:5]:
            print(fila)
        if argumentos.exportar:
            ruta = RAIZ / "resultados" / "features_churn.csv"
            exportar_csv(filas, ruta)
            print(f"CSV generado: {ruta.relative_to(RAIZ)}")
    print("PIPELINE SQL COMPLETADO: OK")


if __name__ == "__main__":
    main()
