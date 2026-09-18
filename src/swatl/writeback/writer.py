"""writeback package: in-place text replacement and EPUB re-zip."""

from __future__ import annotations

import logging
import os
import zipfile
from pathlib import Path

from lxml import html

from swatl.ingest.segmenter import TAIL_MARKER, parse_xhtml
from swatl.models import Segment

logger = logging.getLogger(__name__)

# XHTML namespace commonly used
XHTML_NS = "http://www.w3.org/1999/xhtml"


def writeback_segments(
    epub_dir: Path,
    segments: list[Segment],
    target_lang: str = "en",
    output_path: str | Path | None = None,
    bilingual: bool = False,
) -> Path:
    """Write translated segments back into the EPUB and create the output file.

    Uses in-place text-node replacement: only modified text content changes;
    all other elements (images, CSS, fonts, scripts) remain byte-identical.

    When ``bilingual`` is True, creates a parallel translated copy of each
    modified document in a ``bilingual/`` subdirectory within the EPUB,
    so readers can display source and target side by side.

    Returns the path to the output EPUB.
    """
    output_path = Path(output_path) if output_path else epub_dir.parent / "translated.epub"
    bilingual_output_dir: Path | None = None

    # Group segments by document
    by_doc: dict[str, list[Segment]] = {}
    for seg in segments:
        if seg.translated and seg.status in ("translated", "proofread", "edited"):
            by_doc.setdefault(seg.doc, []).append(seg)

    # Process each document
    modified_docs: set[str] = set()
    for doc_path, doc_segments in by_doc.items():
        full_path = epub_dir / doc_path
        if not full_path.exists():
            logger.warning("Document not found for write-back: %s", doc_path)
            continue

        modified_docs.add(doc_path)
        if bilingual:
            if bilingual_output_dir is None:
                bilingual_output_dir = epub_dir / "bilingual"
                bilingual_output_dir.mkdir(parents=True, exist_ok=True)
            _write_document(full_path, doc_segments, target_lang)
            # Create bilingual copy
            _write_bilingual_doc(
                full_path, doc_segments, target_lang, bilingual_output_dir, doc_path
            )
        else:
            _write_document(full_path, doc_segments, target_lang)

    # Update language attributes on modified documents
    for doc_path in modified_docs:
        full_path = epub_dir / doc_path
        if full_path.exists():
            _set_lang(full_path, target_lang)

    # Declare the target language in the package document so readers pick the
    # right dictionary, hyphenation and speech rules for the exported book.
    _set_opf_language(epub_dir, target_lang)

    # Re-zip the EPUB
    _create_output_epub(epub_dir, output_path)

    logger.info(
        "Write-back complete: %d documents modified, output: %s", len(modified_docs), output_path
    )
    return Path(output_path)


def _find_package_document(epub_dir: Path) -> Path | None:
    """Locate the OPF package document referenced by META-INF/container.xml."""
    from xml.etree import ElementTree as ET

    container = epub_dir / "META-INF" / "container.xml"
    if container.exists():
        try:
            root = ET.parse(container).getroot()
        except ET.ParseError:
            root = None
        if root is not None:
            for element in root.iter():
                if element.tag.rsplit("}", 1)[-1] == "rootfile":
                    full_path = element.get("full-path")
                    if full_path:
                        candidate = epub_dir / full_path
                        if candidate.exists():
                            return candidate

    opfs = sorted(epub_dir.glob("*.opf")) or sorted(epub_dir.rglob("*.opf"))
    return opfs[0] if opfs else None


def _set_opf_language(epub_dir: Path, target_lang: str) -> None:
    """Set ``<dc:language>`` in the OPF package document to *target_lang*."""
    from lxml import etree

    opf_path = _find_package_document(epub_dir)
    if opf_path is None:
        logger.warning("No OPF package document found; cannot update dc:language")
        return

    try:
        tree = etree.parse(str(opf_path))
    except etree.XMLSyntaxError as e:
        logger.warning("Could not parse %s: %s", opf_path, e)
        return

    root = tree.getroot()
    DC_NS = "http://purl.org/dc/elements/1.1/"
    languages = [el for el in root.iter() if el.tag.rsplit("}", 1)[-1] == "language"]
    if not languages:
        # dc:language missing entirely — create it inside <metadata>.
        metadata = next(
            (el for el in root if el.tag.rsplit("}", 1)[-1] == "metadata"),
            None,
        )
        if metadata is None:
            logger.warning("OPF has no <metadata> element; cannot set dc:language")
            return
        element = etree.SubElement(metadata, f"{{{DC_NS}}}language")
        element.text = target_lang
    else:
        for element in languages:
            element.text = target_lang

    tree.write(str(opf_path), encoding="UTF-8", xml_declaration=True)
    logger.debug("Set dc:language=%s in %s", target_lang, opf_path.name)


