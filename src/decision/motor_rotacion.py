"""
Motor de decisión agronómica y evaluación de rotaciones para Field Shift (Villa Mercedes / Justo Daract - San Luis).
Basado en rúbrica multicriterio de 5 dimensiones (15 variables), calibración híbrida de humedad
(NASA SMAP L4 + sonda de suelo a profundidad configurable) y evaluación física-hídrica del suelo.

Ajustes y calibraciones funcionales (Análisis Funcional y Calidad de Datos):
1. Calibración térmica de mínimas satelitales (-1.04 °C respecto a REM Estación 42 Villa Mercedes)
   para evaluar con precisión el umbral de heladas agrometeorológicas (<= 3.0 °C, buffer 4.5 °C).
2. Sonda local de humedad de perfil disponible ponderada por estrato radicular + regla de corte
   (fallback SMAP < 0.08 m³/m³ o percentil nulo sin sonda -> incertidumbre ±28% y validación con calicata).
3. Precipitación consensuada y consistencia zonal (REM 42 Villa Mercedes y Estación 49 Justo Daract /
   Cuenca del Morro, régimen de transición 650–750 mm).
"""

import json
import math
import pathlib
from typing import Any, Dict, List, Optional

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[2]
RUBRICA_PATH = REPOSITORY_ROOT / "data" / "rubrica_rotaciones.json"

UMBRAL_SEQUIA_SUPERFICIAL_SMAP = 0.08  # m³/m³ en los primeros 0-5 cm sin sonda in-situ

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


def _es_lectura_smap_nula_o_invalida(valor: Optional[float]) -> bool:
    """Detecta percentil nulo, NaN o lecturas no físicas en SMAP L4."""
    if valor is None:
        return True
    try:
        val_f = float(valor)
        return math.isnan(val_f) or math.isinf(val_f) or val_f <= 0.0
    except (TypeError, ValueError):
        return True


