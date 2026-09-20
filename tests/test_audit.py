"""Tests for the audit module."""

from swatl.audit.auditor import AuditIssue, AuditReport, audit_segments
from swatl.models import Glossary, GlossaryEntry, Segment


class TestAuditIssues:
    def test_cjk_residue_detection(self):
        """Chinese characters in English output should be flagged."""
        seg = Segment(
            id="p-0001",
            doc="doc",
            anchor=".//p[1]",
            tag="p",
            source_text="你好世界",
            translated="Hello 世界",
            status="translated",
        )
        report = audit_segments([seg])
        assert report.total_segments == 1
        assert report.translated_count == 1
        cjk_issues = [i for i in report.issues if i.type == "cjk_residue"]
        assert len(cjk_issues) == 1
        assert cjk_issues[0].severity == "error"

    def test_omission_detection(self):
        """Very short translation for long CJK source should be flagged."""
        seg = Segment(
            id="p-0001",
            doc="doc",
            anchor=".//p[1]",
            tag="p",
            source_text="这是一个非常长的中文句子，包含了极其丰富的信息内容。",
            translated="Short",
            status="translated",
        )
        report = audit_segments([seg])
        omission_issues = [i for i in report.issues if i.type == "omission"]
        assert len(omission_issues) == 1
        assert omission_issues[0].severity == "warning"

    def test_glossary_miss_detection(self):
        """Source glossary term not in output should be flagged."""
        glossary = Glossary(
            entries=[
                GlossaryEntry(source="三体", target="Three-Body"),
            ]
        )
        seg = Segment(
            id="p-0001",
            doc="doc",
            anchor=".//p[1]",
            tag="p",
            source_text="三体问题困扰了人类数百年。",
            translated="The problem troubled humanity for centuries.",
            status="translated",
        )
        report = audit_segments([seg], glossary)
        glossary_issues = [i for i in report.issues if i.type == "glossary_miss"]
        assert len(glossary_issues) == 1

    def test_empty_translation(self):
        """Trivially short translation should be flagged."""
        seg = Segment(
            id="p-0001",
            doc="doc",
            anchor=".//p[1]",
            tag="p",
            source_text="Some text here",
            translated="a",
            status="translated",
        )
        report = audit_segments([seg])
        short_issues = [i for i in report.issues if i.type == "short"]
        assert len(short_issues) == 1
        assert short_issues[0].severity == "warning"

    def test_short_translation(self):
        """Trivially short translation should be flagged as warning."""
        seg = Segment(
            id="p-0001",
            doc="doc",
            anchor=".//p[1]",
            tag="p",
            source_text="Some text here",
            translated="Ok",
            status="translated",
        )
        report = audit_segments([seg])
        short_issues = [i for i in report.issues if i.type == "short"]
        assert len(short_issues) == 1
        assert short_issues[0].severity == "warning"

    def test_no_issues_clean_translation(self):
        """A good translation should have no issues."""
        seg = Segment(
            id="p-0001",
            doc="doc",
            anchor=".//p[1]",
            tag="p",
            source_text="你好世界",
            translated="Hello world",
            status="translated",
        )
        report = audit_segments([seg])
        assert len(report.issues) == 0
        assert not report.has_critical_issues()

    def test_pending_segments_not_in_report(self):
        """Pending segments should not appear in the report."""
        seg = Segment(
            id="p-0001",
            doc="doc",
            anchor=".//p[1]",
            tag="p",
            source_text="你好",
            status="pending",
        )
        report = audit_segments([seg])
        assert report.total_segments == 1
        assert report.translated_count == 0

    def test_multiple_segments(self):
        """Audit should handle multiple segments correctly."""
        segments = [
            Segment(
                id="p-0001",
                doc="doc",
                anchor=".//p[1]",
                tag="p",
                source_text="你好",
                translated="Hello",
                status="translated",
            ),
            Segment(
                id="p-0002",
                doc="doc",
                anchor=".//p[2]",
                tag="p",
                source_text="世界",
                translated="World!",
                status="translated",
            ),
            Segment(
                id="p-0003",
                doc="doc",
                anchor=".//p[3]",
                tag="p",
                source_text="三体",
                translated="Three-Body",
                status="proofread",
            ),
        ]
        report = audit_segments(segments)
        assert report.total_segments == 3
        assert report.translated_count == 3  # all have non-empty translated values
        assert report.proofread_count == 1
        assert not report.has_critical_issues()

    def test_proofread_count_tracking(self):
        """Proofread segments should be counted separately."""
        segments = [
            Segment(
                id="p-0001",
                doc="doc",
                anchor=".//p[1]",
                tag="p",
                source_text="你好",
                translated="Hello",
                status="proofread",
            ),
            Segment(
                id="p-0002",
                doc="doc",
                anchor=".//p[2]",
                tag="p",
                source_text="世界",
                translated="World",
                status="translated",
            ),
        ]
        report = audit_segments(segments)
        assert report.proofread_count == 1
        assert report.translated_count == 2


class TestAuditReport:
    def test_summary_format(self):
        """Summary should produce readable output."""
        report = AuditReport(total_segments=10, translated_count=8, issues=[])
        summary = report.summary()
        assert "═══ Quality Audit ═══" in summary
        assert "Segments:" in summary
        assert "No issues found." in summary

    def test_summary_with_issues(self):
        """Summary should list issues grouped by type."""
        report = AuditReport(
            total_segments=5,
            translated_count=5,
            issues=[
                AuditIssue(
                    type="cjk_residue",
                    segment_id="p-0001",
                    doc="d",
                    detail="Found CJK chars: 中",
                    severity="error",
                ),
                AuditIssue(
                    type="omission",
                    segment_id="p-0002",
                    doc="d",
                    detail="ratio=0.1",
                    severity="warning",
                ),
            ],
        )
        summary = report.summary()
        assert "cjk_residue" in summary
        assert "omission" in summary

    def test_has_critical_issues(self):
        """Critical issues should be detected."""
        report = AuditReport(
            issues=[
                AuditIssue(
                    type="cjk_residue", segment_id="p-0001", doc="d", detail="", severity="error"
                ),
            ],
        )
        assert report.has_critical_issues()

        report2 = AuditReport(
            issues=[
                AuditIssue(
                    type="omission", segment_id="p-0001", doc="d", detail="", severity="warning"
                ),
            ],
        )
        assert not report2.has_critical_issues()


class TestEmptyTranslationIsAudited:
    """An empty translation is the one thing the audit must never skip."""

    @staticmethod
    def _seg(translated: str) -> Segment:
        return Segment(
            id="p-0001",
            doc="doc",
            anchor=".//p[1]",
            tag="p",
            source_text="红岸基地是一座秘密设施。",
            translated=translated,
            status="translated",
        )

    def test_empty_string_translation_is_flagged(self):
        report = audit_segments([self._seg("")])
        empty = [i for i in report.issues if i.type == "empty"]
        assert len(empty) == 1
        assert empty[0].severity == "error"

    def test_whitespace_translation_is_flagged(self):
        report = audit_segments([self._seg("   ")])
        assert [i.type for i in report.issues if i.type == "empty"] == ["empty"]

    def test_none_translation_is_not_reported_as_empty(self):
        """An unprocessed segment is not an empty translation."""
        seg = self._seg("")
        seg.translated = None
        seg.status = "pending"
        report = audit_segments([seg])
        assert [i for i in report.issues if i.type == "empty"] == []
