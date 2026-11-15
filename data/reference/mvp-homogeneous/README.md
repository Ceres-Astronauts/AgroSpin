# Field Shift — MVP Delivery: Historical Climate + Soil (Homogeneous Data)

Geographic bounding box: lon −65.875 to −64.125 · lat −33.875 to −33.125 (Villa Mercedes, San Luis – southern Cordoba).
Data cutoff: 2026-11-01. CRS: EPSG:4326 (lat/lon). Delivery date: 2026-11-15.

All datasets here are derived from validated, curated records. Every row carries an `origin` column indicating whether the value is
**OBSERVED** (ground-measured), **ESTIMATED** (reanalysis or model), or **REFERENCE** (outside the bounding box or third-party).
Categories are never mixed: an ESTIMATED value is never labeled as OBSERVED.

## Folder Contents

| File | Rows | Purpose | Looker Studio |
|---|---|---|---|
| `climate_monthly_grid_1991_2026.csv` | 13,792 | Rainfall, temperature, ETo, water balance, frosts, heat stress, and ENSO by month and grid point (32 points at 0.25°) | **Primary** |
| `climate_annual_grid_1991_2026.csv` | 1,152 | Annual summary per point: frost-free window, Oct–Mar rain, ETo, degree-days | Yes |
| `climate_zone_daily_1991_2026.csv` | 13,089 | Single daily series for the full bounding box (station-weighted temperature + grid-mean rain and ETo) | Yes |
| `climate_daily_grid_1991_2026.csv` / `.parquet` | 418,848 | Full daily series per grid point with FAO-56 ETo, frost, heat stress, and GDD | CSV 58 MB: upload via Google Sheets/BigQuery, or filter by point |
| `enso_oni_monthly.csv` | 429 | NOAA ONI index and El Nino/La Nina/Neutral phase per month | Yes |
| `soil_moisture_monthly_grid_1991_2026.csv` | 13,792 | Monthly mean soil moisture level from water-balance model — **UNVALIDATED in daily correlation** | Yes, with warning |
| `soil_500m_grid.csv` | 54,600 | Relief, slope, topographic susceptibility, and mean modeled moisture aggregated to ~500 m | **Primary (map)** |
| `soil_1ha_grid.parquet` | 1,352,847 | Same layers at 1 ha (100 m) resolution. For the Python stack, not Looker | No (Parquet; for stack) |
| `soil_gaez_crops_1981_2010.csv` | 5,280 | FAO GAEZ v4 suitability and attainable yield by crop (maize, soybean, sunflower, sorghum, wheat, peanut, alfalfa, barley), 1/12° cells | Yes |
| `soil_sisinta_profiles_box.csv` | 257 | INTA SISINTA soil profile horizons inside the box: texture, pH, organic carbon, available water | Yes |
| `ground_stations.csv` | 19 | Ground weather station catalog (REM, SMN, PIHC, IDECOR, Meteostat) with coordinates and validation verdicts | Yes (map) |
| `column_dictionary.csv` | — | Column definitions, units, and sources | Reference |
| `mvp_requirements_coverage.csv` | — | Mapping from Excel requirements to table/column coverage and partial/out-of-scope gaps | Reference |
| `manifest.json`, `SHA256SUMS` | — | Provenance tracking and integrity check (`sha256sum -c SHA256SUMS`) | — |

Join keys: `point_id` (climate, soil moisture), `year_month` (monthly climate ↔ ENSO), `lat`/`lon` (all coordinates EPSG:4326).

## How to Use in Google Looker Studio

1. **Create data source** → **File Upload** connector (CSV). Upload `climate_monthly_grid_1991_2026.csv`, `soil_500m_grid.csv`, `ground_stations.csv`, and `enso_oni_monthly.csv` first. The CSV upload connector has an approximate 100 MB per-file limit, so the full daily grid is also provided in Parquet or can be loaded via Google Sheets/BigQuery / filtered by `point_id`.
2. **Field types** (Looker sometimes misinfers these):
   - `lat` → *Geo → Latitude*, `lon` → *Geo → Longitude*. Use both for bubble maps; use `soil_500m_grid` for density/heat maps.
   - `year_month` → *Date → Year Month* (`YYYY-MM`). `date` → *Date*.
   - `origin`, `enso_phase`, `completeness_status`, `*_label` → *Text* (use as filters and legends).
3. **Blend data**: monthly climate ↔ ENSO via `year_month`; monthly climate ↔ monthly soil moisture via `point_id` + `year_month`; climate ↔ soil via nearest `lat`/`lon` (climate is 0.25° vs. 500 m soil; nearest-point spatial join is handled in the Python stack, not Looker).
4. **Suggested charts**:
   - Temperature patterns: monthly `tmean_c` series + seasonal `gdd_base10` total.
   - Heat stress: monthly `heat_stress_days` (filter `month` Nov–Feb).
   - Precipitation: monthly `precip_mm` and seasonal `precip_oct_mar_mm`, colored by `enso_phase`.
   - Frost risk: `first_autumn_frost`, `last_spring_frost`, `frost_free_days_season` (annual table).
   - Evapotranspiration: `eto_mm` and `p_eto_balance_mm` (negative = water deficit).
   - Soil: map `mean_slope_pct`, `mean_topographic_susceptibility` (legend: **unvalidated index, NOT a flood map**), and `mean_moisture_level_m3_m3` (legend: **unvalidated in daily correlation**).
