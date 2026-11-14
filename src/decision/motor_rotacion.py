"""
Motor de simulación y evaluación de rotaciones de cultivos para Field Shift.
Adaptado para la zona piloto Villa Mercedes (San Luis) y Corredor Río Cuarto - Villa Mercedes.
Integra calibración satelital (NASA SMAP / POWER / ECOSTRESS) con telemetría terrestre (ESP32).
"""

from typing import Any, Dict, List, Optional

ESTRATEGIAS_ROTACION: Dict[str, Dict[str, Any]] = {
    "base_tradicional": {
        "nombre": "Secuencia Corta Actual (Soja / Maíz con barbecho invernal)",
        "consumo_agua_mm": 550,
        "dias_cobertura": 165,
        "balance_nitrogeno_kg": -45,
        "proteccion_erosion": 3,   # Escala 1 a 10
        "corte_plagas": 2,         # Escala 1 a 10
        "apta_ganaderia": False,
        "rentabilidad_base": 8,    # Escala 1 a 10
        "evidencia": "Mantiene el esquema operativo habitual con baja inversión inicial.",
        "lagunas_info": "No contempla compactación subsuperficial ('piso de arado') ni niveles de fósforo.",
        "riesgo_humano": "Alta exposición a erosión eólica entre mayo y octubre y pérdida sostenida de materia orgánica."
    },
    "cobertura_fijacion": {
        "nombre": "Cultivo de Servicio (Centeno + Vicia villosa) + Maíz",
        "consumo_agua_mm": 640,
        "dias_cobertura": 310,
        "balance_nitrogeno_kg": 55,
        "proteccion_erosion": 9,
        "corte_plagas": 8,
        "apta_ganaderia": True,
        "rentabilidad_base": 6,
        "evidencia": "El centeno ancla suelos franco-arenosos contra el viento y la vicia aporta nitrógeno biológico.",
        "lagunas_info": "Requiere conocer la humedad acumulada en profundidad (1-2 m) antes de sembrar el servicio.",
        "riesgo_humano": "RIESGO HÍDRICO: Si primavera viene seca, el centeno debe secarse temprano para no quitarle agua al maíz."
    },
    "resiliencia_hidrica": {
        "nombre": "Diversificación Rústica (Sorgo Granífero / Girasol)",
        "consumo_agua_mm": 440,
        "dias_cobertura": 210,
        "balance_nitrogeno_kg": -20,
        "proteccion_erosion": 7,
        "corte_plagas": 7,
        "apta_ganaderia": True,
        "rentabilidad_base": 7,
        "evidencia": "Sistema radicular profundo (hasta 1.8 m) con alta eficiencia de uso del agua ante olas de calor.",
        "lagunas_info": "Depende de la profundidad de la napa freática local y de canales comerciales cercanos.",
        "riesgo_humano": "Menor margen bruto en años muy húmedos frente a soja/maíz; requiere validar logística de cosecha."
    }
}


def calibrar_humedad_suelo(
    humedad_smap_superficial: float,
    lecturas_sonda_cm: Optional[Dict[str, float]] = None
) -> Dict[str, Any]:
    """
    SMAP L4 mide humedad superficial (~0-5 cm, sm_surface) con alta incertidumbre en suelos arenosos.
    Si se dispone de nodo terrestre (ESP32 con sensores capacitivos a 10, 30 y 60 cm),
    se pondera el perfil radicular efectivo y se reduce la incertidumbre.
    """
    if not lecturas_sonda_cm:
        return {
            "humedad_efectiva": round(humedad_smap_superficial, 3),
            "fuente": "Solo Satélite NASA SMAP (0-5 cm)",
            "incertidumbre_pct": 28,
            "nota": "Dato superficial satelital. Se recomienda contrastar con perfil profundo o sonda en lote."
        }
    
    # Ponderación zona radicular efectiva: 20% a 10cm, 45% a 30cm, 35% a 60cm
    perfil_real = (
        0.20 * lecturas_sonda_cm.get("10cm", 0.15) +
        0.45 * lecturas_sonda_cm.get("30cm", 0.20) +
        0.35 * lecturas_sonda_cm.get("60cm", 0.22)
    )
    # Fusión híbrida: 75% telemetría in-situ + 25% tendencia satelital SMAP
    humedad_calibrada = 0.75 * perfil_real + 0.25 * humedad_smap_superficial
    desvio = round((humedad_calibrada - humedad_smap_superficial) * 100, 1)
    
    return {
        "humedad_efectiva": round(humedad_calibrada, 3),
        "fuente": "Fusión Híbrida (NASA SMAP + Nodo Terrestre ESP32)",
        "incertidumbre_pct": 7,
        "nota": f"Desvío corregido respecto a satélite: {desvio}%"
    }


