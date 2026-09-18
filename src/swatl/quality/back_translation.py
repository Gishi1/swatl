"""Back-translation quality verification — sample-based Chinese re-check."""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from swatl.models import Segment

logger = logging.getLogger(__name__)


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

    def summary(self) -> str:
        """Return a human-readable summary string."""
        lines = [
            f"Back-Translation Report: {self.segments_tested} tested",
            f"  ✅ OK: {self.ok}",
            f"  ⚠️  Warnings: {self.warnings}",
            f"  ❌ Critical: {self.critical}",
        ]
        return "\n".join(lines)


def _levenshtein_similarity(a: str, b: str) -> float:
    """Compute similarity ratio using Levenshtein distance (simple DP)."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    m, n = len(a), len(b)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])
    distance = dp[m][n]
    max_len = max(m, n)
    return 1.0 - (distance / max_len)


async def back_translate_segment(
    segment: Segment,
    api_base_url: str,
    api_key: str,
    model: str = "deepseek-chat",
) -> BackTranslationResult:
    """Back-translate a single segment using an LLM API."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{api_base_url}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a translator doing quality verification. "
                            "Back-translate the following English text back to Chinese. "
                            "Return only the Chinese translation, nothing else."
                        ),
                    },
                    {
                        "role": "user",
                        "content": segment.translated or "",
                    },
                ],
            },
        )
        response.raise_for_status()
        data = response.json()
        back_translated = data["choices"][0]["message"]["content"].strip()

    similarity = _levenshtein_similarity(segment.source_text, back_translated)

    if similarity >= 0.7:
        flag = "ok"
    elif similarity >= 0.4:
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

    results = []

    async def _process(seg: Segment) -> BackTranslationResult | None:
        try:
            return await back_translate_segment(seg, api_base_url, api_key, model)
        except Exception as e:
            logger.warning("Back-translation failed for segment %s: %s", seg.id, e)
            return None

    tasks = [back_translate_segment(s, api_base_url, api_key, model) for s in sample]
    raw_results = await _run_parallel(tasks)

    for r in raw_results:
        if r is not None:
            results.append(r)

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
    )


async def _run_parallel(tasks: list) -> list:
    """Run async tasks concurrently with limited concurrency."""
    if not tasks:
        return []

    semaphore = __import__("asyncio").Semaphore(3)

    async def _with_sem(task):
        async with semaphore:
            return await task

    return await __import__("asyncio").gather(*[_with_sem(t) for t in tasks])


def save_report(report: BackTranslationReport, output_path: str | Path) -> None:
    """Save back-translation report to a JSON file."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    data = {
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
