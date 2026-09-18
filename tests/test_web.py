"""Tests for the web GUI FastAPI app."""

import json
import re
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from swatl.web.app import app


class TestWebAPI:
    """Test the web API endpoints."""

    def test_index_returns_html(self):
        """GET / should serve the HTML page."""
        client = TestClient(app)
        resp = client.get("/")
        assert resp.status_code == 200
        assert "swatl" in resp.text
        assert "<html" in resp.text

    def test_get_run_not_found(self, tmp_path):
        """GET /api/run should return 404 when no run metadata exists."""
        client = TestClient(app)
        resp = client.get("/api/run", params={"state_dir": str(tmp_path)})
        assert resp.status_code == 404

    def test_get_segments_empty(self, tmp_path):
        """GET /api/segments returns empty list for an empty state dir."""
        client = TestClient(app)
        resp = client.get("/api/segments", params={"state_dir": str(tmp_path)})
        assert resp.status_code == 200
        data = resp.json()
        assert data["segments"] == []
        assert data["total"] == 0
        assert data["total_pages"] == 0

    def test_get_stats_empty(self, tmp_path):
        """GET /api/stats returns zero counts for an empty state dir."""
        client = TestClient(app)
        resp = client.get("/api/stats", params={"state_dir": str(tmp_path)})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["by_status"] == {}

    def test_state_dir_with_slashes(self, tmp_path):
        """Nested state directories must work (query param, not path param)."""
        client = TestClient(app)
        sd = tmp_path / "nested" / "state"
        resp = client.get("/api/segments", params={"state_dir": str(sd)})
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_segment_lifecycle_and_pagination(self, tmp_path):
        """Full segment CRUD via the API plus pagination and filtering."""
        from swatl.models import Segment, SegmentStatus
        from swatl.state import SegmentStore

        sd = str(tmp_path)
        store = SegmentStore(sd)
        store.append_many(
            [
                Segment(
                    id=f"p-{i:04d}",
                    doc="text/ch01.xhtml",
                    anchor=f".//p[{i}]",
                    tag="p",
                    source_text=f"段落 {i}",
                )
                for i in range(1, 8)
            ]
        )

        client = TestClient(app)

        # Pagination
        page1 = client.get("/api/segments", params={"state_dir": sd, "page": 1, "page_size": 3})
        data = page1.json()
        assert data["total"] == 7
        assert data["total_pages"] == 3
        assert len(data["segments"]) == 3
        page3 = client.get("/api/segments", params={"state_dir": sd, "page": 3, "page_size": 3})
        assert len(page3.json()["segments"]) == 1

        # Single segment fetch
        got = client.get("/api/segment/p-0001", params={"state_dir": sd})
        assert got.status_code == 200
        assert got.json()["source_text"] == "段落 1"

        # Update translation + status
        upd = client.patch(
            "/api/segment/p-0001", params={"state_dir": sd}, json={"translated": "Paragraph 1"}
        )
        assert upd.status_code == 200
        assert upd.json()["segment"]["translated"] == "Paragraph 1"

        # Accept / skip
        assert client.post("/api/accept/p-0001", params={"state_dir": sd}).status_code == 200
        assert (
            client.get("/api/segment/p-0001", params={"state_dir": sd}).json()["status"]
            == SegmentStatus.PROOFREAD
        )
        assert client.post("/api/skip/p-0002", params={"state_dir": sd}).status_code == 200

        # Regenerate clears the translation and resets the status
        assert client.post("/api/regenerate/p-0001", params={"state_dir": sd}).status_code == 200
        regenerated = client.get("/api/segment/p-0001", params={"state_dir": sd}).json()
        assert regenerated["status"] == SegmentStatus.PENDING
        assert regenerated["translated"] is None

        # Status filter + text search
        proofread = client.get(
            "/api/segments", params={"state_dir": sd, "status": "skipped"}
        ).json()
        assert proofread["total"] == 1
        found = client.get("/api/segments", params={"state_dir": sd, "q": "段落 4"}).json()
        assert found["total"] == 1
        assert found["segments"][0]["id"] == "p-0004"

        # Invalid status is a client error, not a 500
        bad = client.get("/api/segments", params={"state_dir": sd, "status": "bogus"})
        assert bad.status_code == 400

        # Stats count each unique segment exactly once
        stats = client.get("/api/stats", params={"state_dir": sd}).json()
        assert stats["total"] == 7
        assert stats["by_status"]["pending"] == 6
        assert stats["by_status"]["skipped"] == 1

    def test_update_segment_not_found(self, tmp_path):
        """PATCH for a missing segment returns 404."""
        client = TestClient(app)
        resp = client.patch(
            "/api/segment/seg-1", params={"state_dir": str(tmp_path)}, json={"translated": "test"}
        )
        assert resp.status_code == 404

    def test_accept_segment_not_found(self, tmp_path):
        """POST /api/accept for a missing segment returns 404."""
        client = TestClient(app)
        resp = client.post("/api/accept/seg-1", params={"state_dir": str(tmp_path)})
        assert resp.status_code == 404

    def test_skip_segment_not_found(self, tmp_path):
        """POST /api/skip for a missing segment returns 404."""
        client = TestClient(app)
        resp = client.post("/api/skip/seg-1", params={"state_dir": str(tmp_path)})
        assert resp.status_code == 404

    def test_regenerate_segment_not_found(self, tmp_path):
        """POST /api/regenerate for a missing segment returns 404."""
        client = TestClient(app)
        resp = client.post("/api/regenerate/seg-1", params={"state_dir": str(tmp_path)})
        assert resp.status_code == 404

    def test_list_providers_returns_list(self):
        """GET /api/config should return a list."""
        client = TestClient(app)
        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        if data:
            assert "name" in data[0]
            assert "model" in data[0]


