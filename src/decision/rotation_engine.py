"""
Agronomic decision engine and rotation evaluator for Field Shift (Villa Mercedes / Justo Daract - San Luis).
Based on a 5-dimension (15-variable) multicriteria rubric, hybrid soil moisture calibration
(NASA SMAP L4 + configurable-depth soil probe), and soil physical-water assessment.

Functional adjustments and calibrations (Functional Analysis & Data Quality):
1. Satellite minimum temperature calibration (-1.04 °C relative to REM Station 42 Villa Mercedes)
   to accurately evaluate the agrometeorological frost threshold (<= 3.0 °C, buffer 4.5 °C).
2. Local root-zone weighted soil moisture probe + cutoff fallback rule
   (SMAP < 0.08 m³/m³ or null percentile without probe -> ±28% uncertainty and test-pit validation).
3. Consensus rainfall and zonal consistency (REM 42 Villa Mercedes and Station 49 Justo Daract /
   Cuenca del Morro, 650-750 mm eastern transition regime).
"""

import json
import math
import pathlib
from typing import Any, Dict, List, Optional

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[2]
RUBRIC_PATH = REPOSITORY_ROOT / "data" / "rotation_rubric.json"

SMAP_SURFACE_DROUGHT_THRESHOLD = 0.08  # m³/m³ in top 0-5 cm without an in-situ probe

_WEIGHTS_BY_PRIORITY: Dict[str, Dict[str, float]] = {
    "water": {
        "water_soil": 0.36,
        "climate_temperature": 0.22,
        "production_sustainability": 0.22,
        "agricultural_health": 0.10,
        "business_market": 0.10,
    },
    "soil": {
        "production_sustainability": 0.34,
        "water_soil": 0.28,
        "climate_temperature": 0.16,
        "agricultural_health": 0.12,
        "business_market": 0.10,
    },
    "profit": {
        "business_market": 0.34,
        "water_soil": 0.24,
        "climate_temperature": 0.18,
        "production_sustainability": 0.14,
        "agricultural_health": 0.10,
    },
}


def load_rubric() -> Dict[str, Any]:
    """Load the official rotation strategies and criteria rubric from data/rotation_rubric.json."""
    if not RUBRIC_PATH.is_file():
        raise FileNotFoundError(f"Rubric file not found at {RUBRIC_PATH}")
    return json.loads(RUBRIC_PATH.read_text(encoding="utf-8"))


def _is_smap_reading_null_or_invalid(value: Optional[float]) -> bool:
    """Detect null percentile, NaN, or non-physical SMAP L4 readings."""
    if value is None:
        return True
    try:
        val_f = float(value)
        return math.isnan(val_f) or math.isinf(val_f) or val_f <= 0.0
    except (TypeError, ValueError):
        return True


