"""End-to-end browser tests for the web GUI.

These drive a real Chromium against a real uvicorn server, which is the only
way to catch the class of bug that shipped here originally: a JavaScript syntax
error that silently disabled the whole page while the HTML still returned 200.

Playwright and its browser are optional, so the module is skipped unless they
are installed::

    uv sync --extra e2e
    uv run playwright install chromium
    uv run pytest tests/e2e -q
"""

from __future__ import annotations

import contextlib
import socket
import threading
import time
from dataclasses import dataclass, field

import pytest

pytest.importorskip("playwright.sync_api")
import uvicorn  # noqa: E402
from playwright.sync_api import Page, sync_playwright  # noqa: E402

from swatl.models import Segment, SegmentStatus  # noqa: E402
from swatl.state import SegmentStore  # noqa: E402
from swatl.web.app import app  # noqa: E402

PAGE_SIZE = 100


# ── Infrastructure ──────────────────────────────────────────────────────


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextlib.contextmanager
def _running_server():
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 15
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    if not server.started:  # pragma: no cover - environment failure
        raise RuntimeError("uvicorn did not start in time")

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@dataclass
class Gui:
    """A loaded page plus the browser errors observed while driving it."""

    page: Page
    base_url: str
    errors: list[str] = field(default_factory=list)

    def open(self, state_dir: str | None = None) -> None:
        self.page.goto(self.base_url, wait_until="networkidle")
        if state_dir is not None:
            self.page.fill("#stateDir", state_dir)
            self.page.click("button:has-text('Load')")
            self.page.wait_for_timeout(900)

    def expect_no_errors(self) -> None:
        assert self.errors == []


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def gui(browser):
    with _running_server() as base_url:
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        gui = Gui(page=page, base_url=base_url)
        page.on(
            "console",
            lambda msg: (
                gui.errors.append(f"console.{msg.type}: {msg.text}")
                if msg.type == "error"
                else None
            ),
        )
        page.on("pageerror", lambda exc: gui.errors.append(f"pageerror: {exc}"))
        page.on("requestfailed", lambda req: gui.errors.append(f"requestfailed: {req.url}"))
        page.on("dialog", lambda dialog: dialog.accept())
        yield gui
        page.close()


@pytest.fixture(scope="module")
def state_dir(tmp_path_factory):
    """A state directory with more segments than one page holds."""
    state = tmp_path_factory.mktemp("gui-state")
    store = SegmentStore(state)
    store.append_many(
        [
            Segment(
                id=f"p-{i:04d}",
                doc=f"text/ch{(i % 4) + 1:02d}.xhtml",
                anchor=f".//p[{i}]",
                tag="p",
                source_text=f"第{i}段：三体世界的中文原文。",
                translated=f"Paragraph {i}: an English translation.",
                status=SegmentStatus.PROOFREAD if i % 3 else SegmentStatus.TRANSLATED,
            )
            for i in range(1, 121)
        ]
    )
    return state


# ── Tests ───────────────────────────────────────────────────────────────


def test_page_loads_and_paginates(gui, state_dir):
    gui.open(str(state_dir))

    assert "swatl" in gui.page.title()
    assert gui.page.inner_text("#statTotal") == "120"
    assert gui.page.locator(".segment-card").count() == PAGE_SIZE
    assert f"{PAGE_SIZE} of 120 segments" in gui.page.inner_text("#segCount")

    gui.page.click("button:has-text('Load more')")
    gui.page.wait_for_timeout(800)
    assert gui.page.locator(".segment-card").count() == 120
    assert gui.page.locator("button:has-text('Load more')").count() == 0

    gui.expect_no_errors()


def test_embedded_javascript_parses(gui):
    """A parse error silently disables every handler on the page."""
    gui.open()
    assert gui.page.evaluate("typeof loadState") == "function"
    assert gui.page.evaluate("typeof renderSegments") == "function"
    assert gui.page.evaluate("typeof switchTab") == "function"
    assert gui.page.evaluate("typeof syncStateDir") == "function"
    gui.expect_no_errors()


