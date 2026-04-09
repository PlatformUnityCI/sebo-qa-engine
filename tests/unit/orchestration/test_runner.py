"""Tests for the Runner orchestrator."""

from pathlib import Path

from sebco_qa_engine.core.base_analyzer import BaseAnalyzer
from sebco_qa_engine.core.models import (
    AnalyzerResult,
    ExecutionStatus,
    RunMetrics,
    RunnerResult,
)
from sebco_qa_engine.orchestration.runner import Runner

# ---------------------------------------------------------------------------
# FakeAnalyzer — returns a canned result without subprocess calls
# ---------------------------------------------------------------------------


class FakeAnalyzer(BaseAnalyzer):
    """A test double for BaseAnalyzer that returns a pre-configured result."""

    name = "fake"
    language = "python"

    def __init__(self, output_dir: Path, canned_result: AnalyzerResult | None = None):
        super().__init__(output_dir)
        self._canned_result = canned_result or AnalyzerResult(
            analyzer=self.name,
            language=self.language,
            execution_status=ExecutionStatus.SUCCESS,
            metrics=RunMetrics(score=90.0, total=10, ok_count=9, issue_count=1),
        )

    def run(self) -> str:
        return ""  # Not used — analyze() is overridden via the canned result

    def normalize(self, raw_output: str) -> AnalyzerResult:
        return self._canned_result

    def write_artifacts(self, result: AnalyzerResult) -> None:
        pass  # No-op: no file I/O in tests

    def analyze(self) -> AnalyzerResult:
        # Bypass BaseAnalyzer.analyze() template to return canned result directly
        return self._canned_result


def _make_fake(name="fake", status=ExecutionStatus.SUCCESS, score=90.0, output_dir=None):
    """Create a FakeAnalyzer with a custom name and result."""

    class _FA(FakeAnalyzer):
        pass

    _FA.name = name
    result = AnalyzerResult(
        analyzer=name,
        language="python",
        execution_status=status,
        metrics=RunMetrics(score=score),
    )
    return _FA(output_dir=output_dir or Path("/tmp/fake"), canned_result=result)


# ---------------------------------------------------------------------------
# TestRunnerInit
# ---------------------------------------------------------------------------


class TestRunnerInit:
    def test_run_id_is_auto_generated_uuid_when_not_provided(self):
        runner = Runner(analyzers=[])
        # UUID4 format: 8-4-4-4-12 hex chars with dashes
        import re

        pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
        assert re.match(pattern, runner.run_id), f"Expected UUID4, got: {runner.run_id}"

    def test_run_id_is_stored_when_provided(self):
        runner = Runner(analyzers=[], run_id="my-explicit-run-id")
        assert runner.run_id == "my-explicit-run-id"

    def test_each_runner_gets_unique_auto_run_id(self):
        r1 = Runner(analyzers=[])
        r2 = Runner(analyzers=[])
        assert r1.run_id != r2.run_id

    def test_analyzers_list_stored(self):
        fa = _make_fake(name="fake")
        runner = Runner(analyzers=[fa])
        assert runner.analyzers == [fa]

    def test_empty_analyzers_list_accepted(self):
        runner = Runner(analyzers=[])
        assert runner.analyzers == []


# ---------------------------------------------------------------------------
# TestRunnerRun
# ---------------------------------------------------------------------------


class TestRunnerRun:
    def test_returns_runner_result(self):
        runner = Runner(analyzers=[])
        result = runner.run()
        assert isinstance(result, RunnerResult)

    def test_run_id_on_result_matches_runner_run_id(self):
        runner = Runner(analyzers=[], run_id="deterministic-run")
        result = runner.run()
        assert result.run_id == "deterministic-run"

    def test_results_has_one_entry_per_analyzer(self):
        fa1 = _make_fake(name="fake1")
        fa2 = _make_fake(name="fake2")
        runner = Runner(analyzers=[fa1, fa2])
        result = runner.run()
        assert len(result.results) == 2

    def test_empty_analyzers_produces_empty_results(self):
        runner = Runner(analyzers=[])
        result = runner.run()
        assert result.results == []

    def test_all_succeeded_true_when_no_errors(self):
        fa1 = _make_fake(name="fake1", status=ExecutionStatus.SUCCESS)
        fa2 = _make_fake(name="fake2", status=ExecutionStatus.SUCCESS)
        runner = Runner(analyzers=[fa1, fa2])
        result = runner.run()
        assert result.all_succeeded is True

    def test_all_succeeded_false_when_any_error(self):
        fa_ok = _make_fake(name="fake1", status=ExecutionStatus.SUCCESS)
        fa_err = _make_fake(name="fake2", status=ExecutionStatus.ERROR)
        runner = Runner(analyzers=[fa_ok, fa_err])
        result = runner.run()
        assert result.all_succeeded is False

    def test_analyzers_called_in_order(self):
        """Verify the results are stored in the same order the analyzers were given."""
        fa1 = _make_fake(name="first")
        fa2 = _make_fake(name="second")
        fa3 = _make_fake(name="third")
        runner = Runner(analyzers=[fa1, fa2, fa3])
        result = runner.run()
        assert result.results[0].analyzer == "first"
        assert result.results[1].analyzer == "second"
        assert result.results[2].analyzer == "third"

    def test_analyzer_result_stored_in_results(self):
        fa = _make_fake(name="fake", score=75.0)
        runner = Runner(analyzers=[fa])
        result = runner.run()
        assert result.results[0].metrics.score == 75.0
        assert result.results[0].analyzer == "fake"

    def test_failed_status_does_not_affect_all_succeeded(self):
        """FAILED (parse error) is distinct from ERROR — does not block all_succeeded."""
        fa = _make_fake(name="fake", status=ExecutionStatus.FAILED)
        runner = Runner(analyzers=[fa])
        result = runner.run()
        assert result.all_succeeded is True

    def test_skipped_status_does_not_affect_all_succeeded(self):
        fa = _make_fake(name="fake", status=ExecutionStatus.SKIPPED)
        runner = Runner(analyzers=[fa])
        result = runner.run()
        assert result.all_succeeded is True