5. **Always show the `origin` label** in charts: it distinguishes measured observations from modeled estimates.

## How to Use in the Python Stack (Pandas · Parquet · FastAPI · Leaflet)

```python
import pandas as pd

BASE = "data/reference/mvp-homogeneous"

climate_d = pd.read_parquet(f"{BASE}/climate_daily_grid_1991_2026.parquet")
climate_m = pd.read_parquet(f"{BASE}/climate_monthly_grid_1991_2026.parquet")
soil      = pd.read_parquet(f"{BASE}/soil_1ha_grid.parquet")
gaez      = pd.read_csv(f"{BASE}/soil_gaez_crops_1981_2010.csv")
moist_m   = pd.read_csv(f"{BASE}/soil_moisture_monthly_grid_1991_2026.csv")

def nearest_power_point(lat, lon):
    pts = climate_m[["point_id", "lat", "lon"]].drop_duplicates()
    idx = ((pts.lat - lat) ** 2 + (pts.lon - lon) ** 2).idxmin()
    return pts.loc[idx, "point_id"]

def field_climate(lat, lon, since="2015-01-01"):
    pid = nearest_power_point(lat, lon)
    sub = climate_d[(climate_d.point_id == pid) & (climate_d.date >= since)]
    return sub.to_dict("records")
```

- **FastAPI**: load Parquet/CSV datasets once at startup/first query and serve by `point_id` or `lat`/`lon`; always preserve `origin` metadata in responses.
- **Leaflet**: `ground_stations.csv` and `soil_500m_grid.csv` map directly as WGS84 GeoJSON points. For drawn polygons in Leaflet.draw, average the 1 ha cells in `soil_1ha_grid.parquet` inside the polygon.
- Every record must carry its `origin`/`label`; never mix `ESTIMATED_*` and `OBSERVED_*` values in an unlabeled average.

## Methods and Limitations (Read Before Interpreting)

- **Point climate** = NASA POWER (MERRA-2 reanalysis, 0.25°), labeled `ESTIMATED_POWER`. Ground station temperatures (REM San Luis) appear in `climate_zone_daily_1991_2026.csv` weighted by proximity and variance (`r ≈ 0.97` daily temperature correlation against POWER).
- **ETo** = Daily FAO-56 Penman-Monteith computed from POWER temperature, RH, wind, solar radiation, and pressure with SRTM elevation. 32 days (one final day per grid point) lack ETo due to upstream source gaps.
- **Frost**: Agrometeorological frost threshold `tmin < 3 °C` (plus `tmin ≤ 0 °C`) evaluated on 2 m POWER grid temperature; individual fields may experience lower minimum temperatures.
- **ENSO**: NOAA ONI rolling 3-month trimestral index centered on each month (`EL_NINO` / `LA_NINA` at ±0.5 °C). The last two months of the cutoff window do not yet have ONI values.
- **Soil moisture**: Water-balance model calibrated against 3 SMAP L4 points. RMSE and bias pass validation, whereas daily correlation does **not** (`0.48–0.50` vs. `0.60` target). Consequently, only monthly mean levels are published, tagged `UNVALIDATED_CORRELATION`. 32-point SMAP and GLDAS were excluded from the MVP.
- **Relief**: SRTMGL1 30 m aggregated to 1 ha and ~500 m. 85 cells with `slope_pct > 100%` are flagged `atypical_slope` (likely DEM artifacts) rather than removed.
- **Topographic susceptibility**: 0–1 index (TWI + depressions) on 4x-smoothed relief. **NOT a flood map** and not validated against historical flooding events.
- **GAEZ v4**: Attainable yield and suitability classes (1981–2010, rainfed, high inputs) at 1/12° resolution. No local codebook is included: suitability classes follow raw GAEZ v4 coding (`1 = best ... 8 = worst`); attainable yields are in kg/ha per FAO GAEZ documentation.
- **SISINTA**: 257 horizons across 198 soil profiles within the bounding box. Only 9 horizons have full particle-size texture plus field capacity/PWP lab measurements; remaining horizons are labeled `INCOMPLETE_DATA`.
- **Cordoba coverage**: Fewer ground observations than San Luis; sparse rainfall in Achiras (28 months with data) and missing ground temperature at Bell Ville are key spatial constraints.

Public provenance resources: [`manifest.json`](manifest.json), [`SHA256SUMS`](SHA256SUMS), [`../../sources/`](../../sources/), and [`../../../docs/contracts/`](../../../docs/contracts/). Historical decision IDs in the manifest are not themselves scientific validation.