def _write_bilingual_doc(
    source_path: Path,
    segments: list[Segment],
    target_lang: str,
    bilingual_dir: Path,
    doc_path: str,
) -> None:
    """Create a bilingual copy of the document with translated paragraphs."""
    from lxml import etree, html

    tree = parse_xhtml(source_path)
    root = tree.getroot()
    body = root.find(".//body")
    if body is None:
        body = root

    for seg in segments:
        try:
            elements = body.xpath(seg.anchor)
            if not elements:
                continue

            element = elements[0]
            source_text = element.text or ""
            translated = seg.translated or ""

            # Create a wrapper div
            parent = element.getparent()
            if parent is None:
                parent = body

            wrapper = html.Element("div")
            wrapper.set("style", "margin-bottom:1.5em")
            wrapper.set("class", "swatl-bilingual")

            # Source paragraph
            source_p = html.Element("p")
            source_p.set("style", "color:#666; margin-bottom:0.2em; font-size:0.9em")
            source_p.set("class", "swatl-source")
            source_p.text = source_text

            # Translation paragraph
            trans_p = html.Element("p")
            trans_p.set("style", "margin-top:0.2em")
            trans_p.set("class", "swatl-target")
            trans_p.text = translated

            wrapper.append(source_p)
            wrapper.append(trans_p)

            # Insert wrapper before original, then remove original
            idx = list(parent).index(element) if element in list(parent) else len(parent)
            parent.insert(idx, wrapper)
            parent.remove(element)

        except Exception as e:
            logger.warning("Failed to write bilingual segment %s: %s", seg.id, e)

    # Write the modified HTML tree as XHTML for the EPUB
    out_path = bilingual_dir / doc_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Use html.tostring to serialize, then wrap with XML declaration
    xhtml_ns = "http://www.w3.org/1999/xhtml"
    body_html = tree.getroot().find(".//body")
    html_content = etree.tostring(
        body_html if body_html is not None else tree.getroot(),
        method="html",
        encoding="UTF-8",
        doctype='<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">',
    ).decode("utf-8")

    xhtml_header = f'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">\n<html xmlns="{xhtml_ns}" xml:lang="zh" lang="zh">\n<head>\n  <meta charset="UTF-8"/>\n</head>\n'
    xhtml_footer = "\n</body>\n</html>\n"

    with open(out_path, "wb") as f:
        f.write((xhtml_header + html_content + xhtml_footer).encode("utf-8"))


def _write_document(path: Path, segments: list[Segment], target_lang: str) -> None:
    """Replace text content in a single XHTML document and persist the result."""
    tree = parse_xhtml(path)
    root = tree.getroot()
    body = tree.find(".//body")
    if body is None:
        body = root

    # Sort segments by anchor depth to handle nested replacements properly
    # Process from deepest to shallowest to avoid anchor invalidation
    segments.sort(key=lambda s: s.anchor.count("/"), reverse=True)

    replaced = 0
    for seg in segments:
        try:
            anchor = seg.anchor
            is_tail = anchor.endswith(TAIL_MARKER)
            if is_tail:
                anchor = anchor[: -len(TAIL_MARKER)]

            # Absolute anchors (e.g. /html/head/title[1]) are resolved from the
            # document root; everything else from <body>.
            context = root if anchor.startswith("/") else body
            elements = context.xpath(anchor)
            if not elements:
                logger.warning("Anchor not found for segment %s: %s", seg.id, seg.anchor)
                continue

            # Prefer the match whose text is the segment's source; a relative
            # anchor like ".//p[1]" can also match a nested first paragraph.
            element = elements[0]
            if len(elements) > 1:
                source = seg.source_text.strip()
                attr = "tail" if is_tail else "text"
                element = next(
                    (e for e in elements if (getattr(e, attr) or "").strip() == source),
                    elements[0],
                )
            _replace_text(element, seg.translated or "", target_lang, is_tail=is_tail)
            replaced += 1

        except Exception as e:
            logger.warning("Failed to write segment %s: %s", seg.id, e)

    # This write is what actually puts the translation into the EPUB: without
    # it the modified in-memory tree is silently discarded.
    _serialize_document(tree, root, path)
    logger.debug("Wrote %d/%d segments into %s", replaced, len(segments), path.name)


