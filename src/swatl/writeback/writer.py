"""writeback package: in-place text replacement and EPUB re-zip."""

from __future__ import annotations

import logging
import os
import zipfile
from pathlib import Path
from typing import Any

from lxml import html

from swatl.ingest.segmenter import TAIL_MARKER, parse_xhtml, parse_xml
from swatl.models import Segment

logger = logging.getLogger(__name__)

# XHTML namespace commonly used
XHTML_NS = "http://www.w3.org/1999/xhtml"

# Documents that are XHTML and can therefore take xml:lang and a bilingual copy.
_XHTML_SUFFIXES = (".xhtml", ".html", ".htm")


def _is_xhtml(path: Path) -> bool:
    """Whether *path* is an XHTML content document."""
    return path.suffix.lower() in _XHTML_SUFFIXES


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

    When ``bilingual`` is True, each modified document is rewritten so that
    every source paragraph is followed by its translation, in place: the
    exported EPUB reads as a side-by-side edition (run the export without the
    flag for a monolingual one).

    Returns the path to the output EPUB.
    """
    output_path = Path(output_path) if output_path else epub_dir.parent / "translated.epub"

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
        # A bilingual edition reads as source + target, so the bilingual
        # documents replace the spine content at their original paths. Keeping
        # the original hrefs means the package manifest needs no changes — an
        # earlier version wrote them to a parallel "bilingual/" directory that
        # was never declared in the manifest, so readers could not reach them.
        # Non-XHTML documents (an NCX has labels, not prose) are translated
        # normally in either mode.
        if bilingual and _is_xhtml(full_path):
            _write_bilingual_doc(full_path, doc_segments, target_lang, epub_dir, doc_path)
        else:
            _write_document(full_path, doc_segments, target_lang)

    # Update language attributes on modified documents. Only XHTML documents
    # take xml:lang; running _set_lang over an NCX would parse it as HTML and
    # rewrite the table of contents as a web page.
    for doc_path in modified_docs:
        full_path = epub_dir / doc_path
        if full_path.exists() and _is_xhtml(full_path):
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


def _top_level_container(element, body):
    """The ancestor of *element* that is a direct child of *body*.

    A side-by-side edition duplicates whole blocks, not individual text nodes:
    replacing a paragraph with a pair of paragraphs discarded the inline
    elements inside it, and duplicating an inline element on its own produced
    invalid markup.
    """
    current = element
    while current is not None and current is not body:
        parent = current.getparent()
        if parent is None or parent is body:
            return current if current is not body else None
        current = parent
    return None


def _mark_as_source(element) -> None:
    """Tag a duplicated block so a stylesheet can hide or restyle it."""
    classes = (element.get("class") or "").split()
    if "swatl-source" not in classes:
        classes.append("swatl-source")
    element.set("class", " ".join(classes).strip())


def _write_bilingual_doc(
    source_path: Path,
    segments: list[Segment],
    target_lang: str,
    bilingual_dir: Path,
    doc_path: str,
) -> None:
    """Write one document as a side-by-side version of itself.

    The document is translated in place — so inline markup and its translations
    survive — and then, for every top-level block that changed, a copy of that
    block in the source language is inserted before it. The reader therefore
    sees each block twice: source, then translation.

    ``bilingual_dir`` and *doc_path* resolve to the document being replaced; the
    caller passes the EPUB root and the document's own relative path.
    """
    from copy import deepcopy

    # Parse once and copy: both halves then come from the same tree, and the
    # source text is put back from the segment records below. Deriving the
    # source half by re-reading the file was wrong as soon as the document had
    # been exported before — writeback rewrites documents in place, so a second
    # export read the first export's output and the "source" half was English.
    tree = parse_xhtml(source_path)
    root = tree.getroot()
    body = tree.find(".//body")
    if body is None:
        body = root

    source_tree = deepcopy(tree)
    source_root = source_tree.getroot()
    source_body = source_tree.find(".//body")
    if source_body is None:
        source_body = source_root

    _apply_translations(root, body, segments, target_lang)

    # Restore the original text in the copy: every segment records its source,
    # so the source half is correct even when the file on disk already held
    # translations (an export run twice, or a document reused from an earlier
    # run). Without this the guarantee that the halves differ was lost.
    source_segments = [seg.model_copy(update={"translated": seg.source_text}) for seg in segments]
    _apply_translations(source_root, source_body, source_segments, "")

    # Collect the blocks to duplicate first, then insert from the end so that
    # inserting one block cannot shift the positions of the ones still to come.
    targets: dict[int, Any] = {}
    for seg in segments:
        if not (seg.translated or "").strip() or seg.anchor.startswith("/"):
            continue  # <head> content has no block to duplicate
        try:
            translated_element, _is_tail = _resolve_element(root, body, seg)
            source_element, _is_tail = _resolve_element(source_root, source_body, seg)
        except Exception as e:  # a malformed anchor must not abort the export
            logger.warning("Bilingual copy skipped %s: %s", seg.id, e)
            continue
        if translated_element is None or source_element is None:
            continue

        translated_block = _top_level_container(translated_element, body)
        source_block = _top_level_container(source_element, source_body)
        if translated_block is None or source_block is None:
            continue

        try:
            position = list(body).index(translated_block)
        except ValueError:  # pragma: no cover - defensive
            continue
        # One entry per block: a paragraph, its inline children and its tails all
        # resolve to the same block.
        targets.setdefault(position, source_block)

    for position in sorted(targets, reverse=True):
        copy = deepcopy(targets[position])
        _mark_as_source(copy)
        body.insert(position, copy)

    out_path = bilingual_dir / doc_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Serialise the whole document so the original <head> (title, stylesheets)
    # survives, then set the language attributes on the copy.
    _serialize_document(tree, root, out_path)
    _set_lang(out_path, target_lang)


def _resolve_element(root, body, seg: Segment) -> tuple[Any, bool]:
    """Resolve a segment's anchor to the element (and node kind) it addresses."""
    anchor = seg.anchor
    is_tail = anchor.endswith(TAIL_MARKER)
    if is_tail:
        anchor = anchor[: -len(TAIL_MARKER)]

    # Absolute anchors (e.g. /html/head/title[1]) are resolved from the document
    # root; everything else from <body>.
    context = root if anchor.startswith("/") else body
    elements = context.xpath(anchor)
    if not elements:
        return None, is_tail

    # Anchors are unambiguous child steps, so this normally finds one element;
    # the source-text check stays as a safety net for anchors stored by older
    # versions (which used the ambiguous ".//p[1]").
    element = elements[0]
    if len(elements) > 1:
        source = seg.source_text.strip()
        attr = "tail" if is_tail else "text"
        element = next(
            (e for e in elements if (getattr(e, attr) or "").strip() == source),
            elements[0],
        )
    return element, is_tail


