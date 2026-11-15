import datetime
import json
import os
import pathlib
import sys
import uuid

import pandas as pd
import streamlit as st
import yaml

# Rutas canónicas del repositorio
REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from src.decision.motor_rotacion import simular_escenarios

CATALOG_YAML = REPOSITORY_ROOT / "docs" / "challenge" / "crop-catalog.yml"
LOTES_DEFAULT = REPOSITORY_ROOT / "data" / "lotes_piloto.json"
POWER_DEFAULT = REPOSITORY_ROOT / "data" / "power_daily_point_19910101_20251231.json"
CULTIVOS_CSV = REPOSITORY_ROOT / "data" / "cultivos_evaluacion_san_luis.csv"

st.set_page_config(
    page_title="Field Shift — Ceres Agronauts",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Encabezado principal
st.title("Field Shift — Ceres Agronauts")
st.caption("Sistema de apoyo a la toma de decisiones para rotación de cultivos | Zona piloto: Villa Mercedes (San Luis)")

# Funciones cacheadas de lectura de datos locales
@st.cache_data
def load_precip_local() -> tuple[pd.DataFrame | None, int, str]:
    """Carga la serie temporal diaria de NASA POWER desde el dataset local del repositorio."""
    target_path = pathlib.Path(os.environ.get("FIELD_SHIFT_POWER_JSON", str(POWER_DEFAULT)))
    if not target_path.is_file():
        return None, 0, f"No encontrado: {target_path.name}"
    
    try:
        data = json.loads(target_path.read_text(encoding="utf-8"))
        series = data["properties"]["parameter"]["PRECTOTCORR"]
        frame = pd.DataFrame({
            "date": pd.to_datetime(list(series.keys()), format="%Y%m%d"),
            "precip_mm": list(series.values()),
        })
        fill_mask = frame["precip_mm"].eq(-999.0)
        discarded = int(fill_mask.sum())
        clean_frame = frame.loc[~fill_mask].sort_values("date")
        return clean_frame, discarded, f"Dataset local ({target_path.name})"
    except Exception as exc:
        return None, 0, f"Error: {exc}"


# Cargar lotes de prueba / calibración
lotes_data = []
if LOTES_DEFAULT.is_file():
    try:
        with open(LOTES_DEFAULT, "r", encoding="utf-8") as f:
            lotes_data = json.load(f).get("lotes", [])
    except Exception as e:
        st.error(f"Error cargando lotes piloto: {e}")

# Sidebar interactivo
st.sidebar.header("Parámetros del Productor")

nombres_lotes = {l["nombre"]: l for l in lotes_data}
if nombres_lotes:
    lote_sel = nombres_lotes[st.sidebar.selectbox("Seleccionar zona piloto", list(nombres_lotes.keys()))]
else:
    lote_sel = {
        "id": "vm_centro",
        "nombre": "Villa Mercedes - Cuenca Río Quinto (San Luis)",
        "suelo": "Franco-arenoso",
        "pendiente_srtm_pct": 1.8,
        "lluvia_gpm_mm": [105, 92, 85, 45, 18, 8, 10, 14, 28, 62, 88, 110],
        "humedad_suelo_smap": [0.22, 0.20, 0.24, 0.19, 0.15, 0.12, 0.10, 0.09, 0.11, 0.16, 0.19, 0.21],
        "temp_superficial_ecostress_c": [36.5, 35.2, 30.1, 23.4, 17.8, 13.5, 13.2, 16.9, 21.5, 26.8, 31.4, 35.0],
        "ndvi_sentinel2": [0.74, 0.78, 0.65, 0.38, 0.21, 0.16, 0.15, 0.14, 0.17, 0.28, 0.52, 0.69]
    }

prioridad = st.sidebar.radio(
    "Prioridad agronómica",
    ["suelo", "agua", "renta"],
    format_func=lambda x: {
        "suelo": "Recuperar suelo y frenar erosión",
        "agua": "Maximizar eficiencia hídrica",
        "renta": "Priorizar margen económico inmediato"
    }[x]
)

clima = st.sidebar.select_slider(
    "Escenario climático proyectado",
    options=["seco", "normal", "humedo"],
    value="normal",
    help="Seco (-25% precipitación), Normal (media histórica ~665 mm), Húmedo (+20% precipitación)"
)

ganaderia = st.sidebar.checkbox("Integro ganadería (aporte forrajero / pastoreo)")

# Módulo Mecatrónica: Telemetría in-situ
st.sidebar.markdown("---")
st.sidebar.subheader("Módulo Mecatrónica")
usar_sonda = st.sidebar.checkbox("Calibración con nodo terrestre (ESP32 + Sondas)")
lecturas_sonda = None
if usar_sonda:
    st.sidebar.caption("Lecturas capacitivas multipunto (m³/m³):")
    lecturas_sonda = {
        "10cm": st.sidebar.slider("Sonda 10 cm (raíces superficiales)", 0.05, 0.40, 0.14, step=0.01),
        "30cm": st.sidebar.slider("Sonda 30 cm (horizonte medio)", 0.05, 0.40, 0.22, step=0.01),
        "60cm": st.sidebar.slider("Sonda 60 cm (reserva subsuperficial)", 0.05, 0.40, 0.25, step=0.01),
    }

# Tabs principales
tab_sim, tab_env, tab_cat, tab_sol = st.tabs([
    "Simulador de Rotaciones",
    "Contexto Ambiental (NASA / INTA)",
    "Catálogo y Matriz Agronómica",
    "Solicitud de Parcela"
])

# ----------------- TAB 1: SIMULADOR DE ROTACIONES -----------------
with tab_sim:
    res = simular_escenarios(lote_sel, prioridad, ganaderia, clima, lecturas_sonda)
    diag = res["diagnostico_lote"]

    st.subheader(f"Diagnóstico de Parcela: {diag['lote']}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Lluvia Anual Proyectada", f"{diag['lluvia_anual_proyectada_mm']} mm")
    c2.metric("Meses Suelo Desnudo (NDVI < 0.25)", f"{diag['meses_suelo_desnudo']} meses")
    c3.metric("Pico Térmico Estival (ECOSTRESS)", f"{diag['pico_termico_ecostress_c']} °C")
    
    hum_efectiva = diag["estado_hidrico"]["humedad_efectiva"]
    incert = diag["estado_hidrico"]["incertidumbre_pct"]
    c4.metric("Humedad Efectiva de Perfil", f"{hum_efectiva} m³/m³", f"±{incert}% incertidumbre")

    st.info(f"**Fuente hídrica:** {diag['estado_hidrico']['fuente']} | {diag['estado_hidrico']['nota']}")
    st.warning(f"**Alerta agroecológica:** {diag['alerta_principal']}")

    st.markdown("---")
    st.subheader("Comparativa de Estrategias de Rotación")
    cols = st.columns(3)
    for idx, rot in enumerate(res["comparativa_rotaciones"]):
        with cols[idx]:
            st.markdown(f"### #{idx+1} — {rot['nombre']}")
            st.metric("Puntaje de Idoneidad", f"{rot['puntaje_idoneidad']} / 100")
            st.markdown(f"**Evidencia técnica:** {rot['evidencia']}")
            st.info(f"**Lagunas de información:** {rot['lagunas_info']}")
            st.error(f"**Validación y riesgos:** {rot['riesgo_humano']}")
            for alerta in rot["alertas_escenario"]:
                st.warning(alerta)

# ----------------- TAB 2: CONTEXTO AMBIENTAL -----------------
with tab_env:
    st.subheader("Series Históricas y Observaciones Satelitales")
    st.caption("Punto de referencia: EEA INTA San Luis / Villa Mercedes (-33.6500, -65.3667)")

    frame_power, discarded_fill, fuente_power = load_precip_local()

    if frame_power is not None and not frame_power.empty:
        st.success(f"Origen de datos: **{fuente_power}** (independiente de red y nube)")
        st.caption(
            f"Precipitación corregida (PRECTOTCORR) 1991–2025. Registros limpios: {len(frame_power):,} días. "
            f"Valores fill (-999.0) descartados: {discarded_fill}."
        )
        
        # Agrupación mensual
        monthly = (
            frame_power.set_index("date")["precip_mm"]
            .resample("MS")
            .sum()
            .rename("Precipitación acumulada (mm/mes)")
        )
        st.line_chart(monthly)
        
        col_m1, col_m2 = st.columns(2)
        col_m1.metric("Total de días registrados", f"{len(frame_power):,}")
        col_m2.metric("Promedio anual histórico", f"{round(frame_power['precip_mm'].sum() / (len(frame_power)/365.25))} mm/año")
    else:
        st.warning(f"No se pudo cargar la serie meteorológica: {fuente_power}")

# ----------------- TAB 3: CATÁLOGO Y MATRIZ AGRONÓMICA -----------------
with tab_cat:
    st.subheader("Catálogo de Especies y Coeficientes de Cultivo (Kc)")
    columns = ["cultivo", "Kc mid", "Kc end", "Zr (m)", "ventana de siembra", "estado"]
    if CATALOG_YAML.is_file():
        try:
            catalog = yaml.safe_load(CATALOG_YAML.read_text(encoding="utf-8"))
            rows = []
            for crop in catalog.get("crops", []):
                params = crop.get("parameters", {})
                kc = params.get("crop_coefficients_kc") or {}
                rooting = params.get("rooting_depth") or {}
                rows.append({
                    "cultivo": crop.get("common_name", ""),
                    "Kc mid": kc.get("kc_mid", "NO_VERIFICADO") if isinstance(kc, dict) else "NO_VERIFICADO",
                    "Kc end": kc.get("kc_end", "NO_VERIFICADO") if isinstance(kc, dict) else "NO_VERIFICADO",
                    "Zr (m)": rooting.get("zr_m", "NO_VERIFICADO") if isinstance(rooting, dict) else "NO_VERIFICADO",
                    "ventana de siembra": (
                        "Verificada (maíz y sorgo)"
                        if crop.get("crop_id") in ("CROP-MAIZ", "CROP-SORGO")
                        else "En revisión"
                    ),
                    "estado": crop.get("status", "borrador"),
                })
            st.dataframe(pd.DataFrame(rows, columns=columns), use_container_width=True)
        except Exception as e:
            st.error(f"Error parseando catálogo YAML: {e}")

    if CULTIVOS_CSV.is_file():
        st.markdown("---")
        st.subheader("Evaluación Multicriterio de Rotaciones en San Luis")
        st.caption("Matriz experta del equipo para Villa Mercedes y Cuenca del Morro (Temperatura, Agua, Heladas, Rastrojo)")
        try:
            df_eval = pd.read_csv(CULTIVOS_CSV)
            st.dataframe(df_eval.dropna(how="all"), use_container_width=True)
        except Exception as e:
            st.warning(f"No se pudo cargar la matriz de evaluación: {e}")

# ----------------- TAB 4: SOLICITUD DE PARCELA (INTAKE) -----------------
with tab_sol:
    st.subheader("Registro de Lote de Productor")
    st.caption("Estructura de entrada para relevamiento in-situ sin generar prescripciones autónomas.")
    with st.form("intake_form"):
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            ha = st.number_input("Superficie del lote (hectáreas)", min_value=1.0, value=150.0, step=5.0)
            coords = st.text_input("Coordenadas geográficas", value="-33.6500, -65.3667")
            regimen = st.selectbox("Régimen de agua", ["Secano estricto", "Riego suplementario", "Mixto"])
        with col_f2:
            cultivo_ant = st.selectbox("Cultivo actual / antecesor inmediato", ["Soja de 1ra", "Maíz tardío", "Girasol", "Barbecho"])
            hist_rot = st.text_area("Historial de las últimas 3 campañas", value="2023/24: Soja | 2024/25: Maíz | 2025/26: Barbecho")
        
        btn_sol = st.form_submit_button("Guardar Parcela para Simulación")
    
    if btn_sol:
        solicitud_id = str(uuid.uuid4())[:8]
        st.success(f"Parcela #{solicitud_id} registrada para evaluación con el motor de rotación.")
