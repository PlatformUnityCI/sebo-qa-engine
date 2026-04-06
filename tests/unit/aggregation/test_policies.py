"""Tests for quality gate policies."""

import pytest

from sebco_qa_engine.aggregation.models import GateVerdict
from sebco_qa_engine.aggregation.policies import (
    CompositePolicy,
    GateResult,
    IssueCountPolicy,
    ScoreGatePolicy,
    ScoreThresholds,
    SeverityPolicy,
)
from sebco_qa_engine.core.models import AnalyzerResult, ExecutionStatus, RunMetrics


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
        error_message=error_message,
    )


# ---------------------------------------------------------------------------
# GateResult
# ---------------------------------------------------------------------------

class TestGateResult:
    def test_construction_stores_fields(self):
        gr = GateResult(
            verdict=GateVerdict.PASS,
            reason="all good",
            evaluated_on="score",
        )
        assert gr.verdict == GateVerdict.PASS
        assert gr.reason == "all good"
        assert gr.evaluated_on == "score"

    def test_evaluated_on_defaults_to_empty_string(self):
        gr = GateResult(verdict=GateVerdict.SKIP, reason="no data")
        assert gr.evaluated_on == ""


# ---------------------------------------------------------------------------
# ScoreGatePolicy
# ---------------------------------------------------------------------------

class TestScoreGatePolicy:
    def setup_method(self):
        self.policy = ScoreGatePolicy(ScoreThresholds(warn_below=80.0, fail_below=60.0))

    def test_pass_when_score_above_warn_threshold(self):
        result = self.policy.evaluate(_make_result(score=85.0))
        assert result.verdict == GateVerdict.PASS

    def test_pass_when_score_equals_warn_threshold(self):
        result = self.policy.evaluate(_make_result(score=80.0))
        assert result.verdict == GateVerdict.PASS

    def test_warn_when_score_between_fail_and_warn(self):
        result = self.policy.evaluate(_make_result(score=70.0))
        assert result.verdict == GateVerdict.WARN

    def test_warn_reason_mentions_threshold(self):
        result = self.policy.evaluate(_make_result(score=70.0))
        assert "80.0" in result.reason

    def test_fail_when_score_below_fail_threshold(self):
        result = self.policy.evaluate(_make_result(score=50.0))
        assert result.verdict == GateVerdict.FAIL

    def test_fail_reason_mentions_threshold(self):
        result = self.policy.evaluate(_make_result(score=50.0))
        assert "60.0" in result.reason

    def test_skip_when_execution_status_is_error(self):
        result = self.policy.evaluate(
            _make_result(score=90.0, status=ExecutionStatus.ERROR)
        )
        assert result.verdict == GateVerdict.SKIP

    def test_skip_when_execution_status_is_failed(self):
        result = self.policy.evaluate(
            _make_result(score=90.0, status=ExecutionStatus.FAILED)
        )
        assert result.verdict == GateVerdict.SKIP

    def test_skip_when_execution_status_is_skipped(self):
        result = self.policy.evaluate(
            _make_result(score=90.0, status=ExecutionStatus.SKIPPED)
        )
        assert result.verdict == GateVerdict.SKIP

    def test_skip_when_score_is_none(self):
        result = self.policy.evaluate(_make_result(score=None))
        assert result.verdict == GateVerdict.SKIP

    def test_evaluated_on_is_score(self):
        result = self.policy.evaluate(_make_result(score=90.0))
        assert result.evaluated_on == "score"

    def test_raises_value_error_when_fail_below_greater_than_warn_below(self):
        with pytest.raises(ValueError, match="fail_below"):
            ScoreGatePolicy(ScoreThresholds(warn_below=60.0, fail_below=80.0))


# ---------------------------------------------------------------------------
# IssueCountPolicy
# ---------------------------------------------------------------------------

