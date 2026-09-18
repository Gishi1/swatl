"""Tests for CLI module."""

import sys
from pathlib import Path

# Add parent directory for fixtures import
sys.path.insert(0, str(Path(__file__).parent))
from fixtures.create_fixture import create_fixture_epub
from swatl.cli import _estimate_tokens, app


class TestCli:
    """Test the CLI application."""

    def test_app_created(self):
        """The Typer app should be created."""
        assert app is not None
        # Typer apps have invoke and callback attributes
        assert hasattr(app, "command") or hasattr(app, "callback")

    def test_estimate_tokens_basic(self):
        """Token estimation should produce positive values."""
        from swatl.models import Segment

        segments = [
            Segment(id="p-0001", doc="doc", anchor=".//p[1]", tag="p", source_text="三体世界"),
        ]
        tokens_in, tokens_out = _estimate_tokens(segments)
        assert tokens_in > 0
        assert tokens_out > 0

    def test_estimate_tokens_zh_vs_ascii(self):
        """CJK text should produce more input tokens than ASCII."""
        from swatl.models import Segment

        zh_seg = Segment(
            id="p-0001", doc="doc", anchor=".//p[1]", tag="p", source_text="这是一个中文测试"
        )
        en_seg = Segment(
            id="p-0002", doc="doc", anchor=".//p[1]", tag="p", source_text="This is an English test"
        )

        zh_in, zh_out = _estimate_tokens([zh_seg])
        en_in, en_out = _estimate_tokens([en_seg])

        # CJK chars are counted as 1 token each, ASCII as 1/4
        assert zh_in >= en_in  # 6 CJK chars > 6 ASCII chars // 4

    def test_estimate_tokens_empty(self):
        """Empty segments list should produce zero tokens."""
        assert _estimate_tokens([]) == (0, 0)

    def test_cli_main_exists(self):
        """The main entry point should be callable."""
        from swatl.cli import main

        assert callable(main)

    def test_inspect_epub_output(self, tmp_path):
        """Inspect command should produce valid output for a real EPUB."""
        from typer.testing import CliRunner

        runner = CliRunner()
        fixture = tmp_path / "fixture.epub"
        create_fixture_epub(fixture)

        result = runner.invoke(app, ["inspect", str(fixture)])
        assert result.exit_code == 0
        assert "三体" in result.output
        assert "segments" in result.output.lower() or "Segments" in result.output

    def test_inspect_not_found_error(self, tmp_path):
        """Inspect should error gracefully for missing file."""
        from typer.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(app, ["inspect", "/nonexistent/book.epub"])
        assert result.exit_code != 0
        assert "Error" in result.output or "error" in result.output.lower()

    def test_glossary_init_command(self, tmp_path):
        """Glossary init should create a valid TOML file."""
        import tomlkit
        from typer.testing import CliRunner

        runner = CliRunner()
        output_file = str(tmp_path / "glossary.toml")
        result = runner.invoke(app, ["glossary-init", "--output", output_file])
        assert result.exit_code == 0
        assert tmp_path.joinpath("glossary.toml").exists()

        with open(output_file) as f:
            data = tomlkit.load(f)
        assert "name" in data
        assert data["name"] == "Default Glossary"

    def test_glossary_add_and_load(self, tmp_path):
        """Glossary add should update the file correctly."""
        from typer.testing import CliRunner

        runner = CliRunner()
        glossary_file = str(tmp_path / "glossary.toml")

        # Init first
        result = runner.invoke(app, ["glossary-init", "--output", glossary_file])
        assert result.exit_code == 0

        # Add entry
        result = runner.invoke(
            app,
            [
                "glossary-add",
                glossary_file,
                "--source",
                "三体",
                "--target",
                "Three-Body",
            ],
        )
        assert result.exit_code == 0

        # Load and verify
        from swatl.glossary import load_glossary

        g = load_glossary(glossary_file)
        assert len(g.entries) == 1
        assert g.entries[0].source == "三体"
        assert g.entries[0].target == "Three-Body"

    def test_cli_help(self):
        """CLI help should work."""
        from typer.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "swatl" in result.output.lower() or "AI" in result.output

    def test_translate_dry_run(self, tmp_path):
        """Translate with --dry-run should estimate cost and exit."""
        from typer.testing import CliRunner

        runner = CliRunner()
        fixture = tmp_path / "fixture.epub"
        create_fixture_epub(fixture)

        result = runner.invoke(
            app,
            ["translate", str(fixture), "--dry-run", "--state", str(tmp_path / "state")],
        )
        assert result.exit_code == 0
        assert "Dry run" in result.output or "dry run" in result.output.lower()


