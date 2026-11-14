# P6 — Diseño del motor mínimo de comparación (borrador)

Status: DRAFT DESIGN. No code. Depends on local repo contracts only; no new downloads.

## Purpose
Compare two or more crop rotations for one anchor using explicit, traceable rules, and return the trade-offs and limitations. It must not return a recommendation while E2 is open (`docs/contracts/evidence-claims.md`, `DEC-002`).

## Governing contract
`field-shift/docs/contracts/decisions/evaluation-contract.yml` defines the inputs (field_context, evidence, soil_profile, crops, rotations, farmer_priorities, decision_rules) and the outputs per rotation and per comparison. Invariants that bind the design:
- every material result traces to evidence or an explicit assumption;
- numeric scores must not imply precision beyond the evidence;
- farmer priorities change weights, not observations;
- inactive or shadow rules never affect results;
- spatial scope of the evidence is preserved.

## Minimal inputs the engine may read today
| Input | Source in repo | Usable now |
|---|---|---|
| Crop coefficients Kc mid/end | `reference/crops/catalog.yml` (FAO-56 tabla 12) | yes, with citation |
| Kc inicial | FAO-56 figuras 29-30 (method, not value) | no, method only |
| Rooting depth Zr, depletion fraction p | FAO-56 tabla 22 | yes, with citation |
| Cycle days | Riglos 2023, Tello 2024 | yes, trial scope only |
| Sowing windows | UNSL 2024 (maize, sorghum) | maize and sorghum only, single trial |
| Soil profile | `data/manifests/soil.yml` (pending) | no |
| Climate series | POWER, checked in E2 mechanical note | yes, but E2 not closed |
| Rotations | `docs/contracts/decisions/rotation-template.yml` | structure only |

## Gating rules (proposed)
1. **E2 gate:** if E2 is not closed for the observation layer a score depends on, the engine returns the rotation's inputs and limitations only, with no ranking.
2. **Parameter gate:** a crop with any `NO_VERIFICADO` parameter used by the active rule is excluded from ranking and listed as missing.
3. **Scope gate:** any evidence from a single trial or single season is labelled as such in the output, and cannot be generalised to a regional rule.
4. **Shadow gate:** rules with status other than validated are computed for shadow reporting only.

## Output shape (per rotation)
Fields as in the evaluation contract: `rotation_id`, `comparative_result` (blocked or ranked), `score_components` (only with gates passed), `evidence_refs`, `applied_rule_refs`, `benefits`, `risks`, `trade_offs`, `uncertainty`, `limitations`, `explanation`.

## What this design does not do
- It does not choose the baseline (testigo) rotation. That choice is a decision for the team and the user.
- It does not define a water-balance model. A water-balance model needs soil profile and E2; it is the next design step after both close.
- It does not compute Kc inicial from FAO figures until the rainfall-frequency and ETo inputs are fixed.

## Open decisions for the user
1. Confirm the gating rules above, in particular that no ranking is returned while E2 is open.
2. Name the baseline rotation (testigo) and one alternative, or leave them to the rotation step P5.
3. Confirm whether the first version computes only the water-demand indicator from Kc and Zr, or also includes cycle and sowing timing.