class TestIssueCountPolicy:
    def test_pass_when_count_within_max(self):
        policy = IssueCountPolicy(max_issues=5)
        result = policy.evaluate(_make_result(issue_count=3))
        assert result.verdict == GateVerdict.PASS

    def test_pass_when_count_equals_max(self):
        policy = IssueCountPolicy(max_issues=5)
        result = policy.evaluate(_make_result(issue_count=5))
        assert result.verdict == GateVerdict.PASS

    def test_fail_when_count_exceeds_max(self):
        policy = IssueCountPolicy(max_issues=5)
        result = policy.evaluate(_make_result(issue_count=6))
        assert result.verdict == GateVerdict.FAIL

    def test_zero_tolerance_pass_when_zero_issues(self):
        policy = IssueCountPolicy(max_issues=0)
        result = policy.evaluate(_make_result(issue_count=0))
        assert result.verdict == GateVerdict.PASS

    def test_zero_tolerance_fail_when_any_issue(self):
        policy = IssueCountPolicy(max_issues=0)
        result = policy.evaluate(_make_result(issue_count=1))
        assert result.verdict == GateVerdict.FAIL

    def test_warn_when_count_above_warn_threshold_but_within_max(self):
        policy = IssueCountPolicy(max_issues=10, warn_above=3)
        result = policy.evaluate(_make_result(issue_count=5))
        assert result.verdict == GateVerdict.WARN

    def test_pass_when_count_within_warn_threshold(self):
        policy = IssueCountPolicy(max_issues=10, warn_above=3)
        result = policy.evaluate(_make_result(issue_count=2))
        assert result.verdict == GateVerdict.PASS

    def test_warn_reason_mentions_warn_above(self):
        policy = IssueCountPolicy(max_issues=10, warn_above=3)
        result = policy.evaluate(_make_result(issue_count=5))
        assert "3" in result.reason

    def test_skip_when_execution_status_not_success(self):
        policy = IssueCountPolicy(max_issues=5)
        result = policy.evaluate(
            _make_result(issue_count=2, status=ExecutionStatus.ERROR)
        )
        assert result.verdict == GateVerdict.SKIP

    def test_skip_when_issue_count_is_none(self):
        policy = IssueCountPolicy(max_issues=5)
        result = policy.evaluate(_make_result(issue_count=None))
        assert result.verdict == GateVerdict.SKIP

    def test_evaluated_on_is_issue_count(self):
        policy = IssueCountPolicy(max_issues=5)
        result = policy.evaluate(_make_result(issue_count=2))
        assert result.evaluated_on == "issue_count"

    def test_raises_value_error_when_warn_above_gte_max_issues(self):
        with pytest.raises(ValueError, match="warn_above"):
            IssueCountPolicy(max_issues=5, warn_above=5)

    def test_raises_value_error_when_warn_above_exceeds_max_issues(self):
        with pytest.raises(ValueError, match="warn_above"):
            IssueCountPolicy(max_issues=5, warn_above=6)


# ---------------------------------------------------------------------------
# SeverityPolicy
# ---------------------------------------------------------------------------

class TestSeverityPolicy:
    def _result_with_severity(self, high=0, medium=0, status=ExecutionStatus.SUCCESS):
        return _make_result(
            extra={"severity": {"high": high, "medium": medium, "low": 0}},
            status=status,
        )

    def test_pass_when_within_limits(self):
        policy = SeverityPolicy(max_high=0, max_medium=3)
        result = policy.evaluate(self._result_with_severity(high=0, medium=2))
        assert result.verdict == GateVerdict.PASS

    def test_fail_when_high_exceeds_max_high(self):
        policy = SeverityPolicy(max_high=0, max_medium=3)
        result = policy.evaluate(self._result_with_severity(high=1, medium=0))
        assert result.verdict == GateVerdict.FAIL

    def test_fail_reason_mentions_severity_high(self):
        policy = SeverityPolicy(max_high=0, max_medium=3)
        result = policy.evaluate(self._result_with_severity(high=1, medium=0))
        assert "high" in result.reason.lower()

    def test_warn_when_medium_exceeds_max_medium_but_high_ok(self):
        policy = SeverityPolicy(max_high=0, max_medium=3)
        result = policy.evaluate(self._result_with_severity(high=0, medium=5))
        assert result.verdict == GateVerdict.WARN

    def test_warn_reason_mentions_severity_medium(self):
        policy = SeverityPolicy(max_high=0, max_medium=3)
        result = policy.evaluate(self._result_with_severity(high=0, medium=5))
        assert "medium" in result.reason.lower()

    def test_fail_beats_warn_when_both_exceeded(self):
        policy = SeverityPolicy(max_high=0, max_medium=3)
        result = policy.evaluate(self._result_with_severity(high=2, medium=5))
        assert result.verdict == GateVerdict.FAIL

    def test_skip_when_execution_status_not_success(self):
        policy = SeverityPolicy(max_high=0, max_medium=3)
        result = policy.evaluate(
            self._result_with_severity(status=ExecutionStatus.ERROR)
        )
        assert result.verdict == GateVerdict.SKIP

    def test_skip_when_no_severity_in_extra(self):
        policy = SeverityPolicy(max_high=0, max_medium=3)
        result = policy.evaluate(_make_result(extra={}))
        assert result.verdict == GateVerdict.SKIP

    def test_skip_when_severity_is_none(self):
        policy = SeverityPolicy(max_high=0, max_medium=3)
        result = policy.evaluate(_make_result(extra={"severity": None}))
        assert result.verdict == GateVerdict.SKIP

    def test_works_with_max_high_none(self):
        policy = SeverityPolicy(max_high=None, max_medium=3)
        # Even with many high findings, no FAIL from high when max_high is None
        result = policy.evaluate(self._result_with_severity(high=100, medium=0))
        assert result.verdict == GateVerdict.PASS

    def test_works_with_max_medium_none(self):
        policy = SeverityPolicy(max_high=0, max_medium=None)
        # Even with many medium findings, no WARN from medium when max_medium is None
        result = policy.evaluate(self._result_with_severity(high=0, medium=100))
        assert result.verdict == GateVerdict.PASS

    def test_evaluated_on_is_severity_for_pass(self):
        policy = SeverityPolicy(max_high=0, max_medium=3)
        result = policy.evaluate(self._result_with_severity(high=0, medium=0))
        assert result.evaluated_on == "severity"

    def test_evaluated_on_is_severity_high_on_fail(self):
        policy = SeverityPolicy(max_high=0, max_medium=3)
        result = policy.evaluate(self._result_with_severity(high=1, medium=0))
        assert result.evaluated_on == "severity.high"


