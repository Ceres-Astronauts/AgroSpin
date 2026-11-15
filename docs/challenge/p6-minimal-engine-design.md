# AgroSpin — Rotation Comparison Engine: Implemented Prototype and Scientific Limits

**NASA challenge:** Field Shift: Adapting Farms with NASA Data  
**Status:** Implemented *simulation prototype*; agronomic and field validation **not complete**.  
**Scope:** Documentation of the current implementation, not a new recommendation policy.

## Purpose

AgroSpin compares three proposed crop-rotation strategies for a selected context in the Villa Mercedes / eastern San Luis study area. It combines available regional climate and soil context, declared field conditions, producer priorities, and a manually defined multicriteria rubric.

It is **not** a field-validated agronomic recommendation service. Simulated rankings must not be interpreted as proven crop suitability, yield forecasts, or parcel-scale measurements.

## Current implementation

| Component | Repository location | Current role |
|---|---|---|
| Rotation simulator | [`src/decision/rotation_engine.py`](../../src/decision/rotation_engine.py) | Applies the rubric, scenario modifiers, and comparative sorting |
| Rotation criteria | [`data/rotation_rubric.json`](../../data/rotation_rubric.json) | Defines three candidate rotations and baseline rubric ratings |
| Climate/terrain contextualization | [`src/decision/map_data.py`](../../src/decision/map_data.py) | Reads repository-hosted English-schema MVP datasets and supplies spatial context |
| Published evidence | [`data/reference/mvp-homogeneous/`](../../data/reference/mvp-homogeneous/) | Versioned climate, soil, station, and reference datasets |
| Automated behavior tests | [`tests/test_rotation_engine.py`](../../tests/test_rotation_engine.py) | Exercises deterministic scenarios and API behavior, not agronomic field accuracy |
| Crop knowledge | [`docs/challenge/crop-catalog.yml`](crop-catalog.yml) | Crop characteristics with source references and unresolved values |
| Proposed scientific evaluation contract | [`docs/contracts/decisions/evaluation-contract.yml`](../contracts/decisions/evaluation-contract.yml) | Defines expected evidence and eligibility semantics; **not proof that runtime gates are fully enforced** |

## How the prototype compares alternatives

1. Read a crop-rotation rubric with dimension criteria and scores.
2. Interpret the requested field and rainfall scenario together with available regional data.
3. Apply defined criteria weights and contextual modifiers for producer priorities, irrigation, soil, moisture, planning horizon, and related constraints.
4. Calculate bounded comparative suitability scores and sort alternatives.
5. Return supporting factors, alerts, contextual assumptions, information gaps, and source references.

The scores represent **prototype rubric calculations**. They are not independently validated estimates of yield, financial return, or agronomic success.

## Fixed uncertainty values are heuristics

Sparse local soil and field measurements motivated fallback rules. The engine includes an **±28% uncertainty label**, as well as other hard-coded percentages, thresholds, and score adjustments. These are **heuristic scenario settings**, not statistical confidence intervals, calibrated error bounds, or empirically supported probability statements. Their exact numerical magnitudes have not been independently validated for each field or condition.

Do not interpret ±28% as a quantified 95% interval, a measured error margin, or proof that moisture estimates lie within that range. Explain it as a **high-uncertainty flag caused by evidence gaps**. The simulation should not promote such heuristic values into scientific evidence.

## Validation boundaries

- **Integrity/engineering checks:** acquisition, schema, missing values, and checksums verify reproducibility and basic data handling.
- **Method-specific checks:** NASA POWER comparisons with local REM records support limited climate interpretation, not precise parcel truth.
- **Failed/pending scientific checks:** modeled monthly soil moisture does **not** pass the daily-correlation acceptance threshold (reported 0.48–0.50 versus 0.60). Topographic susceptibility is unvalidated as a flood predictor. Some INTA soil profiles are incomplete.
- **Agronomic decision validation:** crop compatibility, field-level effects, numeric adjustments, and ranking thresholds require independent local evidence or expert/field validation.

The [evidence model](../contracts/evidence-claims.md) and [evaluation contract](../contracts/decisions/evaluation-contract.yml) describe stricter proposed decision gates. **The current simulator can still output a numeric ranking before all of those gates have been scientifically closed.** This implementation gap must be disclosed in demos and documentation, rather than implying that the proposal is already enforced by code.

## What remains to be established

- Reproducible evidence linking each important rule, score, and weight to locally applicable agronomic research.
- A demonstrated baseline/current rotation and comparable management windows for each alternative.
- Soil-profile representativeness and crop-specific available-water assumptions.
- A decision on which field evidence gates must block recommendations rather than merely produce warnings.
- Independent agronomic review or field benchmarking before real farm use.

**Presentation language:** "AgroSpin explores and compares candidate rotations using NASA and local evidence, with transparent assumptions and clearly labeled heuristic rankings." Do not claim validated field recommendations.
