"""Cargador de la entrega MVP (clima histórico + suelo) para el stack Field Shift.

Uso:
    from data.reference.mvp_homogeneo.cargar_mvp import MVP
    mvp = MVP()                       # lee los archivos de esta carpeta una sola vez
    mvp.clima_lote(-33.67, -65.46)    # serie diaria del punto POWER más cercano
    mvp.resumen_anual(-33.67, -65.46) # ventana de heladas, lluvia, ETo por año
    mvp.suelo_cercano(-33.67, -65.46) # celda de 500 m más cercana (relieve, susceptibilidad, humedad)

Todas las funciones devuelven dicts/listas listos para Pydantic/JSON. Cada registro conserva su
columna `origen` o `etiqueta`: OBSERVADO_* (medido), ESTIMADO_* (reanálisis/modelo), REFERENCIA_*.
No mezclar categorías en un mismo promedio sin declararlo.

Todos los archivos de la entrega están en esta carpeta (incluidos clima diario CSV 56 MB y
suelo 1 ha Parquet 48 MB). BASE_DATOS es solo un respaldo si se clona sin ellos.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

BASE = Path(os.environ.get("FIELD_SHIFT_MVP_DIR", Path(__file__).resolve().parent))
BASE_DATOS = Path(os.environ.get(
    "FIELD_SHIFT_MVP_DATOS",
    "/mnt/ssd2tb/field-shift/datasets/e-cutoff-20261101/consumo/homogeneo-mvp/entrega-mvp",
))


def _leer(nombre: str) -> pd.DataFrame:
    """Busca primero en la carpeta del repo y después en el almacén de datos."""
    for base in (BASE, BASE_DATOS):
        p = base / nombre
        if p.exists():
            return pd.read_parquet(p) if p.suffix == ".parquet" else pd.read_csv(p)
    raise FileNotFoundError(f"{nombre} no está en {BASE} ni en {BASE_DATOS}")


class MVP:
    def __init__(self) -> None:
        self.clima_diario = _leer("clima_diario_grilla_1991_2026.parquet")
        self.clima_diario["fecha"] = pd.to_datetime(self.clima_diario["fecha"])
        self.clima_mensual = _leer("clima_mensual_grilla_1991_2026.parquet")
        self.clima_anual = _leer("clima_anual_grilla_1991_2026.csv")
        self.clima_zona = _leer("clima_zona_diario_1991_2026.csv")
        self.enso = _leer("enso_oni_mensual.csv")
        self.humedad_mensual = _leer("humedad_suelo_mensual_grilla_1991_2026.csv")
        self.suelo_500m = _leer("suelo_500m_grilla.csv")
        self.gaez = _leer("suelo_gaez_cultivos_1981_2010.csv")
        self.sisinta = _leer("suelo_sisinta_perfiles_caja.csv")
        self.estaciones = _leer("estaciones_terrestres.csv")
        self._puntos = self.clima_mensual[["punto_id", "lat", "lon"]].drop_duplicates().reset_index(drop=True)

    # ---- utilidades espaciales (EPSG:4326, distancia euclídea en grados: suficiente dentro de la caja) ----
    def punto_power(self, lat: float, lon: float) -> str:
        i = ((self._puntos.lat - lat) ** 2 + (self._puntos.lon - lon) ** 2).idxmin()
        return str(self._puntos.loc[i, "punto_id"])

    def clima_lote(self, lat: float, lon: float, desde: str = "1991-01-01", hasta: str = "2026-11-01") -> list[dict]:
        pid = self.punto_power(lat, lon)
        s = self.clima_diario
        s = s[(s.punto_id == pid) & (s.fecha >= desde) & (s.fecha <= hasta)]
        return s.assign(fecha=s.fecha.dt.strftime("%Y-%m-%d")).to_dict("records")

    def resumen_anual(self, lat: float, lon: float) -> list[dict]:
        pid = self.punto_power(lat, lon)
        return self.clima_anual[self.clima_anual.punto_id == pid].to_dict("records")

    def clima_mensual_lote(self, lat: float, lon: float) -> list[dict]:
        pid = self.punto_power(lat, lon)
        return self.clima_mensual[self.clima_mensual.punto_id == pid].to_dict("records")

    def humedad_lote(self, lat: float, lon: float) -> list[dict]:
        pid = self.punto_power(lat, lon)
        return self.humedad_mensual[self.humedad_mensual.punto_id == pid].to_dict("records")

    def suelo_cercano(self, lat: float, lon: float) -> dict:
        s = self.suelo_500m
        i = ((s.lat - lat) ** 2 + (s.lon - lon) ** 2).idxmin()
        return s.loc[i].to_dict()

    def gaez_cercano(self, lat: float, lon: float) -> list[dict]:
        g = self.gaez
        d = (g.lat - lat) ** 2 + (g.lon - lon) ** 2
        celda = g[d == d.min()]
        return celda.to_dict("records")

    def estaciones_geojson(self) -> dict:
        feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [r.lon, r.lat]},
                  "properties": {k: v for k, v in r._asdict().items() if k not in ("lat", "lon", "Index")}}
                 for r in self.estaciones.itertuples()]
        return {"type": "FeatureCollection", "features": feats}


if __name__ == "__main__":
    m = MVP()
    print("punto:", m.punto_power(-33.67, -65.46))
    print("anual 2020:", [r for r in m.resumen_anual(-33.67, -65.46) if r["anio"] == 2020])
    print("suelo:", m.suelo_cercano(-33.67, -65.46))
