"""
Módulo de acceso geoespacial a los datasets curados en data/curated/ para la caja MVP
(lon [-65.875, -64.125], lat [-33.875, -33.125], EPSG:4326).
"""

import math
import pathlib
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[2]
CURATED_DIR = REPOSITORY_ROOT / "data" / "curated"

BBOX_MVP = {
    "lat_min": -33.875,
    "lat_max": -33.125,
    "lon_min": -65.875,
    "lon_max": -64.125,
}

_ESTACIONES_LLUVIA: Dict[int, Dict[str, Any]] = {
    30109: {"nombre": "Río Cuarto (PIHC 30109)", "lat": -33.1612, "lon": -64.357},
    30492: {"nombre": "Achiras (PIHC 30492)", "lat": -33.175, "lon": -64.995},
}

_ESTACIONES_TEMP: Dict[int, Dict[str, Any]] = {
    87448: {"nombre": "Villa Reynolds Aero (SMN 87448)", "lat": -33.7167, "lon": -65.3667},
    87453: {"nombre": "Río Cuarto Aero (SMN 87453)", "lat": -33.0833, "lon": -64.2667},
}

_CACHE: Dict[str, Any] = {}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r_km = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * r_km * math.asin(min(1.0, math.sqrt(a)))


def _puntos_en_poligono(lats: np.ndarray, lons: np.ndarray, poligono: List[List[float]]) -> np.ndarray:
    """Algoritmo ray-casting vectorizado en NumPy para puntos dentro de un polígono [[lat, lon], ...]."""
    n = len(poligono)
    dentro = np.zeros(len(lats), dtype=bool)
    p1_lat, p1_lon = poligono[0][0], poligono[0][1]
    for i in range(1, n + 1):
        p2_lat, p2_lon = poligono[i % n][0], poligono[i % n][1]
        cond_lat = ((p1_lat <= lats) & (lats < p2_lat)) | ((p2_lat <= lats) & (lats < p1_lat))
        denom = (p2_lat - p1_lat) if (p2_lat - p1_lat) != 0 else 1e-12
        x_intersec = (lats - p1_lat) * (p2_lon - p1_lon) / denom + p1_lon
        dentro ^= cond_lat & (lons < x_intersec)
        p1_lat, p1_lon = p2_lat, p2_lon
    return dentro