def test_server_side_search_and_status_filter(gui, state_dir):
    gui.open(str(state_dir))

    gui.page.fill("#filter", "第7段")
    gui.page.wait_for_timeout(900)
    assert gui.page.locator(".segment-card").count() == 1
    gui.page.fill("#filter", "")
    gui.page.wait_for_timeout(900)

    gui.page.select_option("#statusFilter", "translated")
    gui.page.wait_for_timeout(900)
    assert gui.page.locator(".segment-card").count() == 40  # every third segment
    gui.page.select_option("#statusFilter", "")
    gui.expect_no_errors()


def test_segment_review_actions(gui, state_dir):
    gui.open(str(state_dir))

    gui.page.locator(".segment-card").first.click()
    gui.page.wait_for_timeout(400)
    assert gui.page.locator("#detailPanel.open").count() == 1
    assert gui.page.locator("#editTranslation").is_enabled()

    gui.page.fill("#editTranslation", "A manually edited translation.")
    gui.page.click(".detail-panel button:has-text('Save')")
    gui.page.wait_for_timeout(800)
    assert gui.page.locator("#toast").inner_text() == "Translation saved"

    gui.page.click(".detail-panel button:has-text('Accept')")
    gui.page.wait_for_timeout(800)
    assert gui.page.locator("#toast").inner_text() == "Segment accepted"

    gui.page.keyboard.press("Escape")
    gui.page.wait_for_timeout(300)
    assert gui.page.locator("#detailPanel.open").count() == 0
    gui.expect_no_errors()


def test_context_and_glossary_tabs(gui, state_dir):
    gui.open(str(state_dir))

    gui.page.click("button[data-tab='context']")
    gui.page.wait_for_timeout(500)
    gui.page.click("button:has-text('+ Add')")
    gui.page.wait_for_timeout(300)
    gui.page.fill("#ctxSource", "手动条目")
    gui.page.fill("#ctxTarget", "Manual entry")
    gui.page.click("#addContextModal button:has-text('Save')")
    gui.page.wait_for_timeout(900)
    assert gui.page.locator(".context-card").count() >= 1

    gui.page.click("button[data-tab='glossary']")
    gui.page.wait_for_timeout(500)
    gui.page.click("button:has-text('+ Add Term')")
    gui.page.wait_for_timeout(300)
    gui.page.fill("#glossSource", "三体")
    gui.page.fill("#glossTarget", "Three-Body")
    gui.page.click("#glossaryModal button:has-text('Save')")
    gui.page.wait_for_timeout(900)
    assert gui.page.locator(".glossary-entry").count() >= 1
    gui.expect_no_errors()


def test_missing_state_dir_is_reported_not_created(gui, tmp_path):
    missing = tmp_path / "nope" / "nowhere"
    gui.open(str(missing))

    assert "State directory not found" in gui.page.inner_text("#segmentList")
    assert not missing.exists()
    gui.expect_no_errors()


def test_desktop_screenshot_smoke(gui, state_dir):
    """The layout must not overflow horizontally at a normal window size."""
    gui.open(str(state_dir))
    overflow = gui.page.evaluate(
        "document.documentElement.scrollWidth > document.documentElement.clientWidth"
    )
    assert overflow is False
    gui.expect_no_errors()


def test_context_file_upload_import(gui, state_dir, tmp_path):
    """The upload path uses the /api/context/import/file endpoint."""
    import json as jsonlib

    upload = tmp_path / "pairs.json"
    upload.write_text(
        jsonlib.dumps(
            [{"source": "你好", "target": "Hello"}, {"source": "世界", "target": "World"}]
        ),
        encoding="utf-8",
    )

    gui.open(str(state_dir))
    gui.page.click("button[data-tab='context']")
    gui.page.wait_for_timeout(500)
    gui.page.click("button:has-text('Import')")
    gui.page.wait_for_timeout(300)
    gui.page.set_input_files("#importFile", str(upload))
    gui.page.click("button:has-text('Upload & Import')")
    gui.page.wait_for_timeout(1200)

    assert "Imported 2 entries" in gui.page.locator("#toast").inner_text()
    assert gui.page.locator(".context-card").count() >= 2
    gui.expect_no_errors()
