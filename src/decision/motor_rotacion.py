"""
Motor de decisión agronómica y evaluación de rotaciones para Field Shift (Villa Mercedes / San Luis).
Basado en rúbrica multicriterio de 5 dimensiones (15 variables), calibración híbrida de humedad
(NASA SMAP L4 + nodo terrestre ESP32) y evaluación física-hídrica del suelo.
"""

import json
import pathlib
from typing import Any, Dict, List, Optional

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[2]
RUBRICA_PATH = REPOSITORY_ROOT / "data" / "rubrica_rotaciones.json"

_PESOS_POR_PRIORIDAD: Dict[str, Dict[str, float]] = {
    "agua": {
        "agua_suelo": 0.36,
        "clima_temperatura": 0.22,
        "produccion_sostenibilidad": 0.22,
        "sanidad_agricola": 0.10,
        "negocio_mercado": 0.10,
    },
    "suelo": {
        "produccion_sostenibilidad": 0.34,
        "agua_suelo": 0.28,
        "clima_temperatura": 0.16,
        "sanidad_agricola": 0.12,
        "negocio_mercado": 0.10,
    },
    "renta": {
        "negocio_mercado": 0.34,
        "agua_suelo": 0.24,
        "clima_temperatura": 0.18,
        "produccion_sostenibilidad": 0.14,
        "sanidad_agricola": 0.10,
    },
}


def cargar_rubrica() -> Dict[str, Any]:
    """Carga la rúbrica oficial de rotaciones y criterios desde data/rubrica_rotaciones.json."""
    if not RUBRICA_PATH.is_file():
        raise FileNotFoundError(f"No se encontró la rúbrica en {RUBRICA_PATH}")
    return json.loads(RUBRICA_PATH.read_text(encoding="utf-8"))