def _cargar_datasets() -> Dict[str, Any]:
    """Carga una sola vez los datasets curados desde REPOSITORY_ROOT / 'data' / 'curated'."""
    if _CACHE:
        return _CACHE

    srtm_path = CURATED_DIR / "srtm_1ha_corredor.parquet"
    smap_path = CURATED_DIR / "smap_9km_corredor.parquet"
    lluvia_path = CURATED_DIR / "lluvia_agregada_cordoba.csv"
    smn_path = CURATED_DIR / "capa-smn-gsod.csv"

    for p in (srtm_path, smap_path, lluvia_path, smn_path):
        if not p.is_file():
            raise FileNotFoundError(f"Archivo curado faltante en disco: {p}")

    # 1. Relieve SRTM (1 ha)
    df_srtm = pd.read_parquet(
        srtm_path,
        columns=["lat", "lon", "elevacion_m", "pendiente_pct", "pendiente_max_pct"],
    )
    srtm_arrays = {
        "lat": df_srtm["lat"].to_numpy(dtype=np.float64),
        "lon": df_srtm["lon"].to_numpy(dtype=np.float64),
        "elevacion_m": df_srtm["elevacion_m"].to_numpy(dtype=np.float32),
        "pendiente_pct": df_srtm["pendiente_pct"].to_numpy(dtype=np.float32),
        "pendiente_max_pct": df_srtm["pendiente_max_pct"].to_numpy(dtype=np.float32),
    }

    # 2. Humedad de suelo SMAP (9 km / corredor)
    df_smap = pd.read_parquet(
        smap_path,
        columns=["lat", "lon", "sm_surface_12m", "sm_rootzone_12m", "sm_surface_media", "sm_rootzone_media"],
    )

    # 3. Lluvia normalizada (PIHC): filtrar peso > 0, excluir 30349 (Bell Ville)
    df_lluvia = pd.read_csv(lluvia_path)
    df_lluvia = df_lluvia[(df_lluvia["peso"] > 0) & (df_lluvia["estacion"] != 30349)].copy()
    df_lluvia["mes"] = df_lluvia["ym"].astype(str).str.slice(5, 7).astype(int)

    climatologia_lluvia: Dict[int, Dict[str, Any]] = {}
    for est_id, meta in _ESTACIONES_LLUVIA.items():
        sub = df_lluvia[df_lluvia["estacion"] == est_id]
        if sub.empty:
            continue
        mensual = []
        for m in range(1, 13):
            sub_m = sub[sub["mes"] == m]
            if not sub_m.empty:
                val = float(np.average(sub_m["precipitacion_mm"], weights=sub_m["peso"]))
            else:
                val = float(sub["precipitacion_mm"].mean())
            mensual.append(round(val, 2))
        climatologia_lluvia[est_id] = {
            "nombre": meta["nombre"],
            "lat": meta["lat"],
            "lon": meta["lon"],
            "peso_base": float(sub["peso"].mean()),
            "mensual_12m": mensual,
        }

    # 4. Temperatura calibrada (SMN / GSOD): filtrar peso > 0, priorizar OBSERVADO_SMN y REFERENCIA_SMN_FUERA_CAJA
    df_smn = pd.read_csv(smn_path)
    df_smn = df_smn[df_smn["peso"] > 0].copy()
    df_smn_prio = df_smn[df_smn["origen"].isin(["OBSERVADO_SMN", "REFERENCIA_SMN_FUERA_CAJA"])].copy()
    if df_smn_prio.empty:
        df_smn_prio = df_smn
    df_smn_prio["mes"] = pd.to_datetime(df_smn_prio["fecha"], errors="coerce").dt.month

    climatologia_temp: Dict[int, Dict[str, Any]] = {}
    for est_id, meta in _ESTACIONES_TEMP.items():
        sub = df_smn_prio[df_smn_prio["estacion"] == est_id]
        if sub.empty:
            continue
        tmax_12m = []
        for m in range(1, 13):
            sub_m = sub[sub["mes"] == m]
            val = float(sub_m["tmax_c"].mean()) if not sub_m.empty else float(sub["tmax_c"].mean())
            tmax_12m.append(round(val, 2))
        # Mínima crítica de transición (meses otoño/primavera: abr, may, sep, oct, nov)
        sub_trans = sub[sub["mes"].isin([4, 5, 9, 10, 11])]
        tmin_critica = float(sub_trans["tmin_c"].quantile(0.10)) if not sub_trans.empty else float(sub["tmin_c"].quantile(0.10))
        climatologia_temp[est_id] = {
            "nombre": meta["nombre"],
            "lat": meta["lat"],
            "lon": meta["lon"],
            "peso_base": float(sub["peso"].mean()),
            "tmax_12m": tmax_12m,
            "tmin_critica": round(tmin_critica, 2),
        }

    _CACHE["srtm"] = srtm_arrays
    _CACHE["smap"] = df_smap
    _CACHE["lluvia"] = climatologia_lluvia
    _CACHE["temp"] = climatologia_temp
    return _CACHE


def _validar_en_caja(lat: float, lon: float) -> None:
    if not (BBOX_MVP["lat_min"] <= lat <= BBOX_MVP["lat_max"] and BBOX_MVP["lon_min"] <= lon <= BBOX_MVP["lon_max"]):
        raise ValueError(
            f"Coordenada ({lat:.4f}, {lon:.4f}) fuera de la caja MVP "
            f"lat [{BBOX_MVP['lat_min']}, {BBOX_MVP['lat_max']}], lon [{BBOX_MVP['lon_min']}, {BBOX_MVP['lon_max']}]."
        )


def _ponderar_lluvia(lat: float, lon: float, clim_lluvia: Dict[int, Dict[str, Any]]) -> Tuple[List[float], List[Dict[str, Any]]]:
    pesos_est: List[Tuple[int, float, float]] = []
    for est_id, info in clim_lluvia.items():
        dist_km = _haversine_km(lat, lon, info["lat"], info["lon"])
        w = info["peso_base"] * math.exp(-dist_km / 100.0)
        pesos_est.append((est_id, w, dist_km))

    suma_w = sum(w for _, w, _ in pesos_est) or 1.0
    serie_12m = [0.0] * 12
    detalle_est: List[Dict[str, Any]] = []
    for est_id, w, dist_km in pesos_est:
        wn = w / suma_w
        for i in range(12):
            serie_12m[i] += clim_lluvia[est_id]["mensual_12m"][i] * wn
        detalle_est.append({
            "estacion": est_id,
            "nombre": clim_lluvia[est_id]["nombre"],
            "distancia_km": round(dist_km, 2),
            "peso_relativo": round(wn, 3),
        })
    return [round(v, 2) for v in serie_12m], detalle_est


