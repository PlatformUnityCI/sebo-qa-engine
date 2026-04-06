"""Tests for the Aggregator."""

from pathlib import Path

import pytest

from sebco_qa_engine.aggregation.aggregator import Aggregator
from sebco_qa_engine.aggregation.defaults import DEFAULT_POLICIES
from sebco_qa_engine.aggregation.models import AggregatedReport, GateVerdict
from sebco_qa_engine.aggregation.policies import (
    IssueCountPolicy,
    ScoreGatePolicy,
    ScoreThresholds,
)
from sebco_qa_engine.core.models import (
    AnalyzerResult,
    ExecutionStatus,
    RunMetrics,
    RunnerResult,
)


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------

def _make_result(
    analyzer="mutmut",
    language="python",
    status=ExecutionStatus.SUCCESS,
    score=90.0,
    issue_count=2,
    ok_count=20,
    total=22,
    extra=None,
    error_message="",
    artifacts=None,
):
    return AnalyzerResult(
        analyzer=analyzer,
        language=language,
        execution_status=status,
        metrics=RunMetrics(
            score=score,
            total=total,
            ok_count=ok_count,
            issue_count=issue_count,
            extra=extra or {},
        ),
        artifacts=artifacts or {},
        error_message=error_message,
    )


def _make_runner_result(results, run_id="test-run-001"):
    rr = RunnerResult(run_id=run_id)
    rr.results = list(results)
    return rr


# ---------------------------------------------------------------------------
# TestAggregatorAggregate
# ---------------------------------------------------------------------------

