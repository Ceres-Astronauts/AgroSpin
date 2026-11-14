"""
Motor de simulacion y evaluacion de rotaciones de cultivos para Field Shift.
Adaptado para la zona piloto Villa Mercedes (San Luis) y Corredor Rio Cuarto - Villa Mercedes.
Integra calibracion satelital (NASA SMAP / POWER / ECOSTRESS) con telemetria terrestre (sonda de suelo 10, 30 y 60 cm).

Reglas funcionales consolidadas (Angie Mendez - Analisis Funcional y Calidad de Datos):
- Calibracion termica de minimas satelitales (-1.04 C) para deteccion de heladas agrometeorologicas.
- Sonda local de humedad de perfil disponible (10, 30 y 60 cm): fusion ponderada con satelite SMAP.
- Precipitacion: sin pluviometro en lote, se toma el promedio entre el dato bruto de NASA POWER y el valor
  calibrado local (promedio ponderado conservador / compromiso intermedio), informando el desvio sin saturar la UI.
"""

from typing import Any, Dict, List, Optional

ESTRATEGIAS_ROTACION: Dict[str, Dict[str, Any]] = {
    "base_tradicional": {
        "nombre": "Secuencia Corta Actual (Soja / Maiz con barbecho invernal)",
        "consumo_agua_mm": 550,
        "dias_cobertura": 165,
        "balance_nitrogeno_kg": -45,
        "proteccion_erosion": 3,   # Escala 1 a 10
        "corte_plagas": 2,         # Escala 1 a 10
        "apta_ganaderia": False,
        "rentabilidad_base": 8,    # Escala 1 a 10
        "sensibilidad_helada": "alta",  # Soja de 2da o maiz tardio expuesto a heladas de otono
        "evidencia": "Mantiene el esquema operativo habitual con baja inversion inicial.",
        "lagunas_info": "No contempla compactacion subsuperficial ('piso de arado') ni niveles de fosforo.",
        "riesgo_humano": "Alta exposicion a erosion eolica entre mayo y octubre y perdida sostenida de materia organica."
    },
    "cobertura_fijacion": {
        "nombre": "Cultivo de Servicio (Centeno + Vicia villosa) + Maiz",
        "consumo_agua_mm": 640,
        "dias_cobertura": 310,
        "balance_nitrogeno_kg": 55,
        "proteccion_erosion": 9,
        "corte_plagas": 8,
        "apta_ganaderia": True,
        "rentabilidad_base": 6,
        "sensibilidad_helada": "baja",   # Especies rusticas invernales tolerantes
        "evidencia": "El centeno ancla suelos franco-arenosos contra el viento y la vicia aporta nitrogeno biologico.",
        "lagunas_info": "Requiere conocer la humedad acumulada en profundidad (1-2 m) antes de sembrar el servicio.",
        "riesgo_humano": "RIESGO HIDRICO: Si primavera viene seca, el centeno debe secarse temprano para no quitarle agua al maiz."
    },
    "resiliencia_hidrica": {
        "nombre": "Diversificacion Rustica (Sorgo Granifero / Girasol)",
        "consumo_agua_mm": 440,
        "dias_cobertura": 210,
        "balance_nitrogeno_kg": -20,
        "proteccion_erosion": 7,
        "corte_plagas": 7,
        "apta_ganaderia": True,
        "rentabilidad_base": 7,
        "sensibilidad_helada": "media",
        "evidencia": "Sistema radicular profundo (hasta 1.8 m) con alta eficiencia de uso del agua ante olas de calor.",
        "lagunas_info": "Depende de la profundidad de la napa freatica local y de canales comerciales cercanos.",
        "riesgo_humano": "Menor margen bruto en anos muy humedos frente a soja/maiz; requiere validar logistica de cosecha."
    }
}


