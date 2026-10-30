"""Batería de pruebas de la tabla maestra RFM + Trend, sin librerías extra."""

import csv
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ejecutar import (  # noqa: E402
    CONSULTA, conectar_y_cargar, exportar_csv, obtener_features,
    validar_fecha_corte, validar_resultado,
)


class TestFeaturesChurn(unittest.TestCase):
    def setUp(self):
        self.con = conectar_y_cargar()
        self.filas = obtener_features(self.con)
        self.por_id = {fila["usuario_id"]: fila for fila in self.filas}

    def tearDown(self):
        self.con.close()

    def test_01_conserva_los_12_usuarios(self):
        self.assertEqual(len(self.filas), 12)
        self.assertEqual(set(self.por_id), set(range(1, 13)))

    def test_02_una_fila_por_usuario(self):
        self.assertEqual(len(set(f["usuario_id"] for f in self.filas)), len(self.filas))

    def test_03_sin_compras_se_codifica_sin_nulos(self):
        for i in (3, 7, 11):
            f = self.por_id[i]
            self.assertEqual((f["recency_dias"], f["frequency_pedidos"], f["monetary_total"], f["sin_compras"]), (-1, 0, 0, 1))
            self.assertEqual(f["trend_delta_3m"], 0)

    def test_04_ana_importe_y_frecuencia_multilinea(self):
        f = self.por_id[1]
        self.assertEqual(f["frequency_pedidos"], 7)
        self.assertEqual(f["monetary_total"], 570)
        self.assertEqual(f["recency_dias"], 5)

    def test_05_ana_ventana_historica_de_tres_meses(self):
        f = self.por_id[1]
        self.assertEqual(f["gasto_ultimo_mes"], 225)
        self.assertEqual(f["promedio_historico_3m"], 95)
        self.assertEqual(f["trend_delta_3m"], 130)

    def test_06_ana_lag_mes_anterior(self):
        self.assertEqual(self.por_id[1]["gasto_mes_anterior"], 90)
        self.assertEqual(self.por_id[1]["delta_vs_mes_anterior"], 135)

    def test_07_bruno_sin_actividad_reciente_pero_con_historial(self):
        f = self.por_id[2]
        self.assertEqual((f["frequency_pedidos"], f["monetary_total"]), (3, 245))
        self.assertEqual(f["recency_dias"], 166)
        self.assertEqual(f["gasto_ultimo_mes"], 0)
        self.assertEqual(f["sin_compras"], 0)

    def test_08_jorge_no_cuenta_pedido_cancelado(self):
        f = self.por_id[10]
        self.assertEqual(f["monetary_total"], 210)
        self.assertEqual(f["frequency_pedidos"], 4)
        self.assertEqual(f["trend_delta_3m"], -50)

    def test_09_karen_solo_pendiente_y_futuro_no_compra(self):
        self.assertEqual(self.por_id[11]["frequency_pedidos"], 0)
        self.assertEqual(self.por_id[11]["monetary_total"], 0)

    def test_10_fabio_mes_sin_compras_incluido_en_promedio(self):
        # Junio=100, julio=0, agosto=200; promedio=100, septiembre=20.
        f = self.por_id[6]
        self.assertEqual(f["promedio_historico_3m"], 100)
        self.assertEqual(f["trend_delta_3m"], -80)

    def test_11_pedido_futuro_no_fuga_al_corte(self):
        originales = [dict(f) for f in self.filas]
        self.con.execute("UPDATE detalles_pedido SET precio_unitario = 999999 WHERE pedido_id = 31")
        despues = obtener_features(self.con)
        self.assertEqual(originales, despues)

    def test_12_nuevas_compras_validas_si_estan_antes_del_corte(self):
        self.con.execute("INSERT INTO pedidos VALUES (1000, 3, '2026-09-28', 'completado')")
        self.con.execute("INSERT INTO detalles_pedido VALUES (1000, 1000, 'prueba', 2, 30)")
        nueva = {f["usuario_id"]: f for f in obtener_features(self.con)}
        self.assertEqual(nueva[3]["monetary_total"], 60)
        self.assertEqual(nueva[3]["frequency_pedidos"], 1)
        self.assertEqual(nueva[3]["sin_compras"], 0)

    def test_13_fecha_invalida_no_se_cuenta(self):
        # Pedido 37 tiene '2026-09-31'; SQLite puede normalizarlo a octubre.
        f = self.por_id[9]
        self.assertLess(f["monetary_total"], 999)
        self.assertEqual(f["gasto_ultimo_mes"], 110)

    def test_14_hay_tres_funciones_de_ventana(self):
        sql = CONSULTA.read_text(encoding="utf-8").upper()
        self.assertIn("LAG(", sql)
        self.assertIn("AVG(GASTO_MES) OVER", sql)
        self.assertIn("DENSE_RANK() OVER", sql)
        self.assertIn("PARTITION BY", sql)

    def test_15_validador_de_features_sin_nulos(self):
        validar_resultado(self.con, self.filas)
        criticas = ["frequency_pedidos", "monetary_total", "trend_delta_3m"]
        self.assertTrue(all(f[col] is not None for f in self.filas for col in criticas))

    def test_16_nuevo_corte_permite_otro_mes_cerrado(self):
        nuevo = {f["usuario_id"]: f for f in obtener_features(self.con, "2026-11-01")}
        self.assertEqual(nuevo[11]["frequency_pedidos"], 1)
        self.assertEqual(nuevo[11]["gasto_ultimo_mes"], 999)
        self.assertEqual(nuevo[12]["gasto_ultimo_mes"], 700)

    def test_17_fecha_corte_parcial_se_rechaza(self):
        for v in ("2026-10-15", "2026-13-01", "01/10/2026", "2026-10-1"):
            with self.subTest(fecha=v), self.assertRaises(ValueError):
                validar_fecha_corte(v)

    def test_18_ranking_se_reinicia_por_ciudad(self):
        for ciudad in {f["ciudad"] for f in self.filas}:
            grupo = [f for f in self.filas if f["ciudad"] == ciudad]
            self.assertEqual(min(f["ranking_monetary_ciudad"] for f in grupo), 1)
            for i in grupo:
                for j in grupo:
                    if i["monetary_total"] == j["monetary_total"]:
                        self.assertEqual(i["ranking_monetary_ciudad"], j["ranking_monetary_ciudad"])

    def test_19_exportacion_csv_es_reproducible(self):
        with tempfile.TemporaryDirectory() as temporal:
            ruta = Path(temporal) / "resultado.csv"
            exportar_csv(self.filas, ruta)
            with ruta.open(encoding="utf-8-sig", newline="") as ar:
                filas = list(csv.DictReader(ar))
            self.assertEqual(len(filas), 12)
            self.assertIn("trend_delta_3m", filas[0])

    def test_21_usuario_alta_futura_se_excluye(self):
        self.con.execute("INSERT INTO usuarios VALUES (99, 'Nuevo', 'Mendoza', '2026-11-01')")
        self.con.execute("INSERT INTO pedidos VALUES (1001, 99, '2026-11-02', 'completado')")
        self.con.execute("INSERT INTO detalles_pedido VALUES (1001, 1001, 'prueba', 1, 9999)")
        nuevos = obtener_features(self.con)
        self.assertNotIn(99, {f["usuario_id"] for f in nuevos})
        validar_resultado(self.con, nuevos)

    def test_20_importe_global_39_pedidos(self):
        self.assertEqual(sum(f["frequency_pedidos"] for f in self.filas), 39)
        self.assertEqual(sum(f["monetary_total"] for f in self.filas), 2840)


if __name__ == "__main__":
    unittest.main()
