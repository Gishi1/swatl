"""XHTML segmenter: walk documents, extract translatable text segments with anchors."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote

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
    # The document root; only visited when a document has no <body>.
    "html",
}

# Regex for building XPath-like anchors
_TAG_RE = re.compile(r"^[a-z]+$", re.IGNORECASE)

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


def parse_xml(path: Path):
    """Parse a well-formed XML document (an EPUB2 NCX) without losing namespaces.

    Content documents go through the tolerant HTML parser, which also strips
    namespaces. Feeding it an NCX would rewrite the table of contents as HTML,
    so XML documents get a real XML parser instead. Recovery is enabled because
    a malformed book should still translate, and entity resolution and network
    access are off because the input is untrusted.
    """
    from lxml import etree

    parser = etree.XMLParser(recover=True, resolve_entities=False, no_network=True)
    return etree.parse(str(path), parser)


def _local_name(tag: Any) -> str:
    """Tag name without its ``{namespace}`` prefix, keeping the document's case.

    XPath's ``local-name()`` is case-sensitive and an NCX uses camelCase names
    (``navPoint``, ``docTitle``), so an anchor must carry the original casing to
    resolve. Callers that compare names do so case-insensitively themselves.
    """
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def build_xml_anchor(root: Any, element: Any) -> str:
    """Build a namespace-agnostic XPath from *root* to *element*.

    An NCX declares a default namespace, so an unprefixed path such as
    ``.//navPoint`` matches nothing. Each step is written as
    ``*[local-name()='navPoint'][2]`` — the index is the position among siblings
    with the same local name — which resolves against the original tree during
    write-back without depending on the namespace prefix a producer chose.
    """
    steps: list[str] = []
    current = element
    while current is not None and current is not root:
        name = _local_name(current.tag)
        parent = current.getparent()
        if name:
            siblings = [
                child
                for child in (parent if parent is not None else [])
                if _local_name(child.tag) == name
            ]
            index = siblings.index(current) + 1 if current in siblings else 1
            steps.append(f"*[local-name()='{name}'][{index}]")
        current = parent

    steps.reverse()
    return "./" + "/".join(steps) if steps else "."


def extract_segments_from_ncx(
    doc_path: str,
    root: Any,
    start_index: int = 0,
) -> tuple[list[Segment], int]:
    """Extract the table-of-contents labels from an EPUB2 NCX document.

    Both the ``<docTitle>`` and every ``<navPoint>`` label are shown by reading
    systems, so leaving them in the source language produces a book whose
    contents list is in Chinese while the text is in English.
    """
    segments: list[Segment] = []
    counter = start_index

    for element in root.iter():
        if _local_name(element.tag).lower() != "text":
            continue
        parent = element.getparent()
        if parent is None or _local_name(parent.tag).lower() not in ("navlabel", "doctitle"):
            continue
        text = (element.text or "").strip()
        if not text:
            continue
        counter += 1
        segments.append(
            Segment(
                id=f"ncx-{counter:04d}",
                doc=doc_path,
                anchor=build_xml_anchor(root, element),
                tag="navLabel" if _local_name(parent.tag).lower() == "navlabel" else "docTitle",
                source_text=text,
                part="text",
            )
        )

    return segments, counter


# Language pair direction hints
_ZH_LANGS = {"zh", "zh-cn", "zh-tw", "zh-hans", "zh-hant", "cmn"}
_EN_LANGS = {"en", "en-us", "en-gb", "en-au"}


def build_segment_anchor(body: Any, element: Any) -> str:
    """Build an XPath anchor to *element*.

    Elements inside ``<body>`` get a relative anchor such as ``./p[4]``
    (resolved with ``body.xpath(...)``). Elements outside it — the document
    ``<title>``, for instance — get an absolute anchor such as
    ``/html/head/title[1]`` (resolved with ``root.xpath(...)``).

    Every step is a *child* step (``./blockquote[1]/p[1]``), so the anchor
    resolves to exactly one element. The index is the element's position among
    its siblings of the same tag, which is what XPath's ``p[4]`` means.

    Two earlier mistakes are worth recording. Counting descendants instead of
    siblings produced anchors such as ``.//p[5]`` for a document with only four
    ``<p>`` children of ``<body>``, so write-back silently skipped those
    segments. Using ``.//`` then made anchors ambiguous: ``.//p[1]`` matches the
    first paragraph of *every* parent, so a nested paragraph that happened to
    carry the same text could be overwritten with a body-level translation
    while the intended paragraph kept its source language.
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
        prefix = "./"
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