class TestCliPipelineCommands:
    """End-to-end CLI commands that previously crashed or no-op'd."""

    def _run_pipeline(self, tmp_path):
        from typer.testing import CliRunner

        from swatl.models import Segment, SegmentStatus
        from swatl.state import SegmentStore

        state = tmp_path / "state"
        store = SegmentStore(state)
        store.append_many(
            [
                Segment(
                    id="p-0001",
                    doc="text/ch01.xhtml",
                    anchor=".//p[1]",
                    tag="p",
                    source_text="第一段中文",
                    translated="First paragraph",
                    status=SegmentStatus.PROOFREAD,
                ),
                Segment(
                    id="p-0002",
                    doc="text/ch01.xhtml",
                    anchor=".//p[2]",
                    tag="p",
                    source_text="第二段中文",
                    translated="Second paragraph",
                    status=SegmentStatus.PROOFREAD,
                ),
            ]
        )
        return CliRunner(), store, state

    def test_audit_command_succeeds(self, tmp_path):
        """`audit` must accept the store's segment mapping (regression)."""
        runner, _store, state = self._run_pipeline(tmp_path)
        result = runner.invoke(app, ["audit", "--state", str(state)])
        assert result.exit_code == 0, result.output
        assert "Quality Audit" in result.output

    def test_review_auto_accept_includes_proofread(self, tmp_path):
        """`review -y` reviews proofread segments and never crashes (regression)."""
        runner, store, state = self._run_pipeline(tmp_path)
        result = runner.invoke(app, ["review", "--state", str(state), "-y"])
        assert result.exit_code == 0, result.output
        assert "No translated segments" not in result.output
        assert "2 segments reviewed" in result.output
        # Each segment must be counted exactly once (results were double-appended).
        assert "accept: 2" in result.output

    def test_back_translate_rejects_mock_provider(self, tmp_path):
        """`back-translate --provider mock` explains itself instead of crashing."""
        runner, _store, state = self._run_pipeline(tmp_path)
        result = runner.invoke(app, ["back-translate", "--state", str(state), "--provider", "mock"])
        assert "mock" in result.output.lower()
        assert "metaclass" not in result.output.lower()


class TestContextCommands:
    """`swatl context` manages named context databases."""

    def _invoke(self, *args):
        from typer.testing import CliRunner

        return CliRunner().invoke(app, list(args))

    def test_list_create_delete(self, tmp_path):
        state = str(tmp_path / "state")

        created = self._invoke("context", "create", "santi", "--state", state)
        assert created.exit_code == 0, created.output
        assert "santi" in created.output

        listing = self._invoke("context", "list", "--state", state)
        assert listing.exit_code == 0, listing.output
        assert "default" in listing.output
        assert "santi" in listing.output

        deleted = self._invoke("context", "delete", "santi", "--state", state)
        assert deleted.exit_code == 0, deleted.output

        # The default database is protected.
        protected = self._invoke("context", "delete", "default", "--state", state)
        assert protected.exit_code == 1
        assert "cannot be deleted" in protected.output

    def test_import_export_round_trip(self, tmp_path):
        state = str(tmp_path / "state")
        csv_file = tmp_path / "pairs.csv"
        csv_file.write_text(
            "source,target,entry_type,tags\n三体,Three-Body,manual,sci-fi|term\n",
            encoding="utf-8",
        )

        self._invoke("context", "create", "santi", "--state", state)
        imported = self._invoke(
            "context", "import", str(csv_file), "--state", state, "--db", "santi"
        )
        assert imported.exit_code == 0, imported.output
        assert "Imported 1 of 1" in imported.output

        out_file = tmp_path / "dump.json"
        exported = self._invoke(
            "context",
            "export",
            "--state",
            state,
            "--db",
            "santi",
            "--format",
            "json",
            "-o",
            str(out_file),
        )
        assert exported.exit_code == 0, exported.output
        assert out_file.exists()

        self._invoke("context", "create", "restored", "--state", state)
        restored = self._invoke(
            "context", "import", str(out_file), "--state", state, "--db", "restored"
        )
        assert restored.exit_code == 0, restored.output
        assert "Imported 1 of 1" in restored.output

        stats = self._invoke("context", "stats", "--state", state, "--db", "restored")
        assert "Entries: 1" in stats.output
        assert "manual" in stats.output

    def test_export_to_stdout(self, tmp_path):
        state = str(tmp_path / "state")
        self._invoke("context", "create", "d", "--state", state)
        result = self._invoke(
            "context", "export", "--state", state, "--db", "d", "--format", "csv", "-o", "-"
        )
        assert result.exit_code == 0
        assert "source,target,entry_type,tags" in result.output

    def test_missing_database_errors(self, tmp_path):
        state = str(tmp_path / "state")
        result = self._invoke("context", "export", "--state", state, "--db", "ghost")
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_bad_name_errors(self, tmp_path):
        result = self._invoke("context", "create", "../escape", "--state", str(tmp_path / "s"))
        assert result.exit_code == 1
        assert "Invalid context database name" in result.output

    def test_import_missing_file_errors(self, tmp_path):
        result = self._invoke("context", "import", str(tmp_path / "nope.json"), "--state", "s")
        assert result.exit_code == 1
        assert "file not found" in result.output
