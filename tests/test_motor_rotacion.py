"""Batería de pruebas unitarias para el motor de rotación (Field Shift)."""

import pathlib
import sys
import unittest

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.decision.motor_rotacion import (  # noqa: E402
    calibrar_humedad_suelo,
    calibrar_minima_termica,
    cargar_rubrica,
    evaluar_suelo_lote,
    simular_escenarios,
)


class TestMotorRotacion(unittest.TestCase):
    def test_cargar_rubrica_estructura(self) -> None:
        rubrica = cargar_rubrica()
        self.assertIn("metodos", rubrica)
        self.assertEqual(len(rubrica["metodos"]), 3)
        ids = {m["id"] for m in rubrica["metodos"]}
        self.assertEqual(ids, {"doble_golpe", "bomba_biologica", "resiliencia_hidrica"})

    def test_calibrar_humedad_sin_sonda_vs_con_sonda(self) -> None:
        sin_sonda = calibrar_humedad_suelo(0.18, None)
        self.assertEqual(sin_sonda["incertidumbre_pct"], 28)
        self.assertAlmostEqual(sin_sonda["humedad_efectiva"], 0.18, places=3)

        con_sonda = calibrar_humedad_suelo(0.18, {"10cm": 0.15, "30cm": 0.22, "60cm": 0.25})
        self.assertEqual(con_sonda["incertidumbre_pct"], 7)
        self.assertGreater(con_sonda["humedad_efectiva"], 0.18)

    def test_calibrar_minima_termica(self) -> None:
        res = calibrar_minima_termica(2.0)
        self.assertAlmostEqual(res["tmin_calibrada_c"], 0.96, places=2)

    def test_escenario_seco_secano_franco_arenoso(self) -> None:
        res = simular_escenarios(
            datos_lote={"nombre": "Test Seco"},
            prioridad_usuario="agua",
            tiene_ganaderia=False,
            escenario_lluvia="seco",
            lecturas_sonda={"10cm": 0.08, "30cm": 0.11, "60cm": 0.13},
            textura="franco_arenoso",
            napa_pendiente="sin_napa",
            regimen_agua="secano",
            estado_lote="desnudo",
        )
        rotaciones = res["comparativa_rotaciones"]
        self.assertEqual(len(rotaciones), 3)
        self.assertEqual(rotaciones[0]["id"], "resiliencia_hidrica")

        doble_golpe = next(r for r in rotaciones if r["id"] == "doble_golpe")
        self.assertGreaterEqual(len(doble_golpe["alertas_rojas"]), 1)

    def test_escenario_napa_cercana_cuenca_del_morro(self) -> None:
        res = simular_escenarios(
            datos_lote={"nombre": "Cuenca del Morro"},
            prioridad_usuario="suelo",
            tiene_ganaderia=True,
            escenario_lluvia="normal",
            napa_pendiente="napa_cercana",
            horizonte="largo",
        )
        rotaciones = res["comparativa_rotaciones"]
        self.assertEqual(rotaciones[0]["id"], "bomba_biologica")
        self.assertGreaterEqual(rotaciones[0]["puntaje_idoneidad"], 80.0)

    def test_escenario_con_riego_mitiga_penalizacion_doble_golpe(self) -> None:
        secano = simular_escenarios(
            datos_lote={},
            prioridad_usuario="renta",
            escenario_lluvia="seco",
            regimen_agua="secano",
        )
        riego = simular_escenarios(
            datos_lote={},
            prioridad_usuario="renta",
            escenario_lluvia="seco",
            regimen_agua="riego",
        )
        score_secano = next(r for r in secano["comparativa_rotaciones"] if r["id"] == "doble_golpe")["puntaje_idoneidad"]
        score_riego = next(r for r in riego["comparativa_rotaciones"] if r["id"] == "doble_golpe")["puntaje_idoneidad"]
        self.assertGreater(score_riego, score_secano)

    def test_adversarial_datos_vacios_y_rangos_acotados(self) -> None:
        res = simular_escenarios(
            datos_lote={"lluvia_gpm_mm": [], "humedad_suelo_smap": [], "ndvi_sentinel2": [], "temp_superficial_ecostress_c": []},
            prioridad_usuario="suelo",
            escenario_lluvia="desconocido",
            textura="desconocido",
        )
        for rot in res["comparativa_rotaciones"]:
            self.assertGreaterEqual(rot["puntaje_idoneidad"], 0.0)
            self.assertLessEqual(rot["puntaje_idoneidad"], 100.0)
            self.assertIn("evidencia", rot)
            self.assertIn("lagunas_info", rot)
            self.assertIn("riesgo_humano", rot)

    def test_evaluar_suelo_lote_limoso(self) -> None:
        suelo = evaluar_suelo_lote(
            textura="limoso",
            napa_pendiente="pendiente_anegamiento",
            regimen_agua="secano",
            estado_lote="rastrojo",
            humedad_efectiva=0.20,
            meses_desnudos=2,
        )
        self.assertIn("limoso", suelo["capacidad_retencion"].lower())
        self.assertGreaterEqual(len(suelo["riesgos_suelo"]), 2)


if __name__ == "__main__":
    unittest.main()
