"""EPUB reader: unzip, parse content.opf, determine spine order, extract metadata."""

from __future__ import annotations

import logging
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

NS = {
    "container": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf2": "http://www.idpf.org/2007/opf",
    "opf3": "http://www.idpf.org/2017/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "spine": "http://www.idpf.org/2007/opf",
}

# Namespace prefix for opf3 (may use href attributes without prefix)
OPF3_NS = "http://www.idpf.org/2017/opf"
OPF2_NS = "http://www.idpf.org/2007/opf"
DC_NS = "http://purl.org/dc/elements/1.1/"


class EpubInfo:
    """Structured metadata extracted from an EPUB's OPF."""

    title: str = ""
    author: str | None = None
    language: str = ""
    epub_version: str = ""
    spine_items: list[str]  # list of href paths in spine order
    mime_types: dict[str, str]  # path → media_type from manifest
    nav_items: list[str]  # EPUB3 navigation document(s), not part of the spine
    ncx_items: list[str]  # EPUB2 NCX table(s) of contents, also outside the spine
    # XHTML documents in the manifest that are not in the spine: navigation,
    # cover and supplementary pages. Readers can reach them through links, so
    # they are translated too.
    other_content_items: list[str]

    def __init__(
        self,
        title: str,
        author: str | None,
        language: str,
        epub_version: str,
        spine_items: list[str],
        mime_types: dict[str, str],
        nav_items: list[str] | None = None,
        ncx_items: list[str] | None = None,
        other_content_items: list[str] | None = None,
    ):
        self.title = title
        self.author = author
        self.language = language
        self.epub_version = epub_version
        self.spine_items = spine_items
        self.mime_types = mime_types
        self.nav_items = nav_items or []
        self.ncx_items = ncx_items or []
        self.other_content_items = other_content_items or []


def extract_epub(
    epub_path: str | Path, output_dir: str | Path | None = None
) -> tuple[EpubInfo, Path]:
    """Unzip an EPUB file and return (info, extracted_dir).

    Raises ValueError if the EPUB is malformed.
    """
    epub_path = Path(epub_path)
    if not epub_path.exists():
        raise FileNotFoundError(f"EPUB not found: {epub_path}")

    if not zipfile.is_zipfile(epub_path):
        raise ValueError(f"Not a valid ZIP/EPUB: {epub_path}")

    target = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(prefix="swatl-"))
    target.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(epub_path, "r") as zf:
        zf.extractall(target)

    info = _parse_opf(target)
    return info, target


def _find_file(directory: Path, pattern: str) -> Path | None:
    """Find a file matching *pattern* in *directory* or its subdirs."""
    for candidate in directory.rglob(pattern):
        if candidate.is_file():
            return candidate
    return None


def _parse_opf(extract_dir: Path) -> EpubInfo:
    """Parse META-INF/container.xml → content.opf → spine + metadata."""
    # Step 1: Find container.xml
    # The specification fixes this location; only fall back to a search when it
    # is missing, so a stray nested container.xml cannot shadow the real one.
    container_path = extract_dir / "META-INF" / "container.xml"
    if not container_path.is_file():
        container_path = _find_file(extract_dir, "container.xml")
    if not container_path:
        raise ValueError("No META-INF/container.xml found in EPUB")

    container_root = ET.parse(container_path).getroot()
    # container.xml may or may not have a namespace; handle both
    ns = ""
    if container_root.tag.startswith("{"):
        ns = container_root.tag.split("}")[0] + "}"
    # `ns` already carries its braces, so the path is ".//{uri}rootfile" — the
    # previous f-string added a second pair and never matched anything.
    root_ref = container_root.find(f".//{ns}rootfile" if ns else ".//rootfile")

    if root_ref is None:
        # Fallback: find by local-name via iteration
        for child in container_root.iter():
            local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if local == "rootfile":
                root_ref = child
                break

    if root_ref is None:
        raise ValueError("No <rootfile> element in container.xml")

    opf_relpath = root_ref.get("full-path")
    if not opf_relpath:
        raise ValueError("No full-path attribute on <rootfile>")

    opf_path = extract_dir / opf_relpath
    if not opf_path.exists():
        raise ValueError(f"OPF file not found: {opf_path}")

    return _parse_opf_file(opf_path)


