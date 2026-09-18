# ADR-0006: Namespace Fixtures and Async Provider Interface

**Date:** 2026-01-15
**Status:** Accepted

## Context

During implementation of the full translation pipeline, three critical bugs were discovered:

1. **EPUB metadata extraction failure**: The `child_ns()` function returned namespaces with trailing `}` (e.g., `{http://purl.org/dc/elements/1.1/}`) but was compared against namespace URIs without braces (e.g., `http://purl.org/dc/elements/1.1/`), causing title/author extraction to fail silently.

2. **MockProvider async interface mismatch**: The base `Provider` class defines `async def translate()`, but `MockProvider` implemented `def translate()` (synchronous), causing "object list can't be used in 'await' expression" errors during translation.

3. **Glossary replacement corruption**: The `_mock_translate()` function replaced glossary terms with `<<marker>>` placeholders, but the character-level conversion added spaces between every character, making the replacement markers unfindable during the restoration pass.

## Decision

1. **Fix `child_ns()` to return namespace without trailing brace**: Changed from `tag.split("}")[0] + "}"` to extracting the namespace URL properly using `tag.index("}")` and slicing `tag[1:idx]`.

2. **Make MockProvider methods async**: Changed `translate()`, `proofread()`, and `test()` to `async def` to match the abstract `Provider` interface.

3. **Fix glossary placeholder matching**: Use `' '.join(marker)` to create the expected spaced version of markers for replacement.

## Consequences

- All 50+ tests now pass (53 after adding integration tests)
- Full pipeline works: extract → translate → proofread → audit → writeback
- MockProvider can now be used as a drop-in replacement for real providers in tests
- EPUB metadata extraction works for both EPUB 2.0 and 3.0

## Trade-offs

- Making MockProvider async means test code must `await` calls or use `asyncio.run()`
- The `child_ns()` fix is backward compatible since the function is only used internally

