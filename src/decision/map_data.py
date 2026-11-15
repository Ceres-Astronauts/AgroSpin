"""
Geospatial data access module reading exclusively from repository-tracked English-schema
MVP datasets in data/reference/mvp-homogeneous/ for the MVP bounding box
(lon [-65.875, -64.125], lat [-33.875, -33.125], EPSG:4326).
"""

import datetime as _dt
import math
import pathlib
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[2]
MVP_HOMOGENEOUS_DIR = REPOSITORY_ROOT / "data" / "reference" / "mvp-homogeneous"

BBOX_MVP = {
    "lat_min": -33.875,
    "lat_max": -33.125,
    "lon_min": -65.875,
    "lon_max": -64.125,
}

_GAEZ_CROP_ORDER: List[str] = ["wheat", "soybean", "maize", "sorghum", "sunflower", "alfalfa"]

_CACHE: Dict[str, Any] = {}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r_km = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * r_km * math.asin(min(1.0, math.sqrt(a)))


def _points_in_polygon(lats: np.ndarray, lons: np.ndarray, polygon: List[List[float]]) -> np.ndarray:
    """Vectorized NumPy ray-casting algorithm for points inside a polygon [[lat, lon], ...]."""
    n = len(polygon)
    inside = np.zeros(len(lats), dtype=bool)
    p1_lat, p1_lon = polygon[0][0], polygon[0][1]
    for i in range(1, n + 1):
        p2_lat, p2_lon = polygon[i % n][0], polygon[i % n][1]
        cond_lat = ((p1_lat <= lats) & (lats < p2_lat)) | ((p2_lat <= lats) & (lats < p1_lat))
        denom = (p2_lat - p1_lat) if (p2_lat - p1_lat) != 0 else 1e-12
        x_intersec = (lats - p1_lat) * (p2_lon - p1_lon) / denom + p1_lon
        inside ^= cond_lat & (lons < x_intersec)
        p1_lat, p1_lon = p2_lat, p2_lon
    return inside


def _build_monthly_grid(
    df: pd.DataFrame,
    value_cols: List[str],
    year_max: int = 2025,
) -> List[Dict[str, Any]]:
    """Aggregate monthly 1991-2025 climatologies into 12-month arrays per grid cell."""
    hist = df[df["year"] <= year_max].copy()
    if hist.empty:
        hist = df.copy()
    grouped = (
        hist.groupby(["point_id", "lat", "lon", "month"], as_index=False)[value_cols]
        .mean()
        .sort_values(["point_id", "month"])
    )
    cells: List[Dict[str, Any]] = []
    for (pt_id, lat, lon), sub in grouped.groupby(["point_id", "lat", "lon"], sort=True):
        by_month = sub.set_index("month")
        entry: Dict[str, Any] = {
            "point_id": str(pt_id),
            "lat": float(lat),
            "lon": float(lon),
        }
        for col in value_cols:
            fallback = float(sub[col].mean())
            entry[col] = [
                round(float(by_month.loc[m, col]) if m in by_month.index else fallback, 4)
                for m in range(1, 13)
            ]
        cells.append(entry)
    return cells


def _idw_interpolate_grid(
    lat: float,
    lon: float,
    cells: List[Dict[str, Any]],
    value_keys: List[str],
    k: int = 4,
) -> Tuple[Dict[str, List[float]], List[Dict[str, Any]]]:
    """Interpolate 12-month vectors from the k nearest grid cells via Haversine IDW."""
    ranked = sorted(
        (
            (_haversine_km(lat, lon, cell["lat"], cell["lon"]), cell)
            for cell in cells
        ),
        key=lambda item: item[0],
    )[:k]
    raw_weights = [1.0 / (max(dist_km, 0.5) ** 2) for dist_km, _ in ranked]
    weight_sum = sum(raw_weights) or 1.0

    interpolated: Dict[str, List[float]] = {key: [0.0] * 12 for key in value_keys}
    cell_refs: List[Dict[str, Any]] = []
    for (dist_km, cell), w in zip(ranked, raw_weights):
        wn = w / weight_sum
        for key in value_keys:
            for m_idx in range(12):
                interpolated[key][m_idx] += cell[key][m_idx] * wn
        cell_refs.append({
            "point_id": cell["point_id"],
            "distance_km": round(dist_km, 2),
            "relative_weight": round(wn, 3),
        })

    for key in value_keys:
        digits = 4 if "moisture" in key else 2
        interpolated[key] = [round(v, digits) for v in interpolated[key]]
    return interpolated, cell_refs


