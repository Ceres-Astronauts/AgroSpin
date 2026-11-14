import datetime
import json
import os
import pathlib
import uuid

import pandas as pd
import streamlit as st
import yaml

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[1]
CATALOG = REPOSITORY_ROOT / "docs" / "challenge" / "crop-catalog.yml"

st.set_page_config(page_title="Field Shift", layout="wide")
st.title("Field Shift")
st.warning("E2 NO CERRADO: falta comparación independiente. No hay ranking ni recomendación.")


@st.cache_data
def load_precip(power_json: str) -> tuple[pd.DataFrame | None, int]:
    try:
        data = json.loads(pathlib.Path(power_json).read_text(encoding="utf-8"))
        series = data["properties"]["parameter"]["PRECTOTCORR"]
        if not isinstance(series, dict):
            raise TypeError
        frame = pd.DataFrame(
            {
                "date": pd.to_datetime(list(series.keys()), format="%Y%m%d"),
                "precip_mm": list(series.values()),
            }
        )
    except (KeyError, TypeError, ValueError):
        st.warning("No se pudo leer el JSON de POWER: formato inválido.")
        return None, 0

    fill_values = frame["precip_mm"].eq(-999.0)
    discarded = int(fill_values.sum())
    return frame.loc[~fill_values].sort_values("date"), discarded


@st.cache_data
def load_catalog() -> pd.DataFrame:
    columns = ["cultivo", "Kc mid", "Kc end", "Zr (m)", "ventana de siembra", "estado"]
    if not CATALOG.is_file():
        expected_path = CATALOG.relative_to(REPOSITORY_ROOT).as_posix()
        st.warning(f"No se encontró el catálogo de cultivos: {expected_path}.")
        return pd.DataFrame(columns=columns)

    try:
        catalog = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
        rows = []
        for crop in catalog["crops"]:
            parameters = crop["parameters"]
            kc = parameters.get("crop_coefficients_kc") or {}
            rooting_depth = parameters.get("rooting_depth") or {}
            rows.append(
                {
                    "cultivo": crop["common_name"],
                    "Kc mid": kc.get("kc_mid", "NO_VERIFICADO")
                    if isinstance(kc, dict)
                    else "NO_VERIFICADO",
                    "Kc end": kc.get("kc_end", "NO_VERIFICADO")
                    if isinstance(kc, dict)
                    else "NO_VERIFICADO",
                    "Zr (m)": rooting_depth.get("zr_m", "NO_VERIFICADO")
                    if isinstance(rooting_depth, dict)
                    else "NO_VERIFICADO",
                    "ventana de siembra": (
                        "verificada (solo maíz y sorgo)"
                        if crop["crop_id"] in ("CROP-MAIZ", "CROP-SORGO")
                        else "NO_VERIFICADO"
                    ),
                    "estado": crop["status"],
                }
            )
        return pd.DataFrame(rows, columns=columns)
    except (yaml.YAMLError, KeyError, TypeError):
        st.warning("No se pudo leer el catálogo: YAML inválido o estructura inesperada.")
        return pd.DataFrame(columns=columns)


tab1, tab2, tab3, tab4 = st.tabs(
    ["Contexto ambiental", "Catálogo de cultivos", "Rotaciones", "Mi campo"]
)

with tab1:
    power_json = os.environ.get("FIELD_SHIFT_POWER_JSON", "").strip()
    if not power_json:
        st.warning(
            "No se configuró FIELD_SHIFT_POWER_JSON. Define esa variable con la ruta al JSON de NASA POWER para ver el contexto ambiental."
        )
    elif not pathlib.Path(power_json).is_file():
        st.warning("El archivo indicado por FIELD_SHIFT_POWER_JSON no existe o no es un archivo.")
    else:
        frame, discarded = load_precip(power_json)
        if frame is not None:
            st.caption(f"Valores fill -999.0 descartados: {discarded}")
            if frame.empty:
                st.warning("No hay observaciones utilizables para graficar.")
            else:
                st.caption(
                    f"POWER PRECTOTCORR, punto -33.65 / -65.367, "
                    f"{frame.date.min():%Y-%m-%d} a {frame.date.max():%Y-%m-%d}, "
                    f"{len(frame)} días. Escala regional, no de parcela."
                )
                monthly = (
                    frame.set_index("date")["precip_mm"]
                    .resample("MS")
                    .sum()
                    .rename("mm por mes")
                )
                st.line_chart(monthly)
                st.metric("días con datos", len(frame))

