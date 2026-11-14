# E2 mechanical checks — 2026-11-14

Status: MECHANICAL CHECKS DONE. E2 remains NOT CLOSED. Independent comparison pending.

## Decisions
- SMAP daily aggregation: arithmetic mean of valid 3-hourly observations per UTC day, per point and variable.
- Completeness rule: a day counts as complete only with 8 valid observations; days with fewer are flagged.
- Scope: sm_surface and sm_rootzone only. sm_rootzone_pctl excluded (100% -9999).

## SMAP (AppEEARS SPL4SMGP.008, 2015-03-31 to 2025-12-31, 3 points)
- Days per point and variable: 3,929 (all points, both variables).
- Days with n_obs different from 8: 0.
- Daily mean range: sm_surface 0.0345 to 0.2443 m3/m3; sm_rootzone 0.0324 to 0.1460 m3/m3.
- Independent recomputation (two separate implementations): 23,574 point-variable-day keys, 0 mismatches in n_obs or mean.
- Output files are not committed; raw data is not part of this repository.

## POWER (power_daily_point_19910101_20251231.json, point -33.65, -65.367)
- Variables: T2M, T2M_MAX, T2M_MIN, PRECTOTCORR, RH2M, WS10M, PS, ALLSKY_SFC_SW_DWN.
- Days per variable: 12,784 (1991-01-01 to 2025-12-31). Missing dates: 0.
- Ranges: T2M -3.5 to 32.23 C; T2M_MAX 0.91 to 40.84 C; T2M_MIN -7.62 to 24.76 C; PRECTOTCORR 0.0 to 176.71 mm/day; RH2M 16.21 to 97.17 %; WS10M 0.9 to 11.46 m/s; PS 91.71 to 95.55 kPa; ALLSKY_SFC_SW_DWN 0.27 to 36.23 MJ/m2/day.
- Out of obvious physical range: 0 for temperatures and precipitation.
- To verify: PRECTOTCORR maximum 176.71 mm/day is physically possible but extreme; check against station or SMN records before treating it as valid. This is not a known error.

## Still open for E2
- Independent comparison against local station or field measurements (none acquired; INTA repository unreachable in this session).
- Plausibility of the 176.71 mm/day day against an independent record.
- Soil profile context before any agronomic interpretation of root-zone values.
