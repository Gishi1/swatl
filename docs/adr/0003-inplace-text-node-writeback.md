# ADR-0003 — In-Place Text-Node Write-Back (Not Full Regeneration)

| Field        | Value                          |
|--------------|--------------------------------|
| Status       | Accepted                       |
| Date         | 2025-07-20                     |

## Context

After translation, how do we produce the output EPUB? We can either (a) regenerate the EPUB using ebooklib (which re-writes all elements), or (b) modify only the text nodes in-place and re-zip.

## Decision

**In-place text-node replacement** using raw `zipfile` + `lxml`. ebooklib is not used for write-back.

## Rationale

- **ebooklib regeneration** can reorder, strip, or reformat elements. Known issues: Unicode handling, EPUB3 nav quirks, style attribute rewriting.
- **In-place replacement** guarantees that every element NOT modified (images, CSS, fonts, SVG, scripts, custom metadata) remains **byte-identical** to the input.
- Only text content and `lang`/`xml:lang` attributes change.

## Consequences

- We must implement our own spine parsing (reading `content.opf` directly with lxml). This is ~100 lines of code and is stable for well-formed EPUBs.
- Mixed-content elements (e.g., `<p>Hello <b>world</b></p>`) require careful handling: we wrap the translated portion in a `<span>` or adjust `elem.text` + `elem.tail` to preserve markup.
- ebooklib may be added later as a convenience layer for metadata queries, but never for write-back.
