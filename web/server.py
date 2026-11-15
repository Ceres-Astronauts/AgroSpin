"""FastAPI web server for the Field Shift producer decision interface."""

import json
import pathlib
import sys
from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.decision.map_data import get_map_layers, query_terrain  # noqa: E402
from src.decision.rotation_engine import load_rubric, simulate_scenarios  # noqa: E402

PILOT_FIELDS_DEFAULT = REPOSITORY_ROOT / "data" / "pilot_fields.json"
STATIC_DIR = pathlib.Path(__file__).resolve().parent / "static"

app = FastAPI(title="Field Shift — Ceres Agronauts", version="2.0.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

_MOISTURE_PRESETS: Dict[str, Dict[str, float]] = {
    "dry": {"10cm": 0.08, "30cm": 0.11, "60cm": 0.13},
    "normal": {"10cm": 0.17, "30cm": 0.21, "60cm": 0.23},
    "wet": {"10cm": 0.28, "30cm": 0.32, "60cm": 0.34},
}


class EvaluationRequest(BaseModel):
    field_id: str = Field(default="vm_central")
    texture: Literal["sandy_loam", "silty", "unknown"] = "sandy_loam"
    water_table_slope: Literal["no_water_table", "shallow_water_table", "sloped_waterlogging"] = "no_water_table"
    water_regime: Literal["rainfed", "irrigated"] = "rainfed"
    moisture_status: Literal["dry", "normal", "wet", "probe"] = "normal"
    probe_depth_cm: Optional[float] = Field(default=None, ge=5.0, le=200.0, description="Soil probe installation depth in cm")
    probe_reading: Optional[float] = Field(default=None, ge=0.03, le=0.55, description="Soil moisture reading at probe depth in m³/m³")
    probe_10cm: Optional[float] = Field(default=None, ge=0.05, le=0.45)
    probe_30cm: Optional[float] = Field(default=None, ge=0.05, le=0.45)
    probe_60cm: Optional[float] = Field(default=None, ge=0.05, le=0.45)
    field_condition: Literal["stubble", "bare", "degraded_pasture"] = "stubble"
    rainfall_scenario: Literal["dry", "normal", "wet"] = "normal"
    priority: Literal["water", "profit", "soil"] = "soil"
    horizon: Literal["short", "medium", "long"] = "medium"
    production_system: Literal["agricultural", "mixed", "contractor"] = "agricultural"
    has_livestock: bool = False
    soil_depth: Literal["shallow", "medium", "deep"] = "medium"
    loss_tolerance: Literal["low", "moderate", "high"] = "low"
    manual_annual_rainfall_mm: Optional[float] = Field(default=None, ge=50.0, le=3000.0)
    custom_field_data: Optional[Dict[str, Any]] = None


class MapQueryRequest(BaseModel):
    lat: Optional[float] = None
    lon: Optional[float] = None
    polygon: Optional[List[List[float]]] = None


def _load_fields() -> List[Dict[str, Any]]:
    if PILOT_FIELDS_DEFAULT.is_file():
        try:
            data = json.loads(PILOT_FIELDS_DEFAULT.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return data
            if isinstance(data, dict) and "fields" in data:
                return data["fields"]
        except Exception:
            pass
    return [
        {
            "id": "vm_central",
            "name": "Villa Mercedes — Pilot Field (INTA San Luis)",
            "soil": "Sandy-loam",
            "gpm_rainfall_mm": [55.4] * 12,
            "smap_soil_moisture": [0.18] * 12,
            "sentinel2_ndvi": [0.35, 0.38, 0.32, 0.22, 0.18, 0.17, 0.19, 0.21, 0.28, 0.36, 0.42, 0.40],
            "ecostress_surface_temp_c": [36.5],
        }
    ]


def _classify_traffic_light(score: float, has_red_alert: bool) -> Literal["recommended", "caution", "not_recommended"]:
    if has_red_alert or score < 50:
        return "not_recommended"
    if score >= 68:
        return "recommended"
    return "caution"


def _field_check_points(diag: Dict[str, Any], req: EvaluationRequest) -> List[str]:
    points: List[str] = []
    if diag["bare_soil_months"] >= 4 or req.field_condition == "bare":
        points.append(
            "Evaluate with a local advisor how to keep winter cover on the field (for example rye + vetch) to prevent wind erosion during August-September gusts."
        )
    if req.water_table_slope == "shallow_water_table":
        points.append(
            "Verify water-table depth and salinity across the field: if rising (as in Cuenca del Morro), evaluate perennial alfalfa as a biological pump."
        )
    elif req.water_table_slope == "sloped_waterlogging":
        points.append(
            "Inspect low-lying drainage paths and runoff channels during heavy summer storms; consider waterlogging-tolerant species or permanent living cover."
        )

    if req.water_regime == "rainfed" and (req.rainfall_scenario == "dry" or diag["moisture_status"]["effective_moisture"] < 0.16):
        points.append(
            "Confirm actual plant-available water at 1-2 m depth before seeding: under rainfed low-reserve conditions, avoid annual double cropping and adjust planting date/density."
        )
    else:
        points.append(
            "Validate spring cover-crop termination timing (30-45 days before summer crop planting) so cover growth does not compete with spring recharge."
        )

    if req.texture == "unknown":
        points.append("Run laboratory particle-size texture, pH, and effective rooting depth testing before locking in fertilization or sensitive crops.")
    return points


def _collect_supporting_sources(rotations: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Consolidate and deduplicate all bibliographic sources for the supporting sources menu."""
    seen = set()
    consolidated = []
    for rot in rotations:
        for src in rot.get("sources", []):
            key = (src.get("institution", ""), src.get("title", ""))
            if key not in seen:
                seen.add(key)
                consolidated.append({
                    "rotation": rot["name"],
                    "institution": src.get("institution", "Unknown"),
                    "title": src.get("title", "Untitled"),
                    "url": src.get("url", "#"),
                    "contribution": src.get("contribution", ""),
                })
    return consolidated


def _detailed_technical_analysis(diag: Dict[str, Any], req: EvaluationRequest) -> List[Dict[str, str]]:
    hum = diag["moisture_status"]
    soil = diag["soil_evaluation"]
    return [
        {
            "title": "1. Soil physical and water assessment",
            "detail": (
                f"Declared texture: {soil['retention_capacity']}. Water regime: {req.water_regime}. "
                f"Reserve status: {soil['reserve_status']}. "
                + " ".join(soil["soil_risks"])
            ),
        },
        {
            "title": "2. Water balance and soil-moisture uncertainty",
            "detail": (
                f"Projected rainfall: {diag['projected_annual_rainfall_mm']} mm/yr ('{req.rainfall_scenario}' scenario). "
                f"Calibrated effective moisture: {hum['effective_moisture']} m³/m³ ({hum['source']}, ±{hum['uncertainty_pct']}% uncertainty). "
                f"{hum.get('note', '')}"
            ),
        },
        {
            "title": "3. Surface cover, thermal stress, and frost window",
            "detail": (
                f"Estimated {diag['bare_soil_months']} months with low cover (NDVI < 0.25) and surface thermal peak of {diag['ecostress_thermal_peak_c']} °C. "
                "In Villa Mercedes, agrometeorological frosts (<3 °C) historically span Mar 29 (±24 d) to Nov 09 (±19 d), constraining late second-crop windows."
            ),
        },
    ]


@app.get("/")
def home() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/fields")
def list_fields() -> Dict[str, Any]:
    fields = _load_fields()
    summary = [
        {
            "id": field.get("id", f"field_{i}"),
            "name": field.get("name", f"Field {i + 1}"),
            "soil": field.get("soil", "Sandy-loam"),
        }
        for i, field in enumerate(fields)
    ]
    return {"fields": summary}


@app.get("/api/map/layers")
def map_layers() -> Dict[str, Any]:
    try:
        return get_map_layers()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/map/query")
def query_map(req: MapQueryRequest) -> Dict[str, Any]:
    try:
        return query_terrain(lat=req.lat, lon=req.lon, polygon=req.polygon)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/evaluate")
def evaluate_field(req: EvaluationRequest) -> Dict[str, Any]:
    if req.custom_field_data:
        field_data = dict(req.custom_field_data)
    else:
        fields = _load_fields()
        field = next((x for x in fields if x.get("id") == req.field_id), fields[0] if fields else None)
        if not field:
            raise HTTPException(status_code=404, detail="Selected field was not found.")
        field_data = dict(field)

    if req.manual_annual_rainfall_mm is not None:
        base_rain = field_data.get("gpm_rainfall_mm") or [1.0] * 12
        base_sum = sum(base_rain) or 12.0
        factor = req.manual_annual_rainfall_mm / base_sum
        field_data["gpm_rainfall_mm"] = [round(v * factor, 2) for v in base_rain]
        field_data["rainfall_origin"] = "MANUAL_INPUT"

    if req.field_condition == "bare":
        field_data["sentinel2_ndvi"] = [0.15] * 12
    elif req.field_condition == "degraded_pasture":
        field_data["sentinel2_ndvi"] = [0.45] * 12

    probe_depth_cm = None
    direct_probe_reading = None

    if req.moisture_status == "probe":
        if req.probe_depth_cm is not None and req.probe_reading is not None:
            probe_depth_cm = req.probe_depth_cm
            direct_probe_reading = req.probe_reading
            probe_readings = None
        else:
            probe_readings = {
                "10cm": req.probe_10cm if req.probe_10cm is not None else 0.17,
                "30cm": req.probe_30cm if req.probe_30cm is not None else 0.21,
                "60cm": req.probe_60cm if req.probe_60cm is not None else 0.23,
            }
    elif req.custom_field_data is not None:
        # Map mode relies on the regional modeled moisture estimate unless the producer enters probe readings
        probe_readings = None
    else:
        probe_readings = _MOISTURE_PRESETS[req.moisture_status]

    _DEPTH_MAP = {"shallow": 60.0, "medium": 100.0, "deep": 150.0}
    effective_depth_cm = _DEPTH_MAP.get(req.soil_depth, 100.0)

    sim = simulate_scenarios(
        field_data=field_data,
        user_priority=req.priority,
        has_livestock=req.has_livestock or req.production_system == "mixed",
        rainfall_scenario=req.rainfall_scenario,
        probe_readings=probe_readings,
        texture=req.texture,
        water_table_slope=req.water_table_slope,
        water_regime=req.water_regime,
        field_condition=req.field_condition,
        horizon=req.horizon,
        production_system=req.production_system,
        probe_depth_cm=probe_depth_cm,
        direct_probe_reading=direct_probe_reading,
        effective_depth_cm=effective_depth_cm,
        loss_tolerance=req.loss_tolerance,
    )

    diag = sim["field_diagnosis"]
    cards = []
    for item in sim["rotation_comparison"]:
        score = item["suitability_score"]
        red_alerts = item.get("red_alerts", [])
        traffic_light = _classify_traffic_light(score, len(red_alerts) > 0)
        cards.append(
            {
                "id": item["id"],
                "name": item["name"],
                "sequence": item["sequence"],
                "horizon_label": item["horizon_label"],
                "water_demand_mm": item.get("water_demand_mm"),
                "traffic_light": traffic_light,
                "score": score,
                "base_score": item["base_dimension_score"],
                "contextual_adjustment": item["contextual_adjustment"],
                "summary": item["field_summary"],
                "when_to_rotate": item["when_to_rotate"],
                "termination_criterion": item["termination_criterion"],
                "red_alerts": red_alerts,
                "alerts": item.get("scenario_alerts", []),
                "dimensions": item["dimensions"],
                "sources": item["sources"],
            }
        )

    return {
        "field": diag["field"],
        "soil": diag["soil"],
        "primary_alert": diag["primary_alert"],
        "cards": cards,
        "field_check_points": _field_check_points(diag, req),
        "technical_analysis": _detailed_technical_analysis(diag, req),
        "supporting_sources": _collect_supporting_sources(sim["rotation_comparison"]),
        "applied_weights": diag["applied_weights"],
        "fao56_balance": diag.get("fao56_balance"),
        "missing_dimensions": diag.get("missing_dimensions", []),
        "effective_depth_cm": diag.get("effective_depth_cm"),
        "loss_tolerance": diag.get("loss_tolerance"),
        "mvp_context": diag.get("mvp_context"),
        "technical_details": {
            "projected_annual_rainfall_mm": diag["projected_annual_rainfall_mm"],
            "effective_moisture_m3_m3": diag["moisture_status"]["effective_moisture"],
            "uncertainty_pct": diag["moisture_status"]["uncertainty_pct"],
            "moisture_source": diag["moisture_status"]["source"],
            "thermal_peak_c": diag["ecostress_thermal_peak_c"],
            "bare_soil_months": diag["bare_soil_months"],
        },
    }
