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

from src.decision.mapa_datos import consultar_terreno  # noqa: E402
from src.decision.motor_rotacion import cargar_rubrica, simular_escenarios  # noqa: E402

LOTES_DEFAULT = REPOSITORY_ROOT / "data" / "lotes_piloto.json"
STATIC_DIR = pathlib.Path(__file__).resolve().parent / "static"

app = FastAPI(title="Field Shift — Ceres Agronauts", version="2.0.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

_HUMEDAD_PRESETS: Dict[str, Dict[str, float]] = {
    "seco": {"10cm": 0.08, "30cm": 0.11, "60cm": 0.13},
    "normal": {"10cm": 0.17, "30cm": 0.21, "60cm": 0.23},
    "humedo": {"10cm": 0.28, "30cm": 0.32, "60cm": 0.34},
}


class EvaluacionRequest(BaseModel):
    lote_id: str = Field(default="villa_mercedes_centro")
    textura: Literal["franco_arenoso", "limoso", "desconocido"] = "franco_arenoso"
    napa_pendiente: Literal["sin_napa", "napa_cercana", "pendiente_anegamiento"] = "sin_napa"
    regimen_agua: Literal["secano", "riego"] = "secano"
    humedad_estado: Literal["seco", "normal", "humedo", "sonda"] = "normal"
    sonda_largo_cm: Optional[float] = Field(default=None, ge=5.0, le=200.0, description="Largo o profundidad de inserción de la sonda en cm")
    sonda_medicion: Optional[float] = Field(default=None, ge=0.03, le=0.55, description="Medición de humedad a esa profundidad en m³/m³")
    sonda_10cm: Optional[float] = Field(default=None, ge=0.05, le=0.45)
    sonda_30cm: Optional[float] = Field(default=None, ge=0.05, le=0.45)
    sonda_60cm: Optional[float] = Field(default=None, ge=0.05, le=0.45)
    estado_lote: Literal["rastrojo", "desnudo", "pastura"] = "rastrojo"
    escenario_lluvia: Literal["seco", "normal", "humedo"] = "normal"
    prioridad: Literal["agua", "renta", "suelo"] = "suelo"
    horizonte: Literal["corto", "mediano", "largo"] = "mediano"
    sistema_productivo: Literal["agricola", "mixto", "contratista"] = "agricola"
    tiene_ganaderia: bool = False
    profundidad_suelo: Literal["superficial", "media", "profunda"] = "media"
    tolerancia_perdidas: Literal["baja", "moderada", "alta"] = "baja"
    lluvia_anual_manual_mm: Optional[float] = Field(default=None, ge=50.0, le=3000.0)
    datos_lote_custom: Optional[Dict[str, Any]] = None


class MapaConsultaRequest(BaseModel):
    lat: Optional[float] = None
    lon: Optional[float] = None
    poligono: Optional[List[List[float]]] = None


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


def _clasificar_semaforo(score: float, tiene_alerta_roja: bool) -> Literal["recomendado", "precaucion", "no_recomendado"]:
    if tiene_alerta_roja or score < 50:
        return "no_recomendado"
    if score >= 68:
        return "recomendado"
    return "precaucion"


def _puntos_a_evaluar_en_lote(diag: Dict[str, Any], req: EvaluacionRequest) -> List[str]:
    puntos: List[str] = []
    suelo = diag["evaluacion_suelo"]
    if diag["meses_suelo_desnudo"] >= 4 or req.estado_lote == "desnudo":
        puntos.append(
            "Evaluar junto a un conocedor del lote cómo cubrir el suelo en invierno (por ejemplo con vicia + centeno) para frenar la voladura por vientos de agosto-septiembre."
        )
    if req.napa_pendiente == "napa_cercana":
        puntos.append(
            "Verificar profundidad y salinidad de la napa freática en el lote: si está en ascenso (como en Cuenca del Morro), analizar si conviene alfalfa plurianual como bomba biológica."
        )
    elif req.napa_pendiente == "pendiente_anegamiento":
        puntos.append(
            "Revisar zonas bajas y escurrimiento ante lluvias torrenciales; evaluar especies tolerantes a encharcamiento temporal o cobertura viva permanente."
        )

    if req.regimen_agua == "secano" and (req.escenario_lluvia == "seco" or diag["estado_hidrico"]["humedad_efectiva"] < 0.16):
        puntos.append(
            "Confirmar agua útil real a 1–2 metros de profundidad antes de sembrar: en secano con baja reserva, evitar doble cultivo anual y ajustar fecha/densidad."
        )
    else:
        puntos.append(
            "Validar fecha de corte/secado primaveral de coberturas (30–45 días antes del cultivo estival) para no competir con las lluvias de primavera."
        )

    if req.textura == "desconocido":
        puntos.append("Realizar análisis granulométrico (textura), pH y profundidad efectiva del lote antes de definir fertilización o cultivos sensibles.")
    return puntos


def _recopilar_fuentes_respaldo(rotaciones: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Consolida y desduplica todas las fuentes bibliográficas de respaldo para el menú dedicado."""
    fuentes_vistas = set()
    consolidadas = []
    for rot in rotaciones:
        for f in rot.get("fuentes", []):
            clave = (f.get("institucion", ""), f.get("titulo", ""))
            if clave not in fuentes_vistas:
                fuentes_vistas.add(clave)
                consolidadas.append({
                    "rotacion": rot["nombre"],
                    "institucion": f.get("institucion", "Desconocida"),
                    "titulo": f.get("titulo", "Sin título"),
                    "url": f.get("url", "#"),
                    "aporte": f.get("aporte", ""),
                })
    return consolidadas


def _analisis_tecnico_detallado(diag: Dict[str, Any], req: EvaluacionRequest) -> List[Dict[str, str]]:
    hum = diag["estado_hidrico"]
    suelo = diag["evaluacion_suelo"]
    return [
        {
            "titulo": "1. Evaluación física e hídrica del suelo",
            "detalle": (
                f"Textura declarada: {suelo['capacidad_retencion']}. Régimen: {req.regimen_agua}. "
                f"Estado de reserva: {suelo['estado_reserva']}. "
                + " ".join(suelo["riesgos_suelo"])
            ),
        },
        {
            "titulo": "2. Balance hídrico e incertidumbre de humedad",
            "detalle": (
                f"Lluvia proyectada: {diag['lluvia_anual_proyectada_mm']} mm/año (escenario '{req.escenario_lluvia}'). "
                f"Humedad efectiva calibrada: {hum['humedad_efectiva']} m³/m³ ({hum['fuente']}, incertidumbre ±{hum['incertidumbre_pct']}%). "
                f"{hum.get('nota', '')}"
            ),
        },
        {
            "titulo": "3. Cobertura, estrés térmico y ventana de heladas",
            "detalle": (
                f"Se estiman {diag['meses_suelo_desnudo']} meses con baja cobertura (NDVI < 0.25) y pico térmico superficial de {diag['pico_termico_ecostress_c']} °C. "
                "En Villa Mercedes las heladas agrometeorológicas (<3 °C) promedian del 29/03 (±24 d) al 09/11 (±19 d), condicionando siembras de segunda."
            ),
        },
    ]


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


@app.post("/api/mapa/consultar")
def consultar_mapa(req: MapaConsultaRequest) -> Dict[str, Any]:
    try:
        return consultar_terreno(lat=req.lat, lon=req.lon, poligono=req.poligono)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/evaluar")
def evaluar_lote(req: EvaluacionRequest) -> Dict[str, Any]:
    if req.datos_lote_custom:
        datos_lote = dict(req.datos_lote_custom)
    else:
        lotes = _cargar_lotes()
        lote = next((x for x in lotes if x.get("id") == req.lote_id), lotes[0] if lotes else None)
        if not lote:
            raise HTTPException(status_code=404, detail="No se encontró el lote seleccionado.")
        datos_lote = dict(lote)
        if req.lluvia_anual_manual_mm is not None:
            lluvia_base = datos_lote.get("lluvia_gpm_mm") or [1.0] * 12
            suma_base = sum(lluvia_base) or 12.0
            factor = req.lluvia_anual_manual_mm / suma_base
            datos_lote["lluvia_gpm_mm"] = [round(v * factor, 2) for v in lluvia_base]
            datos_lote["origen_lluvia"] = "INGRESO_MANUAL"
    if req.estado_lote == "desnudo":
        datos_lote["ndvi_sentinel2"] = [0.15] * 12
    elif req.estado_lote == "pastura":
        datos_lote["ndvi_sentinel2"] = [0.45] * 12

    profundidad_sonda_cm = None
    medicion_sonda_directa = None

    if req.humedad_estado == "sonda":
        if req.sonda_largo_cm is not None and req.sonda_medicion is not None:
            profundidad_sonda_cm = req.sonda_largo_cm
            medicion_sonda_directa = req.sonda_medicion
            lecturas_sonda = None
        else:
            lecturas_sonda = {
                "10cm": req.sonda_10cm if req.sonda_10cm is not None else 0.17,
                "30cm": req.sonda_30cm if req.sonda_30cm is not None else 0.21,
                "60cm": req.sonda_60cm if req.sonda_60cm is not None else 0.23,
            }
    else:
        lecturas_sonda = _HUMEDAD_PRESETS[req.humedad_estado]

    _PROFUNDIDAD_MAP = {"superficial": 60.0, "media": 100.0, "profunda": 150.0}
    profundidad_efectiva_cm = _PROFUNDIDAD_MAP.get(req.profundidad_suelo, 100.0)

    sim = simular_escenarios(
        datos_lote=datos_lote,
        prioridad_usuario=req.prioridad,
        tiene_ganaderia=req.tiene_ganaderia or req.sistema_productivo == "mixto",
        escenario_lluvia=req.escenario_lluvia,
        lecturas_sonda=lecturas_sonda,
        textura=req.textura,
        napa_pendiente=req.napa_pendiente,
        regimen_agua=req.regimen_agua,
        estado_lote=req.estado_lote,
        horizonte=req.horizonte,
        sistema_productivo=req.sistema_productivo,
        profundidad_sonda_cm=profundidad_sonda_cm,
        medicion_sonda_directa=medicion_sonda_directa,
        profundidad_efectiva_cm=profundidad_efectiva_cm,
        tolerancia_perdidas=req.tolerancia_perdidas,
    )

    diag = sim["diagnostico_lote"]
    tarjetas = []
    for item in sim["comparativa_rotaciones"]:
        score = item["puntaje_idoneidad"]
        alertas_rojas = item.get("alertas_rojas", [])
        semaforo = _clasificar_semaforo(score, len(alertas_rojas) > 0)
        tarjetas.append(
            {
                "id": item["id"],
                "nombre": item["nombre"],
                "secuencia": item["secuencia"],
                "horizonte_label": item["horizonte_label"],
                "demanda_hidrica_mm": item.get("demanda_hidrica_mm"),
                "semaforo": semaforo,
                "score": score,
                "score_base": item["score_base_dimensiones"],
                "ajuste_contextual": item["ajuste_contextual"],
                "resumen": item["resumen_campo"],
                "cuando_rotar": item["cuando_rotar"],
                "criterio_terminacion": item["criterio_terminacion"],
                "alertas_rojas": alertas_rojas,
                "alertas": item.get("alertas_escenario", []),
                "dimensiones": item["dimensiones"],
                "fuentes": item["fuentes"],
            }
        )

    return {
        "lote": diag["lote"],
        "suelo": diag["suelo"],
        "alerta_principal": diag["alerta_principal"],
        "tarjetas": tarjetas,
        "puntos_evaluar": _puntos_a_evaluar_en_lote(diag, req),
        "analisis_tecnico": _analisis_tecnico_detallado(diag, req),
        "fuentes_respaldo": _recopilar_fuentes_respaldo(sim["comparativa_rotaciones"]),
        "pesos_aplicados": diag["pesos_aplicados"],
        "balance_fao56": diag.get("balance_fao56"),
        "dimensiones_faltantes": diag.get("dimensiones_faltantes", []),
        "profundidad_efectiva_cm": diag.get("profundidad_efectiva_cm"),
        "tolerancia_perdidas": diag.get("tolerancia_perdidas"),
        "detalle_tecnico": {
            "lluvia_anual_proyectada_mm": diag["lluvia_anual_proyectada_mm"],
            "humedad_efectiva_m3_m3": diag["estado_hidrico"]["humedad_efectiva"],
            "incertidumbre_pct": diag["estado_hidrico"]["incertidumbre_pct"],
            "fuente_humedad": diag["estado_hidrico"]["fuente"],
            "pico_termico_c": diag["pico_termico_ecostress_c"],
            "meses_suelo_desnudo": diag["meses_suelo_desnudo"],
        },
    }