def _parse_opf_file(opf_path: Path) -> EpubInfo:
    """Parse a content.opf file to extract spine, metadata, and manifest."""
    tree = ET.parse(opf_path)
    root = tree.getroot()

    # Detect namespace: could be opf2 or opf3
    ns_match = ""
    tag = root.tag
    if tag.startswith("{"):
        ns_match = tag.split("}")[0] + "}"
    else:
        ns_match = ""  # no namespace (opf2)

    dc_ns = DC_NS  # fixed namespace for Dublin Core

    def _q(name: str) -> str:
        if ns_match:
            return f"{ns_match}{name}"
        return name

    # ── Metadata ──
    title = ""
    author = None
    language = ""

    meta_elem = root.find(_q("metadata"))
    if meta_elem is None:
        meta_elem = root  # some EPUBs put metadata at root

    for child in meta_elem:
        child_tag = child.tag
        local_name = child_tag.split("}")[-1] if "}" in child_tag else child_tag

        if local_name == "title":
            ns = child_ns(child_tag)
            if ns == dc_ns or not ns:
                title = child.text or ""
        elif local_name == "creator":
            ns = child_ns(child_tag)
            if ns == dc_ns or not ns:
                author = child.text
        elif local_name == "language":
            ns = child_ns(child_tag)
            if ns == dc_ns or not ns:
                language = (child.text or "").strip()

    # ── Manifest (media types) ──
    manifest: dict[str, str] = {}
    nav_items: list[str] = []
    ncx_items: list[str] = []
    content_items: list[str] = []
    manifest_elem = root.find(_q("manifest"))
    if manifest_elem is not None:
        for item in manifest_elem.findall(_q("item")):
            href = item.get("href", "")
            media_type = item.get("media-type", "")
            item_id = item.get("id", "")
            if href:
                manifest[href] = media_type
                if media_type:
                    manifest[f"id:{item_id}"] = media_type
                properties = item.get("properties", "") or ""
                if "nav" in properties.split():
                    nav_items.append(href)
                # EPUB2 table of contents. Readers show these labels, so they
                # need translating just as much as an EPUB3 nav document.
                if "dtbncx" in media_type or href.lower().endswith(".ncx"):
                    ncx_items.append(href)
                elif "xhtml" in media_type or href.lower().endswith((".xhtml", ".html", ".htm")):
                    content_items.append(href)

    # ── Spine ──
    spine_items: list[str] = []
    spine_elem = root.find(_q("spine"))
    if spine_elem is not None:
        for ref in spine_elem.findall(_q("itemref")):
            href = ref.get("href", "")
            if href:
                spine_items.append(href)
            else:
                # Resolve by idref
                idref = ref.get("idref", "")
                # Find the manifest item with this id
                for item in manifest_elem.findall(_q("item")) if manifest_elem is not None else []:
                    if item.get("id") == idref:
                        spine_items.append(item.get("href", ""))
                        break

    if not spine_items:
        # Fallback for a book whose <spine>/<itemref> cannot be resolved: use
        # every content document in the manifest, in manifest order. The old
        # version read `f.tag.endswith("href")`, but href is an *attribute* of
        # <item>, so it could never match and the book silently produced zero
        # segments instead.
        seen: set[str] = set()
        for item in manifest_elem.findall(_q("item")) if manifest_elem is not None else []:
            href = item.get("href", "")
            if not href or href in seen:
                continue
            media_type = item.get("media-type", "")
            if media_type.endswith("xhtml+xml") or href.endswith((".xhtml", ".html", ".htm")):
                seen.add(href)
                spine_items.append(href)

    epub_version = _detect_version(root)

    # Anything the spine already covers is segmented there; everything else is
    # handled as an extra document. A hybrid EPUB2/3 book, for instance, ships a
    # nav.xhtml that is neither in the spine nor marked properties="nav" — its
    # labels are what a reader shows in the contents list.
    nav_items = [href for href in nav_items if href not in spine_items]
    ncx_items = [href for href in ncx_items if href not in spine_items]
    other_content_items = [href for href in content_items if href not in spine_items]

    return EpubInfo(
        title=title,
        author=author,
        language=language or "zh",
        epub_version=epub_version,
        spine_items=spine_items,
        mime_types=manifest,
        nav_items=nav_items,
        ncx_items=ncx_items,
        other_content_items=other_content_items,
    )


def _detect_version(root) -> str:
    """Detect the EPUB version from the OPF ``version`` attribute or namespace.

    ``root.get("version")`` alone is truthy for *any* value, so every EPUB 2
    book was reported as EPUB 3.0.
    """
    version = (root.get("version") or "").strip()
    if version.startswith("3"):
        return "EPUB 3.0"
    if version.startswith("2"):
        return "EPUB 2.0"
    tag = root.tag
    if "2017" in tag:  # the EPUB 3 package namespace
        return "EPUB 3.0"
    return "EPUB 2.0" if version else "unknown"


def child_ns(tag: str) -> str:
    """Extract namespace from a tag like {http://...}localname."""
    if tag.startswith("{"):
        idx = tag.index("}")
        return tag[1:idx]
    return ""
