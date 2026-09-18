"""XHTML segmenter: walk documents, extract translatable text segments with anchors."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from lxml import html

from swatl.models import Segment

logger = logging.getLogger(__name__)

# Tags to extract
TRANSLATABLE_TAGS = {
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "blockquote",
    "li",
    "figcaption",
    "dt",
    "dd",
    "td",
    "th",
    "em",
    "strong",
    "cite",
    "code",
    "abbr",
}

# Skip these entirely
SKIP_TAGS = {
    "script",
    "style",
    "meta",
    "link",
    "svg",
    "img",
    "input",
    "button",
    "select",
    "textarea",
    "head",
    "title",
    "body",
}

# Regex for building XPath-like anchors
_TAG_RE = re.compile(r"^[a-z]+$", re.IGNORECASE)

# Language pair direction hints
_ZH_LANGS = {"zh", "zh-cn", "zh-tw", "zh-hans", "zh-hant", "cmn"}
_EN_LANGS = {"en", "en-us", "en-gb", "en-au"}


def build_segment_anchor(body: Any, element: Any) -> str:
    """Build a relative XPath anchor from <body> root to *element*.

    Uses positional indexing: e.g. ".//p[4]", ".//h1[1]", ".//li[2]".

    The index is the element's position among its *siblings* of the same tag,
    which is exactly what ``body.xpath(".//p[4]")`` resolves back to. Counting
    descendants instead used to produce anchors such as ``.//p[5]`` for a
    document that only has four ``<p>`` children of ``<body>``, so write-back
    silently skipped those segments.
    """
    # Walk up from element to body, collecting positional info
    ancestors = []
    current = element
    while current is not None:
        ancestors.append(current)
        if current is body:
            break
        current = current.getparent()

    ancestors.reverse()
    ancestors = ancestors[1:]  # exclude body itself

    path_parts: list[str] = []
    for node in ancestors:
        tag = node.tag
        if not isinstance(tag, str):  # comments / processing instructions
            continue
        parent_node = node.getparent()
        if parent_node is None:
            idx = 1
        else:
            same_tag = [
                child
                for child in parent_node
                if isinstance(child.tag, str) and child.tag.lower() == tag.lower()
            ]
            idx = same_tag.index(node) + 1 if node in same_tag else 1
        path_parts.append(f"{tag.lower()}[{idx}]")

    if not path_parts:
        return "./*[1]"  # fallback

    return ".//" + "/".join(path_parts)


def extract_segments_from_doc(
    doc_path: str,
    body: Any,
    start_index: int = 0,
) -> list[Segment]:
    """Extract translatable segments from an lxml ``body`` element.

    Args:
        doc_path: Relative path of the document in the EPUB.
        body: lxml ``<body>`` element (from parsed XHTML).
        start_index: Global segment counter offset for stable IDs.

    Returns:
        List of Segment objects.
    """
    segments: list[Segment] = []
    counter = start_index

    for element in body.iter():
        tag = element.tag.lower()

        # Skip non-text and unwanted elements
        if tag in SKIP_TAGS:
            continue
        if tag not in TRANSLATABLE_TAGS:
            continue

        # Check for empty or whitespace-only text
        text = (element.text or "").strip()
        if not text:
            continue

        # Build anchor
        anchor = build_segment_anchor(body, element)

        # Generate stable ID
        counter += 1
        seg_id = f"{tag}-{counter:04d}"

        segments.append(
            Segment(
                id=seg_id,
                doc=doc_path,
                anchor=anchor,
                tag=tag,
                source_text=text,
            )
        )

    return segments, counter


def extract_segments_from_epub(
    epub_dir: Path,
    spine_items: list[str],
    manifest: dict[str, str],
    book_language: str = "zh",
) -> tuple[list[Segment], int]:
    """Extract segments from all spine XHTML documents.

    Returns (segments, total_doc_count).
    """
    all_segments: list[Segment] = []
    global_counter = 0
    doc_count = 0

    for href in spine_items:
        # Resolve: href might be relative or have extensions
        candidate = epub_dir / href
        if not candidate.exists():
            # Try with .xhtml extension
            if href.endswith(".xhtml"):
                candidate = epub_dir / href
            else:
                candidate = epub_dir / f"{href}.xhtml"
            if not candidate.exists():
                candidate = epub_dir / f"{href}.html"

        if not candidate.exists():
            logger.warning("Spine item not found, skipping: %s", href)
            continue

        doc_count += 1
        rel_path = str(candidate.relative_to(epub_dir))

        try:
            tree = html.parse(str(candidate))
            body = tree.find(".//body")
            if body is None:
                # Try root element
                body = tree.getroot()
        except Exception as e:
            logger.warning("Failed to parse %s: %s", rel_path, e)
            continue

        segs, global_counter = extract_segments_from_doc(rel_path, body, global_counter)
        all_segments.extend(segs)

    return all_segments, doc_count