def simular_escenarios(
    datos_lote: Dict[str, Any],
    prioridad_usuario: str,
    tiene_ganaderia: bool,
    escenario_lluvia: str = "normal",
    lecturas_sonda: Optional[Dict[str, float]] = None
) -> Dict[str, Any]:
    """
    Simula y compara las estrategias de rotación para un lote dado.
    
    :param datos_lote: Diccionario con series o agregados (lluvia_gpm_mm, humedad_suelo_smap, etc.)
    :param prioridad_usuario: 'suelo' | 'agua' | 'renta'
    :param tiene_ganaderia: bool
    :param escenario_lluvia: 'seco' (-25% lluvia) | 'normal' | 'humedo' (+20% lluvia)
    :param lecturas_sonda: dict con lecturas '10cm', '30cm', '60cm' (m³/m³)
    """
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

    diagnostico = {
        "lote": datos_lote.get("nombre", "Lote Piloto"),
        "suelo": datos_lote.get("suelo", "Franco-arenoso"),
        "lluvia_anual_proyectada_mm": round(lluvia_proyectada),
        "meses_suelo_desnudo": meses_desnudos,
        "pico_termico_ecostress_c": temp_max_verano,
        "estado_hidrico": humedad_info,
        "alerta_principal": (
            "Riesgo alto de erosión eólica invernal (suelo descubierto prolongado)"
            if meses_desnudos >= 4 else "Cobertura vegetal invernal adecuada"
        )
    }

    resultados: List[Dict[str, Any]] = []
    for key, est in ESTRATEGIAS_ROTACION.items():
        score = 50.0
        alertas_dinamicas: List[str] = []

        # 1. Balance hídrico
        deficit_mm = est["consumo_agua_mm"] - lluvia_proyectada
        if deficit_mm > 0:
            score -= (deficit_mm * 0.12)
            alertas_dinamicas.append(
                f"Déficit hídrico proyectado de {round(deficit_mm)} mm bajo escenario {escenario_lluvia}."
            )
        else:
            score += 10

        # 2. Penalización por año seco en cultivo de servicio
        if key == "cobertura_fijacion" and escenario_lluvia == "seco":
            score -= 15
            alertas_dinamicas.append(
                "CRÍTICO: En año seco adelantar secado de centeno/vicia para preservar agua útil para el maíz."
            )

        # 3. Respuesta a la humedad calibrada de perfil
        hum_perfil = humedad_info["humedad_efectiva"]
        if hum_perfil < 0.14:
            if key == "cobertura_fijacion":
                score -= 12
                alertas_dinamicas.append(
                    f"Perfil seco ({hum_perfil} m³/m³): baja recarga inicial para sostener cultivo de servicio."
                )
            elif key == "resiliencia_hidrica":
                score += 10
                alertas_dinamicas.append(
                    f"Perfil seco ({hum_perfil} m³/m³): ventaja competitiva para raíces profundas (Sorgo/Girasol)."
                )
        elif hum_perfil > 0.24:
            if key == "cobertura_fijacion":
                score += 8
                alertas_dinamicas.append(
                    f"Buena recarga profunda ({hum_perfil} m³/m³): viabiliza implantación de cobertura sin comprometer cosecha gruesa."
                )

        # 4. Ponderación por prioridad del productor
        if prioridad_usuario == "suelo":
            score += (est["proteccion_erosion"] * 2.5) + (est["balance_nitrogeno_kg"] * 0.15)
        elif prioridad_usuario == "agua":
            score += ((700 - est["consumo_agua_mm"]) * 0.08) + est["proteccion_erosion"]
        elif prioridad_usuario == "renta":
            score += est["rentabilidad_base"] * 3.0

        # 5. Integración ganadera (doble propósito)
        if tiene_ganaderia and est["apta_ganaderia"]:
            score += 8
            alertas_dinamicas.append("Aptitud forrajera: admite pastoreo directo o silo para planteo mixto.")

        score_final = max(0.0, min(100.0, round(score, 1)))

        resultados.append({
            "id": key,
            "nombre": est["nombre"],
            "puntaje_idoneidad": score_final,
            "evidencia": est["evidencia"],
            "lagunas_info": est["lagunas_info"],
            "riesgo_humano": est["riesgo_humano"],
            "alertas_escenario": alertas_dinamicas
        })

    resultados.sort(key=lambda x: x["puntaje_idoneidad"], reverse=True)
    return {
        "diagnostico_lote": diagnostico,
        "comparativa_rotaciones": resultados
    }
