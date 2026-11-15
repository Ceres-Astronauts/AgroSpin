# AgroSpin — Public MVP Status (Draft)

AgroSpin is a decision-support assistant for comparing crop rotations under changing water and climate conditions. It is not a standalone satellite viewer.

## What Is Verified

| Component | Status | Evidence |
|---|---|---|
| Daily precipitation and weather (NASA POWER, 1991–2025) | Acquired and mechanically checked (completeness and value ranges) | `e2-mechanical-checks.md` |
| Soil moisture (NASA SMAP L4 SPL4SMGP.008, 2015–2025, 3 points) | `sm_surface` and `sm_rootzone` at E1 level; daily aggregation verified | `e2-mechanical-checks.md` |
| Crop catalog | Crop coefficients (Kc) and rooting depths cited from FAO-56; missing fields marked `UNVERIFIED` | `crop-catalog.yml` |
| Decision comparison engine design | Documented; multicriteria simulation prototype implemented | `p6-minimal-engine-design.md` |

## What Remains Limited and Why

- **Field-scale calibration (E2) remains open:** rotation comparisons must still be benchmarked against independent local field trials and farm records.
- **Soil profile water balance at parcel scale:** measured field texture and soil depth are sparse across the box (most SISINTA horizons are incomplete).
- **Regional spatial resolution:** NASA satellite and reanalysis grids represent regional macro cells rather than individual fields.

## How Each Result Is Evaluated

Every data source carries explicit provenance (`origin`), evidence level (`E0` to `E7`), and methodological caveats. Unvalidated derived indicators (such as topographic susceptibility and monthly soil moisture balance correlation) are explicitly labeled rather than presented as verified field truth.

## What This Repository Excludes

Private grower operational records, credentials, API secrets, and local working paths. Archival source data are referenced from their original cited institutions.
