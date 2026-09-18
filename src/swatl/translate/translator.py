"""Translation orchestrator: batch segments, manage concurrency, handle retries."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

from swatl.models import Glossary, Segment, SegmentStatus
from swatl.providers.base import Provider

from .prompt_builder import build_context_window, build_translation_prompt
from .translation_memory import TranslationMemory

logger = logging.getLogger(__name__)


class Translator:
    """Orchestrates LLM translation of segment batches."""

    def __init__(
        self,
        provider: Provider,
        source_lang: str = "zh",
        target_lang: str = "en",
        concurrency: int = 4,
        batch_size: int = 10,
        retry_max: int = 3,
        translation_memory: TranslationMemory | None = None,
        style: str = "formal",
        context_retriever=None,  # ContextRetriever from swatl.context
    ) -> None:
        self.provider = provider
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.concurrency = concurrency
        self.batch_size = batch_size
        self.retry_max = retry_max
        self.style = style
        self.system_prompt = build_translation_prompt(source_lang, target_lang, style=style)
        self.translation_memory = translation_memory
        self.tm_hits = 0
        self.context_retriever = context_retriever  # Optional ContextRetriever

    async def translate_all(
        self,
        segments: list[Segment],
        glossary: Glossary | None = None,
    ) -> list[Segment]:
        """Translate all pending segments with batching and retry."""
        # Recorded up front so every early-return path (nothing pending, all
        # cache hits) still carries glossary provenance.
        self.record_glossary_hits(segments, glossary)

        pending = [s for s in segments if s.status == "pending"]
        if not pending:
            logger.info("No pending segments to translate.")
            return segments

        logger.info(
            "Translating %d segments (concurrency=%d, batch_size=%d, tm_entries=%d)",
            len(pending),
            self.concurrency,
            self.batch_size,
            self.translation_memory.count() if self.translation_memory else 0,
        )

        # Check TM cache first
        if self.translation_memory:
            cached = 0
            for seg in pending:
                cached_translation = self.translation_memory.lookup(seg)
                if cached_translation is not None:
                    seg.translated = cached_translation
                    seg.status = SegmentStatus.TRANSLATED
                    seg.tokens_in = 0
                    seg.tokens_out = 0
                    seg.provider = "tm"
                    cached += 1
            if cached:
                logger.info(
                    "TM cache hit: %d/%d segments matched (no LLM call needed)",
                    cached,
                    len(pending),
                )
            # Filter out cached segments so we only translate the rest
            pending = [s for s in pending if s.status != SegmentStatus.TRANSLATED]
            self.tm_hits = cached

        if not pending:
            logger.info("No pending segments to translate (all cached).")
            return segments

        # Process in batches with concurrency control
        semaphore = asyncio.Semaphore(self.concurrency)
        results = []
        failed = []

        async def translate_batch(batch: list[Segment]) -> list[Segment]:
            async with semaphore:
                for attempt in range(1, self.retry_max + 1):
                    try:
                        context = build_context_window(results, n_previous=3)
                        # Build per-segment retrieved context via ContextDB
                        retrieved_contexts: list[str | None] = []
                        if self.context_retriever:
                            proximity_ids = {s.id for s in results}
                            for seg in batch:
                                rc = self.context_retriever.retrieve_and_format(
                                    seg.source_text,
                                    current_doc=seg.doc,
                                    proximity_ids=proximity_ids,
                                )
                                retrieved_contexts.append(rc if rc else None)
                        else:
                            retrieved_contexts = [None] * len(batch)

                        # Rebuild per batch so the glossary and running context
                        # are reflected in the prompt sent to the provider.
                        system_prompt = build_translation_prompt(
                            self.source_lang,
                            self.target_lang,
                            glossary=glossary,
                            context=context,
                            style=self.style,
                        )

                        translated = await self.provider.translate(
                            batch,
                            glossary,
                            self.target_lang,
                            context,
                            retrieved_contexts=retrieved_contexts,
                            system_prompt=system_prompt,
                        )
                        return translated
                    except Exception as e:
                        logger.warning(
                            "Attempt %d/%d failed for %d segments: %s",
                            attempt,
                            self.retry_max,
                            len(batch),
                            e,
                        )
                        if attempt < self.retry_max:
                            await asyncio.sleep(1.5**attempt)
                # All retries failed
                for seg in batch:
                    seg.status = SegmentStatus.FAILED
                    return batch

        # Split into batches
        batches = [
            pending[i : i + self.batch_size] for i in range(0, len(pending), self.batch_size)
        ]

        for i, batch in enumerate(batches):
            start = time.monotonic()
            batch_results = await translate_batch(batch)
            elapsed = time.monotonic() - start
            results.extend(batch_results)

            ok = sum(1 for s in batch_results if s.status != "failed")
            fail = sum(1 for s in batch_results if s.status == "failed")
            logger.info(
                "Batch %d/%d: %d ok, %d failed (%.1fs)",
                i + 1,
                len(batches),
                ok,
                fail,
                elapsed,
            )
            if fail:
                failed.extend([s for s in batch_results if s.status == "failed"])

        # Update original list in-place. Index by id once: a nested scan per
        # result made this O(n²) and dominated run time on large books.
        by_id = {seg.id: seg for seg in segments}
        for seg in results:
            original = by_id.get(seg.id)
            if original is not None:
                original.translated = seg.translated
                original.status = seg.status
                original.provider = seg.provider
                original.tokens_in = seg.tokens_in
                original.tokens_out = seg.tokens_out
                original.glossary_hits = seg.glossary_hits

        logger.info(
            "Translation complete: %d ok, %d failed out of %d total",
            len(results) - len(failed),
            len(failed),
            len(segments),
        )

        # Add new translations to TM cache
        if self.translation_memory:
            added = self.translation_memory.add_many(results + pending)
            self.translation_memory.save_disk_cache()
            logger.info("Added %d new entries to translation memory", added)

        return segments

    @staticmethod
    def record_glossary_hits(segments: list[Segment], glossary: Glossary | None) -> None:
        """Record which glossary source terms occur in each segment.

        Powers the "Glossary hits" panel in the web UI and makes glossary
        compliance auditable after the fact.
        """
        if not glossary or not glossary.entries:
            return
        terms = [e.source for e in glossary.entries if e.source]
        if not terms:
            return
        for seg in segments:
            if not seg.source_text:
                continue
            seg.glossary_hits = [term for term in terms if term in seg.source_text]

    def estimate_tokens(self, segments: list[Segment]) -> tuple[int, int]:
        """Rough token estimate: ~1 token per CJK char, ~4 chars per English token."""
        total_in = 0
        total_out = 0
        for seg in segments:
            cjk_count = sum(1 for c in seg.source_text if "\u4e00" <= c <= "\u9fff")
            ascii_count = len(seg.source_text) - cjk_count
            total_in += cjk_count + ascii_count // 4  # zh chars + ascii
            # Output estimate: roughly same char count for zh→en
            total_out += cjk_count // 2 + ascii_count // 4
        return total_in, total_out


def parse_json_response(content: str) -> dict[str, Any] | None:
    """Extract JSON from an LLM response (may be wrapped in markdown)."""
    # Try direct parse first
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Try to find JSON in markdown code blocks
    json_match = re.search(
        r'```(?:json)?\s*(\{[^{}]*"translated"[^{}]*\})\s*```', content, re.DOTALL
    )
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find any JSON object
    json_match = re.search(r'\{[^{}]*"translated"[^{}]*\}', content, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    return None
