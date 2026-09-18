# ADR-0005 — Glossary + Translation Memory for Consistency

| Field        | Value                          |
|--------------|--------------------------------|
| Status       | Accepted                       |
| Date         | 2025-07-20                     |

## Context

Translation quality depends on consistent terminology. Without controls, the LLM may translate the same term differently across chapters.

## Decision

Use a **glossary** (source → target term pairs) injected into every prompt, plus a **Translation Memory (TM)** cache keyed by segment hash.

## Rationale

- **Glossary injection** into the system prompt forces the LLM to use specified terms. Lokalise and other MT providers use this approach for deterministic terminology.
- **Translation Memory** caches `(segment_hash → translation)` pairs. Benefits:
  - On a re-run of the same EPUB, identical segments reuse the cached translation (cost savings + consistency).
  - On a glossary update, only segments referencing changed glossary terms need re-translation.
- Glossary is a TOML file with per-entry metadata (domain, notes) for human maintainability.

## Consequences

- Glossary management is a user responsibility. We provide `swatl glossary init` / `swatl glossary add` commands.
- TM cache lives in state (`state/tm.json`) and grows over time. Users can prune it.
- Glossary injection increases prompt length. For very large glossaries (>500 terms), only terms matching the current document are injected.