# ---------------------------------------------------------------------------
# CompositePolicy
# ---------------------------------------------------------------------------

class TestCompositePolicy:
    def test_empty_policies_returns_skip(self):
        policy = CompositePolicy(policies=[])
        result = policy.evaluate(_make_result())
        assert result.verdict == GateVerdict.SKIP

    def test_single_policy_delegates_correctly(self):
        inner = ScoreGatePolicy(ScoreThresholds(warn_below=80.0, fail_below=60.0))
        policy = CompositePolicy(policies=[inner])
        result = policy.evaluate(_make_result(score=90.0))
        assert result.verdict == GateVerdict.PASS

    def test_fail_beats_warn(self):
        # score=70 → WARN, issue_count=10 exceeds max=5 → FAIL
        score_policy = ScoreGatePolicy(ScoreThresholds(warn_below=80.0, fail_below=60.0))
        count_policy = IssueCountPolicy(max_issues=5)
        policy = CompositePolicy(policies=[score_policy, count_policy])
        result = policy.evaluate(_make_result(score=70.0, issue_count=10))
        assert result.verdict == GateVerdict.FAIL

    def test_warn_beats_pass(self):
        # score=90 → PASS, issue_count=4 with warn_above=3 → WARN
        score_policy = ScoreGatePolicy(ScoreThresholds(warn_below=80.0, fail_below=60.0))
        count_policy = IssueCountPolicy(max_issues=10, warn_above=3)
        policy = CompositePolicy(policies=[score_policy, count_policy])
        result = policy.evaluate(_make_result(score=90.0, issue_count=4))
        assert result.verdict == GateVerdict.WARN

    def test_pass_beats_skip(self):
        # score=90 → PASS, issue_count=None → SKIP  →  composite should be PASS
        score_policy = ScoreGatePolicy(ScoreThresholds(warn_below=80.0, fail_below=60.0))
        count_policy = IssueCountPolicy(max_issues=5)
        policy = CompositePolicy(policies=[score_policy, count_policy])
        result = policy.evaluate(_make_result(score=90.0, issue_count=None))
        assert result.verdict == GateVerdict.PASS

    def test_all_pass_returns_pass(self):
        p1 = ScoreGatePolicy(ScoreThresholds(warn_below=80.0, fail_below=60.0))
        p2 = IssueCountPolicy(max_issues=10)
        policy = CompositePolicy(policies=[p1, p2])
        result = policy.evaluate(_make_result(score=90.0, issue_count=3))
        assert result.verdict == GateVerdict.PASS

    def test_fail_beats_pass(self):
        # First policy PASS, second FAIL → composite is FAIL
        p_pass = ScoreGatePolicy(ScoreThresholds(warn_below=80.0, fail_below=60.0))
        p_fail = IssueCountPolicy(max_issues=0)
        policy = CompositePolicy(policies=[p_pass, p_fail])
        result = policy.evaluate(_make_result(score=90.0, issue_count=1))
        assert result.verdict == GateVerdict.FAIL