def calibrar_humedad_suelo(
    humedad_smap_superficial: float,
    lecturas_sonda_cm: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    SMAP L4 mide humedad superficial (~0-5 cm, sm_surface) con mayor incertidumbre en suelos arenosos.
    Si se dispone de nodo terrestre (ESP32 con sensores capacitivos a 10, 30 y 60 cm) o estimación
    de perfil, se pondera la zona radicular efectiva y se reduce la incertidumbre.
    """
    if not lecturas_sonda_cm:
        return {
            "humedad_efectiva": round(humedad_smap_superficial, 3),
            "fuente": "Solo Satélite NASA SMAP (0-5 cm)",
            "incertidumbre_pct": 28,
            "nota": "Dato superficial satelital. Se recomienda contrastar con perfil profundo o calicata/sonda en lote.",
        }

    perfil_real = (
        0.20 * lecturas_sonda_cm.get("10cm", 0.15)
        + 0.45 * lecturas_sonda_cm.get("30cm", 0.20)
        + 0.35 * lecturas_sonda_cm.get("60cm", 0.22)
    )
    humedad_calibrada = 0.75 * perfil_real + 0.25 * humedad_smap_superficial
    desvio = round((humedad_calibrada - humedad_smap_superficial) * 100, 1)

    return {
        "humedad_efectiva": round(humedad_calibrada, 3),
        "fuente": "Fusión Híbrida (NASA SMAP + Perfil 10/30/60 cm)",
        "incertidumbre_pct": 7,
        "nota": f"Desvío corregido respecto a satélite superficial: {desvio:+.1f}%.",
    }


def evaluar_suelo_lote(
    textura: str,
    napa_pendiente: str,
    regimen_agua: str,
    estado_lote: str,
    humedad_efectiva: float,
    meses_desnudos: int,
) -> Dict[str, Any]:
    """
    Evalúa el estado físico, hídrico y de conservación del suelo según los criterios
    del documento técnico para San Luis (retención, erosión, drenaje/sellado y napa).
    """
    riesgos_suelo: List[str] = []
    if textura == "franco_arenoso":
        capacidad_retencion = "Baja a moderada (suelo liviano franco-arenoso)"
        riesgos_suelo.append("Alta vulnerabilidad a erosión eólica invernal y baja retención de agua útil.")
    elif textura == "limoso":
        capacidad_retencion = "Moderada a alta (suelo franco-limoso)"
        riesgos_suelo.append("Susceptibilidad al sellado superficial (planchado) y escurrimiento ante lluvias torrenciales.")
    else:
        capacidad_retencion = "Variable (requiere análisis granulométrico por profundidad)"
        riesgos_suelo.append("Sin análisis de textura confirmado; validar profundidad efectiva y capas compactadas.")

    if napa_pendiente == "napa_cercana":
        riesgos_suelo.append("Presencia de napa freática cercana (riesgo de ascenso, anegamiento o salinización si no se consume excedente).")
    elif napa_pendiente == "pendiente_anegamiento":
        riesgos_suelo.append("Lote con pendiente o riesgo de encharcamiento temporal; exige cobertura viva para frenar erosión hídrica.")

    if meses_desnudos >= 4 or estado_lote == "desnudo":
        riesgos_suelo.append("Suelo descubierto prolongado: acelera evaporación directa y pérdida de carbono superficial.")

    if regimen_agua == "secano" and humedad_efectiva < 0.14:
        estado_reserva = "Reserva hídrica inicial crítica / baja"
    elif humedad_efectiva >= 0.24:
        estado_reserva = "Buena recarga hídrica en el perfil"
    else:
        estado_reserva = "Reserva hídrica moderada"

    return {
        "textura": textura,
        "capacidad_retencion": capacidad_retencion,
        "napa_pendiente": napa_pendiente,
        "regimen_agua": regimen_agua,
        "estado_reserva": estado_reserva,
        "riesgos_suelo": riesgos_suelo,
    }


def _calcular_dimensiones_base(metodo: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Calcula el promedio normalizado (0-100) de cada una de las 5 dimensiones
    para evitar el doble conteo de variables hídricas o térmicas correlacionadas.
    """
    resultado: Dict[str, Dict[str, Any]] = {}
    for dim_key, dim_data in metodo["dimensiones"].items():
        criterios = dim_data["criterios"]
        promedio_1_5 = sum(c["puntuacion"] for c in criterios) / len(criterios)
        score_100 = round((promedio_1_5 / 5.0) * 100.0, 1)
        resultado[dim_key] = {
            "nombre": dim_data["nombre"],
            "promedio_1_5": round(promedio_1_5, 2),
            "score_100": score_100,
            "criterios": criterios,
        }
    return resultado


def simular_escenarios(
    datos_lote: Dict[str, Any],
    prioridad_usuario: str = "suelo",
    tiene_ganaderia: bool = False,
    escenario_lluvia: str = "normal",
    lecturas_sonda: Optional[Dict[str, float]] = None,
    textura: str = "franco_arenoso",
    napa_pendiente: str = "sin_napa",
    regimen_agua: str = "secano",
    estado_lote: str = "rastrojo",
    horizonte: str = "mediano",
    sistema_productivo: str = "agricola",
) -> Dict[str, Any]:
    """
    Simula y compara las 3 estrategias de rotación reales de la rúbrica para un lote de San Luis.
    """
    rubrica = cargar_rubrica()
    factores_clima = {"seco": 0.75, "normal": 1.0, "humedo": 1.20}
    factor_clima = factores_clima.get(escenario_lluvia, 1.0)

    lluvias = datos_lote.get("lluvia_gpm_mm", [665 / 12] * 12)
    lluvia_proyectada = sum(lluvias) * factor_clima

    ndvi_series = datos_lote.get("ndvi_sentinel2", [0.3] * 12)
    meses_desnudos = sum(1 for ndvi in ndvi_series if ndvi < 0.25)

    temps = datos_lote.get("temp_superficial_ecostress_c", [35.0])
    temp_max_verano = max(temps)

    smap_series = datos_lote.get("humedad_suelo_smap", [0.18])
    smap_media = sum(smap_series) / len(smap_series) if smap_series else 0.18

    humedad_info = calibrar_humedad_suelo(smap_media, lecturas_sonda)
    humedad_efectiva = humedad_info["humedad_efectiva"]

    suelo_eval = evaluar_suelo_lote(
        textura=textura,
        napa_pendiente=napa_pendiente,
        regimen_agua=regimen_agua,
        estado_lote=estado_lote,
        humedad_efectiva=humedad_efectiva,
        meses_desnudos=meses_desnudos,
    )

    pesos = dict(_PESOS_POR_PRIORIDAD.get(prioridad_usuario, _PESOS_POR_PRIORIDAD["suelo"]))
    if tiene_ganaderia or sistema_productivo == "mixto":
        pesos["produccion_sostenibilidad"] = round(pesos["produccion_sostenibilidad"] + 0.05, 2)
        pesos["negocio_mercado"] = max(0.05, round(pesos["negocio_mercado"] - 0.05, 2))

    diagnostico = {
        "lote": datos_lote.get("nombre", "Lote Piloto Villa Mercedes"),
        "suelo": suelo_eval["capacidad_retencion"],
        "evaluacion_suelo": suelo_eval,
        "lluvia_anual_proyectada_mm": round(lluvia_proyectada),
        "meses_suelo_desnudo": meses_desnudos,
        "pico_termico_ecostress_c": temp_max_verano,
        "estado_hidrico": humedad_info,
        "pesos_aplicados": pesos,
        "alerta_principal": (
            suelo_eval["riesgos_suelo"][0]
            if suelo_eval["riesgos_suelo"]
            else "Condición estructural estable."
        ),
    }

    resultados: List[Dict[str, Any]] = []
    for metodo in rubrica["metodos"]:
        m_id = metodo["id"]
        dims = _calcular_dimensiones_base(metodo)

        score_base = sum(dims[d]["score_100"] * pesos[d] for d in pesos)
        ajuste = 0.0
        alertas_rojas: List[str] = []
        alertas_escenario: List[str] = []

        # Reglas contextuales por método y condiciones reales del lote
        if m_id == "doble_golpe":
            if regimen_agua == "secano" and napa_pendiente != "napa_cercana":
                if escenario_lluvia == "seco" or humedad_efectiva < 0.16 or lluvia_proyectada < 620:
                    ajuste -= 22.0
                    alertas_rojas.append(
                        "ALERTA ROJA HÍDRICA: En secano sin napa cercana, el trigo invernal agota el agua útil y deja el perfil seco para soja/maíz de 2ª, con riesgo alto de falla total."
                    )
                else:
                    ajuste -= 10.0
                    alertas_escenario.append(
                        "Secuencia muy exigente en agua: requiere monitoreo estricto de recarga otoñal y fecha de trilla temprana."
                    )
                alertas_rojas.append(
                    "ALERTA TÉRMICA/HELADAS: Retrasar la siembra de 2ª tras cosechar trigo expone el llenado a heladas tempranas de otoño en Villa Mercedes (fecha media desde fines de marzo/abril)."
                )
            elif regimen_agua == "riego":
                ajuste += 14.0
                alertas_escenario.append(
                    "Con riego complementario se mitiga el déficit invernal del trigo y se habilita la recarga para el cultivo de 2ª."
                )
            elif napa_pendiente == "napa_cercana":
                ajuste += 6.0
                alertas_escenario.append(
                    "Napa cercana puede aportar agua capilar, aunque sigue siendo insuficiente frente a pasturas perennes si hay ascenso freático."
                )

        elif m_id == "bomba_biologica":
            if napa_pendiente in ("napa_cercana", "pendiente_anegamiento"):
                ajuste += 15.0
                alertas_escenario.append(
                    "Estrategia clave para el lote: la alfalfa actúa como bomba biológica consumiendo excedentes freáticos todo el año y frenando la erosión."
                )
            elif escenario_lluvia == "seco" and regimen_agua == "secano" and napa_pendiente == "sin_napa":
                ajuste -= 8.0
                alertas_escenario.append(
                    "En secano sin napa y año seco, la alfalfa exige barbecho primaveral anticipado para no dejar el perfil seco al maíz tardío."
                )

            if sistema_productivo == "contratista" and metodo["requiere_maquinaria_especial"]:
                ajuste -= 6.0
                alertas_escenario.append(
                    "Requiere maquinaria de henificación (segadora/enfardadora) o coordinación con contratistas/ganadería."
                )

        elif m_id == "resiliencia_hidrica":
            if regimen_agua == "secano" and (escenario_lluvia == "seco" or humedad_efectiva < 0.18 or textura == "franco_arenoso"):
                ajuste += 10.0
                alertas_escenario.append(
                    "Óptima adaptación a suelos franco-arenosos y años secos: rastrojo de centeno + vicia frena evaporación y sorgo/girasol estabilizan el piso productivo."
                )
            if napa_pendiente == "napa_cercana":
                ajuste -= 6.0
                alertas_escenario.append(
                    "Con napa cercana en ascenso, su consumo hídrico anual es menor que el de una pastura perenne."
                )
            if estado_lote == "desnudo":
                ajuste += 4.0
                alertas_escenario.append(
                    "La mezcla vicia + centeno corrige rápidamente la falta de cobertura invernal y reduce erosión eólica."
                )

        # Modificador por horizonte temporal elegido por el productor
        if horizonte == metodo["horizonte"]:
            ajuste += 5.0
        elif horizonte == "corto" and metodo["horizonte"] == "largo":
            ajuste -= 8.0
            alertas_escenario.append("Implica compromiso plurianual (4–5 años), mayor al horizonte de corto plazo elegido.")

        # Modificador por ganadería
        if tiene_ganaderia and metodo["apta_ganaderia"]:
            ajuste += 5.0

        score_final = max(0.0, min(100.0, round(score_base + ajuste, 1)))

        evidencia_txt = "; ".join(f"{f['institucion']}: {f['titulo']}" for f in metodo["fuentes"])
        riesgo_txt = " | ".join(alertas_rojas) if alertas_rojas else metodo["cuando_rotar"]
        lagunas_txt = (
            "Validar análisis granulométrico, profundidad de napa y calendario real en campo con un agrónomo local."
        )

        resultados.append({
            "id": m_id,
            "nombre": metodo["nombre"],
            "secuencia": metodo["secuencia"],
            "horizonte_label": metodo["horizonte_label"],
            "puntaje_idoneidad": score_final,
            "score_base_dimensiones": round(score_base, 1),
            "ajuste_contextual": round(ajuste, 1),
            "resumen_campo": metodo["resumen_campo"],
            "cuando_rotar": metodo["cuando_rotar"],
            "criterio_terminacion": metodo["criterio_terminacion"],
            "alertas_rojas": alertas_rojas,
            "alertas_escenario": alertas_escenario,
            "dimensiones": dims,
            "fuentes": metodo["fuentes"],
            "evidencia": evidencia_txt,
            "lagunas_info": lagunas_txt,
            "riesgo_humano": riesgo_txt,
        })

    resultados.sort(key=lambda x: x["puntaje_idoneidad"], reverse=True)
    return {
        "diagnostico_lote": diagnostico,
        "comparativa_rotaciones": resultados,
    }
