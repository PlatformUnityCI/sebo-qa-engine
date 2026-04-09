"""Default quality gate policies for each built-in analyzer.

This is the single source of truth for threshold defaults.
The entrypoint factory reads this dict — individual analyzers and
the Aggregator never hardcode thresholds.

Structure
---------
``DEFAULT_POLICIES`` maps analyzer name → QualityGatePolicy instance.

Adding a new analyzer
---------------------
1. Add the analyzer implementation under ``analyzers/``.
2. Add an entry here with sensible defaults.
3. Add the name to ``SUPPORTED_ANALYZERS`` in ``entrypoint/factory.py``.

Overriding defaults (Fase 3)
-----------------------------
The entrypoint factory will accept a user-supplied mapping that can
override individual entries before passing them to the Aggregator.
For now, defaults are used as-is.
"""

from __future__ import annotations

from sebco_qa_engine.aggregation.policies import (
    IssueCountPolicy,
    QualityGatePolicy,
    ScoreGatePolicy,
    ScoreThresholds,
    SeverityPolicy,
)

# ---------------------------------------------------------------------------
# Thresholds — one place to change them all
# ---------------------------------------------------------------------------

_MUTMUT_THRESHOLDS = ScoreThresholds(warn_below=80.0, fail_below=60.0)
_COVERAGE_THRESHOLDS = ScoreThresholds(warn_below=80.0, fail_below=70.0)
_RADON_THRESHOLDS = ScoreThresholds(warn_below=70.0, fail_below=50.0)

# ---------------------------------------------------------------------------
# Policy registry
# ---------------------------------------------------------------------------

DEFAULT_POLICIES: dict[str, QualityGatePolicy] = {
    # Mutation testing — primary signal is score
    "mutmut": ScoreGatePolicy(_MUTMUT_THRESHOLDS),
    # Linting — zero-tolerance: any violation is a fail
    "flake8": IssueCountPolicy(max_issues=0),
    # Coverage — primary signal is line/branch coverage %
    "coverage": ScoreGatePolicy(_COVERAGE_THRESHOLDS),
    # Security — no high-severity findings; up to 5 medium allowed
    "bandit": SeverityPolicy(max_high=0, max_medium=5),
    # Complexity — maintainability index as score
    "radon": ScoreGatePolicy(_RADON_THRESHOLDS),
}
