"""OpenAI-compatible provider adapter."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import httpx

from swatl.models import Glossary, Segment, SegmentStatus
from swatl.providers.base import Provider

logger = logging.getLogger(__name__)

# How many segments to send in a single chat completion request.
TRANSLATE_BATCH_SIZE = 10

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Best-effort extraction of a single JSON object from an LLM response.

    Handles markdown fences, leading prose, and nested braces inside strings.
    Returns ``None`` when nothing parseable is found.
    """
    if not text:
        return None
    cleaned = text.strip()
    fence = _FENCE_RE.search(cleaned)
    if fence:
        cleaned = fence.group(1).strip()

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(cleaned[start : i + 1])
                except json.JSONDecodeError:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


# Instruction used by "plain" mode unless the provider config overrides it.
DEFAULT_PLAIN_INSTRUCTION = (
    "Translate the following text into {target_language}. "
    "Output only the translation, without any explanation:"
)

# Human-readable language names for instruction-style prompts.
TARGET_LANGUAGE_NAMES = {
    "en": "English",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "ru": "Russian",
    "pt": "Portuguese",
    "it": "Italian",
}

_SEGMENT_WRAPPER_RE = re.compile(
    r"""^\s*<segment\b[^>]*>\s*(?P<body>.*?)\s*</segment>\s*$""", re.DOTALL | re.IGNORECASE
)
_SEGMENT_OPEN_RE = re.compile(r"^\s*<segment\b[^>]*>\s*", re.IGNORECASE)
_SEGMENT_CLOSE_RE = re.compile(r"\s*</segment>\s*$", re.IGNORECASE)
_FENCE_RE_FULL = re.compile(r"^\s*```[a-zA-Z]*\s*(?P<body>.*?)\s*```\s*$", re.DOTALL)
# Model control tokens that leak into the text on local runtimes, e.g.
# "<eos:6124c78e>" or "<|hy_Assistant|>". Deliberately narrow: a plain tag such
# as "</em>" is real markup and must survive.
_CONTROL_TOKEN_RE = re.compile(
    r"<eos:[0-9a-fA-F]+>|<[\|\uff5c][^>]{0,40}[\|\uff5c]>",
)


def _glossary_block(glossary: Glossary | None, source_text: str) -> str:
    """Terminology instructions for the terms present in *source_text*.

    MT models follow a short terminology list well, and it is the only way to
    pin a name that has several defensible translations (红岸基地 could be
    "Red Coast Base", "Red Bank Base" or "Red Shore Base").
    """
    if not glossary or not glossary.entries:
        return ""
    relevant = [e for e in glossary.entries if e.source and e.source in source_text]
    if not relevant:
        return ""
    lines = ["Glossary (use these exact translations):"]
    lines += [f"- {e.source} -> {e.target}" for e in relevant]
    return "\n".join(lines)


def _clean_translation(text: str) -> str:
    """Strip prompt scaffolding a model may have echoed into its answer.

    Real gateways occasionally return ``<segment id="p-0002">…</segment>`` or a
    fenced code block instead of the bare translation, especially when the
    prompt delimits segments with XML tags.
    """
    cleaned = text.strip()

    # Control tokens first: a trailing "<eos:...>" would otherwise hide the
    # closing tag from the wrapper check below.
    cleaned = _CONTROL_TOKEN_RE.sub("", cleaned).strip()

    wrapper = _SEGMENT_WRAPPER_RE.match(cleaned)
    if wrapper:
        cleaned = wrapper.group("body").strip()
    else:
        cleaned = _SEGMENT_OPEN_RE.sub("", cleaned)
        cleaned = _SEGMENT_CLOSE_RE.sub("", cleaned)

    fence = _FENCE_RE_FULL.match(cleaned)
    if fence:
        cleaned = fence.group("body").strip()

    return cleaned.strip()


def _collect_sse_content(body: str) -> str:
    """Assemble assistant text from an OpenAI-style SSE stream body.

    Used when a gateway streams even though ``stream: false`` was requested.
    Reasoning deltas are ignored; only ``delta.content`` is concatenated.
    """
    parts: list[str] = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:") :].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            chunk = json.loads(payload)
        except json.JSONDecodeError:
            continue
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            piece = delta.get("content")
            if piece:
                parts.append(piece)
            if not delta and choice.get("message"):
                message_content = choice["message"].get("content")
                if message_content:
                    parts.append(message_content)
    return "".join(parts)


