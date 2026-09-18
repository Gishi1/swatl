"""Pydantic data models for swatl segments, runs, and configuration."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SegmentStatus(StrEnum):
    PENDING = "pending"
    TRANSLATING = "translating"
    TRANSLATED = "translated"
    PROOFREAD = "proofread"
    EDITED = "edited"
    SKIPPED = "skipped"
    FAILED = "failed"


class Segment(BaseModel):
    """A translatable text unit extracted from an EPUB document."""

    # validate_assignment keeps ``status`` a real SegmentStatus even when a
    # provider assigns a plain string, which otherwise trips Pydantic's
    # serializer warning on every model_dump().
    model_config = ConfigDict(validate_assignment=True)

    id: str  # e.g. "h1-007", "p-0041"
    doc: str  # relative path in EPUB, e.g. "text/ch01.xhtml"
    anchor: str  # XPath selector, e.g. ".//p[4]" (may end with "#tail")
    tag: str  # "p", "h1", "blockquote"
    source_text: str
    translated: str | None = None
    status: SegmentStatus = SegmentStatus.PENDING
    part: str = "text"  # "text" (element's own text) or "tail" (text after it)
    context: str | None = None  # previous N segments for context
    tokens_in: int | None = None
    tokens_out: int | None = None
    provider: str | None = None
    glossary_hits: list[str] = Field(default_factory=list)


class RunMetadata(BaseModel):
    """Global run state saved to run.json."""

    book_title: str
    book_author: str | None = None
    book_lang: str
    book_version: str = ""
    pair: list[str] = Field(default_factory=lambda: ["zh", "en"])
    provider: str = ""
    epub_path: str = ""  # path to source EPUB for export
    state_dir: str = ""  # path to source EPUB extraction dir
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    total_segments: int = 0
    stages_completed: list[str] = Field(default_factory=list)
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    estimated_cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunMetadata:
        return cls(**data)


class GlossaryEntry(BaseModel):
    """A single glossary term: source term → target term."""

    source: str
    target: str
    domain: str = ""


class Glossary(BaseModel):
    """A glossary with metadata and term entries."""

    name: str = ""
    pair: list[str] = Field(default_factory=lambda: ["zh", "en"])

    entries: list[GlossaryEntry] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Glossary:
        return cls(**data)


class ProviderConfig(BaseModel):
    """Configuration for a single LLM provider."""

    type: str  # "openai-compatible", "anthropic"
    base_url: str = ""
    model: str = ""
    api_key_env: str = ""  # environment variable name for the API key
    # How the provider is prompted:
    #   "json"  — batch segments into one request, ask for a JSON id→translation map
    #   "plain" — one segment per request, instruction style, raw text back.
    #             Required by dedicated machine-translation models such as
    #             Tencent Hy-MT2, which do not follow JSON-batch instructions.
    mode: str = "json"
    # Instruction template for "plain" mode. {target_language} is substituted.
    instruction: str | None = None
    # Sequences that end a generation (many local MT models emit control tokens).
    stop: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)