class TestContextDBEndpoints:
    """Test Context DB CRUD API endpoints."""

    def test_list_context_empty(self, tmp_path):
        """GET /api/context?state_dir=... returns empty list when no entries."""
        client = TestClient(app)
        sd = str(tmp_path)
        resp = client.get("/api/context", params={"state_dir": sd})
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create_context_entry(self, tmp_path):
        """POST /api/context?state_dir=... creates a context entry."""
        client = TestClient(app)
        sd = str(tmp_path)
        resp = client.post(
            "/api/context",
            params={"state_dir": sd},
            json={"source_text": "你好", "translated_text": "Hello", "tags": ["test"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["entry"]["source_text"] == "你好"
        entry_id = data["entry"]["id"]

        # Verify it was persisted
        resp2 = client.get("/api/context", params={"state_dir": sd})
        entries = resp2.json()
        assert len(entries) == 1
        assert entries[0]["id"] == entry_id

    def test_search_context_entries(self, tmp_path):
        """GET /api/context/search?state_dir=...&q=... returns matching entries."""
        client = TestClient(app)
        sd = str(tmp_path)
        # Create entries
        client.post(
            "/api/context",
            params={"state_dir": sd},
            json={"source_text": "爱因斯坦", "translated_text": "Einstein"},
        )
        client.post(
            "/api/context",
            params={"state_dir": sd},
            json={"source_text": "相对论", "translated_text": "Relativity"},
        )
        resp = client.get("/api/context/search", params={"state_dir": sd, "q": "相对论"})
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 1
        assert results[0]["source_text"] == "相对论"

    def test_update_context_entry(self, tmp_path):
        """PATCH /api/context/{id}?state_dir=... updates a context entry."""
        client = TestClient(app)
        sd = str(tmp_path)
        resp = client.post(
            "/api/context",
            params={"state_dir": sd},
            json={"source_text": "你好", "translated_text": "Hello"},
        )
        entry_id = resp.json()["entry"]["id"]
        resp = client.patch(
            f"/api/context/{entry_id}",
            params={"state_dir": sd},
            json={"translated_text": "Hola"},
        )
        assert resp.status_code == 200
        assert resp.json()["entry"]["translated_text"] == "Hola"

    def test_update_nonexistent_context_entry(self, tmp_path):
        """PATCH for nonexistent entry returns 404."""
        client = TestClient(app)
        sd = str(tmp_path)
        resp = client.patch(
            "/api/context/nonexistent",
            params={"state_dir": sd},
            json={"translated_text": "test"},
        )
        assert resp.status_code == 404

    def test_delete_context_entry(self, tmp_path):
        """DELETE /api/context/{id}?state_dir=... removes a context entry."""
        client = TestClient(app)
        sd = str(tmp_path)
        resp = client.post(
            "/api/context",
            params={"state_dir": sd},
            json={"source_text": "你好", "translated_text": "Hello"},
        )
        entry_id = resp.json()["entry"]["id"]
        resp = client.delete(
            f"/api/context/{entry_id}",
            params={"state_dir": sd},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        # Verify deletion
        resp2 = client.get("/api/context", params={"state_dir": sd})
        assert len(resp2.json()) == 0

    def test_delete_nonexistent_context_entry(self, tmp_path):
        """DELETE for nonexistent entry returns 404."""
        client = TestClient(app)
        sd = str(tmp_path)
        resp = client.delete(
            "/api/context/nonexistent",
            params={"state_dir": sd},
        )
        assert resp.status_code == 404

    def test_context_stats(self, tmp_path):
        """GET /api/context/stats?state_dir=... returns statistics."""
        client = TestClient(app)
        sd = str(tmp_path)
        client.post(
            "/api/context",
            params={"state_dir": sd},
            json={"source_text": "t1", "entry_type": "segment"},
        )
        client.post(
            "/api/context",
            params={"state_dir": sd},
            json={"source_text": "t2", "entry_type": "manual"},
        )
        resp = client.get("/api/context/stats", params={"state_dir": sd})
        assert resp.status_code == 200
        stats = resp.json()
        assert stats["total"] == 2

    def test_context_filter_by_type(self, tmp_path):
        """GET /api/context?state_dir=...&entry_type=segment filters entries."""
        client = TestClient(app)
        sd = str(tmp_path)
        client.post(
            "/api/context",
            params={"state_dir": sd},
            json={"source_text": "t1", "entry_type": "segment"},
        )
        client.post(
            "/api/context",
            params={"state_dir": sd},
            json={"source_text": "t2", "entry_type": "manual"},
        )
        resp = client.get("/api/context", params={"state_dir": sd, "entry_type": "segment"})
        assert resp.status_code == 200
        entries = resp.json()
        assert len(entries) == 1
        assert entries[0]["entry_type"] == "segment"

    def test_import_text_entries(self, tmp_path):
        """POST /api/context/import/text?state_dir=... imports text as chunks."""
        client = TestClient(app)
        sd = str(tmp_path)
        resp = client.post(
            "/api/context/import/text",
            params={"state_dir": sd},
            data={
                "text": "Hello world this is a test of text import.",
                "source_name": "test.txt",
                "chunk_size": "100",
                "overlap": "0",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["entries_created"] >= 1

    def test_import_json_entries(self, tmp_path):
        """POST /api/context/import/json?state_dir=... imports JSON pairs."""
        client = TestClient(app)
        sd = str(tmp_path)
        json_data = json.dumps(
            [
                {"source": "你好", "target": "Hello"},
                {"source": "世界", "target": "World"},
            ]
        )
        resp = client.post(
            "/api/context/import/json",
            params={"state_dir": sd},
            data={"content": json_data, "source_name": "test.json"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["entries_created"] == 2

    def test_prefill_from_segments(self, tmp_path):
        """POST /api/context/prefill?state_dir=... creates entries from segments."""
        client = TestClient(app)
        sd = str(tmp_path)
        resp = client.post("/api/context/prefill", params={"state_dir": sd})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["entries_created"] == 0  # no segments


class TestGlossaryAPI:
    """Test glossary CRUD API endpoints."""

    def test_list_glossary_empty(self, tmp_path):
        """GET /api/glossary?state_dir=... returns empty entries when no glossary."""
        client = TestClient(app)
        sd = str(tmp_path)
        resp = client.get("/api/glossary", params={"state_dir": sd})
        assert resp.status_code == 200
        data = resp.json()
        assert data["entries"] == []

    def test_add_glossary_term(self, tmp_path):
        """POST /api/glossary?state_dir=... adds a term."""
        client = TestClient(app)
        sd = str(tmp_path)
        resp = client.post(
            "/api/glossary",
            params={"state_dir": sd},
            json={"source": "三体", "target": "Three-Body", "domain": "sci-fi"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["entries"] == 1
        # Verify it was persisted
        resp2 = client.get("/api/glossary", params={"state_dir": sd})
        assert len(resp2.json()["entries"]) == 1
        assert resp2.json()["entries"][0]["source"] == "三体"

    def test_delete_glossary_term(self, tmp_path):
        """DELETE /api/glossary/{index}?state_dir=... removes a term."""
        client = TestClient(app)
        sd = str(tmp_path)
        # Add a term first
        client.post(
            "/api/glossary", params={"state_dir": sd}, json={"source": "测试", "target": "Test"}
        )
        # Delete it
        resp = client.delete("/api/glossary/0", params={"state_dir": sd})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["entries"] == 0


class TestWebUIAssets:
    """Guards for the single-page frontend served at ``/``.

    A JS syntax error in the embedded script silently disables the whole GUI,
    so it is checked explicitly rather than only asserting the HTML loads.
    """

    def test_index_contains_script(self):
        client = TestClient(app)
        html = client.get("/").text
        assert "<script>" in html and "</script>" in html
        assert 'id="segmentList"' in html
        assert 'id="stateDir"' in html

    def test_script_has_no_mangled_escapes(self):
        """Python escape sequences must not leak into the emitted JavaScript."""
        client = TestClient(app)
        html = client.get("/").text
        assert "\\'" not in html, "backslash-escaped quote leaked into the page"

    def test_script_is_valid_javascript(self, tmp_path):
        """Run ``node --check`` on the embedded script when node is available."""
        node = shutil.which("node")
        if not node:
            pytest.skip("node is not installed")
        client = TestClient(app)
        html = client.get("/").text
        script = re.search(r"<script>(.*)</script>", html, re.DOTALL)
        assert script is not None
        js_file = tmp_path / "page.js"
        js_file.write_text(script.group(1), encoding="utf-8")
        proc = subprocess.run(
            [node, "--check", str(js_file)], capture_output=True, text=True, check=False
        )
        assert proc.returncode == 0, proc.stderr


class TestReadOnlyEndpoints:
    """GET endpoints must never create the state directory they are asked about."""

    def test_missing_state_dir_is_reported_and_not_created(self, tmp_path):
        client = TestClient(app)
        missing = tmp_path / "does" / "not" / "exist"

        resp = client.get("/api/segments", params={"state_dir": str(missing)})
        assert resp.status_code == 200
        assert resp.json()["state_dir_exists"] is False

        stats = client.get("/api/stats", params={"state_dir": str(missing)})
        assert stats.status_code == 200
        assert stats.json()["state_dir_exists"] is False

        assert client.get("/api/context", params={"state_dir": str(missing)}).json() == []
        assert (
            client.get("/api/context/stats", params={"state_dir": str(missing)}).json()["total"]
            == 0
        )
        assert (
            client.get("/api/glossary", params={"state_dir": str(missing)}).json()["entries"] == []
        )

        assert not missing.exists(), "read-only endpoints created the state directory"

    def test_existing_state_dir_is_reported(self, tmp_path):
        client = TestClient(app)
        (tmp_path / "segments.jsonl").write_text("", encoding="utf-8")
        resp = client.get("/api/segments", params={"state_dir": str(tmp_path)})
        assert resp.json()["state_dir_exists"] is True
