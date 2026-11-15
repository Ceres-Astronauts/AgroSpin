"""Unit and agronomic integration test suite for the Field Shift rotation decision engine."""

import pathlib
import sys
import unittest

from fastapi.testclient import TestClient

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.decision.map_data import MVP_HOMOGENEOUS_DIR, get_map_layers, query_terrain  # noqa: E402
from src.decision.rotation_engine import (  # noqa: E402
    calibrate_soil_moisture,
    calibrate_thermal_minimum,
    calibrate_zonal_precipitation,
    evaluate_field_soil,
    load_rubric,
    simulate_scenarios,
)
from web.server import app  # noqa: E402


class TestRotationEngine(unittest.TestCase):
    def test_load_rubric_structure(self) -> None:
        rubric = load_rubric()
        self.assertIn("methods", rubric)
        self.assertEqual(len(rubric["methods"]), 3)
        ids = {m["id"] for m in rubric["methods"]}
        self.assertEqual(ids, {"double_crop", "biological_pump", "water_resilience"})

    def test_calibrate_moisture_without_vs_with_probe(self) -> None:
        no_probe = calibrate_soil_moisture(0.18, None)
        self.assertEqual(no_probe["uncertainty_pct"], 28)
        self.assertAlmostEqual(no_probe["effective_moisture"], 0.18, places=3)
        self.assertFalse(no_probe["requires_test_pit_validation"])

        with_probe = calibrate_soil_moisture(0.18, {"10cm": 0.15, "30cm": 0.22, "60cm": 0.25})
        self.assertEqual(with_probe["uncertainty_pct"], 7)
        self.assertGreater(with_probe["effective_moisture"], 0.18)

    def test_calibrate_thermal_minimum(self) -> None:
        # Validate -1.04 °C correction against REM Station 42
        res = calibrate_thermal_minimum(2.0)
        self.assertAlmostEqual(res["calibrated_tmin_c"], 0.96, places=2)
        self.assertTrue(res["frost_risk"])
        self.assertIn("AGRONOMIC FROST ALERT", res["thermal_alert"])

        # Safety buffer zone (3.0 < T <= 4.5 °C)
        res_buffer = calibrate_thermal_minimum(5.0)
        self.assertAlmostEqual(res_buffer["calibrated_tmin_c"], 3.96, places=2)
        self.assertFalse(res_buffer["frost_risk"])
        self.assertTrue(res_buffer["safety_buffer"])
        self.assertIn("COLD CAUTION", res_buffer["thermal_alert"])

        # Thermally safe (> 4.5 °C calibrated)
        res_safe = calibrate_thermal_minimum(8.0)
        self.assertAlmostEqual(res_safe["calibrated_tmin_c"], 6.96, places=2)
        self.assertFalse(res_safe["frost_risk"])
        self.assertFalse(res_safe["safety_buffer"])
        self.assertIn("No imminent frost risk", res_safe["thermal_alert"])

    def test_fallback_smap_extreme_drought_or_null_percentile(self) -> None:
        """Fallback cutoff validation when SMAP < 0.08 or null without an in-situ probe."""
        # 1. SMAP null / None
        res_null = calibrate_soil_moisture(None)
        self.assertEqual(res_null["uncertainty_pct"], 28)
        self.assertTrue(res_null["requires_test_pit_validation"])
        self.assertEqual(res_null["effective_moisture"], 0.08)
        self.assertIn("HIGH UNCERTAINTY", res_null["note"])

        # 2. Extreme SMAP surface drought (0.05 m³/m³) without probe
        res_dry = calibrate_soil_moisture(0.05)
        self.assertEqual(res_dry["uncertainty_pct"], 28)
        self.assertTrue(res_dry["requires_test_pit_validation"])
        self.assertAlmostEqual(res_dry["effective_moisture"], 0.05)
        self.assertIn("Verify the soil profile with a test pit", res_dry["surface_sensor_alert"])

        # 3. SMAP null WITH probe -> probe overrides and clears test-pit warning
        res_probe_rescue = calibrate_soil_moisture(
            smap_surface_moisture=None,
            probe_depth_cm=40.0,
            direct_probe_reading=0.21,
        )
        self.assertFalse(res_probe_rescue["requires_test_pit_validation"])
        self.assertEqual(res_probe_rescue["effective_moisture"], 0.21)

    def test_zonal_precipitation_eastern_transition(self) -> None:
        """Zonal consistency validation (REM 42 Villa Mercedes vs. REM 49 Justo Daract)."""
        # 1. Central Villa Mercedes (600 mm projected)
        rain_vm = calibrate_zonal_precipitation([50.0] * 12, climate_factor=1.0, zone="villa_mercedes")
        self.assertFalse(rain_vm["is_east_transition"])
        self.assertEqual(rain_vm["maize_sorghum_deficit_threshold_mm"], 620.0)
        self.assertIn("REM Station 42", rain_vm["reference_station"])

        # 2. Eastern transition / Justo Daract (720 mm projected)
        rain_jd = calibrate_zonal_precipitation([65.4] * 12, climate_factor=1.0, zone="justo_daract")
        self.assertTrue(rain_jd["is_east_transition"])
        self.assertEqual(rain_jd["maize_sorghum_deficit_threshold_mm"], 580.0)
        self.assertIn("REM Station 49", rain_jd["reference_station"])

    def test_dynamic_probe_shallow_vs_deep_strata(self) -> None:
        # Surface stratum (15 cm): 65% probe weight, 35% SMAP, 12% uncertainty
        shallow_probe = calibrate_soil_moisture(
            smap_surface_moisture=0.18,
            probe_depth_cm=15.0,
            direct_probe_reading=0.10,
        )
        self.assertEqual(shallow_probe["uncertainty_pct"], 12)
        self.assertAlmostEqual(shallow_probe["effective_moisture"], 0.65 * 0.10 + 0.35 * 0.18, places=3)
        self.assertEqual(shallow_probe["probe_depth_cm"], 15.0)

        # Mid stratum (30 cm): 80% probe weight, 20% SMAP, 6% uncertainty
        mid_probe = calibrate_soil_moisture(
            smap_surface_moisture=0.18,
            probe_depth_cm=30.0,
            direct_probe_reading=0.22,
        )
        self.assertEqual(mid_probe["uncertainty_pct"], 6)
        self.assertAlmostEqual(mid_probe["effective_moisture"], 0.80 * 0.22 + 0.20 * 0.18, places=3)

        # Deep stratum (60 cm): 85% probe weight, 15% SMAP, 5% uncertainty
        deep_probe = calibrate_soil_moisture(
            smap_surface_moisture=0.18,
            probe_depth_cm=60.0,
            direct_probe_reading=0.26,
        )
        self.assertEqual(deep_probe["uncertainty_pct"], 5)
        self.assertAlmostEqual(deep_probe["effective_moisture"], 0.85 * 0.26 + 0.15 * 0.18, places=3)

    def test_agronomic_rules_by_probe_depth(self) -> None:
        # 1. Deep probe (60 cm) with recharge (0.24 m³/m³): rewards biological pump (alfalfa)
        res_deep = simulate_scenarios(
            field_data={"name": "Alfalfa Field"},
            probe_depth_cm=60.0,
            direct_probe_reading=0.24,
            water_regime="rainfed",
        )
        pump = next(r for r in res_deep["rotation_comparison"] if r["id"] == "biological_pump")
        self.assertTrue(
            any("Probe at 60 cm confirms deep moisture" in a for a in pump["scenario_alerts"])
        )

        # 2. Shallow probe (20 cm) in dry seedbed (0.10 m³/m³): warns on double crop
        res_shallow_dry = simulate_scenarios(
            field_data={"name": "Double Crop Field"},
            probe_depth_cm=20.0,
            direct_probe_reading=0.10,
            water_regime="rainfed",
        )
        dc = next(r for r in res_shallow_dry["rotation_comparison"] if r["id"] == "double_crop")
        self.assertTrue(
            any("Probe at 20 cm indicates dry seedbed" in a for a in dc["scenario_alerts"])
        )

        # 3. Mid probe (40 cm) with limiting moisture (0.15 m³/m³): boosts water resilience (sorghum/sunflower)
        res_resil = simulate_scenarios(
            field_data={"name": "Hardy Field"},
            probe_depth_cm=40.0,
            direct_probe_reading=0.15,
            water_regime="rainfed",
        )
        resil = next(r for r in res_resil["rotation_comparison"] if r["id"] == "water_resilience")
        self.assertTrue(
            any("Probe at 40 cm shows tight moisture" in a for a in resil["scenario_alerts"])
        )

    def test_consensus_precipitation_nasa_local_mean(self) -> None:
        res = simulate_scenarios(
            field_data={"gpm_rainfall_mm": [50.0] * 12},  # Raw = 600 mm
            rainfall_scenario="normal",
        )
        diag = res["field_diagnosis"]
        self.assertEqual(diag["raw_satellite_rainfall_mm"], 600)
        self.assertEqual(diag["locally_calibrated_rainfall_mm"], 500)
        self.assertEqual(diag["projected_annual_rainfall_mm"], 550)

    def test_dry_rainfed_sandy_loam_scenario(self) -> None:
        res = simulate_scenarios(
            field_data={"name": "Dry Test"},
            user_priority="water",
            has_livestock=False,
            rainfall_scenario="dry",
            probe_readings={"10cm": 0.08, "30cm": 0.11, "60cm": 0.13},
            texture="sandy_loam",
            water_table_slope="no_water_table",
            water_regime="rainfed",
            field_condition="bare",
        )
        rotations = res["rotation_comparison"]
        self.assertEqual(len(rotations), 3)
        self.assertEqual(rotations[0]["id"], "water_resilience")

        double_crop = next(r for r in rotations if r["id"] == "double_crop")
        self.assertGreaterEqual(len(double_crop["red_alerts"]), 1)

    def test_shallow_water_table_cuenca_del_morro_scenario(self) -> None:
        res = simulate_scenarios(
            field_data={"name": "Cuenca del Morro"},
            user_priority="soil",
            has_livestock=True,
            rainfall_scenario="normal",
            water_table_slope="shallow_water_table",
            horizon="long",
        )
        rotations = res["rotation_comparison"]
        self.assertEqual(rotations[0]["id"], "biological_pump")
        self.assertGreaterEqual(rotations[0]["suitability_score"], 80.0)

    def test_irrigated_mitigates_double_crop_penalty(self) -> None:
        rainfed = simulate_scenarios(
            field_data={},
            user_priority="profit",
            rainfall_scenario="dry",
            water_regime="rainfed",
        )
        irrigated = simulate_scenarios(
            field_data={},
            user_priority="profit",
            rainfall_scenario="dry",
            water_regime="irrigated",
        )
        score_rainfed = next(r for r in rainfed["rotation_comparison"] if r["id"] == "double_crop")["suitability_score"]
        score_irrigated = next(r for r in irrigated["rotation_comparison"] if r["id"] == "double_crop")["suitability_score"]
        self.assertGreater(score_irrigated, score_rainfed)

    def test_adversarial_empty_data_bounded_scores(self) -> None:
        res = simulate_scenarios(
            field_data={"gpm_rainfall_mm": [], "smap_soil_moisture": [], "sentinel2_ndvi": [], "ecostress_surface_temp_c": []},
            user_priority="soil",
            rainfall_scenario="unknown",
            texture="unknown",
        )
        for rot in res["rotation_comparison"]:
            self.assertGreaterEqual(rot["suitability_score"], 0.0)
            self.assertLessEqual(rot["suitability_score"], 100.0)
            self.assertIn("evidence", rot)
            self.assertIn("info_gaps", rot)
            self.assertIn("human_risk", rot)

    def test_evaluate_field_soil_silty(self) -> None:
        soil = evaluate_field_soil(
            texture="silty",
            water_table_slope="sloped_waterlogging",
            water_regime="rainfed",
            field_condition="stubble",
            effective_moisture=0.20,
            bare_months=2,
        )
        self.assertIn("silty", soil["retention_capacity"].lower())
        self.assertGreaterEqual(len(soil["soil_risks"]), 2)

    def test_shallow_soil_and_low_loss_tolerance(self) -> None:
        res_shallow = simulate_scenarios(
            field_data={"name": "Shallow Field"},
            water_regime="rainfed",
            water_table_slope="no_water_table",
            effective_depth_cm=60.0,
            loss_tolerance="low",
        )
        res_deep = simulate_scenarios(
            field_data={"name": "Deep Field"},
            water_regime="rainfed",
            water_table_slope="no_water_table",
            effective_depth_cm=150.0,
            loss_tolerance="high",
        )
        dc_shallow = next(r for r in res_shallow["rotation_comparison"] if r["id"] == "double_crop")
        dc_deep = next(r for r in res_deep["rotation_comparison"] if r["id"] == "double_crop")
        self.assertLess(dc_shallow["suitability_score"], dc_deep["suitability_score"])
        self.assertTrue(any("60 cm < 80 cm" in a for a in dc_shallow["scenario_alerts"]))
        self.assertTrue(any("Low loss tolerance" in a for a in dc_shallow["scenario_alerts"]))

        diag = res_shallow["field_diagnosis"]
        self.assertIn("fao56_balance", diag)
        self.assertEqual(len(diag["fao56_balance"]["crop_demands_mm"]), 6)
        self.assertIn("fao56_warning", diag["fao56_balance"])
        self.assertIn("smap_warning", diag["fao56_balance"])
        self.assertGreaterEqual(len(diag["missing_dimensions"]), 3)

    def test_mvp_homogeneous_map_and_layers(self) -> None:
        self.assertTrue((MVP_HOMOGENEOUS_DIR / "soil_1ha_grid.parquet").is_file())
        layers = get_map_layers()
        self.assertEqual(len(layers["stations"]), 19)
        self.assertGreaterEqual(len(layers["sisinta"]), 60)
        self.assertGreater(len(layers["grid_500m"]), 1000)
        self.assertIn("UNVALIDATED", layers["susceptibility_label"])

        res = query_terrain(lat=-33.675, lon=-65.460)
        ctx = res.get("mvp_context", {})
        self.assertIn("topographic_susceptibility", res["terrain"])
        self.assertIn("nearest_sisinta", ctx)
        self.assertEqual(len(ctx.get("gaez_crops", [])), 6)
        self.assertIn("historical_cell_climate", ctx)
        self.assertIn("mvp-homogeneous", res["provenance"]["elevation"])

    def test_fastapi_endpoints_end_to_end(self) -> None:
        client = TestClient(app)

        r_home = client.get("/")
        self.assertEqual(r_home.status_code, 200)
        self.assertIn("AgroSpin", r_home.text)

        r_fields = client.get("/api/fields")
        self.assertEqual(r_fields.status_code, 200)
        fields_payload = r_fields.json()
        self.assertEqual(len(fields_payload["fields"]), 3)
        self.assertEqual(
            {f["id"] for f in fields_payload["fields"]},
            {"rio_cuarto_north", "vm_central", "vm_south"},
        )

        # Manual evaluation without map
        r_eval = client.post("/api/evaluate", json={
            "field_id": "vm_central",
            "texture": "sandy_loam",
            "water_table_slope": "no_water_table",
            "water_regime": "rainfed",
            "moisture_status": "probe",
            "probe_depth_cm": 30.0,
            "probe_reading": 0.21,
            "manual_annual_rainfall_mm": 640.0,
        })
        self.assertEqual(r_eval.status_code, 200)
        eval_data = r_eval.json()
        self.assertEqual(len(eval_data["cards"]), 3)
        self.assertEqual(eval_data["technical_details"]["projected_annual_rainfall_mm"], 640)

        # Out-of-bounds rejection
        r_oob = client.post("/api/map/query", json={"lat": -32.0, "lon": -65.0})
        self.assertEqual(r_oob.status_code, 400)

        r_layers = client.get("/api/map/layers")
        self.assertEqual(r_layers.status_code, 200)
        self.assertEqual(len(r_layers.json()["stations"]), 19)

        r_map = client.post("/api/map/query", json={"lat": -33.675, "lon": -65.460})
        self.assertEqual(r_map.status_code, 200)
        map_data = r_map.json()
        r_map_eval = client.post("/api/evaluate", json={
            "custom_field_data": map_data["field_data"],
            "water_table_slope": map_data["auto_detected"]["water_table_slope"],
            "moisture_status": map_data["auto_detected"]["moisture_status"],
        })
        self.assertEqual(r_map_eval.status_code, 200)
        map_eval = r_map_eval.json()
        self.assertIn("mvp_context", map_eval)
        self.assertEqual(map_eval["technical_details"]["uncertainty_pct"], 28)
        self.assertIn("UNVALIDATED_CORRELATION", map_eval["technical_details"]["moisture_source"])


if __name__ == "__main__":
    unittest.main()