def _ponderar_temperatura(lat: float, lon: float, clim_temp: Dict[int, Dict[str, Any]]) -> Tuple[List[float], float, List[Dict[str, Any]]]:
    pesos_est: List[Tuple[int, float, float]] = []
    for est_id, info in clim_temp.items():
        dist_km = _haversine_km(lat, lon, info["lat"], info["lon"])
        w = info["peso_base"] * math.exp(-dist_km / 100.0)
        pesos_est.append((est_id, w, dist_km))

    suma_w = sum(w for _, w, _ in pesos_est) or 1.0
    tmax_12m = [0.0] * 12
    tmin_critica = 0.0
    detalle_est: List[Dict[str, Any]] = []
    for est_id, w, dist_km in pesos_est:
        wn = w / suma_w
        for i in range(12):
            tmax_12m[i] += clim_temp[est_id]["tmax_12m"][i] * wn
        tmin_critica += clim_temp[est_id]["tmin_critica"] * wn
        detalle_est.append({
            "estacion": est_id,
            "nombre": clim_temp[est_id]["nombre"],
            "distancia_km": round(dist_km, 2),
            "peso_relativo": round(wn, 3),
        })
    return [round(v, 2) for v in tmax_12m], round(tmin_critica, 2), detalle_est


def consultar_terreno(
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    poligono: Optional[List[List[float]]] = None,
) -> Dict[str, Any]:
    """
    Consulta relieve SRTM (1 ha), humedad SMAP (9 km), lluvia PIHC y temperatura SMN
    para un punto (lat, lon) o polígono ([[lat, lon], ...]) dentro de la caja MVP.
    """
    datos = _cargar_datasets()
    srtm = datos["srtm"]

    if poligono and len(poligono) >= 3:
        for pt in poligono:
            _validar_en_caja(float(pt[0]), float(pt[1]))
        lats_p = [float(pt[0]) for pt in poligono]
        lons_p = [float(pt[1]) for pt in poligono]
        centro_lat = sum(lats_p) / len(lats_p)
        centro_lon = sum(lons_p) / len(lons_p)

        mask_bbox = (
            (srtm["lat"] >= min(lats_p))
            & (srtm["lat"] <= max(lats_p))
            & (srtm["lon"] >= min(lons_p))
            & (srtm["lon"] <= max(lons_p))
        )
        idx_bbox = np.where(mask_bbox)[0]
        if len(idx_bbox) > 0:
            en_poly = _puntos_en_poligono(srtm["lat"][idx_bbox], srtm["lon"][idx_bbox], poligono)
            idx_sel = idx_bbox[en_poly]
        else:
            idx_sel = np.array([], dtype=np.int64)

        if len(idx_sel) > 0:
            elevacion_m = float(np.mean(srtm["elevacion_m"][idx_sel]))
            pendiente_pct = float(np.mean(srtm["pendiente_pct"][idx_sel]))
            pendiente_max_pct = float(np.max(srtm["pendiente_max_pct"][idx_sel]))
            superficie_ha = max(1, int(len(idx_sel)))
        else:
            dist2 = (srtm["lat"] - centro_lat) ** 2 + (srtm["lon"] - centro_lon) ** 2
            idx_min = int(np.argmin(dist2))
            elevacion_m = float(srtm["elevacion_m"][idx_min])
            pendiente_pct = float(srtm["pendiente_pct"][idx_min])
            pendiente_max_pct = float(srtm["pendiente_max_pct"][idx_min])
            superficie_ha = 1
    else:
        if lat is None or lon is None:
            raise ValueError("Debe proporcionar (lat, lon) o un polígono válido.")
        centro_lat, centro_lon = float(lat), float(lon)
        _validar_en_caja(centro_lat, centro_lon)

        mask_local = (np.abs(srtm["lat"] - centro_lat) <= 0.01) & (np.abs(srtm["lon"] - centro_lon) <= 0.01)
        idx_local = np.where(mask_local)[0]
        if len(idx_local) > 0:
            dist2 = (srtm["lat"][idx_local] - centro_lat) ** 2 + (srtm["lon"][idx_local] - centro_lon) ** 2
            idx_min = int(idx_local[int(np.argmin(dist2))])
        else:
            dist2 = (srtm["lat"] - centro_lat) ** 2 + (srtm["lon"] - centro_lon) ** 2
            idx_min = int(np.argmin(dist2))

        elevacion_m = float(srtm["elevacion_m"][idx_min])
        pendiente_pct = float(srtm["pendiente_pct"][idx_min])
        pendiente_max_pct = float(srtm["pendiente_max_pct"][idx_min])
        superficie_ha = 1

    # Celda SMAP más cercana
    df_smap = datos["smap"]
    dist_smap = (df_smap["lat"] - centro_lat) ** 2 + (df_smap["lon"] - centro_lon) ** 2
    smap_row = df_smap.iloc[int(dist_smap.idxmin())]
    sm_surface_12m = [round(float(x), 4) for x in smap_row["sm_surface_12m"]]
    sm_rootzone_12m = [round(float(x), 4) for x in smap_row["sm_rootzone_12m"]]
    sm_surface_media = round(float(smap_row["sm_surface_media"]), 4)
    sm_rootzone_media = round(float(smap_row["sm_rootzone_media"]), 4)

    # Lluvia PIHC y Temperatura SMN ponderadas por distancia Haversine
    lluvia_12m, est_lluvia = _ponderar_lluvia(centro_lat, centro_lon, datos["lluvia"])
    tmax_12m, tmin_critica, est_temp = _ponderar_temperatura(centro_lat, centro_lon, datos["temp"])

    napa_pendiente = "pendiente_anegamiento" if pendiente_pct >= 2.0 else "sin_napa"
    if sm_surface_media < 0.14:
        humedad_estado = "seco"
    elif sm_surface_media > 0.24:
        humedad_estado = "humedo"
    else:
        humedad_estado = "normal"

    datos_lote = {
        "id": f"lote_{round(centro_lat, 4)}_{round(centro_lon, 4)}",
        "nombre": f"Lote ({centro_lat:.4f}, {centro_lon:.4f}) · {superficie_ha} ha",
        "suelo": "Franco-arenoso (estimación regional)",
        "lluvia_gpm_mm": lluvia_12m,
        "humedad_suelo_smap": sm_surface_12m,
        "humedad_rootzone_smap": sm_rootzone_12m,
        "temp_superficial_ecostress_c": tmax_12m,
        "temp_min_satelital_c": tmin_critica,
        "ndvi_sentinel2": [0.35, 0.38, 0.32, 0.22, 0.18, 0.17, 0.19, 0.21, 0.28, 0.36, 0.42, 0.40],
        "origen_lluvia": "OBSERVADO_PIHC",
        "origen_temperatura": "OBSERVADO_SMN",
    }

    return {
        "coordenadas": {"lat": round(centro_lat, 5), "lon": round(centro_lon, 5)},
        "terreno": {
            "superficie_ha": superficie_ha,
            "elevacion_m": round(elevacion_m, 1),
            "pendiente_pct": round(pendiente_pct, 2),
            "pendiente_max_pct": round(pendiente_max_pct, 2),
            "lluvia_anual_mm": round(sum(lluvia_12m), 1),
            "sm_surface_media": sm_surface_media,
            "sm_rootzone_media": sm_rootzone_media,
            "tmin_transicion_c": tmin_critica,
        },
        "autodetectado": {
            "napa_pendiente": napa_pendiente,
            "humedad_estado": humedad_estado,
        },
        "datos_lote": datos_lote,
        "provenance": {
            "relieve": "SRTM 1 ha (srtm_1ha_corredor.parquet)",
            "lluvia": "Estaciones PIHC 30109/30492 (lluvia_agregada_cordoba.csv)",
            "temperatura": "Estaciones SMN 87448/87453 (capa-smn-gsod.csv)",
            "humedad": "Humedad regional SMAP 9 km / POWER (smap_9km_corredor.parquet)",
            "estaciones_lluvia": est_lluvia,
            "estaciones_temperatura": est_temp,
        },
        "quality_status": "VALID_WITH_LIMITATIONS",
        "advertencia_escala": (
            "Relieve a escala de 1 ha; humedad de suelo y clima son referencias regionales/estacionales. "
            "Pozos, cárcavas puntuales y textura real requieren revisión en campo."
        ),
    }
