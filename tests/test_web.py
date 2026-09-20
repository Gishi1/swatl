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


class TestImportValidation:
    """Import endpoints must reject bad input cleanly and stay bounded."""

    def test_malformed_json_import_is_a_client_error(self, tmp_path):
        client = TestClient(app)
        resp = client.post(
            "/api/context/import/json",
            params={"state_dir": str(tmp_path)},
            data={"content": "{not json", "source_name": "bad.json"},
        )
        assert resp.status_code == 400
        assert "Invalid JSON" in resp.json()["detail"]

    def test_overlap_larger_than_chunk_size_is_clamped(self, tmp_path):
        """A huge overlap used to explode one paste into thousands of chunks."""
        client = TestClient(app)
        resp = client.post(
            "/api/context/import/text",
            params={"state_dir": str(tmp_path)},
            data={
                "text": "字" * 2000,
                "source_name": "t",
                "chunk_size": "500",
                "overlap": "600",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["chunks_total"] <= 10

    def test_zero_chunk_size_is_rejected(self, tmp_path):
        client = TestClient(app)
        resp = client.post(
            "/api/context/import/text",
            params={"state_dir": str(tmp_path)},
            data={"text": "hello", "chunk_size": "0", "overlap": "0"},
        )
        assert resp.status_code == 422

    def test_file_upload_json_import(self, tmp_path):
        client = TestClient(app)
        payload = json.dumps([{"source": "你好", "target": "Hello"}]).encode("utf-8")
        resp = client.post(
            "/api/context/import/file",
            params={"state_dir": str(tmp_path)},
            files={"file": ("pairs.json", payload, "application/json")},
        )
        assert resp.status_code == 200
        assert resp.json()["entries_created"] == 1

    def test_file_upload_html_import(self, tmp_path):
        client = TestClient(app)
        html = "<html><body><p>第一段</p><p>第二段</p></body></html>".encode()
        resp = client.post(
            "/api/context/import/file",
            params={"state_dir": str(tmp_path)},
            files={"file": ("page.html", html, "text/html")},
            data={"chunk_size": "50", "overlap": "10"},
        )
        assert resp.status_code == 200
        assert resp.json()["entries_created"] >= 1


class TestProviderConfigEndpoint:
    def test_add_provider_reports_config_path(self, tmp_path, monkeypatch):
        """Saving a provider must report where the config was written."""
        from swatl import config as config_module

        target = tmp_path / "providers.toml"
        monkeypatch.setattr(config_module, "_find_default_config", lambda: target)

        client = TestClient(app)
        resp = client.post(
            "/api/config",
            json={
                "name": "myprovider",
                "base_url": "https://api.example.com/v1",
                "model": "my-model",
                "api_key_env": "MY_KEY",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["config_path"] == str(target)
        assert target.exists()


class TestContextDatabasesAPI:
    """Named context databases over the HTTP API."""

    def test_list_create_and_isolate(self, tmp_path):
        client = TestClient(app)
        sd = {"state_dir": str(tmp_path)}

        listing = client.get("/api/context/databases", params=sd).json()
        assert [d["name"] for d in listing] == ["default"]

        created = client.post("/api/context/databases", params=sd, json={"name": "santi"})
        assert created.status_code == 200
        assert [d["name"] for d in created.json()["databases"]] == ["default", "santi"]

        client.post(
            "/api/context",
            params={**sd, "db": "santi"},
            json={"source_text": "三体", "translated_text": "Three-Body"},
        )
        assert len(client.get("/api/context", params=sd).json()) == 0
        assert len(client.get("/api/context", params={**sd, "db": "santi"}).json()) == 1

    def test_duplicate_name_is_a_conflict(self, tmp_path):
        client = TestClient(app)
        sd = {"state_dir": str(tmp_path)}
        client.post("/api/context/databases", params=sd, json={"name": "dup"})
        again = client.post("/api/context/databases", params=sd, json={"name": "dup"})
        assert again.status_code == 409

    def test_invalid_name_is_rejected(self, tmp_path):
        client = TestClient(app)
        sd = {"state_dir": str(tmp_path)}
        resp = client.post("/api/context/databases", params=sd, json={"name": "../escape"})
        assert resp.status_code == 400
        assert not (tmp_path.parent / "escape.json").exists()

        bad = client.get("/api/context", params={**sd, "db": "../escape"})
        assert bad.status_code == 400

    def test_copy_from(self, tmp_path):
        client = TestClient(app)
        sd = {"state_dir": str(tmp_path)}
        client.post("/api/context", params=sd, json={"source_text": "a", "translated_text": "A"})
        client.post(
            "/api/context/databases",
            params=sd,
            json={"name": "clone", "copy_from": "default"},
        )
        assert len(client.get("/api/context", params={**sd, "db": "clone"}).json()) == 1

    def test_delete_database(self, tmp_path):
        client = TestClient(app)
        sd = {"state_dir": str(tmp_path)}
        client.post("/api/context/databases", params=sd, json={"name": "temp"})
        assert client.delete("/api/context/databases/temp", params=sd).status_code == 200
        assert client.delete("/api/context/databases/temp", params=sd).status_code == 404
        assert client.delete("/api/context/databases/default", params=sd).status_code == 400

    def test_export_downloads_json_and_csv(self, tmp_path):
        client = TestClient(app)
        sd = {"state_dir": str(tmp_path)}
        client.post(
            "/api/context",
            params=sd,
            json={"source_text": "三体", "translated_text": "Three-Body", "tags": ["term"]},
        )

        js = client.get("/api/context/export", params={**sd, "format": "json"})
        assert js.status_code == 200
        assert js.headers["content-disposition"] == 'attachment; filename="context-default.json"'
        assert js.json()[0]["source_text"] == "三体"

        csv_resp = client.get("/api/context/export", params={**sd, "format": "csv"})
        assert csv_resp.status_code == 200
        assert csv_resp.text.splitlines()[0] == "source,target,entry_type,tags"

        bad = client.get("/api/context/export", params={**sd, "format": "xml"})
        assert bad.status_code == 400

    def test_export_missing_database_is_404(self, tmp_path):
        client = TestClient(app)
        resp = client.get("/api/context/export", params={"state_dir": str(tmp_path), "db": "nope"})
        assert resp.status_code == 404

    def test_export_import_round_trip_through_the_api(self, tmp_path):
        client = TestClient(app)
        sd = {"state_dir": str(tmp_path)}
        client.post(
            "/api/context",
            params=sd,
            json={"source_text": "三体", "translated_text": "Three-Body", "entry_type": "manual"},
        )
        payload = client.get("/api/context/export", params={**sd, "format": "json"}).text

        client.post("/api/context/databases", params=sd, json={"name": "restored"})
        imported = client.post(
            "/api/context/import/json",
            params={**sd, "db": "restored"},
            data={"content": payload, "source_name": "backup.json"},
        )
        assert imported.status_code == 200
        assert imported.json()["entries_created"] == 1

        entries = client.get("/api/context", params={**sd, "db": "restored"}).json()
        assert entries[0]["entry_type"] == "manual"
        assert entries[0]["translated_text"] == "Three-Body"

    def test_import_text_and_prefill_target_the_selected_db(self, tmp_path):
        client = TestClient(app)
        sd = {"state_dir": str(tmp_path)}
        client.post("/api/context/databases", params=sd, json={"name": "notes"})

        imported = client.post(
            "/api/context/import/text",
            params={**sd, "db": "notes"},
            data={"text": "一些文本" * 40, "chunk_size": "50", "overlap": "10"},
        )
        assert imported.status_code == 200
        assert imported.json()["db"] == "notes"
        assert len(client.get("/api/context", params={**sd, "db": "notes"}).json()) >= 1
        assert client.get("/api/context", params=sd).json() == []

    def test_stats_report_the_database(self, tmp_path):
        client = TestClient(app)
        sd = {"state_dir": str(tmp_path)}
        client.post("/api/context/databases", params=sd, json={"name": "x"})
        stats = client.get("/api/context/stats", params={**sd, "db": "x"}).json()
        assert stats["db"] == "x"
        assert stats["total"] == 0


class TestAccessToken:
    """The optional token protects /api without getting in the way locally."""

    @staticmethod
    def _client():
        from swatl.web.app import set_access_token

        return TestClient(app), set_access_token

    def test_api_is_open_by_default(self, tmp_path):
        pytest.importorskip("fastapi")
        from swatl.web.app import set_access_token

        set_access_token(None)
        try:
            client = TestClient(app)
            assert (
                client.get("/api/segments", params={"state_dir": str(tmp_path)}).status_code == 200
            )
        finally:
            set_access_token(None)

    def test_api_requires_the_token_when_set(self, tmp_path):
        from swatl.web.app import set_access_token

        set_access_token("s3cret")
        try:
            client = TestClient(app)
            denied = client.get("/api/segments", params={"state_dir": str(tmp_path)})
            assert denied.status_code == 401
            assert "token" in denied.json()["detail"].lower()

            allowed = client.get(
                "/api/segments",
                params={"state_dir": str(tmp_path)},
                headers={"Authorization": "Bearer s3cret"},
            )
            assert allowed.status_code == 200
        finally:
            set_access_token(None)

    def test_wrong_token_is_rejected(self, tmp_path):
        from swatl.web.app import set_access_token

        set_access_token("s3cret")
        try:
            client = TestClient(app)
            assert (
                client.get(
                    "/api/segments",
                    params={"state_dir": str(tmp_path)},
                    headers={"Authorization": "Bearer nope"},
                ).status_code
                == 401
            )
            assert (
                client.get(
                    "/api/segments", params={"state_dir": str(tmp_path), "token": "nope"}
                ).status_code
                == 401
            )
        finally:
            set_access_token(None)

    def test_query_parameter_works_for_browsers(self, tmp_path):
        """A browser can be pointed at a URL, so ?token= is accepted too."""
        from swatl.web.app import set_access_token

        set_access_token("s3cret")
        try:
            client = TestClient(app)
            allowed = client.get(
                "/api/segments", params={"state_dir": str(tmp_path), "token": "s3cret"}
            )
            assert allowed.status_code == 200
        finally:
            set_access_token(None)

    def test_page_shell_stays_public(self):
        """The page contains no data, so it can load before the token is read."""
        from swatl.web.app import set_access_token

        set_access_token("s3cret")
        try:
            client = TestClient(app)
            assert client.get("/").status_code == 200
        finally:
            set_access_token(None)

    def test_mutating_endpoints_are_protected(self, tmp_path):
        from swatl.web.app import set_access_token

        set_access_token("s3cret")
        try:
            client = TestClient(app)
            write = client.post(
                "/api/glossary",
                params={"state_dir": str(tmp_path)},
                json={"source": "红岸基地", "target": "Red Coast Base"},
            )
            assert write.status_code == 401
        finally:
            set_access_token(None)

    def test_ui_sends_the_token_with_api_calls(self):
        """The embedded script must attach the header, or the GUI breaks."""
        from swatl.web.ui import html_page

        page = html_page
        assert "authHeaders" in page
        assert "Authorization" in page
        assert "sessionStorage" in page


class TestWebCommandWarning:
    """Binding off loopback without a token must be called out."""

    @staticmethod
    def _run(monkeypatch, args):
        from typer.testing import CliRunner

        from swatl import cli

        started = {}

        def fake_run_server(host, port, token=None):
            started.update({"host": host, "port": port, "token": token})

        monkeypatch.setattr("swatl.web.run_server", fake_run_server, raising=False)
        result = CliRunner().invoke(cli.app, args)
        return result, started

    def test_non_loopback_without_token_warns(self, monkeypatch):
        result, started = self._run(monkeypatch, ["web", "--host", "0.0.0.0", "--port", "8765"])

        assert result.exit_code == 0, result.output
        assert "Warning" in result.output
        assert "token" in result.output.lower()
        assert started["host"] == "0.0.0.0"
        assert started["token"] is None

    def test_token_is_passed_through_and_shown(self, monkeypatch):
        result, started = self._run(
            monkeypatch, ["web", "--host", "0.0.0.0", "--port", "8765", "--token", "s3cret"]
        )

        assert result.exit_code == 0, result.output
        assert "Warning" not in result.output
        assert started["token"] == "s3cret"
        assert "s3cret" in result.output

    def test_loopback_needs_no_token(self, monkeypatch):
        result, started = self._run(monkeypatch, ["web", "--port", "8766"])

        assert result.exit_code == 0, result.output
        assert "Warning" not in result.output
        assert started["host"] == "127.0.0.1"
        assert started["token"] is None


class TestAccessTokenEdgeCases:
    """Tokens the CLI accepts must not break the API."""

    def test_non_ascii_token_via_query_authenticates(self, tmp_path):
        """compare_digest rejects non-ASCII str, which used to 500 every call.

        A header cannot carry non-ASCII (HTTP forbids it), so this arrives as a
        query parameter; the point is that the comparison no longer raises.
        """
        from swatl.web.app import set_access_token

        set_access_token("中文-token-café")
        try:
            client = TestClient(app)
            allowed = client.get(
                "/api/segments",
                params={"state_dir": str(tmp_path), "token": "中文-token-café"},
            )
            assert allowed.status_code == 200

            denied = client.get(
                "/api/segments",
                params={"state_dir": str(tmp_path), "token": "中文-token-café-x"},
            )
            assert denied.status_code == 401
        finally:
            set_access_token(None)

    def test_cli_rejects_a_non_ascii_token(self, monkeypatch):
        """The GUI could never send it, so it is refused up front."""
        from typer.testing import CliRunner

        from swatl import cli

        started = {}
        monkeypatch.setattr(
            "swatl.web.run_server",
            lambda host, port, token=None: started.update({"token": token}),
            raising=False,
        )
        result = CliRunner().invoke(cli.app, ["web", "--token", "中文"])

        assert result.exit_code == 2
        assert "ASCII" in result.output
        assert not started, "the server must not start with an unusable token"

    def test_non_ascii_guess_does_not_crash(self, tmp_path):
        from swatl.web.app import set_access_token

        set_access_token("secret")
        try:
            client = TestClient(app)
            resp = client.get("/api/segments", params={"state_dir": str(tmp_path), "token": "café"})
            assert resp.status_code == 401
        finally:
            set_access_token(None)

    def test_export_endpoint_is_covered_by_the_token(self, tmp_path):
        from swatl.web.app import set_access_token

        set_access_token("secret")
        try:
            client = TestClient(app)
            params = {"state_dir": str(tmp_path), "db": "default", "format": "json"}

            assert client.get("/api/context/export", params=params).status_code == 401

            # With the token the request reaches the endpoint (a database exists
            # by then, so it succeeds rather than 404ing on a missing file).
            client.post(
                "/api/context",
                params={"state_dir": str(tmp_path), "db": "default"},
                json={"source_text": "红岸基地", "translated_text": "Red Coast Base"},
                headers={"Authorization": "Bearer secret"},
            )
            exported = client.get(
                "/api/context/export", params=params, headers={"Authorization": "Bearer secret"}
            )
            assert exported.status_code == 200
        finally:
            set_access_token(None)


class TestTokenInTheUi:
    """The embedded script must read the token and send it everywhere."""

    def test_token_is_read_from_the_fragment(self):
        from swatl.web.ui import html_page

        assert "location.hash" in html_page
        assert "loadToken" in html_page

    def test_every_request_helper_sends_the_token(self):
        import re

        from swatl.web.ui import html_page

        # api() and the three upload helpers.
        assert html_page.count("authHeaders(") >= 5
        # The context export builds its own request, and must not fall back to a
        # plain navigation, which cannot carry the header.
        export = re.search(
            r"async function exportContextDb\(\)\s*\{(.*?)\n\}", html_page, re.DOTALL
        )
        assert export and "authHeaders()" in export.group(1)
        assert "fetch(" in export.group(1)