def calibrate_soil_moisture(
    smap_surface_moisture: Optional[float],
    probe_readings_cm: Optional[Dict[str, float]] = None,
    probe_depth_cm: Optional[float] = None,
    direct_probe_reading: Optional[float] = None,
    effective_depth_cm: float = 100.0,
    loss_tolerance: str = "low",
    moisture_label: Optional[str] = None,
) -> Dict[str, Any]:
    """
    SMAP L4 measures surface soil moisture (~0-5 cm, sm_surface). In San Luis sandy-loam
    or stubble-covered soils, the top 5 cm can dry from evaporation while plant-available
    water remains stored between 30 and 60 cm.
    If SMAP reports < 0.08 m³/m³ or a null percentile without a probe, the fallback cutoff
    rule activates (±28% uncertainty and test-pit check recommended before penalizing the field).
    """
    smap_invalid = _is_smap_reading_null_or_invalid(smap_surface_moisture)
    smap_val = 0.0 if smap_invalid else float(smap_surface_moisture)

    # Case 1: Point soil probe at user-configured installation depth
    if probe_depth_cm is not None and direct_probe_reading is not None:
        p_cm = float(probe_depth_cm)
        reading = float(direct_probe_reading)

        if p_cm <= 15:
            probe_weight, smap_weight = 0.65, 0.35
            stratum = "surface (0-15 cm)"
            uncertainty = 12
        elif p_cm <= 45:
            probe_weight, smap_weight = 0.80, 0.20
            stratum = f"mid-root stratum ({round(p_cm)} cm)"
            uncertainty = 6
        elif p_cm <= 90:
            probe_weight, smap_weight = 0.85, 0.15
            stratum = f"subsurface profile ({round(p_cm)} cm)"
            uncertainty = 5
        else:
            probe_weight, smap_weight = 0.88, 0.12
            stratum = f"deep profile ({round(p_cm)} cm)"
            uncertainty = 5

        if smap_invalid:
            calibrated_moisture = reading
            deviation_text = "surface SMAP value null/unavailable (direct probe reading prioritized)"
        else:
            calibrated_moisture = (probe_weight * reading) + (smap_weight * smap_val)
            deviation = round((calibrated_moisture - smap_val) * 100, 1)
            deviation_text = f"deviation vs. surface satellite: {deviation:+.1f}%"

        return {
            "effective_moisture": round(calibrated_moisture, 3),
            "source": f"Probe Fusion {round(p_cm)} cm + SMAP Satellite",
            "uncertainty_pct": uncertainty,
            "probe_depth_cm": round(p_cm, 1),
            "direct_probe_reading": round(reading, 3),
            "root_stratum": stratum,
            "requires_test_pit_validation": False,
            "surface_sensor_alert": None,
            "note": f"Local probe at {round(p_cm)} cm ({reading:.2f} m³/m³, {stratum}); {deviation_text}.",
        }

    # Case 2: Standard multi-depth profile (10, 30, and 60 cm)
    if probe_readings_cm:
        actual_profile = (
            0.20 * probe_readings_cm.get("10cm", 0.15)
            + 0.45 * probe_readings_cm.get("30cm", 0.20)
            + 0.35 * probe_readings_cm.get("60cm", 0.22)
        )
        calibrated_moisture = actual_profile if smap_invalid else (0.75 * actual_profile + 0.25 * smap_val)
        deviation_text = (
            "surface SMAP null"
            if smap_invalid
            else f"corrected deviation vs. surface satellite: {round((calibrated_moisture - smap_val) * 100, 1):+.1f}%"
        )

        return {
            "effective_moisture": round(calibrated_moisture, 3),
            "source": "Hybrid Fusion (NASA SMAP + 10/30/60 cm Profile)",
            "uncertainty_pct": 7,
            "probe_depth_cm": 60.0,
            "direct_probe_reading": None,
            "root_stratum": "integrated root profile (0-60 cm)",
            "requires_test_pit_validation": False,
            "surface_sensor_alert": None,
            "note": f"Calibrated multi-depth profile; {deviation_text}.",
        }

    # Case 3: Satellite-only / unvalidated regional model without in-situ probe -> Fallback cutoff rule
    if smap_invalid or smap_val < SMAP_SURFACE_DROUGHT_THRESHOLD or moisture_label == "UNVALIDATED_CORRELATION":
        if moisture_label == "UNVALIDATED_CORRELATION" and not smap_invalid:
            ref_moisture = round(smap_val, 3)
            test_pit_alert = (
                f"UNVALIDATED REGIONAL MOISTURE MODEL (±28% uncertainty): Modeled surface index is {smap_val:.3f} m³/m³ "
                "(daily correlation unvalidated against local probes). Check actual soil moisture at 30-60 cm via test pit "
                "or in-situ probe before ruling out planting."
            )
            src_label = "Regional Soil-Water Model (NASA POWER) [UNVALIDATED_CORRELATION]"
        else:
            smap_detail = (
                "null percentile / no valid SMAP reading"
                if smap_invalid
                else f"very low surface SMAP ({smap_val:.3f} m³/m³ < {SMAP_SURFACE_DROUGHT_THRESHOLD} m³/m³)"
            )
            # Retain measured value (or 0.08 reference floor if null) while blocking critical penalties
            ref_moisture = SMAP_SURFACE_DROUGHT_THRESHOLD if smap_invalid else round(smap_val, 3)
            test_pit_alert = (
                f"HIGH UNCERTAINTY (±28%) FROM SURFACE SENSOR: {smap_detail} detected in the top 5 cm. "
                "In San Luis sandy-loam or stubble-covered soils, plant-available water may still be stored at 30-60 cm. "
                "Verify the soil profile with a test pit or auger before ruling out planting."
            )
            src_label = "NASA SMAP Satellite Only (0-5 cm) [Surface Drought Fallback]"
        return {
            "effective_moisture": ref_moisture,
            "source": src_label,
            "uncertainty_pct": 28,
            "probe_depth_cm": None,
            "direct_probe_reading": None,
            "root_stratum": "strict surface / regional model — deep profile unobserved",
            "requires_test_pit_validation": True,
            "surface_sensor_alert": test_pit_alert,
            "note": test_pit_alert,
        }

    return {
        "effective_moisture": round(smap_val, 3),
        "source": "NASA SMAP Satellite Only (0-5 cm)",
        "uncertainty_pct": 28,
        "probe_depth_cm": None,
        "direct_probe_reading": None,
        "root_stratum": "strict surface (0-5 cm)",
        "requires_test_pit_validation": False,
        "surface_sensor_alert": None,
        "note": "Surface satellite reading (0-5 cm). Contrast with an in-situ probe or test pit is recommended.",
    }


