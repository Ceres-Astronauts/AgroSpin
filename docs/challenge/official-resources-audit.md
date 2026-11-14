# Official challenge resources audit — Field Shift (2026-11-14)

Status: PARTIAL. Decision matrix done from the published list supplied to the team. Resolution, access terms, licensing and URL checks not yet completed (see Gaps).

Sources reviewed: published list of 24 resources (from the audit request), plus registered sources in `reference/sources/` and product `data/sources/`. No downloads. No repository changes beyond this note.

## Decision matrix

| # | Resource | Applies to Argentina | Already registered | Decision |
|---|---|---|---|---|
| 1 | NASA SMAP | Yes (global) | Yes, `nasa-smap-spl4smgp-v8` | KEEP (E1 partial) |
| 2 | GPM / IMERG | Yes | Yes, product `gpm-imerg` | DEFER (complementary; roadmap Phase 4) |
| 3 | Landsat / MODIS / VIIRS | Yes | No | INVESTIGATE (only if a vegetation signal is needed) |
| 4 | NASA POWER | Yes | Yes | KEEP (acquired; mechanical validation done) |
| 5 | SRTM | Yes | No | DEFER (not in MVP scope) |
| 6 | ECOSTRESS | Yes | Yes, product `ecostress` | DEFER (MVP+) |
| 7 | USDA Ag Data Commons | No, US | No | REJECT |
| 8 | USDA Web Soil Survey | No, US | No | REJECT |
| 9 | USDA CDL / CropScape | No, US | No | REJECT |
| 10 | PRISM | No, US | No | REJECT |
| 11 | SSURGO / STATSGO2 | No, US | No | REJECT |
| 12 | NAIP | No, US | No | REJECT |
| 13 | NLCD | No, US | No | REJECT |
| 14 | NLDAS / GLDAS | Partial (NLDAS is US-only) | No | DEFER (redundant with POWER) |
| 15 | FAO GAEZ | Yes, global | No | INVESTIGATE (crop suitability; useful for crop catalog) |
| 16 | CoCoRaHS | No, US | No | REJECT |
| 17 | USGS NWIS | No, US | No | REJECT |
| 18 | USDA AMS Market News | No, US | No | REJECT |
| 19 | USDA NASS QuickStats | No, US | No | REJECT (local equivalent: INDEC / MAGyP) |
| 20 | OpenET | No, US coverage | No | REJECT |
| 21 | LANDFIRE | No, US | No | REJECT |
| 22 | GEDI | Yes, out of scope | No | REJECT for MVP |
| 23 | Sentinel-2 | Yes | No | DEFER (field scale; risk under DEC-001) |
| 24 | ERA5 | Yes | No | DEFER (fallback if POWER fails) |

Additional project sources:
- KEEP: FAO-56, INTA SIGA, SISINTA, INTA Mapa Nacional de Cultivos, REM San Luis, SMN surface observations, INTA San Luis crop trials.
- INVESTIGATE: SoilGrids, as soil fallback if SISINTA cannot be accessed.

## Gaps that would change the decision
1. Measured local soil profile: SISINTA acquisition failed.
2. Station data for the independent E2 comparison: REM San Luis and SMN are registered but not downloaded.
3. Crop trial evidence: only maize and sorghum have sowing windows; soybean and sunflower depend on INTA repository access.

## Gaps in this audit (not yet done)
- Spatial and temporal native resolution for each KEEP and INVESTIGATE source (required by audit step 5).
- Access requirements, quality metadata and data-use terms (audit step 6).
- Verification that each URL in the published list resolves. The official challenge page could not be opened from this environment (certificate error); the Hackathlone mirror was not checked.
- Independent review of this matrix before it is used for decisions.
