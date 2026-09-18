# ADR-0002 — Segment-Level Translation with Per-Segment Checkpoints

| Field        | Value                          |
|--------------|--------------------------------|
| Status       | Accepted                       |
| Date         | 2025-07-20                     |

## Context

Should the translator process whole chapters at once, paragraphs individually, or at some other granularity? And how do we handle failures without losing progress?

## Decision

Translate at the **paragraph / text-unit level** (segments matching `<p>`, `<h1>`–`<h6>`, etc.) with **per-segment JSONL checkpoints**.

## Rationale

- **Whole-chapter:** risks losing the entire chapter on a single API failure or token-limit error; expensive; slow feedback.
- **Word-level:** too granular — loses sentence-level context; high API cost; slow.
- **Segment-level (paragraph):** good context window for the LLM; isolated failure = one segment; fast resume; natural unit for proofreading.

Per-segment JSONL checkpoints mean:

- A run can be interrupted at any point and resumed — already-done segments are skipped.
- State is append-only; last-write-wins on re-processing.
- Cost tracking is per-segment, enabling transparent billing.

## Consequences

- The LLM loses some inter-segment coherence (e.g., pronoun references across paragraphs). Mitigation: inject previous N segments as context in the system prompt.
- Glossary terms must be defined at the source level; the model handles cross-segment disambiguation via context injection.
- JSONL format is human-readable and toolable (`grep`, `jq`).
