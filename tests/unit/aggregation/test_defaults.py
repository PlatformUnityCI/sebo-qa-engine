"""Tests for DEFAULT_POLICIES registry."""

from sebco_qa_engine.aggregation.defaults import DEFAULT_POLICIES
from sebco_qa_engine.aggregation.policies import (
    IssueCountPolicy,
    ScoreGatePolicy,
    SeverityPolicy,
)


class TestDefaultPolicies:
    def test_all_expected_analyzer_names_present(self):
        expected = {"mutmut", "flake8", "coverage", "bandit", "radon"}
        assert expected == set(DEFAULT_POLICIES.keys())

    def test_mutmut_uses_score_gate_policy(self):
        assert isinstance(DEFAULT_POLICIES["mutmut"], ScoreGatePolicy)

    def test_flake8_uses_issue_count_policy(self):
        assert isinstance(DEFAULT_POLICIES["flake8"], IssueCountPolicy)

    def test_flake8_has_zero_tolerance(self):
        policy = DEFAULT_POLICIES["flake8"]
        assert policy.max_issues == 0

    def test_coverage_uses_score_gate_policy(self):
        assert isinstance(DEFAULT_POLICIES["coverage"], ScoreGatePolicy)

    def test_bandit_uses_severity_policy(self):
        assert isinstance(DEFAULT_POLICIES["bandit"], SeverityPolicy)

    def test_radon_uses_score_gate_policy(self):
        assert isinstance(DEFAULT_POLICIES["radon"], ScoreGatePolicy)

    def test_mutmut_thresholds(self):
        policy = DEFAULT_POLICIES["mutmut"]
        assert policy.thresholds.warn_below == 80.0
        assert policy.thresholds.fail_below == 60.0

    def test_coverage_thresholds(self):
        policy = DEFAULT_POLICIES["coverage"]
        assert policy.thresholds.warn_below == 80.0
        assert policy.thresholds.fail_below == 70.0

    def test_radon_thresholds(self):
        policy = DEFAULT_POLICIES["radon"]
        assert policy.thresholds.warn_below == 70.0
        assert policy.thresholds.fail_below == 50.0

    def test_bandit_max_high_is_zero(self):
        policy = DEFAULT_POLICIES["bandit"]
        assert policy.max_high == 0

    def test_bandit_max_medium_is_five(self):
        policy = DEFAULT_POLICIES["bandit"]
        assert policy.max_medium == 5
