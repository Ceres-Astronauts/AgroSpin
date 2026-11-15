"""Batería de pruebas unitarias y de integración agronómica para el motor de rotación (Field Shift)."""

import pathlib
import sys
import unittest

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.decision.motor_rotacion import (  # noqa: E402
    calibrar_humedad_suelo,
    calibrar_minima_termica,
    calibrar_precipitacion_zonal,
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
        self.assertFalse(sin_sonda["requiere_validacion_calicata"])

        con_sonda = calibrar_humedad_suelo(0.18, {"10cm": 0.15, "30cm": 0.22, "60cm": 0.25})
        self.assertEqual(con_sonda["incertidumbre_pct"], 7)
        self.assertGreater(con_sonda["humedad_efectiva"], 0.18)

    def test_calibrar_minima_termica(self) -> None:
        # Validación de corrección de -1.04 °C contra estación REM 42
        res = calibrar_minima_termica(2.0)
        self.assertAlmostEqual(res["tmin_calibrada_c"], 0.96, places=2)
        self.assertTrue(res["riesgo_helada"])
        self.assertIn("ALERTA DE HELADA AGRONÓMICA", res["alerta_termica"])

        # Caso en buffer de seguridad (3.0 < T <= 4.5 °C)
        res_buffer = calibrar_minima_termica(5.0)
        self.assertAlmostEqual(res_buffer["tmin_calibrada_c"], 3.96, places=2)
        self.assertFalse(res_buffer["riesgo_helada"])
        self.assertTrue(res_buffer["buffer_seguridad"])
        self.assertIn("PRECAUCIÓN POR FRÍO", res_buffer["alerta_termica"])

        # Caso térmicamente seguro (> 4.5 °C calibrada)
        res_seguro = calibrar_minima_termica(8.0)
        self.assertAlmostEqual(res_seguro["tmin_calibrada_c"], 6.96, places=2)
        self.assertFalse(res_seguro["riesgo_helada"])
        self.assertFalse(res_seguro["buffer_seguridad"])
        self.assertIn("Sin riesgo inminente de helada", res_seguro["alerta_termica"])

    def test_fallback_smap_sequia_extrema_o_percentil_nulo(self) -> None:
        """Tarea A: Validación de corte (fallback) ante SMAP < 0.08 o nulo sin sonda."""
        # 1. SMAP nulo / None
        res_nulo = calibrar_humedad_suelo(None)
        self.assertEqual(res_nulo["incertidumbre_pct"], 28)
        self.assertTrue(res_nulo["requiere_validacion_calicata"])
        self.assertEqual(res_nulo["humedad_efectiva"], 0.08)
        self.assertIn("INCERTIDUMBRE ALTA", res_nulo["nota"])

        # 2. SMAP sequía superficial extrema (0.05 m³/m³) sin sonda
        res_seco = calibrar_humedad_suelo(0.05)
        self.assertEqual(res_seco["incertidumbre_pct"], 28)
        self.assertTrue(res_seco["requiere_validacion_calicata"])
        self.assertAlmostEqual(res_seco["humedad_efectiva"], 0.05)
        self.assertIn("Validar perfil con calicata", res_seco["alerta_sensor_superficial"])

        # 3. SMAP nulo pero CON sonda -> La sonda rescata y anula la alerta de calicata
        res_sonda_rescata = calibrar_humedad_suelo(
            humedad_smap_superficial=None,
            profundidad_sonda_cm=40.0,
            medicion_sonda_directa=0.21,
        )
        self.assertFalse(res_sonda_rescata["requiere_validacion_calicata"])
        self.assertEqual(res_sonda_rescata["humedad_efectiva"], 0.21)

    def test_calibracion_precipitacion_zonal_transicion_este(self) -> None:
        """Tarea B: Validación de consistencia zonal (REM 42 Villa Mercedes vs REM 49 Justo Daract)."""
        # 1. Villa Mercedes central (600 mm proyectada)
        lluvia_vm = calibrar_precipitacion_zonal([50.0] * 12, factor_clima=1.0, zona="villa_mercedes")
        self.assertFalse(lluvia_vm["es_transicion_este"])
        self.assertEqual(lluvia_vm["umbral_deficit_maiz_sorgo_mm"], 620.0)
        self.assertIn("Estación REM 42", lluvia_vm["estacion_referencia"])

        # 2. Transición Este / Justo Daract (720 mm proyectada)
        lluvia_jd = calibrar_precipitacion_zonal([65.4] * 12, factor_clima=1.0, zona="justo_daract")
        self.assertTrue(lluvia_jd["es_transicion_este"])
        self.assertEqual(lluvia_jd["umbral_deficit_maiz_sorgo_mm"], 580.0)
        self.assertIn("Estación REM 49", lluvia_jd["estacion_referencia"])

    def test_sonda_dinamica_estrato_superficial_vs_profundo(self) -> None:
        # Estrato superficial (15 cm): peso 65% sonda, 35% SMAP, incertidumbre 12%
        sonda_sup = calibrar_humedad_suelo(
            humedad_smap_superficial=0.18,
            profundidad_sonda_cm=15.0,
            medicion_sonda_directa=0.10,
        )
        self.assertEqual(sonda_sup["incertidumbre_pct"], 12)
        self.assertAlmostEqual(sonda_sup["humedad_efectiva"], 0.65 * 0.10 + 0.35 * 0.18, places=3)
        self.assertEqual(sonda_sup["profundidad_sonda_cm"], 15.0)

        # Estrato medio (30 cm): peso 80% sonda, 20% SMAP, incertidumbre 6%
        sonda_med = calibrar_humedad_suelo(
            humedad_smap_superficial=0.18,
            profundidad_sonda_cm=30.0,
            medicion_sonda_directa=0.22,
        )
        self.assertEqual(sonda_med["incertidumbre_pct"], 6)
        self.assertAlmostEqual(sonda_med["humedad_efectiva"], 0.80 * 0.22 + 0.20 * 0.18, places=3)

        # Estrato profundo (60 cm): peso 85% sonda, 15% SMAP, incertidumbre 5%
        sonda_prof = calibrar_humedad_suelo(
            humedad_smap_superficial=0.18,
            profundidad_sonda_cm=60.0,
            medicion_sonda_directa=0.26,
        )
        self.assertEqual(sonda_prof["incertidumbre_pct"], 5)
        self.assertAlmostEqual(sonda_prof["humedad_efectiva"], 0.85 * 0.26 + 0.15 * 0.18, places=3)

    def test_reglas_agronomicas_por_profundidad_de_sonda(self) -> None:
        # 1. Sonda profunda (60 cm) con recarga hídrica (0.24 m³/m³): bonifica bomba biológica (alfalfa)
        res_prof = simular_escenarios(
            datos_lote={"nombre": "Lote Alfalfa"},
            profundidad_sonda_cm=60.0,
            medicion_sonda_directa=0.24,
            regimen_agua="secano",
        )
        bomba = next(r for r in res_prof["comparativa_rotaciones"] if r["id"] == "bomba_biologica")
        self.assertTrue(
            any("Sonda a 60 cm confirma buena humedad en profundidad" in a for a in bomba["alertas_escenario"])
        )

        # 2. Sonda superficial (20 cm) en cama de siembra seca (0.10 m³/m³): penaliza doble golpe
        res_sup_seca = simular_escenarios(
            datos_lote={"nombre": "Lote Doble Golpe"},
            profundidad_sonda_cm=20.0,
            medicion_sonda_directa=0.10,
            regimen_agua="secano",
        )
        dg = next(r for r in res_sup_seca["comparativa_rotaciones"] if r["id"] == "doble_golpe")
        self.assertTrue(
            any("Sonda a 20 cm marca cama de siembra seca" in a for a in dg["alertas_escenario"])
        )

        # 3. Sonda media (40 cm) con humedad limitante (0.15 m³/m³): bonifica resiliencia hídrica (sorgo/girasol)
        res_resil = simular_escenarios(
            datos_lote={"nombre": "Lote Rustico"},
            profundidad_sonda_cm=40.0,
            medicion_sonda_directa=0.15,
            regimen_agua="secano",
        )
        resil = next(r for r in res_resil["comparativa_rotaciones"] if r["id"] == "resiliencia_hidrica")
        self.assertTrue(
            any("Sonda a 40 cm muestra humedad justa" in a for a in resil["alertas_escenario"])
        )

    def test_precipitacion_consensuada_media_nasa_local(self) -> None:
        res = simular_escenarios(
            datos_lote={"lluvia_gpm_mm": [50.0] * 12},  # Bruto = 600 mm
            escenario_lluvia="normal",
        )
        diag = res["diagnostico_lote"]
        self.assertEqual(diag["lluvia_satelital_bruta_mm"], 600)
        self.assertEqual(diag["lluvia_calibrada_local_mm"], 500)
        self.assertEqual(diag["lluvia_anual_proyectada_mm"], 550)

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

    def test_profundidad_superficial_y_tolerancia_baja(self) -> None:
        res_superficial = simular_escenarios(
            datos_lote={"nombre": "Lote Somero"},
            regimen_agua="secano",
            napa_pendiente="sin_napa",
            profundidad_efectiva_cm=60.0,
            tolerancia_perdidas="baja",
        )
        res_profundo = simular_escenarios(
            datos_lote={"nombre": "Lote Profundo"},
            regimen_agua="secano",
            napa_pendiente="sin_napa",
            profundidad_efectiva_cm=150.0,
            tolerancia_perdidas="alta",
        )
        dg_sup = next(r for r in res_superficial["comparativa_rotaciones"] if r["id"] == "doble_golpe")
        dg_prof = next(r for r in res_profundo["comparativa_rotaciones"] if r["id"] == "doble_golpe")
        self.assertLess(dg_sup["puntaje_idoneidad"], dg_prof["puntaje_idoneidad"])
        self.assertTrue(any("60 cm < 80 cm" in a for a in dg_sup["alertas_escenario"]))
        self.assertTrue(any("Tolerancia baja a pérdidas" in a for a in dg_sup["alertas_escenario"]))

        diag = res_superficial["diagnostico_lote"]
        self.assertIn("balance_fao56", diag)
        self.assertEqual(len(diag["balance_fao56"]["demanda_cultivos_mm"]), 6)
        self.assertIn("advertencia_fao56", diag["balance_fao56"])
        self.assertIn("advertencia_smap", diag["balance_fao56"])
        self.assertGreaterEqual(len(diag["dimensiones_faltantes"]), 3)

    def test_mvp_homogeneo_mapa_y_capas(self) -> None:
        from src.decision.mapa_datos import CURATED_DIR, consultar_terreno, obtener_capas_mapa

        if not (CURATED_DIR / "srtm_1ha_corredor.parquet").is_file():
            self.skipTest("Datasets curados locales no disponibles en este entorno.")
        capas = obtener_capas_mapa()
        self.assertEqual(len(capas["estaciones"]), 19)
        self.assertGreaterEqual(len(capas["sisinta"]), 60)
        self.assertGreater(len(capas["grilla_500m"]), 1000)

        res = consultar_terreno(lat=-33.675, lon=-65.460)
        ctx = res.get("contexto_mvp", {})
        self.assertIn("susceptibilidad_topografica", res["terreno"])
        self.assertIn("sisinta_cercano", ctx)
        self.assertEqual(len(ctx.get("gaez_cultivos", [])), 6)
        self.assertIn("clima_historica_celda", ctx)


if __name__ == "__main__":
    unittest.main()
