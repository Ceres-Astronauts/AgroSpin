import json
import os
import pathlib
import sys
import uuid

import pandas as pd
import streamlit as st
import yaml

# Canonical repository paths
REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from src.decision.rotation_engine import simulate_scenarios

CATALOG_YAML = REPOSITORY_ROOT / "docs" / "challenge" / "crop-catalog.yml"
FIELDS_DEFAULT = REPOSITORY_ROOT / "data" / "pilot_fields.json"
POWER_DEFAULT = REPOSITORY_ROOT / "data" / "power_daily_point_19910101_20251231.json"
CROPS_CSV = REPOSITORY_ROOT / "data" / "san_luis_crop_evaluation.csv"

st.set_page_config(
    page_title="Field Shift — Ceres Agronauts",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Main header
st.title("Field Shift — Ceres Agronauts")
st.caption("Crop rotation decision-support system | Pilot zone: Villa Mercedes (San Luis)")


@st.cache_data
def load_precip_local() -> tuple[pd.DataFrame | None, int, str]:
    """Load daily NASA POWER time series from the local repository dataset."""
    target_path = pathlib.Path(os.environ.get("FIELD_SHIFT_POWER_JSON", str(POWER_DEFAULT)))
    if not target_path.is_file():
        return None, 0, f"Not found: {target_path.name}"

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
        return clean_frame, discarded, f"Local dataset ({target_path.name})"
    except Exception as exc:
        return None, 0, f"Error: {exc}"


# Load calibration/pilot fields
fields_data = []
if FIELDS_DEFAULT.is_file():
    try:
        with open(FIELDS_DEFAULT, "r", encoding="utf-8") as f:
            fields_data = json.load(f).get("fields", [])
    except Exception as e:
        st.error(f"Error loading pilot fields: {e}")

# Interactive sidebar
st.sidebar.header("Producer Parameters")

field_names = {f["name"]: f for f in fields_data}
if field_names:
    selected_field = field_names[st.sidebar.selectbox("Select pilot zone", list(field_names.keys()))]
else:
    selected_field = {
        "id": "vm_central",
        "name": "Villa Mercedes - Rio Quinto Basin (San Luis)",
        "soil": "Sandy-loam",
        "slope_srtm_pct": 1.8,
        "gpm_rainfall_mm": [105, 92, 85, 45, 18, 8, 10, 14, 28, 62, 88, 110],
        "smap_soil_moisture": [0.22, 0.20, 0.24, 0.19, 0.15, 0.12, 0.10, 0.09, 0.11, 0.16, 0.19, 0.21],
        "ecostress_surface_temp_c": [36.5, 35.2, 30.1, 23.4, 17.8, 13.5, 13.2, 16.9, 21.5, 26.8, 31.4, 35.0],
        "sentinel2_ndvi": [0.74, 0.78, 0.65, 0.38, 0.21, 0.16, 0.15, 0.14, 0.17, 0.28, 0.52, 0.69],
    }

priority = st.sidebar.radio(
    "Agronomic priority",
    ["soil", "water", "profit"],
    format_func=lambda x: {
        "soil": "Restore soil and prevent erosion",
        "water": "Maximize water efficiency",
        "profit": "Prioritize immediate financial return",
    }[x],
)

rainfall_scenario = st.sidebar.select_slider(
    "Projected climate scenario",
    options=["dry", "normal", "wet"],
    value="normal",
    help="Dry (-25% rainfall), Normal (historical mean ~665 mm), Wet (+20% rainfall)",
)

has_livestock = st.sidebar.checkbox("Integrate livestock (forage / grazing use)")

# Mechatronics telemetry module
st.sidebar.markdown("---")
st.sidebar.subheader("Mechatronics Module")
use_probe = st.sidebar.checkbox("Ground node calibration (ESP32 + Soil Probes)")
probe_readings = None
if use_probe:
    st.sidebar.caption("Multi-depth capacitive probe readings (m³/m³):")
    probe_readings = {
        "10cm": st.sidebar.slider("10 cm probe (surface roots)", 0.05, 0.40, 0.14, step=0.01),
        "30cm": st.sidebar.slider("30 cm probe (mid horizon)", 0.05, 0.40, 0.22, step=0.01),
        "60cm": st.sidebar.slider("60 cm probe (subsurface reserve)", 0.05, 0.40, 0.25, step=0.01),
    }

# Main tabs
tab_sim, tab_env, tab_cat, tab_intake = st.tabs([
    "Rotation Simulator",
    "Environmental Context (NASA / INTA)",
    "Catalog & Agronomic Matrix",
    "Field Intake Request",
])

# ----------------- TAB 1: ROTATION SIMULATOR -----------------
with tab_sim:
    res = simulate_scenarios(selected_field, priority, has_livestock, rainfall_scenario, probe_readings)
    diag = res["field_diagnosis"]

    st.subheader(f"Field Diagnosis: {diag['field']}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Projected Annual Rainfall", f"{diag['projected_annual_rainfall_mm']} mm")
    c2.metric("Bare Soil Months (NDVI < 0.25)", f"{diag['bare_soil_months']} mo")
    c3.metric("Summer Thermal Peak (ECOSTRESS)", f"{diag['ecostress_thermal_peak_c']} °C")

    eff_moisture = diag["moisture_status"]["effective_moisture"]
    uncertainty = diag["moisture_status"]["uncertainty_pct"]
    c4.metric("Effective Profile Moisture", f"{eff_moisture} m³/m³", f"±{uncertainty}% uncertainty")

    st.info(f"**Moisture source:** {diag['moisture_status']['source']} | {diag['moisture_status']['note']}")
    st.warning(f"**Agroecological alert:** {diag['primary_alert']}")

    st.markdown("---")
    st.subheader("Rotation Strategy Comparison")
    cols = st.columns(3)
    for idx, rot in enumerate(res["rotation_comparison"]):
        with cols[idx]:
            st.markdown(f"### #{idx+1} — {rot['name']}")
            st.metric("Suitability Score", f"{rot['suitability_score']} / 100")
            st.markdown(f"**Technical evidence:** {rot['evidence']}")
            st.info(f"**Information gaps:** {rot['info_gaps']}")
            st.error(f"**Validation & risks:** {rot['human_risk']}")
            for alert in rot["scenario_alerts"]:
                st.warning(alert)

# ----------------- TAB 2: ENVIRONMENTAL CONTEXT -----------------
with tab_env:
    st.subheader("Historical Time Series & Satellite Observations")
    st.caption("Reference station: EEA INTA San Luis / Villa Mercedes (-33.6500, -65.3667)")

    frame_power, discarded_fill, power_source = load_precip_local()

    if frame_power is not None and not frame_power.empty:
        st.success(f"Data origin: **{power_source}** (offline local archive)")
        st.caption(
            f"Bias-corrected precipitation (PRECTOTCORR) 1991-2025. Valid records: {len(frame_power):,} days. "
            f"Discarded fill values (-999.0): {discarded_fill}."
        )

        monthly = (
            frame_power.set_index("date")["precip_mm"]
            .resample("MS")
            .sum()
            .rename("Cumulative precipitation (mm/month)")
        )
        st.line_chart(monthly)

        col_m1, col_m2 = st.columns(2)
        col_m1.metric("Total recorded days", f"{len(frame_power):,}")
        col_m2.metric("Historical annual average", f"{round(frame_power['precip_mm'].sum() / (len(frame_power)/365.25))} mm/yr")
    else:
        st.warning(f"Could not load weather time series: {power_source}")

# ----------------- TAB 3: CATALOG & AGRONOMIC MATRIX -----------------
with tab_cat:
    st.subheader("Crop Catalog & Crop Coefficients (Kc)")
    columns = ["Crop", "Kc mid", "Kc end", "Zr (m)", "Planting window", "Status"]
    if CATALOG_YAML.is_file():
        try:
            catalog = yaml.safe_load(CATALOG_YAML.read_text(encoding="utf-8"))
            rows = []
            for crop in catalog.get("crops", []):
                params = crop.get("parameters", {})
                kc = params.get("crop_coefficients_kc") or {}
                rooting = params.get("rooting_depth") or {}
                rows.append({
                    "Crop": crop.get("common_name", ""),
                    "Kc mid": kc.get("kc_mid", "UNVERIFIED") if isinstance(kc, dict) else "UNVERIFIED",
                    "Kc end": kc.get("kc_end", "UNVERIFIED") if isinstance(kc, dict) else "UNVERIFIED",
                    "Zr (m)": rooting.get("zr_m", "UNVERIFIED") if isinstance(rooting, dict) else "UNVERIFIED",
                    "Planting window": (
                        "Verified (maize & sorghum)"
                        if crop.get("crop_id") in ("CROP-MAIZ", "CROP-SORGO")
                        else "Under review"
                    ),
                    "Status": crop.get("status", "draft"),
                })
            st.dataframe(pd.DataFrame(rows, columns=columns), use_container_width=True)
        except Exception as e:
            st.error(f"Error parsing YAML catalog: {e}")

    if CROPS_CSV.is_file():
        st.markdown("---")
        st.subheader("Multicriteria Crop Evaluation in San Luis")
        st.caption("Team expert matrix for Villa Mercedes and Cuenca del Morro (Temperature, Water, Frost, Residue)")
        try:
            df_eval = pd.read_csv(CROPS_CSV)
            st.dataframe(df_eval.dropna(how="all"), use_container_width=True)
        except Exception as e:
            st.warning(f"Could not load evaluation matrix: {e}")

# ----------------- TAB 4: FIELD INTAKE -----------------
with tab_intake:
    st.subheader("Producer Field Registration")
    st.caption("Structured field survey intake for on-site scouting without autonomous prescriptions.")
    with st.form("intake_form"):
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            ha = st.number_input("Field area (hectares)", min_value=1.0, value=150.0, step=5.0)
            coords = st.text_input("Geographic coordinates", value="-33.6500, -65.3667")
            water_regime = st.selectbox("Water regime", ["Strict rainfed", "Supplemental irrigation", "Mixed"])
        with col_f2:
            prev_crop = st.selectbox("Current crop / immediate predecessor", ["Full-season soybean", "Late maize", "Sunflower", "Fallow"])
            rot_history = st.text_area("History of last 3 seasons", value="2023/24: Soybean | 2024/25: Maize | 2025/26: Fallow")

        btn_intake = st.form_submit_button("Save Field for Simulation")

    if btn_intake:
        request_id = str(uuid.uuid4())[:8]
        st.success(f"Field #{request_id} saved for evaluation with the rotation engine.")
