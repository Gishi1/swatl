"""Comprehensive E2E test exercising all features together."""

import asyncio

from fixtures.create_fixture import create_fixture_epub
from swatl.audit.auditor import audit_segments
from swatl.ingest import extract_epub, extract_segments_from_epub
from swatl.models import Glossary, GlossaryEntry, Segment
from swatl.providers.mock import MockProvider
from swatl.quality.back_translation import BackTranslationReport, BackTranslationResult
from swatl.state import SegmentStore
from swatl.translate import Translator
from swatl.translate.translation_memory import TranslationMemory
from swatl.writeback import writeback_segments


class TestFullFeatureIntegration:
    """Test the full pipeline with all features enabled."""

    def test_full_pipeline_with_all_features(self, tmp_path):
        """Extract → Translate (with TM + style + glossary) → Proofread → Audit → Export (bilingual)."""
        fixture = tmp_path / "fixture.epub"
        create_fixture_epub(fixture)

        # Extract
        info, epub_dir = extract_epub(fixture)
        assert info.title == "三体"
        assert info.language == "zh"

        segments, doc_count = extract_segments_from_epub(
            epub_dir, info.spine_items, info.mime_types, info.language
        )
        assert len(segments) > 0

        # Glossary
        glossary = Glossary(entries=[GlossaryEntry(source="三体", target="Three-Body")])

        # Translation Memory
        tm_path = tmp_path / "tm.json"
        tm = TranslationMemory(memory_file=tm_path)

        # Translate with MockProvider + TM + style guide + glossary
        prov = MockProvider(name="mock", target_lang="en")
        trans = Translator(
            provider=prov,
            source_lang="zh",
            target_lang="en",
            style="literary",
            translation_memory=tm,
        )
        segments = asyncio.run(trans.translate_all(segments, glossary))

        translated = [s for s in segments if s.status == "translated"]
        assert len(translated) == len(segments)

        # Verify TM was populated
        assert tm.count() == len(segments)

        # Second translation run should use TM cache
        tm2 = TranslationMemory(memory_file=tm_path)
        assert tm2.count() > 0

        # Proofread
        prov2 = MockProvider(name="mock", target_lang="en")
        from swatl.proofread.proofreader import Proofreader

        proofreader = Proofreader(prov2)
        segments = asyncio.run(proofreader.proofread_all(segments, glossary))

        proofread = [s for s in segments if s.status == "proofread"]
        assert len(proofread) == len(segments)

        # Audit (language-aware)
        report = audit_segments(segments, glossary, source_lang="zh")
        assert report.total_segments == len(segments)
        assert report.translated_count == len(segments)

        # Export with bilingual
        output_path = tmp_path / "output.epub"
        result = writeback_segments(
            epub_dir, segments, target_lang="en", output_path=output_path, bilingual=True
        )
        assert result.exists()

        # Verify bilingual output
        import zipfile

        with zipfile.ZipFile(result) as zf:
            names = zf.namelist()
            bdocs = [n for n in names if n.startswith("bilingual/")]
            assert len(bdocs) > 0

    def test_back_translation_report_format(self):
        """Back-translation report has expected structure."""
        seg = Segment(
            id="test-1",
            doc="doc",
            anchor=".//p[1]",
            tag="p",
            source_text="テスト",
            translated="Test result",
            status="translated",
        )
        result = BackTranslationResult(
            segment=seg,
            back_translated="テスト",
            similarity_score=0.85,
            flag="ok",
        )
        report = BackTranslationReport(
            segments_tested=1, ok=1, warnings=0, critical=0, results=[result], details=[]
        )
        # Verify summary is accessible
        summary = report.summary()
        assert "1 tested" in summary

    def test_segment_store_workflow(self, tmp_path):
        """Full store workflow: append → load → update → query."""
        store = SegmentStore(tmp_path)

        # Create segments
        segs = [
            Segment(
                id=f"p-{i:04d}",
                doc="doc",
                anchor=".//p[1]",
                tag="p",
                source_text=f"Source text number {i}",
            )
            for i in range(10)
        ]
        store.append_many(segs)

        # Load and translate
        loaded = store.load_segments()
        for seg in loaded.values():
            seg.translated = f"Translated {seg.id}"
            seg.status = "translated"
        store.append_many(list(loaded.values()))

        # Query by status
        counts = store.status_counts()
        assert counts.get("translated", 0) == 10

        # Update a segment
        seg = store.get_segment("p-0001")
        assert seg is not None
        seg.translated = "Edited translation"
        seg.status = "proofread"
        store.append_segment(seg)

        # Verify update
        updated = store.get_segment("p-0001")
        assert updated.translated == "Edited translation"
        assert updated.status == "proofread"

    def test_web_api_with_real_segments(self, tmp_path):
        """Test web API endpoints with real segment data."""
        from fastapi.testclient import TestClient

        from swatl.web.app import app

        client = TestClient(app)
        rel_dir = tmp_path / "web-state"
        store = SegmentStore(rel_dir)

        # Create segments
        segs = [
            Segment(
                id=f"w-{i:04d}",
                doc="doc",
                anchor=".//p[1]",
                tag="p",
                source_text=f"Web test segment {i}",
            )
            for i in range(5)
        ]
        store.append_many(segs)

        # Get segments API
        resp = client.get("/api/segments", params={"state_dir": str(rel_dir), "page_size": 10})
        assert resp.status_code == 200
        assert resp.json()["total"] == 5

        # Get stats API
        resp = client.get("/api/stats", params={"state_dir": str(rel_dir)})
        assert resp.status_code == 200
        assert resp.json()["total"] == 5

        # Patch a segment
        resp = client.patch(
            "/api/segment/w-0001",
            params={"state_dir": str(rel_dir)},
            json={"translated": "Web edited", "status": "translated"},
        )
        assert resp.status_code == 200

        # Verify via segments API
        resp = client.get("/api/segments", params={"state_dir": str(rel_dir), "page_size": 10})
        segments = resp.json()["segments"]
        seg1 = next((s for s in segments if s["id"] == "w-0001"), None)
        assert seg1 is not None
        assert seg1["translated"] == "Web edited"

    def test_web_api_accept_skip_regenerate(self, tmp_path):
        """Test POST endpoints for accept, skip, and regenerate."""
        from fastapi.testclient import TestClient

        from swatl.web.app import app

        client = TestClient(app)
        rel_dir = tmp_path / "web-state"
        sd = {"state_dir": str(rel_dir)}
        store = SegmentStore(rel_dir)

        seg = Segment(
            id="act-001",
            doc="doc",
            anchor=".//p[1]",
            tag="p",
            source_text="Accept test",
            translated="Accept translated",
            status="translated",
        )
        store.append_segment(seg)

        # Accept
        resp = client.post("/api/accept/act-001", params=sd)
        assert resp.status_code == 200
        assert resp.json()["status"] == "proofread"

        # Verify segment was updated
        loaded = store.load_segments()
        assert loaded["act-001"].status == "proofread"

        # Skip another
        seg2 = Segment(
            id="skip-001",
            doc="doc",
            anchor=".//p[1]",
            tag="p",
            source_text="Skip test",
            translated="Skip translated",
            status="translated",
        )
        store.append_segment(seg2)
        resp = client.post("/api/skip/skip-001", params=sd)
        assert resp.status_code == 200
        assert resp.json()["status"] == "skipped"

        # Regenerate another
        seg3 = Segment(
            id="regen-001",
            doc="doc",
            anchor=".//p[1]",
            tag="p",
            source_text="Regen test",
            translated="Regen translated",
            status="proofread",
        )
        store.append_segment(seg3)
        resp = client.post("/api/regenerate/regen-001", params=sd)
        assert resp.status_code == 200
        assert "regeneration" in resp.json()["message"]

    def test_tm_eviction_with_large_batch(self, tmp_path):
        """Translation Memory eviction works when max_entries is exceeded."""
        tm = TranslationMemory(memory_file=tmp_path / "evict.json", max_entries=5)

        # Create segments with translated text and add to TM
        for i in range(10):
            seg = Segment(
                id=f"seg-{i}",
                doc="doc",
                anchor=".//p[1]",
                tag="p",
                source_text=f"Source {i}",
                translated=f"Translation {i}",
            )
            tm.add(seg)

        # Should only have 5 entries (FIFO eviction)
        assert tm.count() == 5

        # Verify last 5 remain, first 5 evicted
        for i in range(10):
            seg = Segment(
                id=f"seg-{i}",
                doc="doc",
                anchor=".//p[1]",
                tag="p",
                source_text=f"Source {i}",
            )
            cached = tm.lookup(seg)
            if i < 5:
                assert cached is None, f"Source {i} should have been evicted"
            else:
                assert cached is not None, f"Source {i} should be in cache"

    def test_language_aware_audit_on_japanese(self):
        """Japanese source with Hiragana residue is flagged."""
        seg = Segment(
            id="jp-001",
            doc="jp.xhtml",
            anchor=".//p[1]",
            tag="p",
            source_text="こんにちは世界",
            translated="Hello こんにちは",  # Hiragana residue
            status="translated",
        )

        report = audit_segments([seg], glossary=None, source_lang="ja")
        cjk_issues = [i for i in report.issues if i.type == "cjk_residue"]
        assert len(cjk_issues) == 1

    def test_tm_disk_persistence(self, tmp_path):
        """Translation Memory persists to disk and reloads."""
        tm = TranslationMemory(memory_file=tmp_path / "persist.json")

        seg = Segment(
            id="persist-001",
            doc="doc",
            anchor=".//p[1]",
            tag="p",
            source_text="Persistent text",
            translated="Persistent translation",
        )
        tm.add(seg)
        assert tm.count() == 1
        tm.save_disk_cache()

        # Reload from disk
        tm2 = TranslationMemory(memory_file=tmp_path / "persist.json")
        assert tm2.count() == 1
        lookup_seg = Segment(
            id="persist-001",
            doc="doc",
            anchor=".//p[1]",
            tag="p",
            source_text="Persistent text",
        )
        assert tm2.lookup(lookup_seg) == "Persistent translation"
