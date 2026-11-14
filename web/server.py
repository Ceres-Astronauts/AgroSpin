"""Servidor web FastAPI para la interfaz de productor agropecuario (Field Shift)."""

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

from src.decision.motor_rotacion import simular_escenarios  # noqa: E402

LOTES_DEFAULT = REPOSITORY_ROOT / "data" / "lotes_piloto.json"
STATIC_DIR = pathlib.Path(__file__).resolve().parent / "static"

app = FastAPI(title="Field Shift — Ceres Agronauts", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

_HUMEDAD_PRESETS: Dict[str, Dict[str, float]] = {
    "seco": {"10cm": 0.08, "30cm": 0.11, "60cm": 0.13},
    "normal": {"10cm": 0.17, "30cm": 0.21, "60cm": 0.23},
    "humedo": {"10cm": 0.28, "30cm": 0.32, "60cm": 0.34},
}


class EvaluacionRequest(BaseModel):
    lote_id: str = Field(default="villa_mercedes_centro")
    humedad_estado: Literal["seco", "normal", "humedo", "sonda"] = "normal"
    sonda_10cm: Optional[float] = Field(default=None, ge=0.05, le=0.45)
    sonda_30cm: Optional[float] = Field(default=None, ge=0.05, le=0.45)
    sonda_60cm: Optional[float] = Field(default=None, ge=0.05, le=0.45)
    estado_lote: Literal["rastrojo", "desnudo", "pastura"] = "rastrojo"
    escenario_lluvia: Literal["seco", "normal", "humedo"] = "normal"
    prioridad: Literal["agua", "renta", "suelo"] = "suelo"
    tiene_ganaderia: bool = False


def _cargar_lotes() -> List[Dict[str, Any]]:
    if LOTES_DEFAULT.is_file():
        try:
            data = json.loads(LOTES_DEFAULT.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return data
            if isinstance(data, dict) and "lotes" in data:
                return data["lotes"]
        except Exception:
            pass
    return [
        {
            "id": "villa_mercedes_centro",
            "nombre": "Villa Mercedes — Lote Piloto (INTA San Luis)",
            "suelo": "Franco-arenoso",
            "lluvia_gpm_mm": [55.4] * 12,
            "humedad_suelo_smap": [0.18] * 12,
            "ndvi_sentinel2": [0.35, 0.38, 0.32, 0.22, 0.18, 0.17, 0.19, 0.21, 0.28, 0.36, 0.42, 0.40],
            "temp_superficial_ecostress_c": [36.5],
        }
    ]


def _clasificar_semaforo(score: float) -> Literal["recomendado", "precaucion", "no_recomendado"]:
    if score >= 65:
        return "recomendado"
    if score >= 45:
        return "precaucion"
    return "no_recomendado"


@app.get("/")
def home() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/lotes")
def listar_lotes() -> Dict[str, Any]:
    lotes = _cargar_lotes()
    resumen = [
        {
            "id": lote.get("id", f"lote_{i}"),
            "nombre": lote.get("nombre", f"Lote {i + 1}"),
            "suelo": lote.get("suelo", "Franco-arenoso"),
        }
        for i, lote in enumerate(lotes)
    ]
    return {"lotes": resumen}


@app.post("/api/evaluar")
def evaluar_lote(req: EvaluacionRequest) -> Dict[str, Any]:
    lotes = _cargar_lotes()
    lote = next((x for x in lotes if x.get("id") == req.lote_id), lotes[0] if lotes else None)
    if not lote:
        raise HTTPException(status_code=404, detail="No se encontró el lote seleccionado.")

    datos_lote = dict(lote)
    if req.estado_lote == "desnudo":
        datos_lote["ndvi_sentinel2"] = [0.15] * 12
    elif req.estado_lote == "pastura":
        datos_lote["ndvi_sentinel2"] = [0.45] * 12

    if req.humedad_estado == "sonda":
        lecturas_sonda = {
            "10cm": req.sonda_10cm if req.sonda_10cm is not None else 0.17,
            "30cm": req.sonda_30cm if req.sonda_30cm is not None else 0.21,
            "60cm": req.sonda_60cm if req.sonda_60cm is not None else 0.23,
        }
    else:
        lecturas_sonda = _HUMEDAD_PRESETS[req.humedad_estado]

    sim = simular_escenarios(
        datos_lote=datos_lote,
        prioridad_usuario=req.prioridad,
        tiene_ganaderia=req.tiene_ganaderia,
        escenario_lluvia=req.escenario_lluvia,
        lecturas_sonda=lecturas_sonda,
    )

    diag = sim["diagnostico_lote"]
    tarjetas = []
    for item in sim["comparativa_rotaciones"]:
        score = item["puntaje_idoneidad"]
        semaforo = _clasificar_semaforo(score)
        tarjetas.append(
            {
                "nombre": item["nombre"],
                "semaforo": semaforo,
                "score": score,
                "resumen": item.get("riesgo_humano", ""),
                "alertas": item.get("alertas_escenario", []),
            }
        )

    return {
        "lote": diag["lote"],
        "suelo": diag["suelo"],
        "alerta_principal": diag["alerta_principal"],
        "tarjetas": tarjetas,
        "detalle_tecnico": {
            "lluvia_anual_proyectada_mm": diag["lluvia_anual_proyectada_mm"],
            "humedad_efectiva_m3_m3": diag["estado_hidrico"]["humedad_efectiva"],
            "incertidumbre_pct": diag["estado_hidrico"]["incertidumbre_pct"],
            "fuente_humedad": diag["estado_hidrico"]["fuente"],
            "pico_termico_c": diag["pico_termico_ecostress_c"],
            "meses_suelo_desnudo": diag["meses_suelo_desnudo"],
        },
    }