def calibrar_humedad_suelo(
    humedad_smap_superficial: Optional[float],
    lecturas_sonda_cm: Optional[Dict[str, float]] = None,
    profundidad_sonda_cm: Optional[float] = None,
    medicion_sonda_directa: Optional[float] = None,
    profundidad_efectiva_cm: float = 100.0,
    tolerancia_perdidas: str = "baja",
) -> Dict[str, Any]:
    """
    SMAP L4 mide humedad superficial (~0-5 cm, sm_surface). En suelos franco-arenosos o con rastrojo
    de San Luis, los primeros 5 cm pueden estar secos por evaporación mientras existe agua útil
    entre 30 y 60 cm.
    Si SMAP reporta < 0.08 m³/m³ o percentil nulo sin sonda, se activa regla de corte (fallback)
    con incertidumbre ±28% y recomendación de calicata antes de penalizar el lote.
    """
    smap_invalido = _es_lectura_smap_nula_o_invalida(humedad_smap_superficial)
    smap_val = 0.0 if smap_invalido else float(humedad_smap_superficial)

    # Caso 1: Sonda puntual con largo/profundidad configurado por el usuario
    if profundidad_sonda_cm is not None and medicion_sonda_directa is not None:
        p_cm = float(profundidad_sonda_cm)
        med = float(medicion_sonda_directa)

        if p_cm <= 15:
            peso_sonda, peso_smap = 0.65, 0.35
            estrato = "superficial (0–15 cm)"
            incertidumbre = 12
        elif p_cm <= 45:
            peso_sonda, peso_smap = 0.80, 0.20
            estrato = f"estrato radicular medio ({round(p_cm)} cm)"
            incertidumbre = 6
        elif p_cm <= 90:
            peso_sonda, peso_smap = 0.85, 0.15
            estrato = f"perfil subsuperficial ({round(p_cm)} cm)"
            incertidumbre = 5
        else:
            peso_sonda, peso_smap = 0.88, 0.12
            estrato = f"profundidad profunda ({round(p_cm)} cm)"
            incertidumbre = 5

        if smap_invalido:
            humedad_calibrada = med
            desvio_txt = "dato SMAP superficial nulo/no disponible (se prioriza lectura directa de sonda)"
        else:
            humedad_calibrada = (peso_sonda * med) + (peso_smap * smap_val)
            desvio = round((humedad_calibrada - smap_val) * 100, 1)
            desvio_txt = f"desvío respecto a satélite superficial: {desvio:+.1f}%"

        return {
            "humedad_efectiva": round(humedad_calibrada, 3),
            "fuente": f"Fusión Sonda {round(p_cm)} cm + Satélite SMAP",
            "incertidumbre_pct": incertidumbre,
            "profundidad_sonda_cm": round(p_cm, 1),
            "medicion_sonda_directa": round(med, 3),
            "estrato_radicular": estrato,
            "requiere_validacion_calicata": False,
            "alerta_sensor_superficial": None,
            "nota": f"Sonda local a {round(p_cm)} cm ({med:.2f} m³/m³, {estrato}); {desvio_txt}.",
        }

    # Caso 2: Perfil multi-nivel convencional (10, 30 y 60 cm)
    if lecturas_sonda_cm:
        perfil_real = (
            0.20 * lecturas_sonda_cm.get("10cm", 0.15)
            + 0.45 * lecturas_sonda_cm.get("30cm", 0.20)
            + 0.35 * lecturas_sonda_cm.get("60cm", 0.22)
        )
        humedad_calibrada = perfil_real if smap_invalido else (0.75 * perfil_real + 0.25 * smap_val)
        desvio_txt = (
            "SMAP superficial nulo"
            if smap_invalido
            else f"desvío corregido respecto a satélite superficial: {round((humedad_calibrada - smap_val) * 100, 1):+.1f}%"
        )

        return {
            "humedad_efectiva": round(humedad_calibrada, 3),
            "fuente": "Fusión Híbrida (NASA SMAP + Perfil 10/30/60 cm)",
            "incertidumbre_pct": 7,
            "profundidad_sonda_cm": 60.0,
            "medicion_sonda_directa": None,
            "estrato_radicular": "perfil radicular integrado (0–60 cm)",
            "requiere_validacion_calicata": False,
            "alerta_sensor_superficial": None,
            "nota": f"Perfil multi-profundidad calibrado; {desvio_txt}.",
        }

    # Caso 3: Solo satélite sin sonda in-situ -> Regla de corte (Fallback Rule)
    if smap_invalido or smap_val < UMBRAL_SEQUIA_SUPERFICIAL_SMAP:
        detalle_smap = (
            "percentil nulo / sin dato válido en SMAP"
            if smap_invalido
            else f"SMAP superficial muy bajo ({smap_val:.3f} m³/m³ < {UMBRAL_SEQUIA_SUPERFICIAL_SMAP} m³/m³)"
        )
        # Se retiene el valor medido (o piso referencial 0.08 si es nulo) pero bloqueando penalización crítica
        humedad_ref = UMBRAL_SEQUIA_SUPERFICIAL_SMAP if smap_invalido else round(smap_val, 3)
        alerta_calicata = (
            f"INCERTIDUMBRE ALTA (±28%) POR SENSOR SUPERFICIAL: Se detecta {detalle_smap} en los primeros 5 cm. "
            "En suelos franco-arenosos o bajo rastrojo de San Luis puede existir agua útil almacenada entre 30 y 60 cm. "
            "Validar perfil con calicata o barreno antes de descartar la siembra."
        )
        return {
            "humedad_efectiva": humedad_ref,
            "fuente": "Solo Satélite NASA SMAP (0-5 cm) [Fallback Sequía Superficial]",
            "incertidumbre_pct": 28,
            "profundidad_sonda_cm": None,
            "medicion_sonda_directa": None,
            "estrato_radicular": "superficial estricto (0–5 cm) — perfil profundo no observado",
            "requiere_validacion_calicata": True,
            "alerta_sensor_superficial": alerta_calicata,
            "nota": alerta_calicata,
        }

    return {
        "humedad_efectiva": round(smap_val, 3),
        "fuente": "Solo Satélite NASA SMAP (0-5 cm)",
        "incertidumbre_pct": 28,
        "profundidad_sonda_cm": None,
        "medicion_sonda_directa": None,
        "estrato_radicular": "superficial estricto (0–5 cm)",
        "requiere_validacion_calicata": False,
        "alerta_sensor_superficial": None,
        "nota": "Dato superficial satelital (0–5 cm). Se recomienda contrastar con sonda o calicata en el lote.",
    }


