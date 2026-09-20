"""Proofreading orchestrator: second-pass LLM calls for grammar/style."""

from __future__ import annotations

import asyncio
import logging

from swatl.models import Glossary, Segment, SegmentStatus
from swatl.providers.base import Provider

logger = logging.getLogger(__name__)


class Proofreader:
    """Runs a proofreading pass on translated segments."""

    def __init__(
        self,
        provider: Provider,
        concurrency: int = 4,
        retry_max: int = 2,
    ) -> None:
        self.provider = provider
        self.concurrency = concurrency
        self.retry_max = retry_max

    async def proofread_all(
        self,
        segments: list[Segment],
        glossary: Glossary | None = None,
    ) -> list[Segment]:
        """Proofread all translated-but-unproofread segments."""
        if getattr(self.provider, "mode", "json") == "plain":
            logger.warning(
                "%s is an instruction-style translation model and cannot proofread; "
                "no segments were changed. Use a chat model, e.g. "
                "`swatl proofread --provider <chat-model>`.",
                getattr(self.provider, "model", "provider"),
            )
            return segments

        to_proofread = [
            s for s in segments if s.status in ("translated", "edited") and s.translated
        ]
        if not to_proofread:
            logger.info("No segments to proofread.")
            return segments

        logger.info(
            "Proofreading %d segments (concurrency=%d)", len(to_proofread), self.concurrency
        )

        semaphore = asyncio.Semaphore(self.concurrency)
        results = []

        async def proofread_one(seg: Segment) -> Segment:
            async with semaphore:
                for attempt in range(1, self.retry_max + 1):
                    try:
                        result = await self.provider.proofread([seg], glossary)
                        # Trust the provider's status, not the text: on an HTTP
                        # error it returns the segment untouched (still
                        # TRANSLATED), so checking only that the text is truthy
                        # recorded a failed proofread as a successful one.
                        if result and result[0].status == SegmentStatus.PROOFREAD:
                            seg.translated = result[0].translated
                            seg.status = SegmentStatus.PROOFREAD
                            return seg
                    except Exception as e:
                        logger.warning(
                            "Proofread attempt %d/%d failed for %s: %s",
                            attempt,
                            self.retry_max,
                            seg.id,
                            e,
                        )
                        if attempt < self.retry_max:
                            await asyncio.sleep(1.5**attempt)
                # Keep original on failure
                return seg

        tasks = [proofread_one(seg) for seg in to_proofread]
        results = await asyncio.gather(*tasks)

        # Update original list
        for proofread_seg in results:
            original = next((s for s in segments if s.id == proofread_seg.id), None)
            if original:
                original.translated = proofread_seg.translated
                original.status = proofread_seg.status

        logger.info("Proofreading complete: %d segments updated", len(results))
        return segments
