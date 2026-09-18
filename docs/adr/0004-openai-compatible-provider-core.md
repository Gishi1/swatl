# ADR-0004 — OpenAI-Compatible Provider as Core, with Adapters

| Field        | Value                          |
|--------------|--------------------------------|
| Status       | Accepted                       |
| Date         | 2025-07-20                     |

## Context

We need to support both cloud APIs (OpenAI, DeepSeek, Anthropic) and local models (Ollama, vLLM, DashScope/Qwen). Each has a different SDK and API format.

## Decision

Use the **OpenAI chat completions API** as the core provider interface. Any server implementing this API works with a single adapter. Additional adapters are written for Anthropic (Claude) and DeepL (NMT).

## Rationale

The OpenAI-compatible endpoint is the **de facto standard** for LLM inference servers:

| Server | Endpoint |
|---|---|
| OpenAI | `https://api.openai.com/v1` |
| DeepSeek | `https://api.deepseek.com` |
| Ollama | `http://localhost:11434/v1` |
| vLLM | `http://<host>:8000/v1` |
| DashScope (Qwen) | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| LM Studio | `http://localhost:1234/v1` |

One adapter covers all of these. Anthropic and DeepL are added as separate adapters because their APIs are fundamentally different.

## Consequences

- Providers not implementing the OpenAI API require a dedicated adapter.
- Streaming is supported via the OpenAI protocol; non-OpenAI providers may need custom streaming logic.
- Model routing: users pick the provider name in CLI (`--provider deepseek`); the config maps to the correct `base_url` + `model`.