def calibrar_humedad_suelo(
    humedad_smap_superficial: float,
    lecturas_sonda_cm: Optional[Dict[str, float]] = None
) -> Dict[str, Any]:
    """
    SMAP L4 mide humedad superficial (~0-5 cm, sm_surface) con alta incertidumbre en suelos arenosos.
    El agricultor cuenta con sonda en lote a 10, 30 y 60 cm.
    Se pondera el perfil radicular efectivo (20% a 10cm, 45% a 30cm, 35% a 60cm)
    y se fusiona con la tendencia satelital (75% sonda local + 25% SMAP).
    """
    if not lecturas_sonda_cm:
        return {
            "humedad_efectiva": round(humedad_smap_superficial, 3),
            "fuente": "Solo Satelite NASA SMAP (0-5 cm)",
            "incertidumbre_pct": 28,
            "nota": "Dato superficial satelital. Se recomienda ingresar lecturas de sonda de suelo (10, 30 y 60 cm)."
        }
    
    perfil_real = (
        0.20 * lecturas_sonda_cm.get("10cm", 0.15) +
        0.45 * lecturas_sonda_cm.get("30cm", 0.20) +
        0.35 * lecturas_sonda_cm.get("60cm", 0.22)
    )
    humedad_calibrada = 0.75 * perfil_real + 0.25 * humedad_smap_superficial
    desvio = round((humedad_calibrada - humedad_smap_superficial) * 100, 1)
    
    return {
        "humedad_efectiva": round(humedad_calibrada, 3),
        "fuente": "Sonda de Perfil (10-30-60 cm) + NASA SMAP",
        "incertidumbre_pct": 7,
        "nota": f"Perfil calibrado con medicion in-situ (desvio satelite: {desvio}%)"
    }


def evaluar_riesgo_termico_heladas(
    temp_min_satelital: float,
    origen_dato: str = "satelital_nasa_power"
) -> Dict[str, Any]:
    """
    Ajusta la temperatura minima satelital considerando el sesgo detectado en la validacion E2
    frente a la estacion terrestre REM 42 de Villa Mercedes (+1.04 C de subregistro de heladas en satelite).
    Aplica margen precautorio de 1.5 C para alertas agrometeorologicas (< 3 C en abrigo = riesgo helada en suelo).
    """
    if origen_dato == "satelital_nasa_power":
        temp_min_estimada_suelo = round(temp_min_satelital - 1.04, 1)
        margen_seguridad = 1.5
    else:
        temp_min_estimada_suelo = round(temp_min_satelital, 1)
        margen_seguridad = 0.0

    riesgo_helada = temp_min_estimada_suelo <= (3.0 + margen_seguridad)
    helada_severa = temp_min_estimada_suelo <= 0.0

    alerta_termica = None
    if helada_severa:
        alerta_termica = f"ALERTA CRITICA DE HELADA: Minima estimada en lote {temp_min_estimada_suelo} C (Satelite corrigio sesgo de +1.04 C)."
    elif riesgo_helada:
        alerta_termica = f"PRECAUCION HELADA AGRONOMICA: Minima satelite ({temp_min_satelital} C) corregida a {temp_min_estimada_suelo} C en superficie. Riesgo en floracion/llenado."

    return {
        "temp_min_satelital_c": temp_min_satelital,
        "temp_min_estimada_lote_c": temp_min_estimada_suelo,
        "riesgo_helada": riesgo_helada,
        "helada_severa": helada_severa,
        "alerta_termica": alerta_termica
    }


