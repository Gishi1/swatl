"""Tests for save_provider config function."""

from swatl.config import load_providers, save_provider
from swatl.models import ProviderConfig


class TestSaveProvider:
    """Test programmatic provider config saving."""

    def test_save_provider_creates_file(self, tmp_path):
        """save_provider should create the providers.toml file if it doesn't exist."""
        config_file = tmp_path / "providers.toml"
        # Ensure file doesn't exist yet
        provider = ProviderConfig(
            type="openai-compatible",
            base_url="https://api.example.com",
            model="test-model",
            api_key_env="EXAMPLE_API_KEY",
        )
        save_provider("testprovider", provider, config_file)

        # Verify the file contains the provider
        data = load_providers(config_file)
        assert "testprovider" in data
        assert data["testprovider"].model == "test-model"
        assert data["testprovider"].base_url == "https://api.example.com"

    def test_save_provider_adds_to_existing(self, tmp_path):
        """save_provider should add to existing providers without overwriting."""
        config_file = tmp_path / "providers.toml"
        config_file.write_text('[existing]\nmodel = "existing-model"\n')

        provider = ProviderConfig(
            type="openai-compatible",
            base_url="https://api.new.com",
            model="new-model",
            api_key_env="NEW_KEY",
        )
        save_provider("newprovider", provider, config_file)

        data = load_providers(config_file)
        assert "existing" in data
        assert data["existing"].model == "existing-model"
        assert "newprovider" in data
        assert data["newprovider"].model == "new-model"

    def test_save_provider_returns_path(self, tmp_path):
        """The written path is returned so callers can report it."""
        config_file = tmp_path / "nested" / "providers.toml"
        provider = ProviderConfig(
            type="openai-compatible",
            base_url="https://api.example.com/v1",
            model="m",
            api_key_env="KEY",
        )
        written = save_provider("p", provider, config_file)
        assert written == config_file
        assert config_file.exists()


class TestProviderTimeout:
    """Per-request timeout, raised for models that load on demand."""

    def test_default_is_not_written(self, tmp_path):
        """The 60 s default stays out of the file to keep it uncluttered."""
        config_file = tmp_path / "providers.toml"
        save_provider(
            "default",
            ProviderConfig(
                type="openai-compatible",
                base_url="https://api.example.com/v1",
                model="m",
                api_key_env="KEY",
            ),
            config_file,
        )
        assert "timeout" not in config_file.read_text()
        assert load_providers(config_file)["default"].timeout == 60.0

    def test_custom_timeout_round_trips(self, tmp_path):
        """A raised timeout survives a save/load round trip."""
        config_file = tmp_path / "providers.toml"
        save_provider(
            "local",
            ProviderConfig(
                type="openai-compatible",
                base_url="http://127.0.0.1:8080/v1",
                model="local-mt",
                api_key_env="",
                mode="plain",
                timeout=300.0,
            ),
            config_file,
        )
        assert "timeout = 300.0" in config_file.read_text()
        loaded = load_providers(config_file)["local"]
        assert loaded.timeout == 300.0
        assert loaded.mode == "plain"

    def test_timeout_is_not_copied_into_extra(self, tmp_path):
        """timeout is a first-class field, not provider-specific passthrough."""
        config_file = tmp_path / "providers.toml"
        config_file.write_text(
            '[local]\nbase_url = "http://127.0.0.1:8080/v1"\n'
            'model = "m"\ntimeout = 120\ncustom_flag = "kept"\n'
        )
        loaded = load_providers(config_file)["local"]
        assert loaded.timeout == 120.0
        assert "timeout" not in loaded.extra
        assert loaded.extra["custom_flag"] == "kept"
