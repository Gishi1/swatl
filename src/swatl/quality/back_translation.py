"""Back-translation quality verification — sample-based Chinese re-check."""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from swatl.models import Segment

logger = logging.getLogger(__name__)


def _auth_headers(api_key: str) -> dict[str, str]:
    """JSON headers, with Authorization only when a key is configured."""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


# Similarity thresholds per metric: (ok, warning). Below the second value the
# round trip lost or invented so much that the segment is worth a human look.
#
# Calibrated by running real round trips through a local model (26 segments,
# zh->en->zh) and comparing each source with its back-translation:
#
#   chrF  real pairs: min 0.222, median 0.622, mean 0.667
#   chrF  mismatched pairs (a source compared with another segment's
#         back-translation): median 0.018, p90 0.067, p99 0.437
#
# 0.45 keeps about 80% of genuine round trips unflagged while almost every
# mismatched pair lands far below it. Levenshtein is much less discriminating
# (good pairs start at 0.40), so its old 0.70/0.40 cut-offs are unchanged.
THRESHOLDS: dict[str, tuple[float, float]] = {
    "chrf": (0.45, 0.25),
    "levenshtein": (0.70, 0.40),
}

DEFAULT_METRIC = "chrf"


def score_similarity(source: str, back_translated: str, metric: str = DEFAULT_METRIC) -> float:
    """Similarity in ``0 … 1`` between the source and its back-translation.

    ``chrf`` is the standard character n-gram metric and handles Chinese without
    a tokenizer; ``levenshtein`` is the older, coarser edit-distance ratio.
    """
    from swatl.quality.metrics import chrf, levenshtein_similarity

    if metric == "levenshtein":
        return levenshtein_similarity(source, back_translated)
    if metric != "chrf":
        raise ValueError(f"Unknown similarity metric {metric!r}: use 'chrf' or 'levenshtein'")
    return chrf(source, back_translated)


@dataclass
class BackTranslationResult:
    """Result of back-translating a single segment."""

    segment: Segment
    back_translated: str
    similarity_score: float  # 0.0 to 1.0
    flag: str  # "ok", "warning", "critical"


@dataclass
class BackTranslationReport:
    """Report for a batch of back-translated segments."""

    segments_tested: int
    ok: int
    warnings: int
    critical: int
    results: list[BackTranslationResult]
    details: list[dict[str, Any]]
    metric: str = DEFAULT_METRIC

    def summary(self) -> str:
        """Return a human-readable summary string."""
        lines = [
            f"Back-Translation Report: {self.segments_tested} tested ({self.metric})",
            f"  ✅ OK: {self.ok}",
            f"  ⚠️  Warnings: {self.warnings}",
            f"  ❌ Critical: {self.critical}",
        ]
        return "\n".join(lines)


async def back_translate_segment(
    segment: Segment,
    api_base_url: str,
    api_key: str,
    model: str = "deepseek-chat",
    timeout: float = 60.0,
    metric: str = DEFAULT_METRIC,
    source_language: str = "Chinese",
) -> BackTranslationResult:
    """Back-translate a single segment using an LLM API."""
    # Same endpoint convention as the translation provider: base_url already
    # includes any version prefix (e.g. ".../v1").
    from swatl.providers.openai_compat import parse_chat_completion

    base_url = api_base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers=_auth_headers(api_key),
            json={
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a translator doing quality verification. "
                            f"Back-translate the following English text back to {source_language}. "
                            "Return only the translation, nothing else."
                        ),
                    },
                    {
                        "role": "user",
                        "content": segment.translated or "",
                    },
                ],
                # Some gateways stream unless told otherwise.
                "stream": False,
            },
        )
        response.raise_for_status()
        content, _usage = parse_chat_completion(response)
        back_translated = (content or "").strip()

    similarity = score_similarity(segment.source_text, back_translated, metric)
    ok_threshold, warn_threshold = THRESHOLDS[metric]

    if similarity >= ok_threshold:
        flag = "ok"
    elif similarity >= warn_threshold:
        flag = "warning"
    else:
        flag = "critical"

    return BackTranslationResult(
        segment=segment,
        back_translated=back_translated,
        similarity_score=round(similarity, 3),
        flag=flag,
    )


async def back_translate_sample(
    segments: list[Segment],
    api_base_url: str,
    api_key: str,
    model: str = "deepseek-chat",
    sample_size: int = 20,
    seed: int | None = None,
    timeout: float = 60.0,
    metric: str = DEFAULT_METRIC,
    source_language: str = "Chinese",
) -> BackTranslationReport:
    """Back-translate a random sample of translated segments."""
    translated = [
        s for s in segments if s.translated and s.status in ("translated", "proofread", "edited")
    ]
    if not translated:
        return BackTranslationReport(
            segments_tested=0, ok=0, warnings=0, critical=0, results=[], details=[]
        )

    rng = random.Random(seed)
    sample = rng.sample(translated, min(sample_size, len(translated)))

    async def _process(seg: Segment) -> BackTranslationResult | None:
        try:
            return await back_translate_segment(
                seg,
                api_base_url,
                api_key,
                model,
                timeout=timeout,
                metric=metric,
                source_language=source_language,
            )
        except Exception as e:
            logger.warning("Back-translation failed for segment %s: %s", seg.id, e)
            return None

    # A single failing request must not abort the whole report.
    raw_results = await _run_parallel([_process(s) for s in sample])

    results = [r for r in raw_results if isinstance(r, BackTranslationResult)]

    ok = sum(1 for r in results if r.flag == "ok")
    warnings = sum(1 for r in results if r.flag == "warning")
    critical = sum(1 for r in results if r.flag == "critical")

    details = [
        {
            "segment_id": r.segment.id,
            "source": r.segment.source_text,
            "translated": r.segment.translated,
            "back_translated": r.back_translated,
            "similarity": r.similarity_score,
            "flag": r.flag,
        }
        for r in results
    ]

    return BackTranslationReport(
        segments_tested=len(results),
        ok=ok,
        warnings=warnings,
        critical=critical,
        results=results,
        details=details,
        metric=metric,
    )


async def _run_parallel(tasks: list) -> list:
    """Run async tasks concurrently with limited concurrency."""
    if not tasks:
        return []

    semaphore = asyncio.Semaphore(3)

    async def _with_sem(task):
        async with semaphore:
            return await task

    return await asyncio.gather(*[_with_sem(t) for t in tasks], return_exceptions=True)


def save_report(report: BackTranslationReport, output_path: str | Path) -> None:
    """Save back-translation report to a JSON file."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "metric": report.metric,
        "segments_tested": report.segments_tested,
        "ok": report.ok,
        "warnings": report.warnings,
        "critical": report.critical,
        "results": report.details,
    }
    with open(output, "w", encoding="utf-8") as f:
        import json

        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info("Back-translation report saved to %s", output)
