"""ingest package: EPUB reader and segment extractor."""

from .epub_reader import EpubInfo, extract_epub
from .segmenter import extract_segments_from_epub

__all__ = ["EpubInfo", "extract_epub", "extract_segments_from_epub"]
