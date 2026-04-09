"""Quality gate policies for the aggregation layer.

A ``QualityGatePolicy`` evaluates an ``AnalyzerResult`` against configured
thresholds and returns a ``GateResult`` with a verdict and a human-readable
reason.

Design rules
------------
- Policies are stateless value objects — they hold thresholds, nothing else.
- Policies do NOT modify ``AnalyzerResult``.
- Policies do NOT know about each other (composition is handled by
  ``CompositePolicy``).
- If the required signal is unavailable (``None`` or wrong execution_status),
  the policy returns ``GateVerdict.SKIP`` — it never raises.

Built-in policies
-----------------
    ScoreGatePolicy      — evaluates metrics.score against warn/fail thresholds
    IssueCountPolicy     — evaluates metrics.issue_count against max counts
    SeverityPolicy       — evaluates metrics.extra["severity"] breakdown
    CompositePolicy      — combines multiple policies; worst verdict wins

Adding a new policy
-------------------
    1. Subclass ``QualityGatePolicy``.
    2. Implement ``evaluate(result) -> GateResult``.
    3. Guard for ``execution_status != SUCCESS`` and return SKIP.
    4. Guard for ``None`` signals and return SKIP with an explanation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from sebco_qa_engine.aggregation.models import GateVerdict
from sebco_qa_engine.core.models import AnalyzerResult, ExecutionStatus


@dataclass
class GateResult:
    """Outcome of a single policy evaluation.

    Attributes
    ----------
    verdict:
        The quality gate verdict: pass / warn / fail / skip.
    reason:
        Human-readable explanation.
        Example: ``"score 93.02% is above warn threshold (80.0%)"``.
    evaluated_on:
        The signal that drove this verdict.
        Example: ``"score"``, ``"issue_count"``, ``"severity.high"``.
        Useful for the reporter to show which signal triggered a warn/fail.
    """

    verdict: GateVerdict
    reason: str
    evaluated_on: str = ""


# ---------------------------------------------------------------------------
# Base contract
# ---------------------------------------------------------------------------


class QualityGatePolicy(ABC):
    """Abstract base for all quality gate policies.

    Implementations must be safe to call on any ``AnalyzerResult``,
    including ones with ``execution_status != SUCCESS``.
    """

    @abstractmethod
    def evaluate(self, result: AnalyzerResult) -> GateResult:
        """Evaluate *result* and return a ``GateResult``.

        Must NOT raise.  Return ``GateVerdict.SKIP`` for any case where
        evaluation is not possible.
        """


# ---------------------------------------------------------------------------
# Shared guard
# ---------------------------------------------------------------------------


def _guard_execution(result: AnalyzerResult) -> GateResult | None:
    """Return a SKIP GateResult if execution did not succeed, else None.

    Call this at the top of every ``evaluate()`` implementation.
    """
    if result.execution_status != ExecutionStatus.SUCCESS:
        return GateResult(
            verdict=GateVerdict.SKIP,
            reason=f"quality gate skipped — execution_status is '{result.execution_status.value}'",
            evaluated_on="execution_status",
        )
    return None


# ---------------------------------------------------------------------------
# ScoreGatePolicy
# ---------------------------------------------------------------------------


@dataclass
class ScoreThresholds:
    """Thresholds for score-based quality gates.

    Parameters
    ----------
    warn_below:
        Score strictly below this value triggers WARN.
        Example: ``80.0`` means score < 80% → WARN.
    fail_below:
        Score strictly below this value triggers FAIL.
        Must be less than or equal to ``warn_below``.
        Example: ``60.0`` means score < 60% → FAIL.
    """

    warn_below: float
    fail_below: float

    def __post_init__(self) -> None:
        if self.fail_below > self.warn_below:
            raise ValueError(
                f"fail_below ({self.fail_below}) must be <= warn_below ({self.warn_below})"
            )


@dataclass
class ScoreGatePolicy(QualityGatePolicy):
    """Evaluates ``metrics.score`` against warn/fail thresholds.

    Suitable for: mutmut (mutation score), coverage (line/branch %), radon (maintainability).

    Parameters
    ----------
    thresholds:
        ``ScoreThresholds(warn_below=80.0, fail_below=60.0)``

    Examples
    --------
        >>> policy = ScoreGatePolicy(ScoreThresholds(warn_below=80.0, fail_below=60.0))
        >>> result = policy.evaluate(analyzer_result)
        >>> print(result.verdict)  # GateVerdict.PASS / WARN / FAIL / SKIP
    """

    thresholds: ScoreThresholds

    def evaluate(self, result: AnalyzerResult) -> GateResult:
        skip = _guard_execution(result)
        if skip:
            return skip

        score = result.metrics.score
        if score is None:
            return GateResult(
                verdict=GateVerdict.SKIP,
                reason="quality gate skipped — score is not available for this analyzer",
                evaluated_on="score",
            )

        if score < self.thresholds.fail_below:
            return GateResult(
                verdict=GateVerdict.FAIL,
                reason=(f"score {score}% is below fail threshold ({self.thresholds.fail_below}%)"),
                evaluated_on="score",
            )

        if score < self.thresholds.warn_below:
            return GateResult(
                verdict=GateVerdict.WARN,
                reason=(f"score {score}% is below warn threshold ({self.thresholds.warn_below}%)"),
                evaluated_on="score",
            )

        return GateResult(
            verdict=GateVerdict.PASS,
            reason=(f"score {score}% meets warn threshold ({self.thresholds.warn_below}%)"),
            evaluated_on="score",
        )


# ---------------------------------------------------------------------------
# IssueCountPolicy
# ---------------------------------------------------------------------------


@dataclass
class IssueCountPolicy(QualityGatePolicy):
    """Evaluates ``metrics.issue_count`` against maximum counts.

    Suitable for: flake8 (PEP 8 violations), bandit findings (when used
    without severity breakdown), any tool where "number of problems" is the
    primary signal.

    Parameters
    ----------
    max_issues:
        issue_count > max_issues → FAIL.
        Use ``0`` for zero-tolerance (e.g. flake8 in strict mode).
    warn_above:
        issue_count > warn_above → WARN (but still below max_issues).
        ``None`` disables the warning level — result is either PASS or FAIL.

    Examples
    --------
    Zero-tolerance (flake8):

        >>> policy = IssueCountPolicy(max_issues=0)

    Tiered (allow up to 5, warn above 2):

        >>> policy = IssueCountPolicy(max_issues=5, warn_above=2)
    """

    max_issues: int
    warn_above: int | None = None

    def __post_init__(self) -> None:
        if self.warn_above is not None and self.warn_above >= self.max_issues:
            raise ValueError(
                f"warn_above ({self.warn_above}) must be < max_issues ({self.max_issues})"
            )

    def evaluate(self, result: AnalyzerResult) -> GateResult:
        skip = _guard_execution(result)
        if skip:
            return skip

        count = result.metrics.issue_count
        if count is None:
            return GateResult(
                verdict=GateVerdict.SKIP,
                reason="quality gate skipped — issue_count is not available for this analyzer",
                evaluated_on="issue_count",
            )

        if count > self.max_issues:
            return GateResult(
                verdict=GateVerdict.FAIL,
                reason=f"issue_count {count} exceeds max_issues ({self.max_issues})",
                evaluated_on="issue_count",
            )

        if self.warn_above is not None and count > self.warn_above:
            return GateResult(
                verdict=GateVerdict.WARN,
                reason=f"issue_count {count} exceeds warn_above ({self.warn_above})",
                evaluated_on="issue_count",
            )

        return GateResult(
            verdict=GateVerdict.PASS,
            reason=f"issue_count {count} is within limits (max: {self.max_issues})",
            evaluated_on="issue_count",
        )


# ---------------------------------------------------------------------------
# SeverityPolicy
# ---------------------------------------------------------------------------


@dataclass
class SeverityPolicy(QualityGatePolicy):
    """Evaluates severity breakdown from ``metrics.extra["severity"]``.

    Suitable for: bandit (HIGH/MEDIUM/LOW severity findings).

    Expected shape of ``metrics.extra["severity"]``::

        {"high": 0, "medium": 2, "low": 5}

    Parameters
    ----------
    max_high:
        Maximum HIGH-severity findings before FAIL.
        ``None`` = no limit on high.
    max_medium:
        Maximum MEDIUM-severity findings before WARN.
        ``None`` = no limit on medium.

    If ``max_high`` is exceeded, verdict is FAIL regardless of medium.
    If only ``max_medium`` is exceeded, verdict is WARN.

    Examples
    --------
    Strict (zero high, up to 3 medium):

        >>> policy = SeverityPolicy(max_high=0, max_medium=3)

    High-only gate:

        >>> policy = SeverityPolicy(max_high=0, max_medium=None)
    """

    max_high: int | None = None
    max_medium: int | None = None

    def evaluate(self, result: AnalyzerResult) -> GateResult:
        skip = _guard_execution(result)
        if skip:
            return skip

        severity = result.metrics.extra.get("severity")
        if not severity or not isinstance(severity, dict):
            return GateResult(
                verdict=GateVerdict.SKIP,
                reason="quality gate skipped — metrics.extra['severity'] is not available",
                evaluated_on="severity",
            )

        high = severity.get("high", 0)
        medium = severity.get("medium", 0)

        if self.max_high is not None and high > self.max_high:
            return GateResult(
                verdict=GateVerdict.FAIL,
                reason=(f"severity.high {high} exceeds max_high ({self.max_high})"),
                evaluated_on="severity.high",
            )

        if self.max_medium is not None and medium > self.max_medium:
            return GateResult(
                verdict=GateVerdict.WARN,
                reason=(f"severity.medium {medium} exceeds max_medium ({self.max_medium})"),
                evaluated_on="severity.medium",
            )

        parts = []
        if self.max_high is not None:
            parts.append(f"high={high} (max: {self.max_high})")
        if self.max_medium is not None:
            parts.append(f"medium={medium} (max: {self.max_medium})")
        reason = "severity within limits" + (f" — {', '.join(parts)}" if parts else "")

        return GateResult(
            verdict=GateVerdict.PASS,
            reason=reason,
            evaluated_on="severity",
        )


# ---------------------------------------------------------------------------
# CompositePolicy
# ---------------------------------------------------------------------------

# Verdict precedence: FAIL > WARN > PASS > SKIP
_VERDICT_RANK: dict[GateVerdict, int] = {
    GateVerdict.FAIL: 3,
    GateVerdict.WARN: 2,
    GateVerdict.PASS: 1,
    GateVerdict.SKIP: 0,
}


@dataclass
class CompositePolicy(QualityGatePolicy):
    """Combines multiple policies; the worst verdict wins.

    Verdict precedence (highest to lowest): FAIL > WARN > PASS > SKIP.

    If ``policies`` is empty, returns SKIP.

    Parameters
    ----------
    policies:
        List of ``QualityGatePolicy`` instances to evaluate in order.

    Examples
    --------
        >>> policy = CompositePolicy(policies=[
        ...     ScoreGatePolicy(ScoreThresholds(warn_below=80.0, fail_below=60.0)),
        ...     IssueCountPolicy(max_issues=10, warn_above=5),
        ... ])
    """

    policies: list[QualityGatePolicy] = field(default_factory=list)

    def evaluate(self, result: AnalyzerResult) -> GateResult:
        if not self.policies:
            return GateResult(
                verdict=GateVerdict.SKIP,
                reason="quality gate skipped — no policies configured",
                evaluated_on="composite",
            )

        gate_results = [p.evaluate(result) for p in self.policies]

        worst = max(gate_results, key=lambda gr: _VERDICT_RANK[gr.verdict])
        return worst
