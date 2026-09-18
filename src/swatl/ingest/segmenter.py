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
    "caption",
    "a",  # link text, including EPUB3 navigation entries
    # Common inline elements: their text belongs to the surrounding paragraph.
    "span",
    "b",
    "i",
    "u",
    "s",
    "small",
    "q",
    "sub",
    "sup",
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

# Inline elements whose following text node ("tail") is part of the same
# paragraph and must therefore be translated as its own segment. Every entry
# must also be in TRANSLATABLE_TAGS: translating a tail while leaving the
# inline element itself in the source language would produce mixed output.
INLINE_TAGS = {
    "a",
    "abbr",
    "b",
    "cite",
    "code",
    "em",
    "i",
    "q",
    "s",
    "small",
    "span",
    "strong",
    "sub",
    "sup",
    "u",
}

assert INLINE_TAGS <= TRANSLATABLE_TAGS, INLINE_TAGS - TRANSLATABLE_TAGS

# Suffix appended to an anchor that addresses an element's tail text node.
TAIL_MARKER = "#tail"

_ENCODING_DECL_RE = re.compile(rb"""encoding=["']([\w-]+)["']""", re.IGNORECASE)
_CHARSET_RE = re.compile(rb"""charset=["']?([\w-]+)""", re.IGNORECASE)


def detect_document_encoding(path: Path) -> str | None:
    """Return the encoding declared in a content document, if any."""
    try:
        head = Path(path).read_bytes()[:4096]
    except OSError:  # pragma: no cover - defensive
        return None
    match = _ENCODING_DECL_RE.search(head) or _CHARSET_RE.search(head)
    if not match:
        return None
    try:
        return match.group(1).decode("ascii")
    except UnicodeDecodeError:  # pragma: no cover - defensive
        return None


def parse_xhtml(path: Path):
    """Parse an XHTML content document into an lxml tree.

    EPUB requires content documents to be UTF-8 or UTF-16, but libxml2's HTML
    parser falls back to Latin-1 when no encoding is declared, silently
    mangling CJK text. Honour the document's declaration and otherwise assume
    UTF-8.
    """
    encoding = detect_document_encoding(path) or "utf-8"
    return html.parse(str(path), parser=html.HTMLParser(encoding=encoding))


# Language pair direction hints
_ZH_LANGS = {"zh", "zh-cn", "zh-tw", "zh-hans", "zh-hant", "cmn"}
_EN_LANGS = {"en", "en-us", "en-gb", "en-au"}


def build_segment_anchor(body: Any, element: Any) -> str:
    """Build an XPath anchor to *element*.

    Elements inside ``<body>`` get a relative anchor such as ``.//p[4]``
    (resolved with ``body.xpath(...)``). Elements outside it — the document
    ``<title>``, for instance — get an absolute anchor such as
    ``/html/head/title[1]`` (resolved with ``root.xpath(...)``).

    The index is the element's position among its *siblings* of the same tag,
    which is exactly what ``body.xpath(".//p[4]")`` resolves back to. Counting
    descendants instead used to produce anchors such as ``.//p[5]`` for a
    document that only has four ``<p>`` children of ``<body>``, so write-back
    silently skipped those segments.
    """
    # Walk up until we reach <body> (relative anchor) or the document root.
    ancestors = []
    current = element
    inside_body = False
    while current is not None:
        ancestors.append(current)
        if current is body:
            inside_body = True
            break
        current = current.getparent()

    ancestors.reverse()
    if inside_body:
        ancestors = ancestors[1:]  # exclude body itself
        prefix = ".//"
    else:
        prefix = "/"

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

    return prefix + "/".join(path_parts)


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

    def _emit(element, text: str, anchor: str, tag: str, part: str) -> None:
        nonlocal counter
        counter += 1
        segments.append(
            Segment(
                id=f"{tag}-{counter:04d}",
                doc=doc_path,
                anchor=anchor,
                tag=tag,
                source_text=text,
                part=part,
            )
        )

    for element in body.iter():
        if not isinstance(element.tag, str):
            continue
        tag = element.tag.lower()

        # Skip non-text and unwanted elements
        if tag in SKIP_TAGS:
            continue
        if tag not in TRANSLATABLE_TAGS:
            continue

        anchor = build_segment_anchor(body, element)

        # The element's own text node.
        text = (element.text or "").strip()
        if text:
            _emit(element, text, anchor, tag, "text")

        # Text sitting after an inline element is a separate text node with no
        # addressable parent of its own; without this the tail would stay in
        # the source language inside an otherwise translated paragraph.
        if tag in INLINE_TAGS:
            tail = (element.tail or "").strip()
            if tail:
                _emit(element, tail, anchor + TAIL_MARKER, tag, "tail")

    # Document <title> lives outside <body>; translate it too so reader tabs
    # and chapter lists are not left in the source language.
    root = body.getroottree().getroot() if hasattr(body, "getroottree") else None
    if root is not None and root is not body:
        for element in root.iter():
            if not isinstance(element.tag, str) or element.tag.lower() != "title":
                continue
            text = (element.text or "").strip()
            if not text:
                continue
            _emit(element, text, build_segment_anchor(body, element), "title", "text")

    return segments, counter


def _resolve_doc(epub_dir: Path, href: str) -> Path | None:
    """Resolve a manifest/spine href to an existing file inside the EPUB."""
    candidate = epub_dir / href
    if candidate.exists():
        return candidate
    if not href.endswith(".xhtml"):
        candidate = epub_dir / f"{href}.xhtml"
        if candidate.exists():
            return candidate
    candidate = epub_dir / f"{href}.html"
    return candidate if candidate.exists() else None


def extract_segments_from_epub(
    epub_dir: Path,
    spine_items: list[str],
    manifest: dict[str, str],
    book_language: str = "zh",
    extra_docs: list[str] | None = None,
) -> tuple[list[Segment], int]:
    """Extract segments from all spine XHTML documents.

    ``extra_docs`` are additional documents segmented after the spine — the
    EPUB3 navigation document, for example, so the reader's table of contents
    is translated too. They are processed last so spine segment ids stay
    stable regardless of whether a nav document exists.

    Returns (segments, total_doc_count).
    """
    all_segments: list[Segment] = []
    global_counter = 0
    doc_count = 0

    ordered_docs = list(spine_items)
    for href in extra_docs or []:
        if href not in ordered_docs:
            ordered_docs.append(href)

    for href in ordered_docs:
        candidate = _resolve_doc(epub_dir, href)
        if candidate is None:
            if href in spine_items:
                logger.warning("Spine item not found, skipping: %s", href)
            else:
                logger.warning("Document not found, skipping: %s", href)
            continue

        doc_count += 1
        rel_path = str(candidate.relative_to(epub_dir))

        try:
            tree = parse_xhtml(candidate)
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