class TestAggregatorAggregate:
    def setup_method(self, tmp_path=None):
        self.base_dir = Path("/tmp/qa-report")
        self.aggregator = Aggregator(
            policies=DEFAULT_POLICIES,
            base_dir=self.base_dir,
            language="python",
        )

    def test_returns_aggregated_report(self):
        rr = _make_runner_result([_make_result()])
        report = self.aggregator.aggregate(rr)
        assert isinstance(report, AggregatedReport)

    def test_run_id_matches_runner_result(self):
        rr = _make_runner_result([_make_result()], run_id="specific-run-id")
        report = self.aggregator.aggregate(rr)
        assert report.run_id == "specific-run-id"

    def test_language_matches_aggregator_language(self):
        rr = _make_runner_result([_make_result()])
        report = self.aggregator.aggregate(rr)
        assert report.language == "python"

    def test_snapshot_has_correct_execution_status_as_string(self):
        rr = _make_runner_result([_make_result(status=ExecutionStatus.SUCCESS)])
        report = self.aggregator.aggregate(rr)
        assert report.results[0].execution_status == "success"

    def test_score_copied_to_scores_dict(self):
        rr = _make_runner_result([_make_result(analyzer="mutmut", score=88.5)])
        report = self.aggregator.aggregate(rr)
        assert report.scores["mutmut"] == 88.5

    def test_scores_none_when_score_is_none(self):
        rr = _make_runner_result([_make_result(analyzer="mutmut", score=None)])
        report = self.aggregator.aggregate(rr)
        assert report.scores["mutmut"] is None

    def test_summary_declared_count(self):
        rr = _make_runner_result([
            _make_result(analyzer="mutmut"),
            _make_result(analyzer="flake8", issue_count=0),
        ])
        report = self.aggregator.aggregate(rr)
        assert report.summary.declared == 2

    def test_summary_executed_excludes_skipped(self):
        rr = _make_runner_result([
            _make_result(analyzer="mutmut", status=ExecutionStatus.SUCCESS),
            _make_result(analyzer="flake8", status=ExecutionStatus.SKIPPED),
        ])
        report = self.aggregator.aggregate(rr)
        assert report.summary.executed == 1

    def test_summary_passed_count(self):
        # mutmut score=90 → PASS (warn_below=80), flake8 issue_count=0 → PASS
        rr = _make_runner_result([
            _make_result(analyzer="mutmut", score=90.0),
            _make_result(analyzer="flake8", issue_count=0),
        ])
        report = self.aggregator.aggregate(rr)
        assert report.summary.passed == 2

    def test_summary_warned_count(self):
        # mutmut score=70 is below warn_below=80 but above fail_below=60 → WARN
        rr = _make_runner_result([
            _make_result(analyzer="mutmut", score=70.0),
        ])
        report = self.aggregator.aggregate(rr)
        assert report.summary.warned == 1

    def test_summary_failed_count(self):
        # flake8 issue_count=1 with max_issues=0 → FAIL
        rr = _make_runner_result([
            _make_result(analyzer="flake8", issue_count=1),
        ])
        report = self.aggregator.aggregate(rr)
        assert report.summary.failed == 1

    def test_summary_errored_count(self):
        rr = _make_runner_result([
            _make_result(analyzer="mutmut", status=ExecutionStatus.ERROR),
        ])
        report = self.aggregator.aggregate(rr)
        assert report.summary.errored == 1

    def test_summary_skipped_count(self):
        rr = _make_runner_result([
            _make_result(analyzer="mutmut", status=ExecutionStatus.SKIPPED),
        ])
        report = self.aggregator.aggregate(rr)
        assert report.summary.skipped == 1

    def test_executed_pct_calculated_correctly(self):
        # 3 declared, 2 executed (1 skipped)
        rr = _make_runner_result([
            _make_result(analyzer="mutmut", status=ExecutionStatus.SUCCESS),
            _make_result(analyzer="flake8", status=ExecutionStatus.SUCCESS, issue_count=0),
            _make_result(analyzer="coverage", status=ExecutionStatus.SKIPPED, score=85.0),
        ])
        report = self.aggregator.aggregate(rr)
        assert report.summary.executed_pct == round(2 / 3 * 100, 2)

    def test_success_pct_calculated_correctly(self):
        # 2 executed, 1 passed → 50%
        rr = _make_runner_result([
            _make_result(analyzer="mutmut", score=90.0),   # PASS
            _make_result(analyzer="flake8", issue_count=5),  # FAIL
        ])
        report = self.aggregator.aggregate(rr)
        assert report.summary.success_pct == round(1 / 2 * 100, 2)

    def test_success_pct_is_zero_when_executed_is_zero(self):
        rr = _make_runner_result([
            _make_result(analyzer="mutmut", status=ExecutionStatus.SKIPPED),
        ])
        report = self.aggregator.aggregate(rr)
        assert report.summary.success_pct == 0.0

    def test_pending_pct_calculated_correctly(self):
        # declared=3: 1 pass, 1 warn, 1 fail → pending=(warn+fail)/declared = 2/3
        rr = _make_runner_result([
            _make_result(analyzer="mutmut", score=90.0),    # PASS
            _make_result(analyzer="coverage", score=75.0),  # WARN (warn_below=80)
            _make_result(analyzer="flake8", issue_count=1), # FAIL
        ])
        report = self.aggregator.aggregate(rr)
        expected = round(2 / 3 * 100, 2)
        assert report.summary.pending_pct == expected

    def test_skipped_analyzers_not_counted_in_pending_pct(self):
        # declared=2: 1 skipped + 1 passed → pending=0
        rr = _make_runner_result([
            _make_result(analyzer="mutmut", status=ExecutionStatus.SKIPPED),
            _make_result(analyzer="flake8", issue_count=0),  # PASS
        ])
        report = self.aggregator.aggregate(rr)
        assert report.summary.pending_pct == 0.0

    def test_generated_at_is_iso_string(self):
        rr = _make_runner_result([_make_result()])
        report = self.aggregator.aggregate(rr)
        # Should be a non-empty ISO 8601 timestamp
        assert isinstance(report.generated_at, str)
        assert "T" in report.generated_at

    def test_results_count_matches_analyzer_count(self):
        rr = _make_runner_result([
            _make_result(analyzer="mutmut"),
            _make_result(analyzer="flake8", issue_count=0),
        ])
        report = self.aggregator.aggregate(rr)
        assert len(report.results) == 2