def _serialize_document(tree, root, path: Path) -> None:
    """Write an lxml HTML tree back to disk as XHTML.

    lxml's ``ElementTree.write`` re-emits the XML declaration as a bogus
    ``<!--?xml ... ?-->`` comment (an artefact of the tolerant HTML parser),
    so the declaration, doctype and element tree are assembled by hand.
    """
    from lxml import etree

    declaration = b"<?xml version='1.0' encoding='UTF-8'?>\n"
    doctype = (tree.docinfo.doctype or "").strip()
    body = etree.tostring(root, encoding="utf-8", xml_declaration=False)

    with open(path, "wb") as f:
        f.write(declaration)
        if doctype:
            f.write(doctype.encode("utf-8") + b"\n")
        f.write(body)


def _replace_text(
    element: html.HtmlElement, translated: str, target_lang: str, is_tail: bool = False
) -> None:
    """Replace an element's own text or tail, preserving nested markup.

    A segment's ``source_text`` is a single text node of the element (its own
    text, or the text that follows it inside the parent), so the replacement
    must only touch that node. Replacing the whole element (as an earlier
    implementation did) discarded nested ``<em>``, ``<strong>`` or ``<a>``
    children.
    """
    if is_tail:
        element.tail = translated
    else:
        element.text = translated
    if target_lang:
        element.set("xml:lang", target_lang)


def _set_lang(path: Path, target_lang: str) -> None:
    """Set xml:lang and lang attributes on an XHTML document."""
    tree = parse_xhtml(path)
    root = tree.getroot()

    # Set on html element
    root.set("xml:lang", target_lang)
    root.set("lang", target_lang)

    # Also set on body if present
    body = tree.find(".//body")
    if body is not None:
        body.set("xml:lang", target_lang)
        body.set("lang", target_lang)

    # Update content-type in head if present
    head = tree.find(".//head")
    if head is not None:
        for meta in head.findall(".//meta"):
            content_type = meta.get("http-equiv", "").lower()
            if content_type == "content-type":
                import re

                content = meta.get("content", "")
                new_content = re.sub(
                    r"charset=[\w-]+",
                    "charset=UTF-8",
                    content,
                )
                meta.set("content", new_content)

    # Write back preserving XML declaration
    _serialize_document(tree, root, path)


def _create_output_epub(source_dir: Path, output_path: Path) -> None:
    """Create the output EPUB by re-zipping from the temp directory.

    The ``mimetype`` entry is written first and stored uncompressed, as the
    EPUB specification (and Apple Books in particular) requires. It is
    synthesised when the source EPUB did not ship one.
    """
    output_path = Path(output_path)
    source_dir = Path(source_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        output_resolved = output_path.resolve()
    except OSError:  # pragma: no cover - defensive
        output_resolved = output_path

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        mimetype = source_dir / "mimetype"
        if mimetype.is_file():
            zf.write(mimetype, "mimetype", compress_type=zipfile.ZIP_STORED)
        else:
            zf.writestr(
                zipfile.ZipInfo("mimetype"),
                b"application/epub+zip",
                compress_type=zipfile.ZIP_STORED,
            )

        # os.walk, not Path.walk: the latter is Python 3.12+ and this package
        # supports 3.11.
        for root, _dirs, files in os.walk(source_dir):
            for filename in sorted(files):
                file_path = Path(root) / filename
                arcname = str(file_path.relative_to(source_dir))
                if arcname == "mimetype":
                    continue
                if file_path.resolve() == output_resolved:
                    continue
                zf.write(file_path, arcname)
