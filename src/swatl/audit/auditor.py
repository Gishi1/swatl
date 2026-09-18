"""audit package: quality audit for translated EPUBs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from swatl.models import Glossary, Segment


@dataclass
class AuditIssue:
    """A single quality issue found during audit."""

    type: str  # "cjk_residue", "omission", "glossary_miss", "empty", "short"
    segment_id: str
    doc: str
    detail: str
    severity: str = "warning"  # "warning" or "error"


@dataclass
class AuditReport:
    """Complete quality audit report."""

    total_segments: int = 0
    translated_count: int = 0
    proofread_count: int = 0
    issues: list[AuditIssue] = field(default_factory=list)
    structure_docs: int = 0
    images_count: int = 0
    css_count: int = 0
    toc_present: bool = False

    def summary(self) -> str:
        lines = [
            "═══ Quality Audit ═══",
            "",
            f"Segments:  {self.total_segments} ({self.translated_count} translated, {self.proofread_count} proofread)",
            "",
        ]

        if self.issues:
            lines.append("Issues:")
            # Group by type
            by_type: dict[str, list[AuditIssue]] = {}
            for issue in self.issues:
                by_type.setdefault(issue.type, []).append(issue)

            for issue_type, issues in sorted(by_type.items()):
                labels = [i.segment_id for i in issues[:5]]
                if len(issues) > 5:
                    labels.append(f"... and {len(issues) - 5} more")
                lines.append(f"  {issue_type}: {len(issues)} segments  ({', '.join(labels)})")
        else:
            lines.append("No issues found.")

        lines.append("")
        lines.append("OK:")
        lines.append(f"  Documents: {self.structure_docs} source document(s) covered")
        if self.images_count:
            lines.append(f"  Images:    {self.images_count} preserved")
        if self.css_count:
            lines.append(f"  CSS:       {self.css_count} stylesheets preserved")
        if self.toc_present:
            lines.append("  TOC:       Present")

        return "\n".join(lines)

    def has_critical_issues(self) -> bool:
        return any(i.severity == "error" for i in self.issues)


# Regex patterns for CJK character ranges
CJK_UNIFIED = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")  # CJK Unified Ideographs
HIRAGANA = re.compile(r"[\u3040-\u309f]")  # Hiragana
KATAKANA = re.compile(r"[\u30a0-\u30ff\uff66-\uff9f]")  # Katakana


def _detect_cjk_residue(text: str, source_lang: str = "zh") -> list[str]:
    """Detect CJK characters in translated text, language-aware.

    Args:
        text: The translated text to check.
        source_lang: Source language code (e.g. 'zh', 'ja').

    Returns:
        List of unique CJK characters found.
    """
    found: list[str] = []
    if source_lang == "zh":
        # Chinese → any target: flag all CJK in output (Kanji overlap is expected in zh→zh,
        # but in zh→en it's an error)
        found.extend(CJK_UNIFIED.findall(text))
    elif source_lang == "ja":
        # Japanese → any target: flag Hiragana, Katakana, and Kanji in output
        found.extend(HIRAGANA.findall(text))
        found.extend(KATAKANA.findall(text))
        found.extend(CJK_UNIFIED.findall(text))
    else:
        # Generic: flag any CJK block
        found.extend(CJK_UNIFIED.findall(text))
        found.extend(HIRAGANA.findall(text))
        found.extend(KATAKANA.findall(text))
    return found


def _count_cjk_chars(text: str, source_lang: str = "zh") -> int:
    """Count CJK characters in source text for length-ratio heuristics."""
    if source_lang == "ja":
        return (
            len(HIRAGANA.findall(text))
            + len(KATAKANA.findall(text))
            + len(CJK_UNIFIED.findall(text))
        )
    return len(CJK_UNIFIED.findall(text))


def audit_segments(
    segments: list[Segment],
    glossary: Glossary | None = None,
    source_lang: str = "zh",
) -> AuditReport:
    """Run heuristic quality checks on translated segments.

    Checks:
    - CJK residue: source-script characters in target output
    - Omission: translated text is suspiciously short
    - Glossary miss: source glossary terms appear in output
    - Empty/short: translation is empty or trivially short
    """
    report = AuditReport()
    report.total_segments = len(segments)
    report.structure_docs = len({seg.doc for seg in segments})

    for seg in segments:
        if seg.status in ("translated", "proofread", "edited") and seg.translated:
            report.translated_count += 1
            if seg.status == "proofread":
                report.proofread_count += 1

        if not seg.translated or seg.status == "pending":
            continue

        text = seg.translated

        # 1. CJK residue detection (language-aware)
        cjk_matches = _detect_cjk_residue(text, source_lang)
        if cjk_matches:
            report.issues.append(
                AuditIssue(
                    type="cjk_residue",
                    segment_id=seg.id,
                    doc=seg.doc,
                    detail=f"Found CJK chars: {''.join(set(cjk_matches))[:20]}",
                    severity="error",
                )
            )

        # 2. Omission heuristic: length ratio
        if seg.source_text and text:
            ratio = len(text) / len(seg.source_text)
            cjk_in_source = _count_cjk_chars(seg.source_text, source_lang)
            # For zh→en and ja→en, expect the English to be somewhat shorter
            # (CJK chars are denser) but not less than 20% of source
            if ratio < 0.2 and cjk_in_source > len(seg.source_text) * 0.3:
                report.issues.append(
                    AuditIssue(
                        type="omission",
                        segment_id=seg.id,
                        doc=seg.doc,
                        detail=f"length_ratio={ratio:.2f} (source has {cjk_in_source} CJK chars)",
                        severity="warning",
                    )
                )

        # 3. Glossary miss detection
        if glossary and glossary.entries:
            for entry in glossary.entries:
                if entry.source in seg.source_text and entry.target not in text:
                    report.issues.append(
                        AuditIssue(
                            type="glossary_miss",
                            segment_id=seg.id,
                            doc=seg.doc,
                            detail=f"'{entry.source}' expected '{entry.target}' in output",
                            severity="warning",
                        )
                    )

        # 4. Empty or trivially short
        if not text.strip():
            report.issues.append(
                AuditIssue(
                    type="empty",
                    segment_id=seg.id,
                    doc=seg.doc,
                    detail="Translation is empty",
                    severity="error",
                )
            )
        elif len(text.strip()) < 3:
            report.issues.append(
                AuditIssue(
                    type="short",
                    segment_id=seg.id,
                    doc=seg.doc,
                    detail=f"Translation too short: {len(text)} chars",
                    severity="warning",
                )
            )

    return report
