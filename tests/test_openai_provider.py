"""Tests for the OpenAI-compatible provider — the real production path.

Every request is served by an ``httpx.MockTransport``, so these tests exercise
request construction, response parsing, error handling and batching without a
network or an API key.
"""

from __future__ import annotations

import asyncio
import json
import re

import httpx
import pytest

from swatl.models import Glossary, GlossaryEntry, Segment, SegmentStatus
from swatl.providers.openai_compat import OpenAICompatible, extract_json_object

SEGMENT_ID_RE = re.compile(r'<segment id="([^"]+)">')


def _patch_transport(monkeypatch, handler):
    """Route every httpx.AsyncClient through a mock transport."""
    real_async_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


def _segments(n: int, text: str = "中文段落") -> list[Segment]:
    return [
        Segment(id=f"p-{i:04d}", doc="doc", anchor=f".//p[{i}]", tag="p", source_text=text)
        for i in range(1, n + 1)
    ]


def _chat_response(content: str, prompt_tokens: int = 30, completion_tokens: int = 10):
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
        },
    )


def _provider() -> OpenAICompatible:
    return OpenAICompatible(
        base_url="https://api.example.com/v1", model="test-model", api_key="secret"
    )


class TestTranslate:
    def test_each_segment_gets_its_own_translation(self, monkeypatch):
        """A batch must not smear one translation across every segment."""

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            user = body["messages"][-1]["content"]
            ids = SEGMENT_ID_RE.findall(user)
            mapping = {sid: f"English of {sid}" for sid in ids}
            return _chat_response(json.dumps(mapping))

        _patch_transport(monkeypatch, handler)
        segments = _segments(3)
        result = asyncio.run(_provider().translate(segments, None, "en", None))

        assert [s.translated for s in result] == [
            "English of p-0001",
            "English of p-0002",
            "English of p-0003",
        ]
        assert all(s.status == SegmentStatus.TRANSLATED for s in result)
        assert all(s.provider == "test-model" for s in result)

    def test_sends_authorization_and_model(self, monkeypatch):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["auth"] = request.headers.get("authorization")
            seen["url"] = str(request.url)
            body = json.loads(request.content)
            seen["model"] = body["model"]
            ids = SEGMENT_ID_RE.findall(body["messages"][-1]["content"])
            return _chat_response(json.dumps({sid: "x" for sid in ids}))

        _patch_transport(monkeypatch, handler)
        asyncio.run(_provider().translate(_segments(1), None, "en", None))

        assert seen["auth"] == "Bearer secret"
        assert seen["url"] == "https://api.example.com/v1/chat/completions"
        assert seen["model"] == "test-model"

    def test_uses_supplied_system_prompt(self, monkeypatch):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            seen["system"] = body["messages"][0]["content"]
            ids = SEGMENT_ID_RE.findall(body["messages"][-1]["content"])
            return _chat_response(json.dumps({sid: "x" for sid in ids}))

        _patch_transport(monkeypatch, handler)
        asyncio.run(
            _provider().translate(_segments(1), None, "en", None, system_prompt="STYLE: literary")
        )
        assert seen["system"] == "STYLE: literary"

    def test_http_error_marks_segments_failed_instead_of_raising(self, monkeypatch):
        """A 500/401 must fail the batch, not blow up the whole translation."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "boom"})

        _patch_transport(monkeypatch, handler)
        result = asyncio.run(_provider().translate(_segments(3), None, "en", None))

        assert len(result) == 3
        assert all(s.status == SegmentStatus.FAILED for s in result)
        assert all(s.translated is None for s in result)

    def test_network_error_marks_segments_failed(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host", request=request)

        _patch_transport(monkeypatch, handler)
        result = asyncio.run(_provider().translate(_segments(2), None, "en", None))
        assert all(s.status == SegmentStatus.FAILED for s in result)

    def test_markdown_fenced_json_is_parsed(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            ids = SEGMENT_ID_RE.findall(body["messages"][-1]["content"])
            mapping = {sid: f"T:{sid}" for sid in ids}
            fenced = "```json\n" + json.dumps(mapping) + "\n```"
            return _chat_response(fenced)

        _patch_transport(monkeypatch, handler)
        result = asyncio.run(_provider().translate(_segments(2), None, "en", None))
        assert [s.translated for s in result] == ["T:p-0001", "T:p-0002"]

    def test_missing_id_falls_back_to_single_request(self, monkeypatch):
        """An incomplete mapping must not silently drop a segment."""
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            body = json.loads(request.content)
            ids = SEGMENT_ID_RE.findall(body["messages"][-1]["content"])
            if len(ids) > 1:
                # Deliberately omit the second segment from the mapping.
                return _chat_response(json.dumps({ids[0]: "first only"}))
            return _chat_response(json.dumps({"translated": f"single {ids[0]}"}))

        _patch_transport(monkeypatch, handler)
        result = asyncio.run(_provider().translate(_segments(2), None, "en", None))

        assert calls["n"] == 2
        assert result[0].translated == "first only"
        assert result[1].translated == "single p-0002"
        assert all(s.status == SegmentStatus.TRANSLATED for s in result)

    def test_plain_text_response_is_used_verbatim(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return _chat_response("Just the translation, no JSON.")

        _patch_transport(monkeypatch, handler)
        result = asyncio.run(_provider().translate(_segments(1), None, "en", None))
        assert result[0].translated == "Just the translation, no JSON."
        assert result[0].status == SegmentStatus.TRANSLATED

    def test_batches_larger_than_limit_are_split(self, monkeypatch):
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            ids = SEGMENT_ID_RE.findall(body["messages"][-1]["content"])
            requests.append(ids)
            return _chat_response(json.dumps({sid: f"T:{sid}" for sid in ids}))

        _patch_transport(monkeypatch, handler)
        segments = _segments(25)
        result = asyncio.run(_provider().translate(segments, None, "en", None))

        assert [len(r) for r in requests] == [10, 10, 5]
        assert len(result) == 25
        assert all(s.translated == f"T:{s.id}" for s in result)

    def test_empty_input_makes_no_request(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError("no request should be sent")

        _patch_transport(monkeypatch, handler)
        assert asyncio.run(_provider().translate([], None, "en", None)) == []

    def test_token_usage_is_recorded_per_segment(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            ids = SEGMENT_ID_RE.findall(body["messages"][-1]["content"])
            return _chat_response(
                json.dumps({sid: "x" for sid in ids}), prompt_tokens=40, completion_tokens=20
            )

        _patch_transport(monkeypatch, handler)
        result = asyncio.run(_provider().translate(_segments(4), None, "en", None))
        assert all(s.tokens_in == 10 for s in result)
        assert all(s.tokens_out == 5 for s in result)


class TestProofread:
    def test_proofread_applies_improved_text(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return _chat_response(json.dumps({"translated": "Improved sentence."}))

        _patch_transport(monkeypatch, handler)
        seg = _segments(1)[0]
        seg.translated = "improved sentence"
        seg.status = SegmentStatus.TRANSLATED

        result = asyncio.run(_provider().proofread([seg], None))
        assert result[0].translated == "Improved sentence."
        assert result[0].status == SegmentStatus.PROOFREAD

    def test_proofread_keeps_original_on_error(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"error": "rate limited"})

        _patch_transport(monkeypatch, handler)
        seg = _segments(1)[0]
        seg.translated = "unchanged"
        result = asyncio.run(_provider().proofread([seg], None))
        assert result[0].translated == "unchanged"

    def test_proofread_skips_untranslated(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError("no request should be sent")

        _patch_transport(monkeypatch, handler)
        seg = _segments(1)[0]
        result = asyncio.run(_provider().proofread([seg], None))
        assert result[0].translated is None


class TestConnectivity:
    def test_ok(self, monkeypatch):
        _patch_transport(monkeypatch, lambda request: _chat_response("hi"))
        result = asyncio.run(_provider().test())
        assert result["ok"] is True
        assert result["error"] is None

    def test_failure_is_reported(self, monkeypatch):
        _patch_transport(monkeypatch, lambda request: httpx.Response(401, json={}))
        result = asyncio.run(_provider().test())
        assert result["ok"] is False
        assert result["error"]


class TestGlossaryPrompt:
    def test_fallback_prompt_includes_glossary(self):
        glossary = Glossary(entries=[GlossaryEntry(source="三体", target="Three-Body")])
        prompt = _provider()._build_system_prompt("en", glossary, None)
        assert "三体 → Three-Body" in prompt


@pytest.mark.parametrize(
    "raw",
    [
        '{"translated": "hello"}',
        '```json\n{"translated": "hello"}\n```',
        'Sure! {"translated": "hello"} Hope that helps.',
        '{"translated": "a {brace} inside"}',
    ],
)
def test_extract_json_object_handles_llm_noise(raw):
    assert extract_json_object(raw) == {
        "translated": "a {brace} inside" if "{brace}" in raw else "hello"
    }


def test_extract_json_object_returns_none_for_garbage():
    assert extract_json_object("no json here") is None
    assert extract_json_object("") is None


class TestStreamingGatewayInterop:
    """Some OpenAI-compatible gateways stream unless told not to."""

    def test_request_asks_for_a_non_streaming_response(self, monkeypatch):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            return _chat_response(json.dumps({"p-0001": "x"}))

        _patch_transport(monkeypatch, handler)
        asyncio.run(_provider().translate(_segments(1), None, "en", None))
        assert seen["body"]["stream"] is False

    def test_sse_response_is_assembled(self, monkeypatch):
        """A gateway that ignores stream=false still yields usable text."""
        sse = "\n\n".join(
            [
                'data: {"choices":[{"index":0,"delta":{"role":"assistant","content":""}}]}',
                'data: {"choices":[{"index":0,"delta":{"reasoning_content":"thinking"}}]}',
                'data: {"choices":[{"index":0,"delta":{"content":"{\\"p-0001\\": "}}]}',
                'data: {"choices":[{"index":0,"delta":{"content":"\\"Three-Body\\"}"}}]}',
                "data: [DONE]",
            ]
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})

        _patch_transport(monkeypatch, handler)
        result = asyncio.run(_provider().translate(_segments(1), None, "en", None))

        assert result[0].translated == "Three-Body"
        assert result[0].status == SegmentStatus.TRANSLATED

    def test_sse_without_content_is_handled(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                text='data: {"choices":[{"delta":{"reasoning_content":"hmm"}}]}\n\ndata: [DONE]',
                headers={"content-type": "text/event-stream"},
            )

        _patch_transport(monkeypatch, handler)
        result = asyncio.run(_provider().translate(_segments(1), None, "en", None))
        # Falls back to the single-segment request, which also streams empty,
        # so the segment ends up failed rather than raising.
        assert result[0].status in (SegmentStatus.FAILED, SegmentStatus.TRANSLATED)

    def test_collect_sse_content_directly(self):
        from swatl.providers.openai_compat import _collect_sse_content

        body = (
            'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
            "data: [DONE]\n\n"
        )
        assert _collect_sse_content(body) == "Hello"
        assert _collect_sse_content("") == ""
        assert _collect_sse_content("data: not-json\n\n") == ""


class TestTranslationCleanup:
    """Models sometimes echo the segment scaffolding into the answer."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ('<segment id="p-0001">Hello</segment>', "Hello"),
            ('<segment id="p-0001">\nHello\n</segment>\n', "Hello"),
            ("<segment>Hello</segment>", "Hello"),
            ("```\nHello\n```", "Hello"),
            ("```json\nHello\n```", "Hello"),
            ("  Hello  ", "Hello"),
            ("Hello <segment> world", "Hello <segment> world"),  # not a wrapper
        ],
    )
    def test_clean_translation(self, raw, expected):
        from swatl.providers.openai_compat import _clean_translation

        assert _clean_translation(raw) == expected

    def test_wrapped_values_are_cleaned_during_translation(self, monkeypatch):
        """Regression: a real gateway returned the wrapper inside the value."""

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            ids = SEGMENT_ID_RE.findall(body["messages"][-1]["content"])
            mapping = {sid: f'<segment id="{sid}">Translated {sid}</segment>' for sid in ids}
            return _chat_response(json.dumps(mapping))

        _patch_transport(monkeypatch, handler)
        result = asyncio.run(_provider().translate(_segments(3), None, "en", None))
        assert [s.translated for s in result] == [
            "Translated p-0001",
            "Translated p-0002",
            "Translated p-0003",
        ]

    def test_the_prompt_asks_models_not_to_echo_tags(self, monkeypatch):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            seen["prompt"] = body["messages"][-1]["content"]
            ids = SEGMENT_ID_RE.findall(seen["prompt"])
            return _chat_response(json.dumps({sid: "x" for sid in ids}))

        _patch_transport(monkeypatch, handler)
        asyncio.run(_provider().translate(_segments(2), None, "en", None))
        assert "Do not repeat the <segment> tags" in seen["prompt"]


