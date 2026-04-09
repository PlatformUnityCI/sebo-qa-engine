"""Tests for core data models."""

from sebco_qa_engine.core.models import (
    AnalyzerResult,
    ExecutionStatus,
    RunMetrics,
    RunnerResult,
)


class TestExecutionStatus:
    def test_values_are_strings(self):
        assert ExecutionStatus.SUCCESS == "success"
        assert ExecutionStatus.FAILED == "failed"
        assert ExecutionStatus.ERROR == "error"
        assert ExecutionStatus.SKIPPED == "skipped"

    def test_failed_vs_error_are_distinct(self):
        """FAILED = tool ran but output unprocessable. ERROR = tool did not run."""
        assert ExecutionStatus.FAILED != ExecutionStatus.ERROR

    def test_is_str_enum(self):
        assert isinstance(ExecutionStatus.SUCCESS, str)


class TestRunMetrics:
    def test_defaults_are_none(self):
        m = RunMetrics()
        assert m.score is None
        assert m.total is None
        assert m.ok_count is None
        assert m.issue_count is None
        assert m.extra == {}

    def test_extra_accepts_arbitrary_data(self):
        m = RunMetrics(extra={"severity": {"high": 0, "medium": 2}})
        assert m.extra["severity"]["medium"] == 2

    def test_ok_count_and_issue_count_are_independent(self):
        m = RunMetrics(ok_count=40, issue_count=3)
        assert m.ok_count == 40
        assert m.issue_count == 3


class TestAnalyzerResult:
    def test_default_execution_status_is_success(self):
        r = AnalyzerResult(analyzer="test", language="python")
        assert r.execution_status == ExecutionStatus.SUCCESS

    def test_artifacts_default_empty(self):
        r = AnalyzerResult(analyzer="test", language="python")
        assert r.artifacts == {}

    def test_details_default_empty(self):
        r = AnalyzerResult(analyzer="test", language="python")
        assert r.details == []

    def test_error_status_with_message(self):
        r = AnalyzerResult(
            analyzer="mutmut",
            language="python",
            execution_status=ExecutionStatus.ERROR,
            error_message="Command not found: mutmut",
        )
        assert r.execution_status == ExecutionStatus.ERROR
        assert r.error_message == "Command not found: mutmut"

    def test_failed_status_distinct_from_error(self):
        """FAILED = ran but engine couldn't parse output."""
        r = AnalyzerResult(
            analyzer="flake8",
            language="python",
            execution_status=ExecutionStatus.FAILED,
            error_message="Unexpected output format",
        )
        assert r.execution_status == ExecutionStatus.FAILED
        assert r.execution_status != ExecutionStatus.ERROR

    def test_no_quality_gate_on_result(self):
        """AnalyzerResult intentionally has no quality_gate field."""
        r = AnalyzerResult(analyzer="test", language="python")
        assert not hasattr(r, "quality_gate")
        assert not hasattr(r, "status")


class TestRunnerResult:
    def test_defaults(self):
        rr = RunnerResult()
        assert rr.results == []
        assert rr.run_id == ""

    def test_run_id_stored(self):
        rr = RunnerResult(run_id="abc-123")
        assert rr.run_id == "abc-123"

    def test_all_succeeded_true_when_no_errors(self):
        rr = RunnerResult(
            results=[
                AnalyzerResult(
                    analyzer="a", language="python", execution_status=ExecutionStatus.SUCCESS
                ),
                AnalyzerResult(
                    analyzer="b", language="python", execution_status=ExecutionStatus.FAILED
                ),
            ]
        )
        assert rr.all_succeeded is True

    def test_all_succeeded_false_when_any_error(self):
        rr = RunnerResult(
            results=[
                AnalyzerResult(
                    analyzer="a", language="python", execution_status=ExecutionStatus.SUCCESS
                ),
                AnalyzerResult(
                    analyzer="b", language="python", execution_status=ExecutionStatus.ERROR
                ),
            ]
        )
        assert rr.all_succeeded is False

    def test_all_succeeded_true_when_empty(self):
        assert RunnerResult().all_succeeded is True

    def test_skipped_does_not_affect_all_succeeded(self):
        rr = RunnerResult(
            results=[
                AnalyzerResult(
                    analyzer="a", language="python", execution_status=ExecutionStatus.SKIPPED
                ),
            ]
        )
        assert rr.all_succeeded is True
