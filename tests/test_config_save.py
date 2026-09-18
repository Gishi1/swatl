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
