"""CLI entry point for swatl."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel

app = typer.Typer(
    name="swatl",
    help="AI translation and proofreading studio for EPUB books.",
    add_completion=False,
)

console = Console()
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("swatl")

# Third-party libraries log one line per HTTP request at INFO; that noise would
# swamp the CLI's own progress output.
for _noisy in (
    "httpx",
    "httpcore",
    "urllib3",
    "openai",
    "sentence_transformers",
    "huggingface_hub",
    "filelock",
    "faiss",
    "joblib",
):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

DEFAULT_STATE_DIR = ".swatl-state"
DEFAULT_PROVIDER = "deepseek"


def _get_provider_config(provider_name: str) -> dict[str, Any]:
    """Get provider config from environment (for CLI simplicity)."""
    from swatl.config import load_providers

    configs = load_providers()
    if provider_name not in configs:
        console.print(f"[yellow]Provider '{provider_name}' not found in config.[/yellow]")
        console.print("  Use `--config` to specify a config file, or set env vars.")
        # Fall back to defaults
        return {
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "api_key_env": "DEEPSEEK_API_KEY",
        }
    cfg = configs[provider_name]
    return {
        "base_url": cfg.base_url,
        "model": cfg.model,
        "api_key_env": cfg.api_key_env,
    }


def _resolve_provider_config(provider_name: str):
    """Build a :class:`ProviderConfig` for *provider_name* (config file + defaults)."""
    from swatl.models import ProviderConfig

    cfg = _get_provider_config(provider_name)
    return ProviderConfig(
        type="openai-compatible",
        base_url=cfg.get("base_url", ""),
        model=cfg.get("model", ""),
        api_key_env=cfg.get("api_key_env", ""),
    )


def _build_provider(provider: str, target_lang: str = "en"):
    """Construct a provider for a CLI command.

    ``--provider mock`` yields the deterministic offline provider so the whole
    pipeline can be exercised end-to-end without API keys. Returns
    ``(provider, ProviderConfig)``.
    """
    from swatl.providers.mock import MockProvider

    cfg = _resolve_provider_config(provider)
    if provider == "mock":
        console.print("[bold blue]Using MockProvider (testing mode)[/bold blue]")
        return MockProvider(name="mock", target_lang=target_lang), cfg

    from swatl.config import get_api_key
    from swatl.providers.openai_compat import OpenAICompatible

    try:
        api_key = get_api_key(cfg)
    except OSError as e:
        console.print(f"[red]API key not set for env var '{cfg.api_key_env}'[/red]")
        console.print("  Set the environment variable and try again.")
        raise SystemExit(1) from e

    return (
        OpenAICompatible(base_url=cfg.base_url, model=cfg.model, api_key=api_key),
        cfg,
    )


@app.command()
def inspect(
    epub: str = typer.Argument(..., help="Path to the EPUB file to inspect."),
    glossary: str | None = typer.Option(None, "--glossary", "-g", help="Path to glossary TOML."),
) -> None:
    """Inspect an EPUB file: show metadata, segment count, and cost estimates."""
    from swatl.ingest import extract_epub, extract_segments_from_epub

    try:
        info, epub_dir = extract_epub(epub)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1) from e

    segments, doc_count = extract_segments_from_epub(
        epub_dir,
        info.spine_items,
        info.mime_types,
        info.language,
        extra_docs=info.nav_items,
    )

    # Estimate tokens and costs
    tokens_in, tokens_out = _estimate_tokens(segments)

    # Cost estimates (per million tokens)
    costs = {
        "DeepSeek": (0.14, 0.28),  # $0.14/M input, $0.28/M output
        "Qwen3-MT": (0.70, 1.40),  # $0.70/M input, $1.40/M output
        "GPT-4o": (2.50, 10.0),  # approximate
        "Claude Sonnet": (3.00, 15.0),  # approximate
    }

    console.print(
        Panel(
            f"File:       {Path(epub).name}\n"
            f"Title:      {info.title}\n"
            f"Author:     {info.author or 'Unknown'}\n"
            f"Version:    {info.epub_version}\n"
            f"Language:   {info.language}\n"
            f"Documents:  {doc_count}\n"
            f"Spine:      {len(info.spine_items)} documents\n"
            f"Segments:   {len(segments)}\n"
            f"Tokens:     ~{tokens_in:,} in / ~{tokens_out:,} out\n"
            + "\n".join(
                f"  {name}: ~${(t_in * cost_in / 1e6):.2f} / ~${(t_out * cost_out / 1e6):.2f}"
                for name, (cost_in, cost_out), (t_in, t_out) in zip(
                    costs, costs.values(), [(tokens_in, tokens_out)] * len(costs), strict=True
                )
            ),
            title="EPUB Info",
            subtitle="swatl",
        )
    )


@app.command()
def translate(
    epub: str = typer.Argument(..., help="Path to the EPUB file to translate."),
    target: str = typer.Option(
        "en", "--target", "-t", help="Target language (ISO code, e.g. 'en')."
    ),
    provider: str = typer.Option(
        DEFAULT_PROVIDER, "--provider", "-p", help="Provider name from config."
    ),
    state: str = typer.Option(
        DEFAULT_STATE_DIR, "--state", "-s", help="State directory for checkpoints."
    ),
    resume: bool = typer.Option(True, "--resume/--no-resume", help="Resume from last checkpoint."),
    concurrency: int = typer.Option(4, "--concurrency", "-c", help="Max parallel LLM calls."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Estimate cost without making API calls."
    ),
    glossary_path: str | None = typer.Option(
        None, "--glossary", "-g", help="Path to glossary TOML."
    ),
    translation_memory: str | None = typer.Option(
        None, "--translation-memory", "-m", help="Path to translation memory JSON file."
    ),
    style: str = typer.Option(
        "formal",
        "--style",
        "-st",
        help="Translation tone: formal, casual, literary, or technical.",
    ),
) -> None:
    """Translate an EPUB book using an LLM provider."""
    from swatl.glossary import load_glossary
    from swatl.ingest import extract_epub, extract_segments_from_epub
    from swatl.models import RunMetadata
    from swatl.state import SegmentStore
    from swatl.translate import Translator

    try:
        info, epub_dir = extract_epub(epub)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1) from e

    console.print("[bold]Extracting segments...[/bold]")
    segments, doc_count = extract_segments_from_epub(
        epub_dir,
        info.spine_items,
        info.mime_types,
        info.language,
        extra_docs=info.nav_items,
    )
    console.print(f"  {len(segments)} segments from {doc_count} documents")

    # Load glossary
    glossary = None
    if glossary_path:
        glossary = load_glossary(glossary_path)

    # Load/create state
    state_dir = Path(state)
    store = SegmentStore(state_dir)

    if resume:
        existing = store.load_segments()
        if existing:
            console.print(f"[yellow]Resuming: {len(existing)} existing segments found.[/yellow]")
            segments = list(existing.values())
        else:
            # Save initial segments
            store.append_many(segments)
    else:
        store.append_many(segments)

    # Estimate tokens
    tokens_in, tokens_out = _estimate_tokens(segments)
    cost_deepseek = (tokens_in * 0.14 + tokens_out * 0.28) / 1e6
    console.print(f"[bold]Estimated cost @ DeepSeek: ~${cost_deepseek:.2f}[/bold]")

    if dry_run:
        console.print("[green]Dry run — no API calls made.[/green]")
        return

    # Create provider
    prov, cfg = _build_provider(provider, target)

    console.print(f"[bold]Translating with {prov.provider_type} ({cfg.model})...[/bold]")
    console.print(f"  Concurrency: {concurrency}, Target: {target}")

    trans = Translator(
        provider=prov,
        source_lang=info.language,
        target_lang=target,
        concurrency=concurrency,
        style=style,
    )

    # Set up translation memory if provided
    if translation_memory:
        from swatl.translate.translation_memory import TranslationMemory

        tm_path = Path(translation_memory)
        tm = TranslationMemory(memory_file=tm_path)
        trans.translation_memory = tm
        console.print(f"[bold]Translation memory loaded: {tm.count()} entries[/bold]")

    # Run translation
    segments = asyncio.run(trans.translate_all(segments, glossary))

    # Save results
    translated = [s for s in segments if s.status == "translated"]
    store.append_many(translated)

    # Save run metadata
    run = RunMetadata(
        book_title=info.title,
        book_author=info.author,
        book_lang=info.language,
        book_version=info.epub_version,
        epub_path=str(Path(epub).resolve()),
        state_dir=str(epub_dir.resolve()),
        pair=[info.language, target],
        provider=cfg.model,
        total_segments=len(segments),
        stages_completed=["extract", "translate"],
        total_tokens_in=tokens_in,
        total_tokens_out=tokens_out,
        estimated_cost_usd=cost_deepseek,
    )
    store.save_run(run)

    # Show summary
    status_counts = store.status_counts()
    console.print("")
    console.print(
        Panel(
            f"Total:     {len(segments)} segments\n"
            f"Translated: {status_counts.get('translated', 0)}\n"
            f"Failed:     {status_counts.get('failed', 0)}\n"
            f"Tokens in:  ~{tokens_in:,}\n"
            f"Tokens out: ~{tokens_out:,}\n"
            f"Est. cost:  ~${cost_deepseek:.2f} (DeepSeek)\n"
            f"State dir:  {state_dir}",
            title="Translation Summary",
        )
    )

    console.print("\n[green]✓ Translation complete![/green]")
    console.print(
        f"  Next: `swatl proofread --state {state}` → `swatl export --state {state} -o output.epub`"
    )


@app.command()
def proofread(
    state: str = typer.Option(DEFAULT_STATE_DIR, "--state", "-s", help="State directory."),
    provider: str = typer.Option(DEFAULT_PROVIDER, "--provider", "-p", help="Provider name."),
    concurrency: int = typer.Option(4, "--concurrency", "-c", help="Max parallel LLM calls."),
    glossary_path: str | None = typer.Option(
        None, "--glossary", "-g", help="Path to glossary TOML."
    ),
) -> None:
    """Run a proofreading pass on translated segments."""
    from swatl.glossary import load_glossary
    from swatl.state import SegmentStore

    store = SegmentStore(state)
    segments = store.load_segments()

    glossary = None
    if glossary_path:
        glossary = load_glossary(glossary_path)

    prov, _cfg = _build_provider(provider)

    from swatl.proofread import Proofreader

    proofreader = Proofreader(prov, concurrency=concurrency)
    segments_list = list(segments.values())
    segments_list = asyncio.run(proofreader.proofread_all(segments_list, glossary))

    # Save results
    store.append_many(segments_list)

    status_counts = store.status_counts()
    console.print(
        f"Proofreading complete: {status_counts.get('proofread', 0)} proofread, "
        f"{status_counts.get('translated', 0)} still untranslated"
    )


@app.command()
def review(
    state: str = typer.Option(DEFAULT_STATE_DIR, "--state", "-s", help="State directory."),
    glossary_path: str | None = typer.Option(
        None, "--glossary", "-g", help="Path to glossary TOML."
    ),
    skip_interactive: bool = typer.Option(
        False, "--skip-interactive", "-y", help="Auto-accept all segments without prompting."
    ),
) -> None:
    """Review translated segments: accept, edit, skip, or regenerate."""
    from rich.prompt import Prompt

    from swatl.glossary import load_glossary
    from swatl.review.reviewer import ReviewSession
    from swatl.state import SegmentStore

    store = SegmentStore(state)
    glossary = None
    if glossary_path:
        glossary = load_glossary(glossary_path)

    session = ReviewSession(store=store, glossary=glossary)
    session.load_segments()

    if session.total == 0:
        console.print("[yellow]No translated segments to review.[/yellow]")
        return

    console.print(f"[bold]Review session:[/bold] {session.total} segments")
    console.print(
        "  Commands: [cyan]n[/cyan] (next)  [cyan]p[/cyan] (prev)  [cyan]a[/cyan] (accept)  "
        "[cyan]e[/cyan] (edit)  [cyan]s[/cyan] (skip)  [cyan]r[/cyan] (regenerate)  "
        "[cyan]q[/cyan] (quit)"
    )
    console.print("")

    item = session.current()
    while item is not None:
        seg = item.segment
        # Display segment
        console.print(f"[bold]{seg.id}[/bold] ({seg.doc}:{seg.anchor}) [{seg.status}]")
        console.print(
            f"  Source:     {seg.source_text[:200]}{'...' if len(seg.source_text) > 200 else ''}"
        )
        if seg.translated:
            console.print(
                f"  Translated: {seg.translated[:200]}{'...' if len(seg.translated) > 200 else ''}"
            )
        if item.issues:
            console.print("[red]  Issues:[/red]")
            for issue in item.issues[:5]:
                console.print(f"    - [{issue.get('severity', '')}] {issue.get('description', '')}")

        if skip_interactive:
            session.accept()
            console.print(f"  [dim]Auto-accepted {seg.id}[/dim]")
            item = session.next_item()
            continue

        action = Prompt.ask(
            "  Action",
            choices=["n", "p", "a", "e", "s", "r", "q"],
            default="n",
        )
        if action == "n":
            item = session.next_item()
            continue
        if action == "p":
            item = session.prev_item()
            continue
        if action == "q":
            console.print("  [dim]Quit. Saving session.[/dim]")
            break

        # accept/edit/skip/regenerate record their own result on the session.
        if action == "a":
            session.accept()
            console.print(f"  [green]✓ Accepted {seg.id}[/green]")
        elif action == "e":
            new_text = Prompt.ask(
                "  New translation",
                default=seg.translated or "",
            )
            session.edit(new_text)
            console.print(f"  [green]✓ Edited {seg.id}[/green]")
        elif action == "s":
            session.skip()
            console.print(f"  [yellow]Skipped {seg.id}[/yellow]")
        elif action == "r":
            session.regenerate()
            console.print(f"  [yellow]Regenerated {seg.id}[/yellow]")

        item = session.next_item()

    session.done()
    console.print("")
    console.print(session.summary())
    console.print("[green]✓ Review complete![/green]")


@app.command()
def audit(
    state: str = typer.Option(DEFAULT_STATE_DIR, "--state", "-s", help="State directory."),
    glossary_path: str | None = typer.Option(
        None, "--glossary", "-g", help="Path to glossary TOML."
    ),
    source_lang: str = typer.Option(
        "zh", "--source-lang", help="Source language (zh, ja, etc.) for language-aware audit."
    ),
) -> None:
    """Run a quality audit on translated segments."""
    from swatl.audit import audit_segments
    from swatl.glossary import load_glossary
    from swatl.state import SegmentStore

    store = SegmentStore(state)
    segments = list(store.load_segments().values())

    glossary = None
    if glossary_path:
        glossary = load_glossary(glossary_path)

    report = audit_segments(segments, glossary, source_lang=source_lang)
    console.print(report.summary())


@app.command()
def export(
    state: str = typer.Option(DEFAULT_STATE_DIR, "--state", "-s", help="State directory."),
    output: str = typer.Option("translated.epub", "--output", "-o", help="Output EPUB path."),
    bilingual: bool = typer.Option(False, "--bilingual", "-b", help="Export bilingual EPUB."),
) -> None:
    """Export the translated EPUB with in-place text replacement."""
    from swatl.state import SegmentStore
    from swatl.writeback.writer import writeback_segments

    store = SegmentStore(state)
    run = store.load_run()
    if not run:
        console.print("[red]No run metadata found. Run `translate` first.[/red]")
        raise SystemExit(1)

    segments = store.load_segments()
    segments_list = list(segments.values())

    epub_dir = Path(run.state_dir) if run.state_dir else Path(state) / "_epub"
    if not epub_dir.exists():
        # Try to extract from the source EPUB
        from swatl.ingest import extract_epub

        src_epub = Path(run.epub_path)
        if src_epub.exists():
            _, epub_dir = extract_epub(src_epub, output_dir=epub_dir)
        else:
            console.print(f"[red]Source EPUB not found: {run.epub_path}[/red]")
            raise SystemExit(1)

    result_path = writeback_segments(
        epub_dir,
        segments_list,
        target_lang=run.pair[-1] if len(run.pair) > 1 else "en",
        output_path=output,
        bilingual=bilingual,
    )
    if bilingual:
        console.print("[green]✓ Bilingual export complete![/green]")
    else:
        console.print(f"[green]✓ Export complete: {result_path}[/green]")


@app.command()
def back_translate(
    state: str = typer.Option(DEFAULT_STATE_DIR, "--state", "-s", help="State directory."),
    sample_size: int = typer.Option(
        20, "--sample", "-n", help="Number of segments to back-translate."
    ),
    provider: str = typer.Option(
        DEFAULT_PROVIDER, "--provider", "-p", help="Provider name for back-translation."
    ),
    output: str = typer.Option(
        "back_translation_report.json", "--output", "-o", help="Output JSON report."
    ),
) -> None:
    """Run back-translation quality verification on a sample of translated segments."""
    from swatl.config import get_api_key
    from swatl.quality.back_translation import (
        back_translate_sample,
        save_report,
    )
    from swatl.state import SegmentStore

    state_dir = Path(state)
    store = SegmentStore(state_dir)
    segments = list(store.load_segments().values())
    translated = [
        s for s in segments if s.translated and s.status in ("translated", "proofread", "edited")
    ]

    if not translated:
        console.print("[red]No translated segments found. Run 'translate' first.[/red]")
        raise SystemExit(1)

    console.print(
        f"[bold]Back-translation check: {len(translated)} segments, sampling {sample_size}[/bold]"
    )

    if provider == "mock":
        console.print(
            "[yellow]Back-translation needs a real LLM; 'mock' cannot score quality.[/yellow]"
        )
        console.print("  Use a configured provider, e.g. --provider deepseek.")
        raise SystemExit(1)

    cfg = _resolve_provider_config(provider)
    try:
        api_key = get_api_key(cfg)
    except OSError as _e:
        console.print(f"[red]API key not set for env var '{cfg.api_key_env}'[/red]")
        raise SystemExit(1) from _e

    console.print(f"[bold]Sending {sample_size} segments to {cfg.base_url} ({cfg.model})...[/bold]")

    import asyncio

    report = asyncio.run(
        back_translate_sample(
            translated,
            api_base_url=cfg.base_url,
            api_key=api_key,
            model=cfg.model,
            sample_size=sample_size,
        )
    )

    console.print(f"[bold]{report.summary()}[/bold]")

    if report.warnings > 0 or report.critical > 0:
        console.print(
            "[yellow]⚠ Some segments may need attention. See report for details.[/yellow]"
        )
        # Print critical/warning details
        for d in report.details:
            if d["flag"] in ("warning", "critical"):
                console.print(
                    f"  [{d['flag'].upper()}] {d['segment_id']}: similarity={d['similarity']:.2f}"
                )
                console.print(f"    Source:     {d['source'][:80]}")
                console.print(f"    Translation: {d['translated'][:80]}")
                console.print(f"    Back-trans:  {d['back_translated'][:80]}")

    save_report(report, output)
    console.print(f"[green]✓ Report saved to {output}[/green]")


@app.command()
def config(
    provider: str = typer.Argument(..., help="Provider name."),
) -> None:
    """Test provider connectivity."""
    cfg = _get_provider_config(provider)
    console.print(f"Provider '{provider}':")
    console.print(f"  Model:  {cfg['model']}")
    console.print(f"  Base:   {cfg['base_url']}")
    console.print(f"  Key env: {cfg.get('api_key_env', '(not set)')}")


def _estimate_tokens(segments: list, source_lang: str = "zh") -> tuple[int, int]:
    """Rough token estimate for CJK→English translation."""
    total_in = 0
    total_out = 0
    for seg in segments:
        text = seg.source_text
        cjk = len([c for c in text if "\u4e00" <= c <= "\u9fff"])
        hira = len([c for c in text if "\u3040" <= c <= "\u309f"])
        kata = len([c for c in text if "\u30a0" <= c <= "\u30ff"])
        total_cjk = cjk + hira + kata if source_lang == "ja" else cjk
        ascii = len(text) - total_cjk
        # CJK chars count as ~1 token each, ASCII ~1/4
        total_in += total_cjk + ascii // 4
        # Output tokens vary by pair: ja→en has more particles (~1.2x), zh→en similar
        multiplier = 1.2 if source_lang == "ja" else 1.0
        total_out += int((total_cjk // 2 + ascii // 4) * multiplier)
    return total_in, total_out


@app.command()
def glossary_init(
    output: str = typer.Option("glossary.toml", "--output", "-o", help="Output glossary file."),
) -> None:
    """Initialize an empty glossary file."""
    from swatl.glossary import create_default_glossary, save_glossary

    g = create_default_glossary()
    save_glossary(g, output)
    console.print(f"[green]✓ Glossary initialized: {output}[/green]")
    console.print("  Add entries with [[entries]] sections in TOML format.")


@app.command()
def glossary_add(
    glossary_file: str = typer.Argument(..., help="Path to glossary TOML."),
    source: str = typer.Option(..., "--source", "-s", help="Source term."),
    target: str = typer.Option(..., "--target", "-t", help="Target translation."),
    domain: str = typer.Option("", "--domain", "-d", help="Domain/category (optional)."),
) -> None:
    """Add a term to a glossary file."""
    from swatl.glossary import load_glossary, save_glossary
    from swatl.models import GlossaryEntry

    g = load_glossary(glossary_file)
    g.entries.append(GlossaryEntry(source=source, target=target, domain=domain))
    save_glossary(g, glossary_file)
    console.print(f"[green]✓ Added '{source}' → '{target}' to {glossary_file}[/green]")


@app.command()
def web(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Bind host."),
    port: int = typer.Option(8080, "--port", "-p", help="Bind port."),
) -> None:
    """Launch the web GUI."""
    console.print(f"[bold]Starting swatl web GUI at http://{host}:{port}[/bold]")
    console.print("  Press Ctrl+C to stop.")
    from swatl.web import run_server

    run_server(host, port)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
