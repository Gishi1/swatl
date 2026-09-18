"""smoke tests — verify the package imports and has a version string."""

import swatl


def test_package_imports_and_has_version():
    """The package should import cleanly and expose a version."""
    assert swatl.__version__
    assert isinstance(swatl.__version__, str)
    assert swatl.__version__.count(".") >= 1  # semver-ish


def test_cli_entry_point_exists():
    """The CLI module should be importable (placeholder until Phase 1)."""
    # Phase 0: just verify the module path is set up correctly.
    # Phase 1: assert callable(swatl.cli.main)
    pass