def parse_chat_completion(response) -> tuple[str, dict[str, Any]]:
    """Extract (content, usage) from a chat-completions response.

    Handles both a normal JSON body and the SSE stream some gateways return
    even when ``stream: false`` was requested.
    """
    if "text/event-stream" in response.headers.get("content-type", ""):
        return _collect_sse_content(response.text), {}

    data = response.json()
    choices = data.get("choices") or []
    content = choices[0].get("message", {}).get("content", "") if choices else ""
    usage = data.get("usage") or {}
    return content, usage


class OpenAICompatible(Provider):
    """Provider that speaks the OpenAI chat completions API.

    Covers: OpenAI, DeepSeek, Ollama, vLLM, DashScope/Qwen, LM Studio,
    Omniroute and other OpenAI-compatible gateways.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        extra: dict[str, Any] | None = None,
        mode: str = "json",
        instruction: str | None = None,
        stop: list[str] | None = None,
    ) -> None:
        if mode not in ("json", "plain"):
            raise ValueError(f"Unknown provider mode {mode!r}: use 'json' or 'plain'")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.extra = extra or {}
        self.mode = mode
        self.instruction = instruction or DEFAULT_PLAIN_INSTRUCTION
        self.stop = list(stop or [])
        self.cost_per_token_in: float = 0.0  # provider-specific
        self.cost_per_token_out: float = 0.0
        self._compression_warned = False
        self._proofread_skip_warned = False

    def _warn_if_gateway_compresses(self, response) -> None:
        """Warn once when a gateway says it is rewriting our prompts.

        Gateways such as Omniroute compress prompts to save tokens. That can
        drop instructions or alter source text, which shows up as subtly wrong
        translations rather than an error, so it is worth surfacing.
        """
        if self._compression_warned:
            return
        for name, value in response.headers.items():
            if "compress" not in name.lower():
                continue
            if value.strip().lower().startswith(("off", "none", "false", "disabled")):
                continue
            self._compression_warned = True
            logger.warning(
                "Gateway reports active prompt compression (%s: %s). "
                "Translations may be altered; disable compression on the gateway "
                "for faithful output.",
                name,
                value,
            )
            return

    @property
    def provider_type(self) -> str:
        return "openai-compatible"

    # ── Prompt construction ─────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _build_system_prompt(
        self,
        target_lang: str,
        glossary: Glossary | None,
        context: str | None,
        source_lang: str = "zh",
    ) -> str:
        lines = [
            f"You are a professional {source_lang} → {target_lang} translator.",
            "Translate the following text accurately and naturally.",
            "Preserve all HTML tags and formatting. Do NOT add commentary.",
            "",
        ]

        if glossary and glossary.entries:
            lines.append("Glossary (use these exact translations):")
            for entry in glossary.entries:
                lines.append(f"- {entry.source} → {entry.target}")
            lines.append("")

        if context:
            lines.extend(
                [
                    "Previous context (for continuity):",
                    context,
                    "",
                ]
            )

        lines.append('Return JSON: {"translated": "..."}')
        return "\n".join(lines)

    def _build_user_prompt(
        self,
        segments: list[Segment],
        retrieved_contexts: list[str | None] | None = None,
    ) -> str:
        """Build the user message for a batch of segments.

        For multi-segment batches the model is asked for a JSON object mapping
        segment id → translation. Asking for one combined ``translated`` value
        made every segment in the batch receive the same text.
        """
        parts: list[str] = []
        if len(segments) > 1:
            example = ", ".join(f'"{s.id}": "<translation>"' for s in segments[:2])
            parts.append(
                "Translate the text inside each <segment> below. Respond with a single "
                "JSON object that maps EVERY segment id to its translation, and nothing "
                "else. Do not repeat the <segment> tags or the segment id in a "
                "translation.\n"
                f"Example shape: {{{example}}}\n"
            )

        for i, seg in enumerate(segments):
            rc = (
                retrieved_contexts[i]
                if retrieved_contexts and i < len(retrieved_contexts)
                else None
            )
            block = f'<segment id="{seg.id}">\n{seg.source_text}\n</segment>'
            if rc:
                block = f"<related_context>\n{rc}\n</related_context>\n" + block
            parts.append(block)
        return "\n".join(parts)

    # ── HTTP helpers ────────────────────────────────────────────────────

    async def _chat(
        self,
        client: httpx.AsyncClient,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
    ) -> tuple[str, dict[str, Any]]:
        """Send one chat completion request and return (content, usage)."""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            # Ask for a single JSON response. Some gateways (Omniroute, for one)
            # stream by default and would otherwise return text/event-stream.
            "stream": False,
            **self.extra,
        }
        response = await client.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json=payload,
        )
        response.raise_for_status()
        self._warn_if_gateway_compresses(response)
        return parse_chat_completion(response)

    @staticmethod
    @staticmethod
    def _lookup_translation(mapping: dict[str, Any], seg: Segment, batch_size: int) -> str | None:
        """Pull one segment's translation out of a parsed response object."""
        value = mapping.get(seg.id)
        if isinstance(value, dict):
            value = value.get("translated")
        if isinstance(value, str) and value.strip():
            return _clean_translation(value)
        # A single-segment response may use the flat {"translated": ...} shape.
        if batch_size == 1:
            flat = mapping.get("translated")
            if isinstance(flat, str) and flat.strip():
                return _clean_translation(flat)
        return None

    # ── Provider interface ──────────────────────────────────────────────

    async def translate(
        self,
        segments: list[Segment],
        glossary: Glossary | None,
        target_lang: str,
        context: str | None,
        retrieved_contexts: list[str | None] | None = None,
        system_prompt: str | None = None,
    ) -> list[Segment]:
        """Translate segments via the OpenAI-compatible API."""
        if not segments:
            return []

        if self.mode == "plain":
            return await self._translate_plain(
                segments, target_lang, glossary=glossary, retrieved_contexts=retrieved_contexts
            )

        system = system_prompt or self._build_system_prompt(target_lang, glossary, context)
        results: list[Segment] = []

        async with httpx.AsyncClient(timeout=60.0) as client:
            for start in range(0, len(segments), TRANSLATE_BATCH_SIZE):
                batch = segments[start : start + TRANSLATE_BATCH_SIZE]
                rc = (
                    retrieved_contexts[start : start + TRANSLATE_BATCH_SIZE]
                    if retrieved_contexts
                    else None
                )
                user_prompt = self._build_user_prompt(batch, rc)

                try:
                    content, usage = await self._chat(client, system, user_prompt, 0.3)
                except (httpx.HTTPError, ValueError, KeyError) as e:
                    logger.warning(
                        "Translation request failed for %d segment(s): %s", len(batch), e
                    )
                    for seg in batch:
                        seg.status = SegmentStatus.FAILED
                        seg.translated = None
                        results.append(seg)
                    continue

                mapping = extract_json_object(content) or {}
                usage_in = int(usage.get("prompt_tokens", 0) or 0)
                usage_out = int(usage.get("completion_tokens", 0) or 0)

                for seg in batch:
                    translated = self._lookup_translation(mapping, seg, len(batch))
                    if translated is None:
                        # The model did not return a per-id mapping for this
                        # segment: retry it alone so no paragraph is dropped.
                        translated = await self._translate_one(client, system, seg)

                    if translated is None:
                        seg.status = SegmentStatus.FAILED
                        seg.translated = None
                    else:
                        seg.translated = translated
                        seg.status = SegmentStatus.TRANSLATED
                        seg.provider = self.model
                        seg.tokens_in = usage_in // max(len(batch), 1)
                        seg.tokens_out = usage_out // max(len(batch), 1)
                    results.append(seg)

        return results

    async def _translate_plain(
        self,
        segments: list[Segment],
        target_lang: str,
        glossary: Glossary | None = None,
        retrieved_contexts: list[str | None] | None = None,
    ) -> list[Segment]:
        """Translate one segment per request, instruction style.

        Dedicated machine-translation models (Tencent Hy-MT2 and friends) are
        trained to answer a short instruction with the translation only; asking
        them for a JSON id map produces prose or an empty response.
        """
        import httpx

        language = TARGET_LANGUAGE_NAMES.get(target_lang.lower(), target_lang)
        results: list[Segment] = []

        async with httpx.AsyncClient(timeout=60.0) as client:
            for index, seg in enumerate(segments):
                prompt_text = seg.source_text
                if retrieved_contexts and index < len(retrieved_contexts):
                    hint = retrieved_contexts[index]
                    if hint:
                        prompt_text = f"{hint}\n\n{prompt_text}"

                user_prompt = self.instruction.replace("{target_language}", language)
                terms = _glossary_block(glossary, seg.source_text)
                if terms:
                    user_prompt = f"{user_prompt}\n\n{terms}"
                user_prompt = f"{user_prompt}\n\n{prompt_text}"

                payload: dict[str, Any] = {
                    "model": self.model,
                    "messages": [{"role": "user", "content": user_prompt}],
                    # Greedy decoding: translation should not be creative.
                    "temperature": 0,
                    "stream": False,
                    **self.extra,
                }
                if self.stop:
                    payload["stop"] = self.stop

                try:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers=self._headers(),
                        json=payload,
                    )
                    response.raise_for_status()
                    self._warn_if_gateway_compresses(response)
                    content, _usage = parse_chat_completion(response)
                except (httpx.HTTPError, ValueError, KeyError) as e:
                    logger.warning("Plain translation failed for %s: %s", seg.id, e)
                    seg.status = SegmentStatus.FAILED
                    seg.translated = None
                    results.append(seg)
                    continue

                translated = _clean_translation(content or "")
                if not translated:
                    logger.warning("Empty translation for %s", seg.id)
                    seg.status = SegmentStatus.FAILED
                    seg.translated = None
                else:
                    seg.translated = translated
                    seg.status = SegmentStatus.TRANSLATED
                    seg.provider = self.model
                results.append(seg)

        return results

    async def _translate_one(
        self, client: httpx.AsyncClient, system_prompt: str, seg: Segment
    ) -> str | None:
        """Translate a single segment (fallback path)."""
        user_prompt = (
            f'<segment id="{seg.id}">\n{seg.source_text}\n</segment>\n\n'
            'Respond with exactly: {"translated": "<translation>"}'
        )
        try:
            content, _usage = await self._chat(client, system_prompt, user_prompt, 0.3)
        except (httpx.HTTPError, ValueError, KeyError) as e:
            logger.warning("Fallback translation failed for %s: %s", seg.id, e)
            return None

        mapping = extract_json_object(content)
        if mapping is None:
            return _clean_translation(content or "") or None
        translation = mapping.get("translated")
        if isinstance(translation, str) and translation.strip():
            return _clean_translation(translation)
        return _clean_translation(content or "") or None

    async def proofread(self, segments: list[Segment], glossary: Glossary | None) -> list[Segment]:
        """Proofread translated segments, one request per segment.

        Instruction-style translation models are skipped: they cannot follow the
        proofreading instruction, and in practice they rewrite text that was
        already correct while dropping glossary-pinned terminology. Use a chat
        model for this pass.
        """
        if self.mode == "plain":
            if not self._proofread_skip_warned:
                self._proofread_skip_warned = True
                logger.warning(
                    "%s is an instruction-style translation model; skipping proofreading. "
                    "Run `swatl proofread --provider <chat-model>` instead.",
                    self.model,
                )
            return segments

        results: list[Segment] = []
        system = system_prompt_proofread()

        async with httpx.AsyncClient(timeout=60.0) as client:
            for seg in segments:
                if not seg.translated:
                    results.append(seg)
                    continue

                user_content = (
                    f"Original: {seg.source_text}\n"
                    f"Translation: {seg.translated}\n\n"
                    "Proofread the translation for grammar, style, and naturalness.\n"
                    'Return JSON: {"translated": "improved version"}'
                )

                try:
                    content, _usage = await self._chat(client, system, user_content, 0.4)
                except (httpx.HTTPError, ValueError, KeyError) as e:
                    logger.warning("Proofread request failed for %s: %s", seg.id, e)
                    results.append(seg)  # Keep original on error
                    continue

                mapping = extract_json_object(content)
                if mapping is not None:
                    improved = mapping.get("translated")
                    if isinstance(improved, str) and improved.strip():
                        seg.translated = improved.strip()
                        seg.status = SegmentStatus.PROOFREAD
                results.append(seg)

        return results

    async def test(self) -> dict:
        """Test provider connectivity with a minimal request."""
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": "Hello"}],
                        "max_tokens": 5,
                    },
                )
                response.raise_for_status()
                return {
                    "ok": True,
                    "latency_ms": int((time.monotonic() - start) * 1000),
                    "error": None,
                }
        except Exception as e:
            return {
                "ok": False,
                "latency_ms": int((time.monotonic() - start) * 1000),
                "error": str(e),
            }


def system_prompt_proofread() -> str:
    return (
        "You are an English language proofreader. Review and improve the following "
        "translation for grammar, style, and naturalness. Preserve the meaning.\n"
        'Return JSON: {"translated": "improved version"}'
    )