# ---------------------------------------------------------------------------
# TestAggregatorWithNoPolicy
# ---------------------------------------------------------------------------

class TestAggregatorWithNoPolicy:
    def test_analyzer_with_no_policy_gets_skip_verdict(self):
        aggregator = Aggregator(
            policies={},  # No policies registered at all
            base_dir=Path("/tmp/qa"),
            language="python",
        )
        rr = _make_runner_result([_make_result(analyzer="mutmut")])
        report = aggregator.aggregate(rr)
        assert report.results[0].quality_gate == GateVerdict.SKIP.value

    def test_analyzer_with_policy_gets_evaluated(self):
        policy = ScoreGatePolicy(ScoreThresholds(warn_below=80.0, fail_below=60.0))
        aggregator = Aggregator(
            policies={"mutmut": policy},
            base_dir=Path("/tmp/qa"),
            language="python",
        )
        rr = _make_runner_result([_make_result(analyzer="mutmut", score=90.0)])
        report = aggregator.aggregate(rr)
        assert report.results[0].quality_gate == GateVerdict.PASS.value

    def test_skip_reason_mentions_no_policy(self):
        aggregator = Aggregator(
            policies={},
            base_dir=Path("/tmp/qa"),
            language="python",
        )
        rr = _make_runner_result([_make_result(analyzer="unknown-tool")])
        report = aggregator.aggregate(rr)
        assert "no policy" in report.results[0].gate_reason.lower()


# ---------------------------------------------------------------------------
# TestAggregatorRelativizePaths
# ---------------------------------------------------------------------------

class TestAggregatorRelativizePaths:
    def test_artifact_paths_relativized_to_base_dir(self, tmp_path):
        base_dir = tmp_path / "qa-report"
        base_dir.mkdir()
        artifact_file = base_dir / "mutmut" / "raw" / "mutmut-raw.txt"
        artifact_file.parent.mkdir(parents=True)
        artifact_file.touch()

        aggregator = Aggregator(
            policies=DEFAULT_POLICIES,
            base_dir=base_dir,
            language="python",
        )
        result = _make_result(
            analyzer="mutmut",
            artifacts={"raw": artifact_file},
        )
        rr = _make_runner_result([result])
        report = aggregator.aggregate(rr)

        snapshot = report.results[0]
        assert "raw" in snapshot.artifact_paths
        # Should be relative: "mutmut/raw/mutmut-raw.txt"
        assert snapshot.artifact_paths["raw"] == str(
            Path("mutmut") / "raw" / "mutmut-raw.txt"
        )

    def test_falls_back_to_absolute_string_if_relativization_fails(self, tmp_path):
        # base_dir and artifact are on different "trees" — relativization will fail
        base_dir = tmp_path / "qa-report"
        base_dir.mkdir()
        # artifact path is outside base_dir
        unrelated_path = Path("/some/totally/different/path/artifact.txt")

        aggregator = Aggregator(
            policies=DEFAULT_POLICIES,
            base_dir=base_dir,
            language="python",
        )
        result = _make_result(
            analyzer="mutmut",
            artifacts={"raw": unrelated_path},
        )
        rr = _make_runner_result([result])
        report = aggregator.aggregate(rr)

        snapshot = report.results[0]
        # Fallback: absolute string representation
        assert snapshot.artifact_paths["raw"] == str(unrelated_path)

    def test_empty_artifacts_produce_empty_artifact_paths(self):
        aggregator = Aggregator(
            policies=DEFAULT_POLICIES,
            base_dir=Path("/tmp/qa"),
            language="python",
        )
        result = _make_result(analyzer="mutmut", artifacts={})
        rr = _make_runner_result([result])
        report = aggregator.aggregate(rr)
        assert report.results[0].artifact_paths == {}
