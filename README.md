# Field Shift — NASA Space Apps Challenge 2026 MVP

Field Shift is an agricultural decision-support prototype for comparing crop-rotation alternatives under water stress and climate variability. It is **not just a satellite data viewer**.

**MVP area:** 65.875°W–64.125°W, 33.875°S–33.125°S (Villa Mercedes, San Luis, and southern Córdoba, Argentina). **Data cutoff:** 2026-11-01.

## Climate and soil evidence

The published datasets live in [`data/reference/mvp-homogeneo/`](data/reference/mvp-homogeneo/), with CSV/Parquet tables, a data dictionary, manifest, and checksums. Filenames and machine-readable field identifiers have not yet been translated because application consumers depend on the current schema.

| Dataset | Decision-relevant information |
|---|---|
| `clima_mensual_grilla_1991_2026`, `clima_anual_grilla_1991_2026` | Historical regional rainfall, temperature, FAO-56 ETo, P−ETo, frost, heat-stress days, and growing degree days across 32 grid points |
| `clima_diario_grilla_1991_2026`, `clima_zona_diario_1991_2026` | Daily climate series and a study-area aggregate |
| `enso_oni_mensual` | NOAA ONI and ENSO phase |
| `suelo_1ha_grilla`, `suelo_500m_grilla` | SRTM-derived elevation, slope, topographic susceptibility, and modeled mean soil moisture |
| `suelo_gaez_cultivos_1981_2010` | FAO GAEZ v4 historical crop suitability and attainable-yield reference |
| `suelo_sisinta_perfiles_caja` | INTA SISINTA profile horizons and available soil properties |
| `humedad_suelo_mensual_grilla_1991_2026` | Modeled mean monthly soil moisture, **not validated for daily correlation** |
| `estaciones_terrestres` | 19 ground weather station entries with locations and quality labels |

The `origen` field differentiates ground observations (`OBSERVADO_*`), estimates (`ESTIMADO_*`), and references (`REFERENCIA_*`). These must not be conflated. Verify the dataset files using `sha256sum -c SHA256SUMS` from the dataset directory.

## Scientific and product limitations

- NASA POWER regional climatology was compared with San Luis REM temperature data (reported correlation about **0.97**); this does **not** establish accuracy for individual parcels.
- SRTM-derived terrain includes flagged anomalous slopes. The topographic susceptibility index is **not a validated flood map**.
- The area includes 198 INTA SISINTA soil profiles (257 horizons), but only nine horizons have sufficiently complete texture and field-capacity information.
- GAEZ v4 crop suitability/yield data describe a historical 1981–2010 regional reference; local codebook coverage is incomplete.
- The soil-moisture balance model did **not** meet the daily correlation acceptance threshold (about 0.48–0.50 versus 0.60). Published monthly means carry the `NO_VALIDADA_CORRELACION` warning.
- Regional data, including POWER and GAEZ, cannot be presented as direct parcel measurements merely because they are resampled.
- The repository contains an **interactive rotation-comparison simulator with scoring logic**, but the scores and rankings are **prototype outputs, not field-validated agronomic recommendations**.

## Public project documentation

- [MVP data guide](data/reference/mvp-homogeneo/README.md), [manifest](data/reference/mvp-homogeneo/manifest.json), and [checksums](data/reference/mvp-homogeneo/SHA256SUMS)
- [NASA and local data source specifications](data/sources/README.md)
- [Data methodology](data/ARCHITECTURE.md) and [decision/evidence contracts](docs/contracts/README.md)
- [Crop catalog](docs/challenge/crop-catalog.yml), [project overview](docs/project-overview.md), and [NASA presentation](presentation/README.md)

This public repository provides the product code, reference datasets, scientific metadata, and documentation. It does not contain private operations data, credentials, or original upstream raw archives.