def calibrar_precipitacion_zonal(
    lluvias_mm: List[float],
    factor_clima: float = 1.0,
    zona: str = "villa_mercedes",
) -> Dict[str, Any]:
    """
    Calibra la precipitación anual combinando el dato satelital bruto (NASA POWER) y el valor
    corregido por sobreestimación regional (+20% en REM 42 Villa Mercedes y Estación 49 Justo Daract).
    Identifica si el lote pertenece a la franja de transición hacia el Este (650–750 mm, Justo Daract /
    Cuenca del Morro), donde aumenta la tolerancia al déficit hídrico para maíz tardío y sorgo.
    """
def calibrar_precipitacion_zonal(
    lluvias_mm: List[float],
    factor_clima: float = 1.0,
    zona: Optional[str] = None,
    origen_lluvia: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Calibra la precipitación anual combinando el dato satelital bruto (NASA POWER) y el valor
    corregido por sobreestimación regional (+20% en REM 42 Villa Mercedes y Estación 49 Justo Daract).
    Si el dato proviene de estación observada (OBSERVADO_PIHC) o carga manual (INGRESO_MANUAL),
    se usa directamente sin aplicar descuento satelital.
    Identifica si el lote pertenece a la franja de transición hacia el Este (650–750 mm, Justo Daract /
    Cuenca del Morro), donde aumenta la tolerancia al déficit hídrico para maíz tardío y sorgo.
    """
    lluvia_satelital_bruta = sum(lluvias_mm) if lluvias_mm else 665.0
    if origen_lluvia in ("OBSERVADO_PIHC", "INGRESO_MANUAL"):
        lluvia_calibrada_local = lluvia_satelital_bruta
        lluvia_media_consenso = lluvia_satelital_bruta
    else:
        lluvia_calibrada_local = lluvia_satelital_bruta / 1.20
        lluvia_media_consenso = (lluvia_satelital_bruta + lluvia_calibrada_local) / 2.0
    lluvia_proyectada = lluvia_media_consenso * factor_clima

    zona_norm = (zona or "villa_mercedes").lower().strip()
    es_transicion_este = (
        zona_norm in ("justo_daract", "cuenca_del_morro", "este_transicion", "estacion_49")
        or (650.0 <= lluvia_proyectada <= 780.0)
    )

    if es_transicion_este:
        estacion_ref = "Estación REM 49 (Justo Daract / Cuenca del Morro — régimen transición Este 650–750 mm)"
        # Mayor recarga estival en el Este permite tolerar umbrales ligeramente más bajos sin falla crítica
        umbral_deficit_maiz_sorgo_mm = 580.0
    else:
        estacion_ref = "Estación REM 42 (Villa Mercedes — semiárido central)"
        umbral_deficit_maiz_sorgo_mm = 620.0

    return {
        "lluvia_anual_proyectada_mm": round(lluvia_proyectada),
        "lluvia_satelital_bruta_mm": round(lluvia_satelital_bruta * factor_clima),
        "lluvia_calibrada_local_mm": round(lluvia_calibrada_local * factor_clima),
        "zona_agroecologica": "transicion_este_650_750" if es_transicion_este else "semiarido_central",
        "estacion_referencia": estacion_ref,
        "es_transicion_este": es_transicion_este,
        "umbral_deficit_maiz_sorgo_mm": umbral_deficit_maiz_sorgo_mm,
    }


def calibrar_minima_termica(tmin_satelital: float) -> Dict[str, Any]:
    """
    Calibración térmica de mínimas satelitales (NASA POWER T2M_MIN vs REM Estación 42 Villa Mercedes).
    El satélite sobreestima las mínimas en promedio +1.04 °C (10.30 °C vs 9.26 °C).
    Evalúa el umbral agrometeorológico crítico (<= 3.0 °C) y margen preventivo (<= 4.5 °C).
    """
    tmin_calibrada = round(tmin_satelital - 1.04, 2)
    riesgo_helada = tmin_calibrada <= 3.0
    buffer_seguridad = tmin_calibrada <= 4.5

    if riesgo_helada:
        alerta = (
            f"ALERTA DE HELADA AGRONÓMICA: Mínima calibrada {tmin_calibrada} °C "
            f"(satélite reportó {tmin_satelital} °C). Riesgo directo en floración o llenado de grano."
        )
    elif buffer_seguridad:
        alerta = (
            f"PRECAUCIÓN POR FRÍO: Mínima calibrada {tmin_calibrada} °C, cerca del umbral "
            "de daño por helada agrometeorológica (3.0 °C)."
        )
    else:
        alerta = f"Sin riesgo inminente de helada: mínima calibrada en {tmin_calibrada} °C."

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
    requiere_validacion_calicata: bool = False,
) -> Dict[str, Any]:
    """
    Evalúa el estado físico, hídrico y de conservación del suelo según los criterios
    técnicos para San Luis (retención, erosión eólica/hídrica, planchado y napa freática).
    """
    riesgos_suelo: List[str] = []
    if textura == "franco_arenoso":
        capacidad_retencion = "Baja a moderada (suelo liviano franco-arenoso)"
        riesgos_suelo.append(
            "Alta susceptibilidad a voladura (erosión eólica invernal) y baja capacidad de almacenaje por centímetro de perfil."
        )
    elif textura == "limoso":
        capacidad_retencion = "Moderada a alta (suelo franco-limoso)"
        riesgos_suelo.append(
            "Riesgo de planchado (encostramiento superficial) y escurrimiento tras lluvias intensas de verano."
        )
    else:
        capacidad_retencion = "Variable (requiere análisis granulométrico por estrato)"
        riesgos_suelo.append(
            "Sin textura confirmada: revisar profundidad efectiva y posibles pisos de arado o compactación."
        )

    if napa_pendiente == "napa_cercana":
        riesgos_suelo.append(
            "Napa freática cercana: riesgo de ascenso capilar, encharcamiento o salinización si no se mantiene consumo activo."
        )
    elif napa_pendiente == "pendiente_anegamiento":
        riesgos_suelo.append(
            "Lote con pendiente o bajos tendidos: requiere cobertura viva o rastrojo anclado para frenar cárcavas y escurrimiento."
        )

    if meses_desnudos >= 4 or estado_lote == "desnudo":
        riesgos_suelo.append(
            "Barbecho descubierto prolongado: dispara la evaporación directa y la pérdida de materia orgánica."
        )

    if requiere_validacion_calicata:
        estado_reserva = "Indeterminada en profundidad (superficie seca en SMAP; verificar agua útil con calicata a 30–60 cm)"
    elif regimen_agua == "secano" and humedad_efectiva < 0.14:
        estado_reserva = "Reserva hídrica inicial ajustada / baja"
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
    """Calcula el promedio normalizado (0-100) de cada una de las 5 dimensiones."""
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
    profundidad_efectiva_cm: float = 100.0,
    tolerancia_perdidas: str = "baja",
) -> Dict[str, Any]:
    """
    Simula y compara las 3 estrategias de rotación reales de la rúbrica para un lote de San Luis
    (Villa Mercedes y zona de transición Este / Justo Daract).
    """
    rubrica = cargar_rubrica()
    factores_clima = {"seco": 0.75, "normal": 1.0, "humedo": 1.20}
    factor_clima = factores_clima.get(escenario_lluvia, 1.0)

    # Calibración de precipitación consensuada y consistencia zonal (REM 42 y Estación 49)
    lluvias = datos_lote.get("lluvia_gpm_mm", [665 / 12] * 12)
    zona_lote = datos_lote.get("zona_agroecologica") or datos_lote.get("zona", "villa_mercedes")
    lluvia_info = calibrar_precipitacion_zonal(
        lluvias,
        factor_clima=factor_clima,
        zona=zona_lote,
        origen_lluvia=datos_lote.get("origen_lluvia"),
    )
    lluvia_proyectada = lluvia_info["lluvia_anual_proyectada_mm"]
    es_transicion_este = lluvia_info["es_transicion_este"]
    umbral_deficit_maiz_sorgo = lluvia_info["umbral_deficit_maiz_sorgo_mm"]

    ndvi_series = datos_lote.get("ndvi_sentinel2", [0.3] * 12)
    meses_desnudos = sum(1 for ndvi in ndvi_series if ndvi < 0.25)

    temps = datos_lote.get("temp_superficial_ecostress_c", [35.0])
    temp_max_verano = max(temps) if temps else 35.0
    tmin_satelital = datos_lote.get("temp_min_satelital_c", 3.8)
    if datos_lote.get("origen_temperatura") == "OBSERVADO_SMN":
        analisis_heladas = {
            "tmin_satelital_c": round(tmin_satelital, 2),
            "tmin_calibrada_c": round(tmin_satelital, 2),
            "riesgo_helada": tmin_satelital <= 3.0,
            "buffer_seguridad": tmin_satelital <= 4.5,
            "correccion_aplicada_c": 0.0,
            "alerta_termica": (
                f"Dato observado SMN ({tmin_satelital:.2f} °C): "
                + ("Riesgo de helada agrometeorológica (<= 3.0 °C)." if tmin_satelital <= 3.0 else "Sin riesgo inmediato de helada.")
            ),
        }
    else:
        analisis_heladas = calibrar_minima_termica(tmin_satelital)

    smap_series = datos_lote.get("humedad_suelo_smap", [0.18])
    smap_validos = [v for v in smap_series if not _es_lectura_smap_nula_o_invalida(v)]
    smap_media: Optional[float] = (sum(smap_validos) / len(smap_validos)) if smap_validos else None

    humedad_info = calibrar_humedad_suelo(
        smap_media,
        lecturas_sonda,
        profundidad_sonda_cm,
        medicion_sonda_directa,
    )
    humedad_efectiva = humedad_info["humedad_efectiva"]
    requiere_calicata = humedad_info["requiere_validacion_calicata"]

    suelo_eval = evaluar_suelo_lote(
        textura=textura,
        napa_pendiente=napa_pendiente,
        regimen_agua=regimen_agua,
        estado_lote=estado_lote,
        humedad_efectiva=humedad_efectiva,
        meses_desnudos=meses_desnudos,
        requiere_validacion_calicata=requiere_calicata,
    )

    pesos = dict(_PESOS_POR_PRIORIDAD.get(prioridad_usuario, _PESOS_POR_PRIORIDAD["suelo"]))
    if tiene_ganaderia or sistema_productivo == "mixto":
        pesos["produccion_sostenibilidad"] = round(pesos["produccion_sostenibilidad"] + 0.05, 2)
        pesos["negocio_mercado"] = max(0.05, round(pesos["negocio_mercado"] - 0.05, 2))

    _DEMANDA_CULTIVOS = [
        ("Trigo", 450, 650, "mm/ciclo"),
        ("Soja", 450, 700, "mm/ciclo"),
        ("Maíz", 500, 800, "mm/ciclo"),
        ("Sorgo", 450, 650, "mm/ciclo"),
        ("Girasol", 600, 1000, "mm/ciclo"),
        ("Alfalfa", 800, 1600, "mm/período de referencia"),
    ]
    _DEMANDA_POR_METODO = {
        "doble_golpe": "450–650 (Trigo) + 450–700 (Soja) mm/ciclo",
        "bomba_biologica": "800–1600 mm/período de referencia (Alfalfa / pastura)",
        "resiliencia_hidrica": "450–650 (Sorgo) / 500–800 (Maíz) / 450–700 (Soja) mm/ciclo",
    }
    demanda_cultivos_mm = []
    for cultivo, d_min, d_max, unidad in _DEMANDA_CULTIVOS:
        if lluvia_proyectada < d_min:
            estado_orientativo = "por_debajo_rango"
        elif lluvia_proyectada <= d_max:
            estado_orientativo = "en_rango"
        else:
            estado_orientativo = "por_encima_rango"
        demanda_cultivos_mm.append({
            "cultivo": cultivo,
            "min_mm": d_min,
            "max_mm": d_max,
            "unidad": unidad,
            "estado_orientativo": estado_orientativo,
        })

    diagnostico = {
        "lote": datos_lote.get("nombre", "Lote Piloto Villa Mercedes"),
        "zona_agroecologica": lluvia_info["zona_agroecologica"],
        "estacion_pluviometrica_ref": lluvia_info["estacion_referencia"],
        "suelo": suelo_eval["capacidad_retencion"],
        "evaluacion_suelo": suelo_eval,
        "profundidad_efectiva_cm": profundidad_efectiva_cm,
        "tolerancia_perdidas": tolerancia_perdidas,
        "lluvia_anual_proyectada_mm": lluvia_proyectada,
        "lluvia_satelital_bruta_mm": lluvia_info["lluvia_satelital_bruta_mm"],
        "lluvia_calibrada_local_mm": lluvia_info["lluvia_calibrada_local_mm"],
        "meses_suelo_desnudo": meses_desnudos,
        "pico_termico_ecostress_c": temp_max_verano,
        "analisis_heladas": analisis_heladas,
        "estado_hidrico": humedad_info,
        "pesos_aplicados": pesos,
        "balance_fao56": {
            "lluvia_proyectada_mm": round(lluvia_proyectada),
            "demanda_cultivos_mm": demanda_cultivos_mm,
            "advertencia_fao56": (
                "Comparación orientativa lluvia vs. ETc (FAO-56). Que la lluvia anual proyectada sea menor a la demanda "
                "del cultivo NO implica déficit automático: intervienen reserva hídrica inicial del suelo, precipitación efectiva, "
                "escorrentía, drenaje profundo y aporte de napa."
            ),
            "advertencia_smap": (
                "La humedad superficial regional SMAP (0–5 cm) es una señal de contexto macro y NO equivale al agua útil "
                "disponible en la zona radicular ni reemplaza mediciones parcelarias."
            ),
        },
        "dimensiones_faltantes": [
            "Historial agronómico de 3–5 años del lote (rotaciones previas, rindes y presión de malezas).",
            "Análisis de laboratorio de granulometría, materia orgánica y balance NPK (la fijación biológica de N no reemplaza la fertilización).",
            "Margen bruto local (USD/ha o ARS/ha) y evaluación financiera diferenciando OPEX anual de CAPEX plurianual.",
        ],
        "alerta_principal": (
            humedad_info["alerta_sensor_superficial"]
            if requiere_calicata and humedad_info["alerta_sensor_superficial"]
            else (
                suelo_eval["riesgos_suelo"][0]
                if suelo_eval["riesgos_suelo"]
                else "Suelo con balance hídrico y cobertura estables."
            )
        ),
    }

    resultados: List[Dict[str, Any]] = []

    for metodo in rubrica["metodos"]:
        m_id = metodo["id"]
        dims = _calcular_dimensiones_base(metodo)

        score_base = sum(dims[k]["score_100"] * pesos[k] for k in dims)

        ajuste = 0.0
        alertas_escenario: List[str] = []
        alertas_rojas: List[str] = []

        # Reglas contextuales por estrategia agronómica y condiciones reales del lote
        if m_id == "doble_golpe":
            if profundidad_sonda_cm and profundidad_sonda_cm <= 25 and humedad_efectiva < 0.16:
                ajuste -= 8.0
                alertas_escenario.append(
                    f"Sonda a {round(profundidad_sonda_cm)} cm marca cama de siembra seca ({humedad_efectiva} m³/m³): riesgo de nacimiento desparejo en siembra de segunda."
                )
            elif profundidad_sonda_cm and profundidad_sonda_cm >= 40 and humedad_efectiva >= 0.22 and regimen_agua != "riego":
                ajuste += 4.0
                alertas_escenario.append(
                    f"Sonda a {round(profundidad_sonda_cm)} cm confirma humedad subsuperficial ({humedad_efectiva} m³/m³), dando sostén al llenado de grano del maíz tardío o soja de 2ª."
                )

            if regimen_agua == "secano" and napa_pendiente != "napa_cercana":
                # Si SMAP < 0.08 o nulo sin sonda, no aplicamos penalización crítica (-22) hasta validar con calicata
                if requiere_calicata:
                    ajuste -= 8.0
                    alertas_escenario.append(
                        "VALIDACIÓN PENDIENTE (CALICATA): El satélite solo ve los primeros 5 cm secos (±28% incertidumbre). "
                        "Hacer pozo de observación a 30–60 cm antes de descartar la siembra de segunda."
                    )
                elif escenario_lluvia == "seco" or humedad_efectiva < 0.16 or lluvia_proyectada < umbral_deficit_maiz_sorgo:
                    if es_transicion_este and lluvia_proyectada >= 650 and escenario_lluvia != "seco" and humedad_efectiva >= 0.14:
                        # Tolerancia ampliada para maíz tardío en transición Este (Justo Daract 650-750 mm)
                        ajuste -= 10.0
                        alertas_escenario.append(
                            f"Régimen de transición Este ({lluvia_proyectada} mm, ref. Justo Daract): "
                            "permite plantear maíz tardío sobre trigo si se trilla temprano y se asegura recarga primaveral."
                        )
                    else:
                        ajuste -= 22.0
                        alertas_rojas.append(
                            "ALERTA ROJA HÍDRICA: En secano sin napa cercana, el trigo consume el agua útil invernal y deja el perfil seco para soja de 2ª o maíz tardío, con alto riesgo de merma."
                        )
                else:
                    ajuste -= 10.0
                    alertas_escenario.append(
                        "Planteo exigente en agua: requiere trilla temprana del trigo (fines de noviembre) y siembra directa inmediata sobre rastrojo para capturar lluvias estivales."
                    )

                alertas_rojas.append(
                    f"ALERTA DE HELADAS TEMPRANAS: Mínima calibrada {analisis_heladas['tmin_calibrada_c']} °C (-1.04 °C respecto a satélite). "
                    "Atrasar la siembra de maíz tardío o soja de 2ª más allá de mediados de diciembre expone el llenado a heladas tempranas de otoño."
                )
            elif regimen_agua == "riego":
                ajuste += 14.0
                alertas_escenario.append(
                    "Con riego complementario se cubre el déficit invernal del trigo y se asegura la implantación del cultivo de segunda."
                )
            elif napa_pendiente == "napa_cercana":
                ajuste += 6.0
                alertas_escenario.append(
                    "La napa cercana aporta humedad por capilaridad para el cultivo de segunda, aunque con menor consumo anual que una pastura perenne."
                )

        elif m_id == "bomba_biologica":
            if profundidad_sonda_cm and profundidad_sonda_cm >= 50 and humedad_efectiva >= 0.22:
                ajuste += 8.0
                alertas_escenario.append(
                    f"Sonda a {round(profundidad_sonda_cm)} cm confirma buena humedad en profundidad ({humedad_efectiva} m³/m³): condición óptima para implantar alfalfa en otoño."
                )
            elif profundidad_sonda_cm and profundidad_sonda_cm >= 50 and humedad_efectiva < 0.14:
                ajuste -= 6.0
                alertas_escenario.append(
                    f"Sonda a {round(profundidad_sonda_cm)} cm indica perfil profundo seco ({humedad_efectiva} m³/m³): esperar recarga otoñal antes de sembrar alfalfa."
                )

            if napa_pendiente in ("napa_cercana", "pendiente_anegamiento"):
                ajuste += 15.0
                alertas_escenario.append(
                    "Estrategia recomendada para Cuenca del Morro y bajos: la alfalfa actúa como bomba biológica, deprime la napa freática todo el año y frena la erosión hídrica."
                )
            elif escenario_lluvia == "seco" and regimen_agua == "secano" and napa_pendiente == "sin_napa":
                ajuste -= 8.0
                alertas_escenario.append(
                    "En secano sin napa y año seco, al salir de alfalfa conviene cortar/quemar con anticipación (fin de invierno) para recargar el perfil antes del maíz tardío."
                )

            if sistema_productivo == "contratista" and metodo["requiere_maquinaria_especial"]:
                ajuste -= 6.0
                alertas_escenario.append(
                    "Exige coordinación con contratista forrajero (corte, hilerado y confección de rollos/megafardos) o aprovechamiento ganadero directo."
                )

        elif m_id == "resiliencia_hidrica":
            if profundidad_sonda_cm and profundidad_sonda_cm >= 30 and humedad_efectiva < 0.18:
                ajuste += 6.0
                alertas_escenario.append(
                    f"Sonda a {round(profundidad_sonda_cm)} cm muestra humedad justa ({humedad_efectiva} m³/m³): la rusticidad radicular de sorgo granífero o girasol estabiliza el piso de rinde."
                )

            if regimen_agua == "secano" and (
                escenario_lluvia == "seco"
                or humedad_efectiva < 0.18
                or textura == "franco_arenoso"
                or requiere_calicata
            ):
                ajuste += 10.0
                alertas_escenario.append(
                    "Alta seguridad en suelos franco-arenosos y años secos: el centeno + vicia ancla el suelo contra la voladura invernal. "
                    "Secar la vicia antes de octubre para no comprometer el agua de siembra del sorgo o girasol."
                )

            if es_transicion_este and lluvia_proyectada >= 650:
                ajuste += 4.0
                alertas_escenario.append(
                    f"En franja de transición Este ({lluvia_proyectada} mm, ref. Justo Daract), el aporte de nitrógeno de la vicia + recarga primaveral potencia el techo de rinde en sorgo o maíz tardío."
                )

            if napa_pendiente == "napa_cercana":
                ajuste -= 6.0
                alertas_escenario.append(
                    "Con napa freática en ascenso, un cultivo anual consume menos excedente hídrico que una alfalfa perenne."
                )
            if estado_lote == "desnudo":
                ajuste += 4.0
                alertas_escenario.append(
                    "La consociación centeno + vicia villosa cubre rápido el lote descubierto, frena la evaporación y aporta nitrógeno biológico."
                )

        # Modificador por profundidad efectiva del suelo (TAW)
        if profundidad_efectiva_cm < 80:
            if m_id == "doble_golpe" and regimen_agua == "secano":
                ajuste -= 10.0
                alertas_escenario.append(
                    f"Suelo superficial ({round(profundidad_efectiva_cm)} cm < 80 cm): reduce el agua útil total (TAW) y eleva el riesgo hídrico en doble cultivo en secano."
                )
            elif m_id == "bomba_biologica" and napa_pendiente == "sin_napa":
                ajuste -= 8.0
                alertas_escenario.append(
                    f"Suelo superficial ({round(profundidad_efectiva_cm)} cm < 80 cm) sin napa freática: limita la exploración radicular profunda de pasturas perennes."
                )
            elif m_id == "resiliencia_hidrica":
                ajuste += 4.0
                alertas_escenario.append(
                    f"Suelo superficial ({round(profundidad_efectiva_cm)} cm): conviene priorizar cultivos rústicos (ej. sorgo) y cobertura permanente."
                )

        # Modificador por tolerancia a pérdidas / riesgo financiero
        if tolerancia_perdidas == "baja":
            if m_id == "doble_golpe":
                ajuste -= 8.0
                alertas_escenario.append(
                    "Tolerancia baja a pérdidas: el doble cultivo anual duplica la exposición de capital operativo (OPEX) en la campaña."
                )
            elif m_id == "resiliencia_hidrica":
                ajuste += 6.0
            elif m_id == "bomba_biologica":
                ajuste -= 3.0
                alertas_escenario.append(
                    "Tolerancia baja a pérdidas: requiere evaluar la inmovilización inicial de capital (CAPEX) de implantación de pastura."
                )
        elif tolerancia_perdidas == "alta" and m_id == "doble_golpe":
            ajuste += 4.0

        # Modificador por horizonte temporal elegido por el productor
        if horizonte == metodo["horizonte"]:
            ajuste += 5.0
        elif horizonte == "corto" and metodo["horizonte"] == "largo":
            ajuste -= 8.0
            alertas_escenario.append("Requiere compromiso plurianual (4–5 años), superior al horizonte de corto plazo seleccionado.")

        # Modificador por ganadería
        if tiene_ganaderia and metodo["apta_ganaderia"]:
            ajuste += 5.0

        score_final = max(0.0, min(100.0, round(score_base + ajuste, 1)))

        evidencia_txt = "; ".join(f"{f['institucion']}: {f['titulo']}" for f in metodo["fuentes"])
        riesgo_txt = " | ".join(alertas_rojas) if alertas_rojas else metodo["cuando_rotar"]
        lagunas_txt = (
            "Realizar calicata de 30–60 cm para confirmar humedad útil subsuperficial, textura por horizonte y profundidad de napa."
            if requiere_calicata
            else "Validar análisis de suelo (textura y materia orgánica), profundidad de napa y ventana real de siembra con un asesor agronómico local."
        )

        resultados.append({
            "id": m_id,
            "nombre": metodo["nombre"],
            "secuencia": metodo["secuencia"],
            "horizonte_label": metodo["horizonte_label"],
            "demanda_hidrica_mm": _DEMANDA_POR_METODO.get(m_id, "450–800 mm/ciclo (orientativo)"),
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