def _apply_translations(root, body, segments: list[Segment], target_lang: str) -> int:
    """Replace every segment's text node in place, preserving the markup.

    Only the addressed text node changes: nested ``<em>``, ``<a>`` and friends
    keep their own text and their own translations.
    """
    replaced = 0
    # Deepest anchors first, so an ancestor's replacement cannot invalidate a
    # descendant's anchor.
    for seg in sorted(segments, key=lambda s: s.anchor.count("/"), reverse=True):
        try:
            element, is_tail = _resolve_element(root, body, seg)
            if element is None:
                logger.warning("Anchor not found for segment %s: %s", seg.id, seg.anchor)
                continue
            _replace_text(element, seg.translated or "", target_lang, is_tail=is_tail)
            replaced += 1
        except Exception as e:
            logger.warning("Failed to write segment %s: %s", seg.id, e)
    return replaced


def _write_document(path: Path, segments: list[Segment], target_lang: str) -> None:
    """Replace text content in one document and persist the result.

    XHTML content documents go through the tolerant HTML parser; an NCX (or any
    other XML document) must not, because that parser drops namespaces and
    serialises the file back as HTML.
    """
    if _is_xhtml(path):
        tree = parse_xhtml(path)
        body = tree.find(".//body")
    else:
        tree = parse_xml(path)
        body = None
    root = tree.getroot()
    if body is None:
        body = root

    replaced = _apply_translations(root, body, segments, target_lang)

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
    # The segmenter stores a stripped source text and providers return stripped
    # output, so the whitespace that separated this text node from its
    # neighbours has to be restored: without it `<p>他说 <em>你好</em> 世界。</p>`
    # renders as "He saidhelloworld." instead of "He said hello world.".
    original = (element.tail if is_tail else element.text) or ""
    leading = original[: len(original) - len(original.lstrip())]
    trailing = original[len(original.rstrip()) :]
    replacement = f"{leading}{translated}{trailing}" if translated else original

    if is_tail:
        element.tail = replacement
    else:
        element.text = replacement
    if target_lang:
        # The Clark notation is required on a namespace-aware XML tree (an NCX),
        # where the literal name "xml:lang" is rejected as invalid; lxml
        # serialises this form as xml:lang on HTML trees as well.
        element.set("{http://www.w3.org/XML/1998/namespace}lang", target_lang)


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
