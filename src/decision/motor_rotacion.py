"""
Motor de decisión agronómica y evaluación de rotaciones para Field Shift (Villa Mercedes / San Luis).
Basado en rúbrica multicriterio de 5 dimensiones (15 variables), calibración híbrida de humedad
(NASA SMAP L4 + sonda de suelo 10, 30 y 60 cm) y evaluación física-hídrica del suelo.

Ajustes y calibraciones funcionales (Angie Méndez - Análisis Funcional y Calidad de Datos):
1. Calibración térmica de mínimas satelitales (-1.04 °C respecto a REM Estación 42 Villa Mercedes)
   para evaluar con precisión el umbral de heladas agrometeorológicas (<= 3.0 °C).
2. Sonda local de humedad de perfil disponible (10, 30 y 60 cm) ponderada para mitigar incertidumbre de SMAP.
3. Precipitación consensuada: al no contar con pluviómetro in-situ en el lote, se calcula la media
   entre el dato satelital bruto (NASA POWER) y el valor calibrado local (descuento del 20% de sobreestimación),
   manteniendo limpia el área visual del productor.
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
    profundidad_sonda_cm: Optional[float] = None,
    medicion_sonda_directa: Optional[float] = None,
) -> Dict[str, Any]:
    """
    SMAP L4 mide humedad superficial (~0-5 cm, sm_surface) con mayor incertidumbre en suelos arenosos.
    Si se dispone de medición con sonda a profundidad específica (profundidad_sonda_cm y medicion_sonda_directa)
    o de perfil multiprofundidad (10, 30 y 60 cm), se pondera la zona radicular efectiva y se reduce la incertidumbre.
    """
    # Caso 1: Sonda puntual con largo/profundidad configurado por el usuario
    if profundidad_sonda_cm is not None and medicion_sonda_directa is not None:
        p_cm = float(profundidad_sonda_cm)
        med = float(medicion_sonda_directa)
        
        # Ponderación según profundidad de inserción radicular
        if p_cm <= 15:
            # Sonda superficial (0-15 cm): alta correlación con evaporación directa
            peso_sonda = 0.65
            peso_smap = 0.35
            estrato = "superficial (0–15 cm)"
            incertidumbre = 12
        elif p_cm <= 45:
            # Sonda media / estrato radicular principal (15-45 cm): máxima representatividad de agua útil
            peso_sonda = 0.80
            peso_smap = 0.20
            estrato = f"estrato radicular medio ({round(p_cm)} cm)"
            incertidumbre = 6
        elif p_cm <= 90:
            # Sonda profunda (45-90 cm): reserva de fondo para cultivos de verano y especies rústicas
            peso_sonda = 0.85
            peso_smap = 0.15
            estrato = f"perfil subsuperficial ({round(p_cm)} cm)"
            incertidumbre = 5
        else:
            # Sonda muy profunda (>90 cm): agua freática o reserva profunda de ciclo completo
            peso_sonda = 0.88
            peso_smap = 0.12
            estrato = f"profundidad profunda ({round(p_cm)} cm)"
            incertidumbre = 5

        humedad_calibrada = (peso_sonda * med) + (peso_smap * humedad_smap_superficial)
        desvio = round((humedad_calibrada - humedad_smap_superficial) * 100, 1)

        return {
            "humedad_efectiva": round(humedad_calibrada, 3),
            "fuente": f"Fusión Sonda {round(p_cm)} cm + Satélite SMAP",
            "incertidumbre_pct": incertidumbre,
            "profundidad_sonda_cm": round(p_cm, 1),
            "medicion_sonda_directa": round(med, 3),
            "estrato_radicular": estrato,
            "nota": f"Sonda local a {round(p_cm)} cm ({med:.2f} m³/m³, {estrato}). Desvío respecto a satélite superficial: {desvio:+.1f}%.",
        }

    # Caso 2: Perfil multi-nivel convencional (10, 30 y 60 cm)
    if lecturas_sonda_cm:
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
            "profundidad_sonda_cm": 60.0,
            "medicion_sonda_directa": None,
            "estrato_radicular": "perfil radicular integrado (0–60 cm)",
            "nota": f"Desvío corregido respecto a satélite superficial: {desvio:+.1f}%.",
        }

    # Caso 3: Solo satélite sin sonda in-situ
    return {
        "humedad_efectiva": round(humedad_smap_superficial, 3),
        "fuente": "Solo Satélite NASA SMAP (0-5 cm)",
        "incertidumbre_pct": 28,
        "profundidad_sonda_cm": None,
        "medicion_sonda_directa": None,
        "estrato_radicular": "superficial estricto (0–5 cm)",
        "nota": "Dato superficial satelital. Se recomienda contrastar con sonda in-situ en el lote.",
    }


def calibrar_minima_termica(tmin_satelital: float) -> Dict[str, Any]:
    """
    Calibración térmica de mínimas satelitales (NASA POWER T2M_MIN vs REM Estación 42 Villa Mercedes).
    El satélite sobreestima las mínimas en promedio +1.04 °C (10.30 °C vs 9.26 °C).
    La temperatura real a nivel de cultivo / suelo es más fría, incrementando el riesgo
    de heladas agrometeorológicas (umbral <= 3.0 °C).
    """
    tmin_calibrada = round(tmin_satelital - 1.04, 2)
    riesgo_helada = tmin_calibrada <= 3.0
    buffer_seguridad = tmin_calibrada <= 4.5  # Margen preventivo para heladas agronómicas

    if riesgo_helada:
        alerta = f"ALERTA HELADA AGROMETEOROLÓGICA: Mínima calibrada {tmin_calibrada} °C (satélite reportó {tmin_satelital} °C). Riesgo crítico para floración/llenado."
    elif buffer_seguridad:
        alerta = f"PRECAUCIÓN TÉRMICA: Mínima calibrada {tmin_calibrada} °C próxima al umbral de daño agrometeorológico (3.0 °C)."
    else:
        alerta = f"Térmicamente seguro: Mínima calibrada {tmin_calibrada} °C sin riesgo inminente de helada."

    return {
        "tmin_satelital_c": tmin_satelital,
        "tmin_calibrada_c": tmin_calibrada,
        "correccion_aplicada_c": -1.04,
        "riesgo_helada": riesgo_helada,
        "buffer_seguridad": buffer_seguridad,
        "alerta_termica": alerta,
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
    profundidad_sonda_cm: Optional[float] = None,
    medicion_sonda_directa: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Simula y compara las 3 estrategias de rotación reales de la rúbrica para un lote de San Luis.
    """
    rubrica = cargar_rubrica()
    factores_clima = {"seco": 0.75, "normal": 1.0, "humedo": 1.20}
    factor_clima = factores_clima.get(escenario_lluvia, 1.0)

    # Calibración de precipitación consensuada (Angie Méndez):
    # NASA POWER sobreestima la lluvia en Villa Mercedes en +20.0% (+1.340 mm en 11 años).
    # Dado que el agricultor cuenta con sonda de humedad de suelo (10, 30 y 60 cm) pero sin pluviómetro en lote,
    # se adopta la media entre la lectura satelital bruta y el valor calibrado local (reducción de sobreestimación).
    lluvias = datos_lote.get("lluvia_gpm_mm", [665 / 12] * 12)
    lluvia_satelital_bruta = sum(lluvias)
    lluvia_calibrada_local = lluvia_satelital_bruta / 1.20  # Corrección por sobreestimación del 20%
    lluvia_media_consenso = (lluvia_satelital_bruta + lluvia_calibrada_local) / 2.0
    lluvia_proyectada = lluvia_media_consenso * factor_clima

    ndvi_series = datos_lote.get("ndvi_sentinel2", [0.3] * 12)
    meses_desnudos = sum(1 for ndvi in ndvi_series if ndvi < 0.25)

    temps = datos_lote.get("temp_superficial_ecostress_c", [35.0])
    temp_max_verano = max(temps) if temps else 35.0
    # Temperatura mínima satelital (de lote o promedio histórico de referencia 9.0 °C en transición)
    tmin_satelital = datos_lote.get("temp_min_satelital_c", 3.8)
    analisis_heladas = calibrar_minima_termica(tmin_satelital)

    smap_series = datos_lote.get("humedad_suelo_smap", [0.18])
    smap_media = sum(smap_series) / len(smap_series) if smap_series else 0.18

    humedad_info = calibrar_humedad_suelo(smap_media, lecturas_sonda, profundidad_sonda_cm, medicion_sonda_directa)
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
        "lluvia_satelital_bruta_mm": round(lluvia_satelital_bruta * factor_clima),
        "lluvia_calibrada_local_mm": round(lluvia_calibrada_local * factor_clima),
        "meses_suelo_desnudo": meses_desnudos,
        "pico_termico_ecostress_c": temp_max_verano,
        "analisis_heladas": analisis_heladas,
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
            # Si el productor tiene sonda superficial (<=20 cm) y la humedad es deficiente, alerta riesgo de implantación de doble cultivo
            if profundidad_sonda_cm and profundidad_sonda_cm <= 25 and humedad_efectiva < 0.16:
                ajuste -= 8.0
                alertas_escenario.append(
                    f"Sonda a {round(profundidad_sonda_cm)} cm indica cama de siembra seca ({humedad_efectiva} m³/m³): riesgo severo de emergencia despareja en doble cultivo."
                )
            elif profundidad_sonda_cm and profundidad_sonda_cm >= 40 and humedad_efectiva >= 0.22 and regimen_agua != "riego":
                ajuste += 4.0
                alertas_escenario.append(
                    f"Sonda a {round(profundidad_sonda_cm)} cm confirma recarga subsuperficial ({humedad_efectiva} m³/m³), dando mayor sostén al llenado de grano."
                )

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
                    f"ALERTA TÉRMICA/HELADAS: Mínima calibrada {analisis_heladas['tmin_calibrada_c']} °C (-1.04 °C sobre satélite). Retrasar la siembra de 2ª tras cosechar trigo expone el llenado a heladas tempranas de otoño en Villa Mercedes (ventana crítica marzo-noviembre)."
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
            # Si el productor midió con sonda en profundidad (>50 cm) y detecta humedad alta, valida el uso de raíces profundas
            if profundidad_sonda_cm and profundidad_sonda_cm >= 50 and humedad_efectiva >= 0.22:
                ajuste += 8.0
                alertas_escenario.append(
                    f"Sonda a {round(profundidad_sonda_cm)} cm confirma buena recarga profunda ({humedad_efectiva} m³/m³): ideal para implantación de raíces profundas (alfalfa/pasturas)."
                )
            elif profundidad_sonda_cm and profundidad_sonda_cm >= 50 and humedad_efectiva < 0.14:
                ajuste -= 6.0
                alertas_escenario.append(
                    f"Sonda a {round(profundidad_sonda_cm)} cm detecta estrato profundo seco ({humedad_efectiva} m³/m³): atrasar siembra o asegurar reserva freática."
                )

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
            # Si la sonda se colocó a profundidad intermedia o profunda (>=30 cm) y la humedad es limitante, el sorgo/girasol es la mejor opción
            if profundidad_sonda_cm and profundidad_sonda_cm >= 30 and humedad_efectiva < 0.18:
                ajuste += 6.0
                alertas_escenario.append(
                    f"Sonda a {round(profundidad_sonda_cm)} cm reporta perfil ajustado ({humedad_efectiva} m³/m³): rusticidad y raíces exploratorias de sorgo/girasol brindan alta seguridad."
                )

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