def simular_escenarios(
    datos_lote: Dict[str, Any],
    prioridad_usuario: str,
    tiene_ganaderia: bool,
    escenario_lluvia: str = "normal",
    lecturas_sonda: Optional[Dict[str, float]] = None
) -> Dict[str, Any]:
    """
    Simula y compara las estrategias de rotacion para un lote dado.
    
    Precipitacion: al no disponer de pluviometro en lote, el motor calcula la media
    entre el valor bruto de NASA POWER y el valor calibrado local (reduccion del 20%
    por sobreestimacion sistematica observada en Villa Mercedes).
    """
    factores_clima = {"seco": 0.75, "normal": 1.0, "humedo": 1.20}
    factor_clima = factores_clima.get(escenario_lluvia, 1.0)
    
    lluvias_raw = datos_lote.get("lluvia_gpm_mm", [665 / 12] * 12)
    lluvia_satelital_bruta = sum(lluvias_raw)
    
    # Calculo de la media de precipitacion (NASA POWER bruto vs Calibrado local -20%)
    lluvia_calibrada_local = lluvia_satelital_bruta * (1.0 / 1.20)
    lluvia_media_consenso = (lluvia_satelital_bruta + lluvia_calibrada_local) / 2.0
    
    # Proyeccion segun escenario climatico (seco, normal o humedo)
    lluvia_proyectada = lluvia_media_consenso * factor_clima
    
    ndvi_series = datos_lote.get("ndvi_sentinel2", [0.3] * 12)
    meses_desnudos = sum(1 for ndvi in ndvi_series if ndvi < 0.25)
    
    temps = datos_lote.get("temp_superficial_ecostress_c", [35.0])
    temp_max_verano = max(temps)
    
    temp_min_sat = datos_lote.get("temp_min_invierno_c", 4.2)
    analisis_heladas = evaluar_riesgo_termico_heladas(temp_min_sat)
    
    smap_series = datos_lote.get("humedad_suelo_smap", [0.18])
    smap_media = sum(smap_series) / len(smap_series) if smap_series else 0.18
    
    humedad_info = calibrar_humedad_suelo(smap_media, lecturas_sonda)

    diagnostico = {
        "lote": datos_lote.get("nombre", "Lote Piloto"),
        "suelo": datos_lote.get("suelo", "Franco-arenoso"),
        "lluvia_anual_proyectada_mm": round(lluvia_proyectada),
        "lluvia_satelital_bruta_mm": round(lluvia_satelital_bruta * factor_clima),
        "lluvia_calibrada_minima_mm": round(lluvia_calibrada_local * factor_clima),
        "meses_suelo_desnudo": meses_desnudos,
        "pico_termico_ecostress_c": temp_max_verano,
        "analisis_heladas": analisis_heladas,
        "estado_hidrico": humedad_info,
        "alerta_principal": (
            "Riesgo alto de erosion eolica invernal (suelo descubierto prolongado)"
            if meses_desnudos >= 4 else "Cobertura vegetal invernal adecuada"
        )
    }

    resultados: List[Dict[str, Any]] = []
    for key, est in ESTRATEGIAS_ROTACION.items():
        score = 50.0
        alertas_dinamicas: List[str] = []

        # 1. Balance hidrico basado en la media consensuada
        deficit_mm = est["consumo_agua_mm"] - lluvia_proyectada
        if deficit_mm > 0:
            score -= (deficit_mm * 0.12)
            alertas_dinamicas.append(
                f"Deficit hidrico proyectado de {round(deficit_mm)} mm bajo escenario {escenario_lluvia}."
            )
        else:
            score += 10

        # 2. Penalizacion por ano seco en cultivo de servicio
        if key == "cobertura_fijacion" and escenario_lluvia == "seco":
            score -= 15
            alertas_dinamicas.append(
                "CRITICO: En ano seco adelantar secado de centeno/vicia para preservar agua util para el maiz."
            )

        # 3. Respuesta a la humedad calibrada de perfil de sonda
        hum_perfil = humedad_info["humedad_efectiva"]
        if hum_perfil < 0.14:
            if key == "cobertura_fijacion":
                score -= 12
                alertas_dinamicas.append(
                    f"Perfil seco ({hum_perfil} m3/m3): baja recarga inicial para sostener cultivo de servicio."
                )
            elif key == "resiliencia_hidrica":
                score += 10
                alertas_dinamicas.append(
                    f"Perfil seco ({hum_perfil} m3/m3): ventaja competitiva para raices profundas (Sorgo/Girasol)."
                )
        elif hum_perfil > 0.24:
            if key == "cobertura_fijacion":
                score += 8
                alertas_dinamicas.append(
                    f"Buena recarga profunda ({hum_perfil} m3/m3): viabiliza implantacion de cobertura sin comprometer cosecha gruesa."
                )

        # 4. Impacto de heladas calibradas segun sensibilidad del cultivo
        if analisis_heladas["riesgo_helada"] and est.get("sensibilidad_helada") == "alta":
            score -= 10
            alertas_dinamicas.append(
                f"RIESGO TERMICO: Sensibilidad alta a heladas otonales/tardias. {analisis_heladas['alerta_termica']}"
            )

        # 5. Ponderacion por prioridad del productor
        if prioridad_usuario == "suelo":
            score += (est["proteccion_erosion"] * 2.5) + (est["balance_nitrogeno_kg"] * 0.15)
        elif prioridad_usuario == "agua":
            score += ((700 - est["consumo_agua_mm"]) * 0.08) + est["proteccion_erosion"]
        elif prioridad_usuario == "renta":
            score += est["rentabilidad_base"] * 3.0

        # 6. Integracion ganadera (doble proposito)
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
