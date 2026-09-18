"""Glossary loader and manager."""

from __future__ import annotations

from pathlib import Path

import tomlkit

from swatl.models import Glossary, GlossaryEntry


def load_glossary(path: str | Path) -> Glossary:
    """Load a glossary from a TOML file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Glossary file not found: {path}")

    with open(path, encoding="utf-8") as f:
        data = tomlkit.load(f)

    entries_data = data.get("entries", [])
    if isinstance(entries_data, list):
        entries = []
        for entry in entries_data:
            if isinstance(entry, dict):
                entries.append(
                    GlossaryEntry(
                        source=str(entry.get("source", "")),
                        target=str(entry.get("target", "")),
                        domain=str(entry.get("domain", "")),
                    )
                )
    else:
        entries = []

    return Glossary(
        name=str(data.get("name", "")),
        pair=list(data.get("pair", ["zh", "en"])),
        entries=entries,
    )


def save_glossary(glossary: Glossary, path: str | Path) -> None:
    """Save a glossary to a TOML file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    doc = tomlkit.document()
    doc.add("name", glossary.name)
    doc.add("pair", glossary.pair)

    entry_array = tomlkit.aot()  # array of tables (proper TOML for entries)
    for entry in glossary.entries:
        tbl = tomlkit.table()
        tbl["source"] = entry.source
        tbl["target"] = entry.target
        if entry.domain:
            tbl["domain"] = entry.domain
        entry_array.append(tbl)

    doc.add("entries", entry_array)

    with open(path, "w", encoding="utf-8") as f:
        tomlkit.dump(doc, f)


def create_default_glossary() -> Glossary:
    """Create a default empty glossary with zh→en pair."""
    return Glossary(name="Default Glossary", pair=["zh", "en"])
