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


class TestPlainMode:
    """Instruction-style translation for dedicated MT models (Hy-MT2 etc.)."""

    def _plain(self, **kwargs):
        return OpenAICompatible(
            base_url="https://mt.example.com/v1", model="hy-mt2", api_key="", mode="plain", **kwargs
        )

    def test_unknown_mode_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown provider mode"):
            OpenAICompatible("https://x/v1", "m", mode="chatty")

    def test_one_request_per_segment_with_raw_text_out(self, monkeypatch):
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            seen.append(body)
            return _chat_response("The universe is vast.")

        _patch_transport(monkeypatch, handler)
        result = asyncio.run(self._plain().translate(_segments(3), None, "en", None))

        assert len(seen) == 3  # one request per segment, no JSON batching
        assert [s.translated for s in result] == ["The universe is vast."] * 3
        assert all(s.status == SegmentStatus.TRANSLATED for s in result)

    def test_prompt_uses_an_instruction_and_no_system_role(self, monkeypatch):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            return _chat_response("ok")

        _patch_transport(monkeypatch, handler)
        asyncio.run(self._plain().translate(_segments(1), None, "ja", None))

        messages = seen["body"]["messages"]
        assert len(messages) == 1 and messages[0]["role"] == "user"
        assert "Japanese" in messages[0]["content"]
        assert "中文段落" in messages[0]["content"]
        assert seen["body"]["temperature"] == 0
        assert seen["body"]["stream"] is False

    def test_custom_instruction_is_used(self, monkeypatch):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            return _chat_response("ok")

        _patch_transport(monkeypatch, handler)
        provider = self._plain(
            instruction="\u5c06\u4ee5\u4e0b\u6587\u672c\u7ffb\u8bd1\u6210{target_language}:"
        )
        asyncio.run(provider.translate(_segments(1), None, "en", None))
        assert seen["body"]["messages"][0]["content"].startswith(
            "\u5c06\u4ee5\u4e0b\u6587\u672c\u7ffb\u8bd1\u6210English:"
        )

    def test_stop_sequences_are_forwarded(self, monkeypatch):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            return _chat_response("ok")

        _patch_transport(monkeypatch, handler)
        provider = self._plain(stop=["<eos:6124c78e>", "<\uff5chy_User\uff5c>"])
        asyncio.run(provider.translate(_segments(1), None, "en", None))
        assert seen["body"]["stop"] == ["<eos:6124c78e>", "<\uff5chy_User\uff5c>"]

    def test_control_tokens_are_stripped_from_the_output(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return _chat_response("<segment>Sophon</segment><eos:6124c78e>")

        _patch_transport(monkeypatch, handler)
        result = asyncio.run(self._plain().translate(_segments(1), None, "en", None))
        assert result[0].translated == "Sophon"

    def test_retrieved_context_is_prepended(self, monkeypatch):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            return _chat_response("ok")

        _patch_transport(monkeypatch, handler)
        asyncio.run(
            self._plain().translate(
                _segments(1),
                None,
                "en",
                None,
                retrieved_contexts=["Reference context:\n\u667a\u5b50 \u2192 Sophon"],
            )
        )
        content = seen["body"]["messages"][0]["content"]
        assert "Sophon" in content and content.index("Sophon") < content.index(
            "\u4e2d\u6587\u6bb5\u843d"
        )

    def test_empty_response_marks_the_segment_failed(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return _chat_response("")

        _patch_transport(monkeypatch, handler)
        result = asyncio.run(self._plain().translate(_segments(1), None, "en", None))
        assert result[0].status == SegmentStatus.FAILED
        assert result[0].translated is None

    def test_http_error_marks_the_batch_failed_without_raising(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "boom"})

        _patch_transport(monkeypatch, handler)
        result = asyncio.run(self._plain().translate(_segments(3), None, "en", None))
        assert all(s.status == SegmentStatus.FAILED for s in result)


class TestPlainModeGlossary:
    """Terminology must reach instruction-style models too."""

    def _plain(self):
        return OpenAICompatible(base_url="https://mt.example.com/v1", model="hy-mt2", mode="plain")

    def test_glossary_terms_are_injected(self, monkeypatch):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["prompt"] = json.loads(request.content)["messages"][0]["content"]
            return _chat_response("Red Coast Base")

        _patch_transport(monkeypatch, handler)
        glossary = Glossary(
            entries=[
                GlossaryEntry(source="红岸基地", target="Red Coast Base"),
                GlossaryEntry(source="智子", target="Sophon"),
            ]
        )
        seg = Segment(
            id="p-1", doc="d", anchor=".//p[1]", tag="p", source_text="叶文洁站在红岸基地的窗前。"
        )
        asyncio.run(self._plain().translate([seg], glossary, "en", None))

        assert "红岸基地 -> Red Coast Base" in seen["prompt"]
        # Only terms present in this segment are sent.
        assert "智子" not in seen["prompt"]

    def test_no_glossary_leaves_the_prompt_clean(self, monkeypatch):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["prompt"] = json.loads(request.content)["messages"][0]["content"]
            return _chat_response("ok")

        _patch_transport(monkeypatch, handler)
        asyncio.run(self._plain().translate(_segments(1), None, "en", None))
        assert "Glossary" not in seen["prompt"]


class TestPlainModeProofreading:
    """An MT model must not be asked to proofread."""

    def test_proofread_is_skipped_for_plain_mode(self, monkeypatch, caplog):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return _chat_response("rewritten")

        _patch_transport(monkeypatch, handler)
        provider = OpenAICompatible("https://mt/v1", "hy-mt2", mode="plain")
        seg = _segments(1)[0]
        seg.translated = "Ye Wenjie stood by the window of Red Coast Base."
        seg.status = SegmentStatus.TRANSLATED

        with caplog.at_level("WARNING"):
            result = asyncio.run(provider.proofread([seg], None))

        assert calls == []  # no request was made
        assert result[0].translated == "Ye Wenjie stood by the window of Red Coast Base."
        assert result[0].status == SegmentStatus.TRANSLATED
        assert any("skipping proofreading" in r.message for r in caplog.records)

    def test_json_mode_still_proofreads(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return _chat_response(json.dumps({"translated": "Improved."}))

        _patch_transport(monkeypatch, handler)
        seg = _segments(1)[0]
        seg.translated = "improved"
        result = asyncio.run(_provider().proofread([seg], None))
        assert result[0].translated == "Improved."
        assert result[0].status == SegmentStatus.PROOFREAD


class TestRequestTimeout:
    """The HTTP timeout is configurable — local models can take a long time.

    llama-server started with ``--sleep-idle-seconds`` unloads its weights when
    idle, so the first request after a pause also waits for the model to be read
    back in. That easily exceeds the 60 s default.
    """

    def test_default_timeout_is_sixty_seconds(self):
        assert _provider().timeout == 60.0

    def test_configured_timeout_reaches_httpx(self, monkeypatch):
        seen: list[float | None] = []
        real_async_client = httpx.AsyncClient

        def factory(*args, **kwargs):
            seen.append(kwargs.get("timeout"))
            kwargs["transport"] = httpx.MockTransport(
                lambda request: _chat_response('{"p-0001": "Hello"}')
            )
            return real_async_client(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", factory)
        provider = OpenAICompatible(
            base_url="https://mt.example.com/v1", model="local-mt", timeout=300.0
        )
        assert provider.timeout == 300.0

        asyncio.run(provider.translate(_segments(1), None, "en", None))

        assert seen and seen[0] == 300.0


class TestEmptyAfterCleaning:
    """A response that cleans to nothing is a failure, not a translation."""

    def test_wrapper_only_batch_value_is_failed(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return _chat_response(json.dumps({"p-0001": '<segment id="p-0001"></segment>'}))

        _patch_transport(monkeypatch, handler)
        segments = _segments(1)
        result = asyncio.run(_provider().translate(segments, None, "en", None))

        assert result[0].translated is None
        assert result[0].status == SegmentStatus.FAILED

    def test_empty_string_batch_value_is_failed(self, monkeypatch):
        _patch_transport(
            monkeypatch,
            lambda request: _chat_response(json.dumps({"p-0001": "   "})),
        )
        result = asyncio.run(_provider().translate(_segments(1), None, "en", None))

        assert result[0].status == SegmentStatus.FAILED


class TestFallbackDoesNotStoreEnvelope:
    """The single-segment fallback must never store raw JSON as the text."""

    def test_id_map_response_is_not_used_as_text(self, monkeypatch):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                # Batch request returns nothing for the segment.
                return _chat_response(json.dumps({}))
            # The lone retry answers with the batch shape instead of
            # {"translated": ...}.
            return _chat_response(json.dumps({"p-0001": "Hello there"}))

        _patch_transport(monkeypatch, handler)
        result = asyncio.run(_provider().translate(_segments(1), None, "en", None))

        assert result[0].translated == "Hello there"
        assert result[0].status == SegmentStatus.TRANSLATED

    def test_useless_object_fails_instead_of_storing_json(self, monkeypatch):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return _chat_response(json.dumps({}))
            return _chat_response(json.dumps({"note": "I cannot help with that"}))

        _patch_transport(monkeypatch, handler)
        result = asyncio.run(_provider().translate(_segments(1), None, "en", None))

        assert result[0].translated is None
        assert result[0].status == SegmentStatus.FAILED
        assert "note" not in (result[0].translated or "")


class TestTransientFailuresAreRetried:
    """A 429/502 must not permanently fail a batch."""

    def test_retries_then_succeeds(self, monkeypatch):
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            if attempts["n"] < 3:
                return httpx.Response(429, headers={"retry-after": "0"})
            return _chat_response(json.dumps({"p-0001": "Hello"}))

        _patch_transport(monkeypatch, handler)
        provider = OpenAICompatible(
            base_url="https://api.example.com/v1", model="m", api_key="k", max_retries=3
        )
        result = asyncio.run(provider.translate(_segments(1), None, "en", None))

        assert attempts["n"] == 3  # two retries then a success
        assert result[0].translated == "Hello"
        assert result[0].status == SegmentStatus.TRANSLATED

    def test_non_retryable_status_fails_immediately(self, monkeypatch):
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            return httpx.Response(400, json={"error": "bad request"})

        _patch_transport(monkeypatch, handler)
        provider = OpenAICompatible(
            base_url="https://api.example.com/v1", model="m", api_key="k", max_retries=3
        )
        result = asyncio.run(provider.translate(_segments(1), None, "en", None))

        assert attempts["n"] == 1  # a 400 is not retried
        assert result[0].status == SegmentStatus.FAILED

    def test_gives_up_after_max_retries(self, monkeypatch):
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            return httpx.Response(503, headers={"retry-after": "0"})

        _patch_transport(monkeypatch, handler)
        provider = OpenAICompatible(
            base_url="https://api.example.com/v1", model="m", api_key="k", max_retries=3
        )
        result = asyncio.run(provider.translate(_segments(1), None, "en", None))

        assert attempts["n"] == 3
        assert result[0].status == SegmentStatus.FAILED
