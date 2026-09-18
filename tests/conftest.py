"""Test fixtures: EPUB creation and glossary."""

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def fixture_epub_path(tmp_path_factory):
    """Create a fixture EPUB once per test session."""
    from fixtures.create_fixture import create_fixture_epub

    dest = tmp_path_factory.mktemp("fixtures") / "fixture.epub"
    create_fixture_epub(dest)
    return dest


@pytest.fixture
def fixture_epub(tmp_path):
    """Create a fixture EPUB for each test."""
    from fixtures.create_fixture import create_fixture_epub

    dest = tmp_path / "fixture.epub"
    create_fixture_epub(dest)
    return dest


@pytest.fixture
def sample_glossary(tmp_path):
    """Create a sample glossary TOML."""
    from swatl.glossary import Glossary, GlossaryEntry, save_glossary

    g = Glossary(
        name="Test Glossary",
        pair=["zh", "en"],
        entries=[
            GlossaryEntry(source="三体", target="Three-Body"),
            GlossaryEntry(source="叶文洁", target="Ye Wenjie"),
        ],
    )
    path = tmp_path / "glossary.toml"
    save_glossary(g, path)
    return path
