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


class TestNewAuditChecks:
    """Checks for the two failure modes this project has actually hit."""

    @staticmethod
    def _seg(sid: str, source: str, translated: str) -> Segment:
        return Segment(
            id=sid,
            doc="doc",
            anchor=f"./p[{sid[-1]}]",
            tag="p",
            source_text=source,
            translated=translated,
            status="translated",
        )

    def test_unchanged_translation_is_an_error(self):
        report = audit_segments(
            [self._seg("p-0001", "红岸基地是一座秘密设施。", "红岸基地是一座秘密设施。")]
        )
        issues = [i for i in report.issues if i.type == "untranslated"]
        assert len(issues) == 1
        assert issues[0].severity == "error"
        assert report.has_critical_issues()

    def test_unchanged_text_without_cjk_is_not_reported(self):
        """A number or a name has nothing to translate."""
        report = audit_segments([self._seg("p-0001", "2024", "2024")])
        assert [i for i in report.issues if i.type == "untranslated"] == []

    def test_changed_number_is_reported(self):
        report = audit_segments([self._seg("p-0001", "他在1987年到达。", "He arrived in 1997.")])
        issues = [i for i in report.issues if i.type == "number_mismatch"]
        assert len(issues) == 1
        assert "1987" in issues[0].detail and "1997" in issues[0].detail

    def test_matching_numbers_are_not_reported(self):
        report = audit_segments([self._seg("p-0001", "他在1987年到达。", "He arrived in 1987.")])
        assert [i for i in report.issues if i.type == "number_mismatch"] == []

    def test_dropped_number_is_reported(self):
        report = audit_segments([self._seg("p-0001", "第27号文件", "The document")])
        assert [i for i in report.issues if i.type == "number_mismatch"]

    def test_duplicate_translation_for_different_sources_is_an_error(self):
        """The smearing bug: one response reused for every segment."""
        shared = "Red Coast Base is a secret facility of great importance."
        segments = [
            self._seg("p-0001", "红岸基地是一座秘密设施。", shared),
            self._seg("p-0002", "叶文洁站在窗前。", shared),
            self._seg("p-0003", "宇宙很大。", shared),
        ]
        report = audit_segments(segments)

        duplicates = [i for i in report.issues if i.type == "duplicate_translation"]
        assert len(duplicates) == 2  # the 2nd and 3rd share the 1st's text
        assert duplicates[0].segment_id == "p-0002"
        assert "p-0001" in duplicates[0].detail

    def test_repeated_short_translation_is_fine(self):
        segments = [
            self._seg("p-0001", "是的。", "Yes."),
            self._seg("p-0002", "好的。", "Yes."),
        ]
        report = audit_segments(segments)
        assert [i for i in report.issues if i.type == "duplicate_translation"] == []

    def test_same_source_repeated_is_fine(self):
        """A refrain legitimately has the same source and translation."""
        shared = "不要回答！不要回答！不要回答！"
        segments = [
            self._seg("p-0001", shared, "Do not answer! Do not answer!"),
            self._seg("p-0002", shared, "Do not answer! Do not answer!"),
        ]
        report = audit_segments(segments)
        assert [i for i in report.issues if i.type == "duplicate_translation"] == []

    def test_summary_groups_the_new_types(self):
        shared = "The same sentence appears here for both segments."
        report = audit_segments(
            [
                self._seg("p-0001", "红岸基地。", shared),
                self._seg("p-0002", "叶文洁。", shared),
            ]
        )
        assert "duplicate_translation" in report.summary()


class TestNumberNormalisation:
    """Equivalent notations must compare equal; changed numbers must not."""

    @staticmethod
    def _seg(source: str, translated: str) -> Segment:
        return Segment(
            id="p-0001",
            doc="doc",
            anchor="./p[1]",
            tag="p",
            source_text=source,
            translated=translated,
            status="translated",
        )

    def _flagged(self, source: str, translated: str) -> bool:
        report = audit_segments([self._seg(source, translated)])
        return any(i.type == "number_mismatch" for i in report.issues)

    def test_full_width_digits_are_equivalent(self):
        assert not self._flagged("第２７号文件", "Document No. 27")

    def test_thousands_separators_are_equivalent(self):
        assert not self._flagged("共3,500人", "3,500 people")
        assert not self._flagged("共３，５００人", "3500 people")

    def test_decimal_is_not_confused_with_a_separator(self):
        assert self._flagged("3.5米", "35 metres")

    def test_repeated_number_stated_once_is_not_reported(self):
        """Chinese repeats a number for emphasis where English often does not."""
        assert not self._flagged("1987年，1987年的夏天", "the summer of 1987")

    def test_plain_space_does_not_join_two_numbers(self):
        """A space separates numbers; only comma/underscore are thousands marks."""
        assert not self._flagged("1987 500", "1987, 500")
        assert not self._flagged("1998 500 people", "In 1998 and 500 people")

    def test_circled_and_superscript_digits_are_not_folded(self):
        """NFKC would turn ① into 1 and ² into 2, inventing numbers."""
        assert not self._flagged("第①章 开工", "Chapter One: start work")
        assert not self._flagged("略²", "brief")
        assert not self._flagged("占 ½", "half")

    def test_reordering_is_not_reported(self):
        assert not self._flagged("1987年和1997年", "In 1997 and 1987.")


class TestDuplicateScanScope:
    """The duplicate check must look only at segments the audit covers."""

    def test_pending_segment_with_stale_text_is_ignored(self):
        shared = "The same sentence appears in both segments here."
        pending = Segment(
            id="p-0001",
            doc="doc",
            anchor="./p[1]",
            tag="p",
            source_text="红岸基地",
            translated=shared,
            status="pending",
        )
        translated = Segment(
            id="p-0002",
            doc="doc",
            anchor="./p[2]",
            tag="p",
            source_text="叶文洁",
            translated=shared,
            status="translated",
        )
        report = audit_segments([pending, translated])

        assert [i for i in report.issues if i.type == "duplicate_translation"] == []