def calibrate_zonal_precipitation(
    rainfall_mm: List[float],
    climate_factor: float = 1.0,
    zone: Optional[str] = None,
    rainfall_origin: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Calibrate annual rainfall by combining raw satellite data (NASA POWER) with the value
    corrected for regional overestimation (+20% at REM 42 Villa Mercedes and Station 49 Justo Daract).
    If the value comes from an observed weather station (OBSERVED_PIHC) or manual user entry (MANUAL_INPUT),
    it is used directly without applying the satellite bias discount.
    Identifies whether the field lies in the eastern transition belt (650-750 mm, Justo Daract /
    Cuenca del Morro), where water-deficit tolerance increases for late maize and sorghum.
    """
    raw_satellite_rainfall = sum(rainfall_mm) if rainfall_mm else 665.0
    if rainfall_origin in ("OBSERVED_PIHC", "MANUAL_INPUT"):
        locally_calibrated_rainfall = raw_satellite_rainfall
        consensus_mean_rainfall = raw_satellite_rainfall
    else:
        locally_calibrated_rainfall = raw_satellite_rainfall / 1.20
        consensus_mean_rainfall = (raw_satellite_rainfall + locally_calibrated_rainfall) / 2.0
    projected_rainfall = consensus_mean_rainfall * climate_factor

    zone_norm = (zone or "villa_mercedes").lower().strip()
    is_east_transition = (
        zone_norm in ("justo_daract", "cuenca_del_morro", "east_transition", "eastern_transition", "station_49")
        or (650.0 <= projected_rainfall <= 780.0)
    )

    if is_east_transition:
        ref_station = "REM Station 49 (Justo Daract / Cuenca del Morro — 650-750 mm eastern transition regime)"
        # Higher summer recharge in the east tolerates slightly lower thresholds without critical failure
        maize_sorghum_deficit_threshold_mm = 580.0
    else:
        ref_station = "REM Station 42 (Villa Mercedes — central semiarid zone)"
        maize_sorghum_deficit_threshold_mm = 620.0

    return {
        "projected_annual_rainfall_mm": round(projected_rainfall),
        "raw_satellite_rainfall_mm": round(raw_satellite_rainfall * climate_factor),
        "locally_calibrated_rainfall_mm": round(locally_calibrated_rainfall * climate_factor),
        "agroecological_zone": "east_transition_650_750" if is_east_transition else "central_semiarid",
        "reference_station": ref_station,
        "is_east_transition": is_east_transition,
        "maize_sorghum_deficit_threshold_mm": maize_sorghum_deficit_threshold_mm,
    }


def calibrate_thermal_minimum(satellite_tmin: float) -> Dict[str, Any]:
    """
    Calibrate satellite minimum temperatures (NASA POWER T2M_MIN vs. REM Station 42 Villa Mercedes).
    Satellite data overestimates minimum temperatures by an average of +1.04 °C (10.30 °C vs. 9.26 °C).
    Evaluates the critical agrometeorological frost threshold (<= 3.0 °C) and preventive buffer (<= 4.5 °C).
    """
    calibrated_tmin = round(satellite_tmin - 1.04, 2)
    frost_risk = calibrated_tmin <= 3.0
    safety_buffer = calibrated_tmin <= 4.5

    if frost_risk:
        alert = (
            f"AGRONOMIC FROST ALERT: Calibrated minimum {calibrated_tmin} °C "
            f"(satellite reported {satellite_tmin} °C). Direct risk during flowering or grain fill."
        )
    elif safety_buffer:
        alert = (
            f"COLD CAUTION: Calibrated minimum {calibrated_tmin} °C, near the "
            "agrometeorological frost damage threshold (3.0 °C)."
        )
    else:
        alert = f"No imminent frost risk: calibrated minimum at {calibrated_tmin} °C."

    return {
        "satellite_tmin_c": satellite_tmin,
        "calibrated_tmin_c": calibrated_tmin,
        "applied_correction_c": -1.04,
        "frost_risk": frost_risk,
        "safety_buffer": safety_buffer,
        "thermal_alert": alert,
    }


def evaluate_field_soil(
    texture: str,
    water_table_slope: str,
    water_regime: str,
    field_condition: str,
    effective_moisture: float,
    bare_months: int,
    requires_test_pit_validation: bool = False,
) -> Dict[str, Any]:
    """
    Evaluate physical, water, and conservation status of the soil based on technical criteria
    for San Luis (retention, wind/water erosion, surface crusting, and shallow water table).
    """
    soil_risks: List[str] = []
    if texture == "sandy_loam":
        retention_capacity = "Low to moderate (light sandy-loam soil)"
        soil_risks.append(
            "High susceptibility to wind erosion (winter blowouts) and low water-storage capacity per centimeter of profile."
        )
    elif texture == "silty":
        retention_capacity = "Moderate to high (silty-loam soil)"
        soil_risks.append(
            "Risk of surface crusting (sealing) and runoff following intense summer rainfall events."
        )
    else:
        retention_capacity = "Variable (requires particle-size lab analysis by horizon)"
        soil_risks.append(
            "Unconfirmed texture: inspect effective rooting depth and potential tillage pans or compaction."
        )

    if water_table_slope == "shallow_water_table":
        soil_risks.append(
            "Shallow water table: risk of capillary rise, waterlogging, or salinization without active year-round water uptake."
        )
    elif water_table_slope == "sloped_waterlogging":
        soil_risks.append(
            "Sloped field or flat lowland: requires living cover or anchored stubble to halt gullies and runoff."
        )

    if bare_months >= 4 or field_condition == "bare":
        soil_risks.append(
            "Prolonged bare fallow: accelerates direct soil evaporation and organic matter loss."
        )

    if requires_test_pit_validation:
        reserve_status = "Undetermined at depth (dry surface in SMAP; check plant-available water at 30-60 cm via test pit)"
    elif water_regime == "rainfed" and effective_moisture < 0.14:
        reserve_status = "Tight / low initial soil moisture reserve"
    elif effective_moisture >= 0.24:
        reserve_status = "Good soil-profile moisture recharge"
    else:
        reserve_status = "Moderate soil moisture reserve"

    return {
        "texture": texture,
        "retention_capacity": retention_capacity,
        "water_table_slope": water_table_slope,
        "water_regime": water_regime,
        "reserve_status": reserve_status,
        "soil_risks": soil_risks,
    }


def _compute_base_dimensions(method: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Compute the normalized (0-100) mean score for each of the 5 evaluation dimensions."""
    result: Dict[str, Dict[str, Any]] = {}
    for dim_key, dim_data in method["dimensions"].items():
        criteria = dim_data["criteria"]
        avg_1_5 = sum(c["score"] for c in criteria) / len(criteria)
        score_100 = round((avg_1_5 / 5.0) * 100.0, 1)
        result[dim_key] = {
            "name": dim_data["name"],
            "avg_1_5": round(avg_1_5, 2),
            "score_100": score_100,
            "criteria": criteria,
        }
    return result


def simulate_scenarios(
    field_data: Dict[str, Any],
    user_priority: str = "soil",
    has_livestock: bool = False,
    rainfall_scenario: str = "normal",
    probe_readings: Optional[Dict[str, float]] = None,
    texture: str = "sandy_loam",
    water_table_slope: str = "no_water_table",
    water_regime: str = "rainfed",
    field_condition: str = "stubble",
    horizon: str = "medium",
    production_system: str = "agricultural",
    probe_depth_cm: Optional[float] = None,
    direct_probe_reading: Optional[float] = None,
    effective_depth_cm: float = 100.0,
    loss_tolerance: str = "low",
) -> Dict[str, Any]:
    """
    Simulate and compare the 3 real rubric rotation strategies for a San Luis field
    (Villa Mercedes and eastern Justo Daract transition zone).
    """
    rubric = load_rubric()
    climate_factors = {"dry": 0.75, "normal": 1.0, "wet": 1.20}
    climate_factor = climate_factors.get(rainfall_scenario, 1.0)

    # Consensus precipitation calibration and zonal consistency (REM 42 and Station 49)
    rainfall_series = field_data.get("gpm_rainfall_mm", [665 / 12] * 12)
    field_zone = field_data.get("agroecological_zone") or field_data.get("zone", "villa_mercedes")
    rainfall_info = calibrate_zonal_precipitation(
        rainfall_series,
        climate_factor=climate_factor,
        zone=field_zone,
        rainfall_origin=field_data.get("rainfall_origin"),
    )
    projected_rainfall = rainfall_info["projected_annual_rainfall_mm"]
    is_east_transition = rainfall_info["is_east_transition"]
    maize_sorghum_deficit_threshold = rainfall_info["maize_sorghum_deficit_threshold_mm"]

    ndvi_series = field_data.get("sentinel2_ndvi", [0.3] * 12)
    bare_months = sum(1 for ndvi in ndvi_series if ndvi < 0.25)

    temps = field_data.get("ecostress_surface_temp_c", [35.0])
    summer_max_temp = max(temps) if temps else 35.0
    satellite_tmin = field_data.get("satellite_tmin_c", 3.8)
    temp_origin = field_data.get("temp_origin")
    if temp_origin in ("OBSERVED_SMN", "OBSERVED_STATION_WEIGHTED", "OBSERVED_REM"):
        temp_prefix = (
            "Observed SMN station reading"
            if temp_origin == "OBSERVED_SMN"
            else "Observed corridor station-weighted p10 minimum"
        )
        frost_analysis = {
            "satellite_tmin_c": round(satellite_tmin, 2),
            "calibrated_tmin_c": round(satellite_tmin, 2),
            "frost_risk": satellite_tmin <= 3.0,
            "safety_buffer": satellite_tmin <= 4.5,
            "applied_correction_c": 0.0,
            "thermal_alert": (
                f"{temp_prefix} ({satellite_tmin:.2f} °C): "
                + ("Agrometeorological frost risk (<= 3.0 °C)." if satellite_tmin <= 3.0 else "No immediate frost risk.")
            ),
        }
    else:
        frost_analysis = calibrate_thermal_minimum(satellite_tmin)

    smap_series = field_data.get("smap_soil_moisture", [0.18])
    valid_smap = [v for v in smap_series if not _is_smap_reading_null_or_invalid(v)]
    mean_smap: Optional[float] = (sum(valid_smap) / len(valid_smap)) if valid_smap else None

    moisture_info = calibrate_soil_moisture(
        mean_smap,
        probe_readings,
        probe_depth_cm,
        direct_probe_reading,
        effective_depth_cm=effective_depth_cm,
        loss_tolerance=loss_tolerance,
        moisture_label=field_data.get("moisture_label"),
    )
    effective_moisture = moisture_info["effective_moisture"]
    requires_test_pit = moisture_info["requires_test_pit_validation"]

    soil_eval = evaluate_field_soil(
        texture=texture,
        water_table_slope=water_table_slope,
        water_regime=water_regime,
        field_condition=field_condition,
        effective_moisture=effective_moisture,
        bare_months=bare_months,
        requires_test_pit_validation=requires_test_pit,
    )

    weights = dict(_WEIGHTS_BY_PRIORITY.get(user_priority, _WEIGHTS_BY_PRIORITY["soil"]))
    if has_livestock or production_system == "mixed":
        weights["production_sustainability"] = round(weights["production_sustainability"] + 0.05, 2)
        weights["business_market"] = max(0.05, round(weights["business_market"] - 0.05, 2))

    _CROP_DEMANDS = [
        ("Wheat", 450, 650, "mm/cycle"),
        ("Soybean", 450, 700, "mm/cycle"),
        ("Maize", 500, 800, "mm/cycle"),
        ("Sorghum", 450, 650, "mm/cycle"),
        ("Sunflower", 600, 1000, "mm/cycle"),
        ("Alfalfa", 800, 1600, "mm/reference period"),
    ]
    _DEMAND_BY_METHOD = {
        "double_crop": "450-650 (Wheat) + 450-700 (Soybean) mm/cycle",
        "biological_pump": "800-1600 mm/reference period (Alfalfa / pasture)",
        "water_resilience": "450-650 (Sorghum) / 500-800 (Maize) / 450-700 (Soybean) mm/cycle",
    }
    crop_demands_mm = []
    for crop, d_min, d_max, unit in _CROP_DEMANDS:
        if projected_rainfall < d_min:
            indicative_status = "below_range"
        elif projected_rainfall <= d_max:
            indicative_status = "in_range"
        else:
            indicative_status = "above_range"
        crop_demands_mm.append({
            "crop": crop,
            "min_mm": d_min,
            "max_mm": d_max,
            "unit": unit,
            "indicative_status": indicative_status,
        })

    diagnosis = {
        "field": field_data.get("name", "Villa Mercedes Pilot Field"),
        "agroecological_zone": rainfall_info["agroecological_zone"],
        "reference_rain_station": rainfall_info["reference_station"],
        "soil": soil_eval["retention_capacity"],
        "soil_evaluation": soil_eval,
        "mvp_context": field_data.get("mvp_context"),
        "effective_depth_cm": effective_depth_cm,
        "loss_tolerance": loss_tolerance,
        "projected_annual_rainfall_mm": projected_rainfall,
        "raw_satellite_rainfall_mm": rainfall_info["raw_satellite_rainfall_mm"],
        "locally_calibrated_rainfall_mm": rainfall_info["locally_calibrated_rainfall_mm"],
        "bare_soil_months": bare_months,
        "ecostress_thermal_peak_c": summer_max_temp,
        "frost_analysis": frost_analysis,
        "moisture_status": moisture_info,
        "applied_weights": weights,
        "fao56_balance": {
            "projected_rainfall_mm": round(projected_rainfall),
            "crop_demands_mm": crop_demands_mm,
            "fao56_warning": (
                "Indicative rainfall vs. ETc comparison (FAO-56). Projected annual rainfall below crop water demand "
                "does NOT automatically imply a deficit: initial stored soil moisture, effective rainfall, runoff, "
                "deep drainage, and capillary contribution from a water table all play a role."
            ),
            "smap_warning": (
                "Regional SMAP surface soil moisture (0-5 cm) provides macro context only and is NOT equivalent "
                "to root-zone plant-available water nor a substitute for field-scale measurements."
            ),
        },
        "missing_dimensions": [
            "3-5 year field agronomic history (previous rotations, yields, and weed pressure).",
            "Laboratory particle-size analysis, organic matter content, and NPK nutrient balance (biological N fixation does not replace fertilization).",
            "Local gross margin (USD/ha or ARS/ha) and financial assessment separating annual OPEX from multi-year CAPEX.",
        ],
        "primary_alert": (
            moisture_info["surface_sensor_alert"]
            if requires_test_pit and moisture_info["surface_sensor_alert"]
            else (
                soil_eval["soil_risks"][0]
                if soil_eval["soil_risks"]
                else "Soil shows a stable moisture balance and surface cover."
            )
        ),
    }

    results: List[Dict[str, Any]] = []

    for method in rubric["methods"]:
        m_id = method["id"]
        dims = _compute_base_dimensions(method)

        base_score = sum(dims[k]["score_100"] * weights[k] for k in dims)

        adjustment = 0.0
        scenario_alerts: List[str] = []
        red_alerts: List[str] = []

        # Contextual rules by agronomic strategy and actual field conditions
        if m_id == "double_crop":
            if probe_depth_cm and probe_depth_cm <= 25 and effective_moisture < 0.16:
                adjustment -= 8.0
                scenario_alerts.append(
                    f"Probe at {round(probe_depth_cm)} cm indicates dry seedbed ({effective_moisture} m³/m³): risk of uneven emergence in second-crop planting."
                )
            elif probe_depth_cm and probe_depth_cm >= 40 and effective_moisture >= 0.22 and water_regime != "irrigated":
                adjustment += 4.0
                scenario_alerts.append(
                    f"Probe at {round(probe_depth_cm)} cm confirms subsurface moisture ({effective_moisture} m³/m³), supporting grain fill for late maize or double-crop soybean."
                )

            if water_regime == "rainfed" and water_table_slope != "shallow_water_table":
                # If SMAP < 0.08 or null without probe, withhold the critical penalty (-22) until test-pit check
                if requires_test_pit:
                    adjustment -= 8.0
                    scenario_alerts.append(
                        "PENDING TEST-PIT VALIDATION: Satellite only sees dry top 5 cm (±28% uncertainty). "
                        "Inspect profile at 30-60 cm via test pit before discarding the second crop."
                    )
                elif rainfall_scenario == "dry" or effective_moisture < 0.16 or projected_rainfall < maize_sorghum_deficit_threshold:
                    if is_east_transition and projected_rainfall >= 650 and rainfall_scenario != "dry" and effective_moisture >= 0.14:
                        # Expanded tolerance for late maize in eastern transition (Justo Daract 650-750 mm)
                        adjustment -= 10.0
                        scenario_alerts.append(
                            f"Eastern transition regime ({projected_rainfall} mm, ref. Justo Daract): "
                            "allows late maize after wheat if harvested early and spring recharge occurs."
                        )
                    else:
                        adjustment -= 22.0
                        red_alerts.append(
                            "WATER RED ALERT: Under rainfed conditions without a shallow water table, winter wheat depletes soil water "
                            "and leaves a dry profile for double-crop soybean or late maize, creating high yield-loss risk."
                        )
                else:
                    adjustment -= 10.0
                    scenario_alerts.append(
                        "Water-demanding strategy: requires early wheat harvest (late November) and immediate no-till seeding into stubble to capture summer rains."
                    )

                frost_basis = (
                    "observed ground-station composite"
                    if frost_analysis.get("applied_correction_c", 0.0) == 0.0
                    else "-1.04 °C vs. satellite"
                )
                red_alerts.append(
                    f"EARLY FROST ALERT: Transition minimum temperature {frost_analysis['calibrated_tmin_c']} °C ({frost_basis}). "
                    "Delaying late maize or second-crop soybean seeding past mid-December exposes grain fill to early autumn frosts."
                )
            elif water_regime == "irrigated":
                adjustment += 14.0
                scenario_alerts.append(
                    "Supplemental irrigation offsets wheat winter water drawdown and secures establishment of the second crop."
                )
            elif water_table_slope == "shallow_water_table":
                adjustment += 6.0
                scenario_alerts.append(
                    "A shallow water table supplies moisture via capillary rise for the second crop, though annual uptake is lower than a perennial pasture."
                )

        elif m_id == "biological_pump":
            if probe_depth_cm and probe_depth_cm >= 50 and effective_moisture >= 0.22:
                adjustment += 8.0
                scenario_alerts.append(
                    f"Probe at {round(probe_depth_cm)} cm confirms deep moisture ({effective_moisture} m³/m³): optimal condition for autumn alfalfa establishment."
                )
            elif probe_depth_cm and probe_depth_cm >= 50 and effective_moisture < 0.14:
                adjustment -= 6.0
                scenario_alerts.append(
                    f"Probe at {round(probe_depth_cm)} cm indicates dry deep profile ({effective_moisture} m³/m³): wait for autumn recharge before seeding alfalfa."
                )

            if water_table_slope in ("shallow_water_table", "sloped_waterlogging"):
                adjustment += 15.0
                scenario_alerts.append(
                    "Recommended strategy for Cuenca del Morro and lowlands: alfalfa acts as a biological pump, lowering the water table year-round and halting water erosion."
                )
            elif rainfall_scenario == "dry" and water_regime == "rainfed" and water_table_slope == "no_water_table":
                adjustment -= 8.0
                scenario_alerts.append(
                    "In dry rainfed years without a water table, terminate alfalfa early (late winter) to allow soil-profile recharge before late maize."
                )

            if production_system == "contractor" and method["requires_special_machinery"]:
                adjustment -= 6.0
                scenario_alerts.append(
                    "Requires coordination with a forage contractor (mowing, raking, and round/large square baling) or direct livestock grazing."
                )

        elif m_id == "water_resilience":
            if probe_depth_cm and probe_depth_cm >= 30 and effective_moisture < 0.18:
                adjustment += 6.0
                scenario_alerts.append(
                    f"Probe at {round(probe_depth_cm)} cm shows tight moisture ({effective_moisture} m³/m³): root hardiness of grain sorghum or sunflower stabilizes the yield floor."
                )

            if water_regime == "rainfed" and (
                rainfall_scenario == "dry"
                or effective_moisture < 0.18
                or texture == "sandy_loam"
                or requires_test_pit
            ):
                adjustment += 10.0
                scenario_alerts.append(
                    "High reliability on sandy-loam soils and in dry years: rye + vetch anchors topsoil against winter wind erosion. "
                    "Terminate vetch before October to avoid depleting planting moisture for sorghum or sunflower."
                )

            if is_east_transition and projected_rainfall >= 650:
                adjustment += 4.0
                scenario_alerts.append(
                    f"In the eastern transition belt ({projected_rainfall} mm, ref. Justo Daract), biological nitrogen from vetch + spring recharge boosts yield potential in sorghum or late maize."
                )

            if water_table_slope == "shallow_water_table":
                adjustment -= 6.0
                scenario_alerts.append(
                    "With a rising water table, annual crops consume less excess groundwater than perennial alfalfa."
                )
            if field_condition == "bare":
                adjustment += 4.0
                scenario_alerts.append(
                    "The rye + hairy vetch mix rapidly covers bare ground, reduces evaporation, and contributes biological nitrogen."
                )

        # Effective soil depth (TAW) modifier
        if effective_depth_cm < 80:
            if m_id == "double_crop" and water_regime == "rainfed":
                adjustment -= 10.0
                scenario_alerts.append(
                    f"Shallow soil ({round(effective_depth_cm)} cm < 80 cm): reduces total available water (TAW) and heightens water risk in rainfed double cropping."
                )
            elif m_id == "biological_pump" and water_table_slope == "no_water_table":
                adjustment -= 8.0
                scenario_alerts.append(
                    f"Shallow soil ({round(effective_depth_cm)} cm < 80 cm) without a water table: limits deep root exploration of perennial pastures."
                )
            elif m_id == "water_resilience":
                adjustment += 4.0
                scenario_alerts.append(
                    f"Shallow soil ({round(effective_depth_cm)} cm): prioritize hardy crops (e.g., sorghum) and continuous residue cover."
                )

        # Loss tolerance / financial risk modifier
        if loss_tolerance == "low":
            if m_id == "double_crop":
                adjustment -= 8.0
                scenario_alerts.append(
                    "Low loss tolerance: annual double cropping doubles operating capital exposure (OPEX) within a single season."
                )
            elif m_id == "water_resilience":
                adjustment += 6.0
            elif m_id == "biological_pump":
                adjustment -= 3.0
                scenario_alerts.append(
                    "Low loss tolerance: requires evaluating initial capital lock-up (CAPEX) for pasture establishment."
                )
        elif loss_tolerance == "high" and m_id == "double_crop":
            adjustment += 4.0

        # Planning horizon modifier
        if horizon == method["horizon"]:
            adjustment += 5.0
        elif horizon == "short" and method["horizon"] == "long":
            adjustment -= 8.0
            scenario_alerts.append("Requires a multi-year commitment (4-5 years), exceeding the selected short-term horizon.")

        # Livestock integration modifier
        if has_livestock and method["suitable_for_livestock"]:
            adjustment += 5.0

        final_score = max(0.0, min(100.0, round(base_score + adjustment, 1)))

        evidence_text = "; ".join(f"{s['institution']}: {s['title']}" for s in method["sources"])
        risk_text = " | ".join(red_alerts) if red_alerts else method["when_to_rotate"]
        gaps_text = (
            "Dig a 30-60 cm test pit to verify subsurface plant-available moisture, horizon texture, and water-table depth."
            if requires_test_pit
            else "Validate soil laboratory tests (texture and organic matter), water-table depth, and actual planting window with a local agronomist."
        )

        results.append({
            "id": m_id,
            "name": method["name"],
            "sequence": method["sequence"],
            "horizon_label": method["horizon_label"],
            "water_demand_mm": _DEMAND_BY_METHOD.get(m_id, "450-800 mm/cycle (indicative)"),
            "suitability_score": final_score,
            "base_dimension_score": round(base_score, 1),
            "contextual_adjustment": round(adjustment, 1),
            "field_summary": method["field_summary"],
            "when_to_rotate": method["when_to_rotate"],
            "termination_criterion": method["termination_criterion"],
            "red_alerts": red_alerts,
            "scenario_alerts": scenario_alerts,
            "dimensions": dims,
            "sources": method["sources"],
            "evidence": evidence_text,
            "info_gaps": gaps_text,
            "human_risk": risk_text,
        })

    results.sort(key=lambda x: x["suitability_score"], reverse=True)
    return {
        "field_diagnosis": diagnosis,
        "rotation_comparison": results,
    }