def _in_skipped_subtree(element: Any, body: Any) -> bool:
    """Whether *element* sits inside an element whose content is not translated.

    ``<script>``, ``<style>`` and ``<svg>`` subtrees are copied through
    untouched; their descendants must not be segmented even though some of them
    (``<text>`` inside ``<svg>``, for instance) have translatable-looking tags.

    ``<body>`` is in :data:`SKIP_TAGS` only so that its *own* text node is not
    segmented, so it is excluded here: callers may legitimately pass the
    document root instead of ``<body>``, and treating the real ``<body>`` as a
    skipped subtree would silently disable segmentation for the whole document.
    """
    current = element.getparent()
    while current is not None and current is not body:
        tag = current.tag
        if isinstance(tag, str) and tag.lower() in SKIP_TAGS and tag.lower() != "body":
            return True
        current = current.getparent()
    return False


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

        # Elements inside a skipped subtree (<script>, <style>, <svg>) carry no
        # translatable text; their own text is not in TRANSLATABLE_TAGS, and
        # their tails are inside a subtree that must stay untouched.
        if element is body or _in_skipped_subtree(element, body):
            continue

        anchor = build_segment_anchor(body, element)

        # The element's own text node. Any element that is not explicitly
        # skipped can hold text: gating this on a list of known tags silently
        # dropped whole paragraphs in bare <div>, <section> and <figure>
        # wrappers, which are common in EPUBs that do not wrap every block in a
        # <p>.
        if tag not in SKIP_TAGS:
            text = (element.text or "").strip()
            if text:
                _emit(element, text, anchor, tag, "text")

        # Text sitting after an element is a separate text node with no
        # addressable parent of its own (`<p>第一行<br/>第二行</p>`: "第二行"
        # belongs to neither p.text nor br.text), so it needs its own anchor.
        # This runs for every element, not just inline ones: restricting it to
        # INLINE_TAGS silently dropped the text after <br/>, <img/> and <ruby/>,
        # which stayed in the source language inside an otherwise translated
        # paragraph.
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
    """Resolve a manifest/spine href to an existing file inside the EPUB.

    Hrefs are URIs: they may be percent-encoded (``%20`` for a space) and may
    carry a fragment (``ch01.xhtml#section``). Comparing them with the
    filesystem path directly meant such a document resolved to nothing and was
    skipped, leaving that chapter in the source language.
    """
    href = href.split("#", 1)[0]
    if not href:
        return None
    candidates = [href]
    decoded = unquote(href)
    if decoded != href:
        candidates.append(decoded)

    for raw in candidates:
        candidate = epub_dir / raw
        if candidate.exists():
            return candidate

    for raw in candidates:
        if not raw.lower().endswith((".xhtml", ".html", ".htm")):
            for suffix in (".xhtml", ".html"):
                candidate = epub_dir / f"{raw}{suffix}"
                if candidate.exists():
                    return candidate
    return None


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

        # An NCX is XML, not XHTML: it has no <body>, and the HTML parser would
        # both drop its namespace and rewrite the file as HTML on export.
        if candidate.suffix.lower() == ".ncx":
            try:
                ncx_root = parse_xml(candidate).getroot()
            except Exception as e:
                logger.warning("Failed to parse NCX %s: %s", rel_path, e)
                continue
            segs, global_counter = extract_segments_from_ncx(rel_path, ncx_root, global_counter)
            all_segments.extend(segs)
            continue

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