def _nearest_ground_stations(
    lat: float,
    lon: float,
    df_stations: Optional[pd.DataFrame],
    variable_filter: str,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """Return nearest validated inside-box ground stations measuring the requested variable."""
    if df_stations is None or df_stations.empty:
        return []
    obs = df_stations[
        df_stations["validation_status"].astype(str).str.startswith("OBSERVED")
        & df_stations["variables"].astype(str).str.lower().str.contains(variable_filter)
    ].copy()
    if obs.empty:
        obs = df_stations[df_stations["mvp_box"] == "INSIDE"].copy()
    if obs.empty:
        return []

    obs["distance_km"] = [
        _haversine_km(lat, lon, float(r["lat"]), float(r["lon"]))
        for _, r in obs.iterrows()
    ]
    obs = obs.sort_values("distance_km").head(limit)
    out: List[Dict[str, Any]] = []
    for _, r in obs.iterrows():
        out.append({
            "station_id": str(r["station_id"]),
            "name": f"{r['name']} ({r['network']})",
            "distance_km": round(float(r["distance_km"]), 2),
            "validation_status": str(r["validation_status"]),
        })
    return out


def _load_datasets() -> Dict[str, Any]:
    """Load GitHub-tracked MVP homogeneous datasets once from disk."""
    if _CACHE:
        return _CACHE

    soil_1ha_path = MVP_HOMOGENEOUS_DIR / "soil_1ha_grid.parquet"
    climate_monthly_path = MVP_HOMOGENEOUS_DIR / "climate_monthly_grid_1991_2026.parquet"
    climate_zone_path = MVP_HOMOGENEOUS_DIR / "climate_zone_daily_1991_2026.csv"
    soil_moisture_path = MVP_HOMOGENEOUS_DIR / "soil_moisture_monthly_grid_1991_2026.csv"

    for p in (soil_1ha_path, climate_monthly_path, climate_zone_path, soil_moisture_path):
        if not p.is_file():
            raise FileNotFoundError(f"Missing MVP homogeneous dataset on disk: {p}")

    # 1. SRTM relief & terrain attributes (1 ha)
    df_srtm = pd.read_parquet(
        soil_1ha_path,
        columns=["lat", "lon", "elevation_m", "slope_pct", "max_slope_pct"],
    )
    srtm_arrays = {
        "lat": df_srtm["lat"].to_numpy(dtype=np.float64),
        "lon": df_srtm["lon"].to_numpy(dtype=np.float64),
        "elevation_m": df_srtm["elevation_m"].to_numpy(dtype=np.float32),
        "slope_pct": df_srtm["slope_pct"].to_numpy(dtype=np.float32),
        "max_slope_pct": df_srtm["max_slope_pct"].to_numpy(dtype=np.float32),
    }

    # 2. NASA POWER monthly 0.25 deg grid climatology (1991-2025, 32 cells)
    df_cm = pd.read_parquet(
        climate_monthly_path,
        columns=["point_id", "lat", "lon", "year", "month", "precip_mm", "tmax_mean_c"],
    )
    climate_cells = _build_monthly_grid(df_cm, ["precip_mm", "tmax_mean_c"], year_max=2025)

    # 3. Observed corridor-weighted daily minimum temperatures (Apr/May/Sep/Oct/Nov p10)
    df_cz = pd.read_csv(climate_zone_path, usecols=["date", "tmax_weighted", "tmin_weighted"])
    df_cz["month"] = pd.to_datetime(df_cz["date"], errors="coerce").dt.month
    trans_tmin = df_cz[df_cz["month"].isin([4, 5, 9, 10, 11])]["tmin_weighted"].dropna()
    critical_tmin = round(float(trans_tmin.quantile(0.10)), 2) if not trans_tmin.empty else 3.71

    # 4. Modeled monthly soil moisture grid (1991-2025, UNVALIDATED_CORRELATION)
    df_sm = pd.read_csv(
        soil_moisture_path,
        usecols=["point_id", "lat", "lon", "year", "month", "mean_moisture_m3_m3"],
    )
    moisture_cells = _build_monthly_grid(df_sm, ["mean_moisture_m3_m3"], year_max=2025)
    cell_means = [sum(c["mean_moisture_m3_m3"]) / 12.0 for c in moisture_cells]
    sm_q25 = float(np.quantile(cell_means, 0.25)) if cell_means else 0.073
    sm_q75 = float(np.quantile(cell_means, 0.75)) if cell_means else 0.084

    # 5. Supporting overlays & context tables (stations, SISINTA, GAEZ v4, annual climate, ENSO, 500m grid)
    mvp: Dict[str, Any] = {}

    st_path = MVP_HOMOGENEOUS_DIR / "ground_stations.csv"
    if st_path.is_file():
        mvp["stations"] = pd.read_csv(st_path)

    sis_path = MVP_HOMOGENEOUS_DIR / "soil_sisinta_profiles_box.csv"
    if sis_path.is_file():
        df_sis = pd.read_csv(sis_path)
        df_sis = df_sis.sort_values(["lat", "lon", "upper_depth_cm"], na_position="last")
        mvp["sisinta"] = df_sis.groupby(["lat", "lon"], as_index=False).first()

    gaez_path = MVP_HOMOGENEOUS_DIR / "soil_gaez_crops_1981_2010.csv"
    if gaez_path.is_file():
        mvp["gaez"] = pd.read_csv(gaez_path)

    ca_path = MVP_HOMOGENEOUS_DIR / "climate_annual_grid_1991_2026.csv"
    if ca_path.is_file():
        df_ca = pd.read_csv(ca_path)
        df_ca_hist = df_ca[df_ca["year"] <= 2025].copy()
        for date_col, out_col in (
            ("first_autumn_frost", "first_doy"),
            ("last_spring_frost", "last_doy"),
        ):
            dt = pd.to_datetime(df_ca_hist[date_col], errors="coerce")
            df_ca_hist[out_col] = dt.dt.day_of_year
        mvp["annual_climate_summary"] = (
            df_ca_hist.groupby(["point_id", "lat", "lon"], as_index=False)
            .agg(
                mean_annual_precip_mm=("precip_total_mm", "mean"),
                mean_annual_eto_mm=("eto_total_mm", "mean"),
                mean_p_eto_balance_mm=("p_eto_balance_mm", "mean"),
                mean_heat_stress_days=("heat_stress_days", "mean"),
                mean_frost_free_days=("frost_free_days_season", "mean"),
                first_frost_doy=("first_doy", "mean"),
                last_frost_doy=("last_doy", "mean"),
            )
        )

    enso_path = MVP_HOMOGENEOUS_DIR / "enso_oni_monthly.csv"
    if enso_path.is_file():
        df_enso = pd.read_csv(enso_path).dropna(subset=["oni_anomaly_c"])
        if not df_enso.empty:
            latest = df_enso.sort_values("year_month").iloc[-1]
            mvp["latest_enso"] = {
                "year_month": str(latest["year_month"]),
                "oni_anomaly_c": round(float(latest["oni_anomaly_c"]), 2),
                "enso_phase": str(latest["enso_phase"]),
            }

    s500_path = MVP_HOMOGENEOUS_DIR / "soil_500m_grid.csv"
    if s500_path.is_file():
        mvp["soil_500m"] = pd.read_csv(
            s500_path,
            usecols=["lat", "lon", "mean_slope_pct", "mean_topographic_susceptibility", "susceptibility_label"],
        )

    _CACHE["srtm"] = srtm_arrays
    _CACHE["climate_cells"] = climate_cells
    _CACHE["critical_tmin"] = critical_tmin
    _CACHE["moisture_cells"] = moisture_cells
    _CACHE["moisture_thresholds"] = (sm_q25, sm_q75)
    _CACHE["mvp"] = mvp
    return _CACHE


def _validate_in_box(lat: float, lon: float) -> None:
    if not (BBOX_MVP["lat_min"] <= lat <= BBOX_MVP["lat_max"] and BBOX_MVP["lon_min"] <= lon <= BBOX_MVP["lon_max"]):
        raise ValueError(
            f"Coordinate ({lat:.4f}, {lon:.4f}) is outside the MVP bounding box "
            f"lat [{BBOX_MVP['lat_min']}, {BBOX_MVP['lat_max']}], lon [{BBOX_MVP['lon_min']}, {BBOX_MVP['lon_max']}]."
        )


def query_terrain(
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    polygon: Optional[List[List[float]]] = None,
) -> Dict[str, Any]:
    """
    Query 1 ha relief, NASA POWER monthly climate, modeled soil moisture, observed station
    transition temperatures, SISINTA soil profiles, and FAO GAEZ v4 context for a point or
    polygon inside the MVP bounding box using only repository-tracked files.
    """
    data = _load_datasets()
    srtm = data["srtm"]

    if polygon and len(polygon) >= 3:
        for pt in polygon:
            _validate_in_box(float(pt[0]), float(pt[1]))
        lats_p = [float(pt[0]) for pt in polygon]
        lons_p = [float(pt[1]) for pt in polygon]
        center_lat = sum(lats_p) / len(lats_p)
        center_lon = sum(lons_p) / len(lons_p)

        mask_bbox = (
            (srtm["lat"] >= min(lats_p))
            & (srtm["lat"] <= max(lats_p))
            & (srtm["lon"] >= min(lons_p))
            & (srtm["lon"] <= max(lons_p))
        )
        idx_bbox = np.where(mask_bbox)[0]
        if len(idx_bbox) > 0:
            in_poly = _points_in_polygon(srtm["lat"][idx_bbox], srtm["lon"][idx_bbox], polygon)
            idx_sel = idx_bbox[in_poly]
        else:
            idx_sel = np.array([], dtype=np.int64)

        if len(idx_sel) > 0:
            elevation_m = float(np.mean(srtm["elevation_m"][idx_sel]))
            slope_pct = float(np.mean(srtm["slope_pct"][idx_sel]))
            max_slope_pct = float(np.max(srtm["max_slope_pct"][idx_sel]))
            area_ha = max(1, int(len(idx_sel)))
        else:
            dist2 = (srtm["lat"] - center_lat) ** 2 + (srtm["lon"] - center_lon) ** 2
            idx_min = int(np.argmin(dist2))
            elevation_m = float(srtm["elevation_m"][idx_min])
            slope_pct = float(srtm["slope_pct"][idx_min])
            max_slope_pct = float(srtm["max_slope_pct"][idx_min])
            area_ha = 1
    else:
        if lat is None or lon is None:
            raise ValueError("You must provide (lat, lon) or a valid polygon.")
        center_lat, center_lon = float(lat), float(lon)
        _validate_in_box(center_lat, center_lon)

        mask_local = (np.abs(srtm["lat"] - center_lat) <= 0.01) & (np.abs(srtm["lon"] - center_lon) <= 0.01)
        idx_local = np.where(mask_local)[0]
        if len(idx_local) > 0:
            dist2 = (srtm["lat"][idx_local] - center_lat) ** 2 + (srtm["lon"][idx_local] - center_lon) ** 2
            idx_min = int(idx_local[int(np.argmin(dist2))])
        else:
            dist2 = (srtm["lat"] - center_lat) ** 2 + (srtm["lon"] - center_lon) ** 2
            idx_min = int(np.argmin(dist2))

        elevation_m = float(srtm["elevation_m"][idx_min])
        slope_pct = float(srtm["slope_pct"][idx_min])
        max_slope_pct = float(srtm["max_slope_pct"][idx_min])
        area_ha = 1

    # Spatial IDW interpolation on NASA POWER climate grid and modeled moisture grid
    climate_interp, grid_refs = _idw_interpolate_grid(
        center_lat,
        center_lon,
        data["climate_cells"],
        ["precip_mm", "tmax_mean_c"],
        k=4,
    )
    rainfall_12m = climate_interp["precip_mm"]
    tmax_12m = climate_interp["tmax_mean_c"]

    moisture_interp, _ = _idw_interpolate_grid(
        center_lat,
        center_lon,
        data["moisture_cells"],
        ["mean_moisture_m3_m3"],
        k=4,
    )
    sm_surface_12m = moisture_interp["mean_moisture_m3_m3"]
    sm_surface_mean = round(sum(sm_surface_12m) / len(sm_surface_12m), 4)

    critical_tmin = float(data["critical_tmin"])
    sm_q25, sm_q75 = data["moisture_thresholds"]

    water_table_slope = "sloped_waterlogging" if slope_pct >= 2.0 else "no_water_table"
    if sm_surface_mean < sm_q25:
        moisture_status = "dry"
    elif sm_surface_mean > sm_q75:
        moisture_status = "wet"
    else:
        moisture_status = "normal"

    mvp = data.get("mvp", {})
    mvp_context = _query_mvp_context(center_lat, center_lon, mvp)
    rain_stations = _nearest_ground_stations(center_lat, center_lon, mvp.get("stations"), "precip")
    temp_stations = _nearest_ground_stations(center_lat, center_lon, mvp.get("stations"), "temperature")

    field_data = {
        "id": f"field_{round(center_lat, 4)}_{round(center_lon, 4)}",
        "name": f"Field ({center_lat:.4f}, {center_lon:.4f}) · {area_ha} ha",
        "soil": "Sandy-loam (regional estimate)",
        "gpm_rainfall_mm": rainfall_12m,
        "smap_soil_moisture": sm_surface_12m,
        "ecostress_surface_temp_c": tmax_12m,
        "satellite_tmin_c": critical_tmin,
        "sentinel2_ndvi": [0.35, 0.38, 0.32, 0.22, 0.18, 0.17, 0.19, 0.21, 0.28, 0.36, 0.42, 0.40],
        "rainfall_origin": "ESTIMATED_POWER",
        "temp_origin": "OBSERVED_STATION_WEIGHTED",
        "moisture_origin": "ESTIMATED_POWER_MODEL",
        "moisture_label": "UNVALIDATED_CORRELATION",
        "mvp_context": mvp_context,
    }

    terrain_out: Dict[str, Any] = {
        "area_ha": area_ha,
        "elevation_m": round(elevation_m, 1),
        "slope_pct": round(slope_pct, 2),
        "max_slope_pct": round(max_slope_pct, 2),
        "annual_rainfall_mm": round(sum(rainfall_12m), 1),
        "sm_surface_mean": sm_surface_mean,
        "moisture_model_label": "UNVALIDATED_CORRELATION",
        "transition_tmin_c": critical_tmin,
    }
    if mvp_context.get("topographic_susceptibility") is not None:
        terrain_out["topographic_susceptibility"] = mvp_context["topographic_susceptibility"]
        terrain_out["susceptibility_label"] = mvp_context.get("susceptibility_label", "UNVALIDATED")

    return {
        "coordinates": {"lat": round(center_lat, 5), "lon": round(center_lon, 5)},
        "terrain": terrain_out,
        "auto_detected": {
            "water_table_slope": water_table_slope,
            "moisture_status": moisture_status,
        },
        "mvp_context": mvp_context,
        "field_data": field_data,
        "provenance": {
            "elevation": "SRTM 1 ha (data/reference/mvp-homogeneous/soil_1ha_grid.parquet)",
            "rainfall": "NASA POWER 0.25 deg 1991-2025 IDW climatology (climate_monthly_grid_1991_2026.parquet)",
            "temperature": "Corridor weighted ground stations 1991-2026 p10 transition (climate_zone_daily_1991_2026.csv)",
            "moisture": "NASA POWER soil-water balance model 1991-2025 [UNVALIDATED_CORRELATION] (soil_moisture_monthly_grid_1991_2026.csv)",
            "mvp_homogeneous": "NASA POWER Climate/ETo, Modeled Soil Moisture, GAEZ v4, INTA SISINTA & 19-Station Network",
            "grid_cells": grid_refs,
            "rainfall_stations": rain_stations,
            "temperature_stations": temp_stations,
        },
        "quality_status": "VALID_WITH_LIMITATIONS",
        "scale_warning": (
            "1 ha resolution relief; rainfall, soil moisture model (UNVALIDATED_CORRELATION), and GAEZ v4 "
            "are regional references. Low spots, subsurface moisture, and true soil texture require in-field inspection."
        ),
    }


def _opt_float(val: Any, ndigits: int = 2) -> Optional[float]:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    try:
        f = float(val)
        return None if math.isnan(f) else round(f, ndigits)
    except (TypeError, ValueError):
        return None


def _doy_to_short_date(doy: Optional[float]) -> Optional[str]:
    if doy is None or math.isnan(doy):
        return None
    day = max(1, min(365, int(round(doy))))
    dt_val = _dt.date(2025, 1, 1) + _dt.timedelta(days=day - 1)
    return dt_val.strftime("%b %d")


def _query_mvp_context(lat: float, lon: float, mvp: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if not mvp:
        return out

    # 1. Topographic susceptibility (UNVALIDATED) from 500m soil grid
    df_500 = mvp.get("soil_500m")
    if df_500 is not None and not df_500.empty:
        d2 = (df_500["lat"] - lat) ** 2 + (df_500["lon"] - lon) ** 2
        row = df_500.iloc[int(d2.idxmin())]
        out["topographic_susceptibility"] = _opt_float(row["mean_topographic_susceptibility"], 3)
        out["susceptibility_label"] = str(row.get("susceptibility_label", "UNVALIDATED"))

    # 2. Historical annual POWER climate + FAO-56 ETo + Actual frost window + ENSO
    df_ca = mvp.get("annual_climate_summary")
    if df_ca is not None and not df_ca.empty:
        d2 = (df_ca["lat"] - lat) ** 2 + (df_ca["lon"] - lon) ** 2
        row = df_ca.iloc[int(d2.idxmin())]
        hist_climate: Dict[str, Any] = {
            "point_id": str(row["point_id"]),
            "origin": "ESTIMATED_POWER",
            "mean_annual_precip_mm": _opt_float(row["mean_annual_precip_mm"], 1),
            "mean_annual_eto_mm": _opt_float(row["mean_annual_eto_mm"], 1),
            "mean_p_eto_balance_mm": _opt_float(row["mean_p_eto_balance_mm"], 1),
            "mean_heat_stress_days": _opt_float(row["mean_heat_stress_days"], 1),
            "mean_frost_free_days": _opt_float(row["mean_frost_free_days"], 0),
            "mean_first_autumn_frost": _doy_to_short_date(row["first_frost_doy"]),
            "mean_last_spring_frost": _doy_to_short_date(row["last_frost_doy"]),
        }
        if "latest_enso" in mvp:
            hist_climate["latest_enso"] = mvp["latest_enso"]
        out["historical_cell_climate"] = hist_climate

    # 3. Nearest INTA SISINTA soil profile (visual reference only)
    df_sis = mvp.get("sisinta")
    if df_sis is not None and not df_sis.empty:
        d2 = (df_sis["lat"] - lat) ** 2 + (df_sis["lon"] - lon) ** 2
        row = df_sis.iloc[int(d2.idxmin())]
        dist_km = _haversine_km(lat, lon, float(row["lat"]), float(row["lon"]))
        out["nearest_sisinta"] = {
            "record_no": _opt_float(row.get("record_no"), 0),
            "distance_km": round(dist_km, 2),
            "upper_depth_cm": _opt_float(row.get("upper_depth_cm"), 0),
            "lower_depth_cm": _opt_float(row.get("lower_depth_cm"), 0),
            "clay_pct": _opt_float(row.get("clay_pct"), 1),
            "silt_pct": _opt_float(row.get("silt_2_50_pct"), 1),
            "sand_pct": _opt_float(row.get("total_sand_pct"), 1),
            "ph_water": _opt_float(row.get("ph_water"), 2),
            "organic_carbon_pct": _opt_float(row.get("organic_carbon_pct"), 2),
            "calc_available_water_pct": _opt_float(row.get("calc_available_water_pct"), 1),
            "completeness_status": str(row.get("completeness_status", "INCOMPLETE_DATA")),
            "origin": str(row.get("origin", "OBSERVED_SISINTA")),
        }

    # 4. FAO GAEZ v4 suitability & attainable yield (1981-2010, no codebook)
    df_gaez = mvp.get("gaez")
    if df_gaez is not None and not df_gaez.empty:
        coords_g = df_gaez[["lat", "lon"]].drop_duplicates()
        d2 = (coords_g["lat"] - lat) ** 2 + (coords_g["lon"] - lon) ** 2
        pt = coords_g.loc[int(d2.idxmin())]
        sub = df_gaez[(df_gaez["lat"] == pt["lat"]) & (df_gaez["lon"] == pt["lon"])]
        gaez_list = []
        for crop_key in _GAEZ_CROP_ORDER:
            sc = sub[sub["crop"] == crop_key]
            if sc.empty:
                continue
            suit = sc[sc["layer"] == "cropland_suitability_class"]["value"]
            yld = sc[sc["layer"] == "cropland_attainable_yield"]["value"]
            gaez_list.append({
                "crop": crop_key.capitalize(),
                "suitability_class": _opt_float(suit.iloc[0], 0) if not suit.empty else None,
                "attainable_yield_kg_ha": _opt_float(yld.iloc[0], 0) if not yld.empty else None,
            })
        out["gaez_crops"] = gaez_list
        out["gaez_origin"] = "REGIONAL_GAEZ_V4_NO_CODEBOOK"

    return out


def get_map_layers() -> Dict[str, Any]:
    """Return interactive homogeneous MVP overlays for the Leaflet map viewer."""
    data = _load_datasets()
    mvp = data.get("mvp", {})

    stations: List[Dict[str, Any]] = []
    df_st = mvp.get("stations")
    if df_st is not None and not df_st.empty:
        for _, r in df_st.iterrows():
            stations.append({
                "station_id": str(r["station_id"]),
                "name": str(r["name"]),
                "lat": round(float(r["lat"]), 5),
                "lon": round(float(r["lon"]), 5),
                "network": str(r["network"]),
                "variables": str(r["variables"]),
                "validation_status": str(r["validation_status"]),
                "mvp_box": str(r["mvp_box"]),
            })

    sisinta: List[Dict[str, Any]] = []
    df_sis = mvp.get("sisinta")
    if df_sis is not None and not df_sis.empty:
        for _, r in df_sis.iterrows():
            sisinta.append({
                "record_no": _opt_float(r.get("record_no"), 0),
                "lat": round(float(r["lat"]), 5),
                "lon": round(float(r["lon"]), 5),
                "upper_depth_cm": _opt_float(r.get("upper_depth_cm"), 0),
                "lower_depth_cm": _opt_float(r.get("lower_depth_cm"), 0),
                "clay_pct": _opt_float(r.get("clay_pct"), 1),
                "silt_pct": _opt_float(r.get("silt_2_50_pct"), 1),
                "sand_pct": _opt_float(r.get("total_sand_pct"), 1),
                "ph_water": _opt_float(r.get("ph_water"), 2),
                "organic_carbon_pct": _opt_float(r.get("organic_carbon_pct"), 2),
                "calc_available_water_pct": _opt_float(r.get("calc_available_water_pct"), 1),
                "completeness_status": str(r.get("completeness_status", "INCOMPLETE_DATA")),
            })

    # Uniformly subsampled 500m grid (~3,400 points) for fast Leaflet canvas rendering
    grid_500m: List[List[float]] = []
    df_500 = mvp.get("soil_500m")
    if df_500 is not None and not df_500.empty:
        sub = df_500.iloc[::16]
        for _, r in sub.iterrows():
            susc = _opt_float(r["mean_topographic_susceptibility"], 3) or 0.0
            slope = _opt_float(r["mean_slope_pct"], 2) or 0.0
            grid_500m.append([round(float(r["lat"]), 4), round(float(r["lon"]), 4), susc, slope])

    return {
        "stations": stations,
        "sisinta": sisinta,
        "grid_500m": grid_500m,
        "susceptibility_label": "UNVALIDATED (TWI topographic index + depressions; NOT a flood map)",
    }