class TestGatewayCompressionWarning:
    """A gateway that rewrites prompts should not do so silently."""

    def test_warns_when_compression_is_active(self, monkeypatch, caplog):
        def handler(request: httpx.Request) -> httpx.Response:
            ids = SEGMENT_ID_RE.findall(json.loads(request.content)["messages"][-1]["content"])
            response = _chat_response(json.dumps({sid: "x" for sid in ids}))
            response.headers["x-omniroute-compression"] = "stacked; source=default"
            return response

        _patch_transport(monkeypatch, handler)
        provider = _provider()
        with caplog.at_level("WARNING"):
            asyncio.run(provider.translate(_segments(1), None, "en", None))
        assert any("prompt compression" in r.message for r in caplog.records)

    def test_does_not_warn_when_compression_is_off(self, monkeypatch, caplog):
        def handler(request: httpx.Request) -> httpx.Response:
            ids = SEGMENT_ID_RE.findall(json.loads(request.content)["messages"][-1]["content"])
            response = _chat_response(json.dumps({sid: "x" for sid in ids}))
            response.headers["x-omniroute-compression"] = "off; source=off"
            return response

        _patch_transport(monkeypatch, handler)
        with caplog.at_level("WARNING"):
            asyncio.run(_provider().translate(_segments(1), None, "en", None))
        assert not any("prompt compression" in r.message for r in caplog.records)

    def test_warns_only_once(self, monkeypatch, caplog):
        def handler(request: httpx.Request) -> httpx.Response:
            ids = SEGMENT_ID_RE.findall(json.loads(request.content)["messages"][-1]["content"])
            response = _chat_response(json.dumps({sid: "x" for sid in ids}))
            response.headers["x-omniroute-compression"] = "stacked"
            return response

        _patch_transport(monkeypatch, handler)
        provider = _provider()
        with caplog.at_level("WARNING"):
            asyncio.run(provider.translate(_segments(25), None, "en", None))
        assert sum(1 for r in caplog.records if "prompt compression" in r.message) == 1
