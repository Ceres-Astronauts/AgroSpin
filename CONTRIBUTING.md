# Contributing

Field Shift is a public, evidence-driven project developed for the NASA International Space Apps Challenge 2026.

## Canonical language

English is the canonical language of the repository. Use English for documentation, issues, pull requests, commit messages, code comments, schemas, structured context, and presentation material.

## Working principles

Contributions should prioritize:

1. Human readability.
2. Evidence and provenance.
3. Traceability of decisions.
4. Reproducibility.
5. Simplicity before abstraction.
6. Explicit uncertainty and limitations.

Avoid speculative architecture. Add structure when a concrete requirement, dataset, decision, or implementation need justifies it.

## Documentation and context

`docs/` is primarily human-oriented explanatory documentation.

`data/sources/` and `data/manifests/` describe source identity and provenance, and `docs/contracts/` contains public data and decision contracts.

Keep product documentation self-contained; link to established public evidence rather than duplicate scientific claims.

## Data and evidence

When introducing a dataset, model assumption, or domain claim, document as appropriate:

- source and provider
- dataset or product identifier
- intended use
- relevant spatial and temporal scope
- known limitations
- provenance or retrieval method
- validation status

Do not present inferred or AI-generated information as evidence solely because an AI system produced it.

## AI-assisted contributions

AI-assisted work is allowed and expected where it improves productivity or analysis.

Human contributors remain responsible for validating factual claims, scientific assumptions, code behavior, data transformations, citations, provenance, and changes to accepted decision logic.

Field Shift follows a human-first, AI-optimized approach: AI should reduce reconstruction and repetitive work, not become a prerequisite for understanding the project.

## Scientific decision changes

Agronomic hypotheses and decision-rule changes require evidence, reproducible tests, uncertainty disclosure, and human review before becoming active.

## Security and privacy

Never commit:

- passwords
- API keys
- access tokens
- private keys
- local `.env` files
- personal information
- confidential information
- proprietary datasets without permission
- private NASA Earthdata credentials

Use environment variables and local credential mechanisms. Commit only safe examples such as `.env.example`.

## Commit style

Prefer small, conceptually coherent commits. Conventional-style prefixes are encouraged, for example:

- `docs:` documentation
- `feat:` product capability
- `feat(context):` canonical context capability
- `feat(sources):` source registry changes
- `feat(learning):` learning lifecycle changes
- `chore:` repository maintenance or bootstrap
- `test:` tests and validation assets