with tab2:
    st.dataframe(load_catalog())

with tab3:
    st.info(
        "Constructor de rotaciones: pendiente. Sin balance hídrico (falta perfil de suelo) "
        "y sin ranking (E2 abierto)."
    )

with tab4:
    st.write(
        "Describí tu situación. Esto arma la solicitud estructurada; no genera una recomendación."
    )
    with st.form("intake"):
        hectareas = st.number_input("Superficie (ha)", min_value=0.0, value=100.0, step=1.0)
        ubicacion = st.text_input("Ubicación (lat, lon)", value="-33.65, -65.3667")
        riego = st.selectbox("Régimen hídrico", ["Secano", "Riego", "Mixto"])
        cultivo_actual = st.selectbox(
            "Cultivo actual",
            [
                "(ninguno)",
                "Maíz",
                "Soja",
                "Girasol",
                "Sorgo granífero",
                "Trigo",
                "Maní",
                "Alfalfa",
                "Cebada",
            ],
        )
        historial = st.text_area(
            "Historial de cultivos últimos 3 años",
            placeholder="ej. soja, maíz, trigo",
        )
        objetivos = st.multiselect(
            "Prioridades",
            [
                "Reducir riesgo de sequía",
                "Conservar agua",
                "Cuidar suelo",
                "Productividad",
                "Diversificar",
            ],
        )
        restricciones = st.text_area("Restricciones (maquinaria, mercado, operativas)")
        enviado = st.form_submit_button("Armar solicitud")

    if enviado:
        faltantes = []
        if not historial.strip():
            faltantes.append("historial de cultivos")
        if not objetivos:
            faltantes.append("prioridades")
        if riego == "Riego":
            faltantes.append("datos de agua de riego")

        solicitud = {
            "superficie_ha": hectareas,
            "ubicacion": ubicacion,
            "regimen_hidrico": riego,
            "cultivo_actual": cultivo_actual,
            "historial": historial,
            "prioridades": objetivos,
            "restricciones": restricciones,
        }
        registro = {
            "schema": "intake_v1",
            "id": str(uuid.uuid4()),
            "created_utc": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
            "solicitud": solicitud,
            "faltantes": faltantes,
        }
        intake_dir = pathlib.Path(os.environ.get("FIELD_SHIFT_INTAKE_DIR", "./intakes"))
        if not intake_dir.is_absolute():
            intake_dir = REPOSITORY_ROOT / intake_dir
        intake_dir.mkdir(parents=True, exist_ok=True)
        intake_path = intake_dir / f"{registro['id']}.json"
        intake_path.write_text(
            json.dumps(registro, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        st.success(f"Solicitud guardada: {intake_path.name}")
        st.subheader("Solicitud estructurada")
        st.json(solicitud)
        st.subheader("Qué falta antes de evaluar")
        st.write(faltantes or ["Nada obligatorio para el intake."])
        st.subheader("Estado de la evaluación")
        st.error(
            "Bloqueado: E2 no cerrado y suelo local pendiente. No hay ranking ni recomendación."
        )
        st.info(
            "Evidencia disponible para el ancla: POWER (precipitación, 1991–2025) y SMAP "
            "sm_surface/sm_rootzone (E1 pasado, E2 abierto). Escala regional, no de parcela."
        )
