"""Tests for aggregation data models."""

from sebco_qa_engine.aggregation.models import (
    AggregatedReport,
    AnalyzerSnapshot,
    GateVerdict,
    RunSummary,
)


class TestGateVerdict:
    def test_values_are_strings(self):
        assert GateVerdict.PASS == "pass"
        assert GateVerdict.WARN == "warn"
        assert GateVerdict.FAIL == "fail"
        assert GateVerdict.SKIP == "skip"

    def test_all_four_variants_exist(self):
        members = {v.name for v in GateVerdict}
        assert members == {"PASS", "WARN", "FAIL", "SKIP"}

    def test_is_str_enum(self):
        assert isinstance(GateVerdict.PASS, str)
        assert isinstance(GateVerdict.FAIL, str)


class TestAnalyzerSnapshot:
    def test_construction_stores_all_required_fields(self):
        snap = AnalyzerSnapshot(
            analyzer="mutmut",
            language="python",
            execution_status="success",
            quality_gate="pass",
            gate_reason="score 90.0% meets warn threshold (80.0%)",
        )
        assert snap.analyzer == "mutmut"
        assert snap.language == "python"
        assert snap.execution_status == "success"
        assert snap.quality_gate == "pass"
        assert snap.gate_reason == "score 90.0% meets warn threshold (80.0%)"

    def test_defaults_extra_is_empty_dict(self):
        snap = AnalyzerSnapshot(
            analyzer="flake8",
            language="python",
            execution_status="success",
            quality_gate="pass",
            gate_reason="ok",
        )
        assert snap.extra == {}

    def test_defaults_artifact_paths_is_empty_dict(self):
        snap = AnalyzerSnapshot(
            analyzer="flake8",
            language="python",
            execution_status="success",
            quality_gate="pass",
            gate_reason="ok",
        )
        assert snap.artifact_paths == {}

    def test_optional_numeric_fields_default_to_none(self):
        snap = AnalyzerSnapshot(
            analyzer="flake8",
            language="python",
            execution_status="success",
            quality_gate="pass",
            gate_reason="ok",
        )
        assert snap.score is None
        assert snap.total is None
        assert snap.ok_count is None
        assert snap.issue_count is None

    def test_error_message_defaults_to_empty_string(self):
        snap = AnalyzerSnapshot(
            analyzer="flake8",
            language="python",
            execution_status="error",
            quality_gate="skip",
            gate_reason="skipped",
        )
        assert snap.error_message == ""

    def test_all_optional_fields_stored(self):
        snap = AnalyzerSnapshot(
            analyzer="bandit",
            language="python",
            execution_status="success",
            quality_gate="warn",
            gate_reason="medium issues exceeded",
            score=85.0,
            total=100,
            ok_count=80,
            issue_count=5,
            extra={"severity": {"high": 0, "medium": 2}},
            artifact_paths={"raw": "bandit/raw/bandit.txt"},
            error_message="",
        )
        assert snap.score == 85.0
        assert snap.total == 100
        assert snap.ok_count == 80
        assert snap.issue_count == 5
        assert snap.extra == {"severity": {"high": 0, "medium": 2}}
        assert snap.artifact_paths == {"raw": "bandit/raw/bandit.txt"}


class TestRunSummary:
    def test_all_counts_default_to_zero(self):
        s = RunSummary()
        assert s.declared == 0
        assert s.executed == 0
        assert s.passed == 0
        assert s.warned == 0
        assert s.failed == 0
        assert s.errored == 0
        assert s.skipped == 0

    def test_all_percentages_default_to_zero(self):
        s = RunSummary()
        assert s.executed_pct == 0.0
        assert s.success_pct == 0.0
        assert s.pending_pct == 0.0

    def test_all_fields_stored(self):
        s = RunSummary(
            declared=5,
            executed=4,
            passed=3,
            warned=1,
            failed=0,
            errored=0,
            skipped=1,
            executed_pct=80.0,
            success_pct=75.0,
            pending_pct=20.0,
        )
        assert s.declared == 5
        assert s.executed == 4
        assert s.passed == 3
        assert s.warned == 1
        assert s.failed == 0
        assert s.errored == 0
        assert s.skipped == 1
        assert s.executed_pct == 80.0
        assert s.success_pct == 75.0
        assert s.pending_pct == 20.0


class TestAggregatedReport:
    def test_run_id_stored(self):
        report = AggregatedReport(
            run_id="abc-123",
            language="python",
            generated_at="2026-04-06T00:00:00+00:00",
        )
        assert report.run_id == "abc-123"

    def test_language_stored(self):
        report = AggregatedReport(
            run_id="abc-123",
            language="python",
            generated_at="2026-04-06T00:00:00+00:00",
        )
        assert report.language == "python"

    def test_generated_at_stored(self):
        ts = "2026-04-06T00:00:00+00:00"
        report = AggregatedReport(run_id="x", language="python", generated_at=ts)
        assert report.generated_at == ts

    def test_results_defaults_to_empty_list(self):
        report = AggregatedReport(run_id="x", language="python", generated_at="ts")
        assert report.results == []
        assert isinstance(report.results, list)

    def test_summary_defaults_to_empty_run_summary(self):
        report = AggregatedReport(run_id="x", language="python", generated_at="ts")
        assert isinstance(report.summary, RunSummary)
        assert report.summary.declared == 0

    def test_scores_defaults_to_empty_dict(self):
        report = AggregatedReport(run_id="x", language="python", generated_at="ts")
        assert report.scores == {}
