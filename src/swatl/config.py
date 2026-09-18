"""Configuration loader for swatl providers."""

from __future__ import annotations

import os
from pathlib import Path

import tomlkit

from swatl.models import ProviderConfig

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "swatl"
DEFAULT_PROVIDERS_FILE = "providers.toml"

# Reserved top-level section in the providers file: it configures the
# embedding backend rather than naming a translation provider.
EMBEDDING_SECTION = "embedding"


def load_providers(
    config_path: str | Path | None = None,
) -> dict[str, ProviderConfig]:
    """Load all provider configs from a TOML file.

    If *config_path* is None, tries:
    1. ``~/.config/swatl/providers.toml``
    2. ``./config/providers.toml``
    3. ``./providers.toml``

    Returns a mapping of provider name → ProviderConfig.
    """
    path = Path(config_path) if config_path else _find_default_config()
    if not path.exists():
        return {}

    with open(path, encoding="utf-8") as f:
        data = tomlkit.load(f)

    providers: dict[str, ProviderConfig] = {}
    for name, cfg in data.items():
        if name == EMBEDDING_SECTION:
            continue
        providers[name] = ProviderConfig(
            type=cfg.get("type", "openai-compatible"),
            base_url=cfg.get("base_url", ""),
            model=cfg.get("model", ""),
            api_key_env=cfg.get("api_key_env", ""),
            extra={
                k: v
                for k, v in cfg.items()
                if k not in ("type", "base_url", "model", "api_key_env")
            },
        )
    return providers


def load_embedding_config(config_path: str | Path | None = None):
    """Load the optional ``[embedding]`` section of the providers file.

    Returns an :class:`~swatl.context.embedder.EmbedderConfig`, or ``None`` when
    the section is absent.
    """
    from swatl.context.embedder import EmbedderConfig

    path = Path(config_path) if config_path else _find_default_config()
    if not path.exists():
        return None

    with open(path, encoding="utf-8") as f:
        data = tomlkit.load(f)

    section = data.get(EMBEDDING_SECTION)
    if not section:
        return None

    api_key = str(section.get("api_key", ""))
    api_key_env = str(section.get("api_key_env", ""))
    if not api_key and api_key_env:
        api_key = os.environ.get(api_key_env, "")

    return EmbedderConfig(
        backend=str(section.get("backend", "ollama")),
        model=str(section.get("model", "bge-m3")),
        base_url=str(section.get("base_url", "")),
        api_key=api_key,
        dimension=int(section.get("dimension", 0) or 0),
    )


def get_api_key(provider: ProviderConfig) -> str:
    """Read the API key from the provider's configured env var.

    An empty ``api_key_env`` means the endpoint needs no authentication
    (Ollama, LM Studio, and most local gateways); the returned key is then an
    empty string and no Authorization header is sent.
    """
    if not provider.api_key_env:
        return ""

    key = os.environ.get(provider.api_key_env, "")
    if not key:
        raise OSError(
            f"API key not set for provider '{provider.model}' "
            f"(env var '{provider.api_key_env}') — set it before translating."
        )
    return key


def _find_default_config() -> Path:
    for candidate in (
        DEFAULT_CONFIG_DIR / DEFAULT_PROVIDERS_FILE,
        Path.cwd() / "config" / DEFAULT_PROVIDERS_FILE,
        Path.cwd() / DEFAULT_PROVIDERS_FILE,
    ):
        if candidate.exists():
            return candidate
    return DEFAULT_CONFIG_DIR / DEFAULT_PROVIDERS_FILE


def save_provider(
    name: str, provider: ProviderConfig, config_path: str | Path | None = None
) -> Path:
    """Persist a provider config to a TOML file.

    If *config_path* is None, uses the default config location. Returns the
    path that was written, so callers can tell the user where it landed.
    """
    path = Path(config_path) if config_path else _find_default_config()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    with open(path, encoding="utf-8") as f:
        data = tomlkit.load(f)

    data[name] = tomlkit.table()
    data[name]["type"] = provider.type
    data[name]["base_url"] = provider.base_url
    data[name]["model"] = provider.model
    data[name]["api_key_env"] = provider.api_key_env

    with open(path, "w", encoding="utf-8") as f:
        tomlkit.dump(data, f)

    return path
