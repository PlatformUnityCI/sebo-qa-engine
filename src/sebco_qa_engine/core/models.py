"""Shared data models for QA engine analyzers.

These models form the normalized contract between analyzers, orchestration,
aggregation and reporting layers.

Rules
-----
- Every model here MUST be meaningful to more than one analyzer.
- Analyzer-specific detail types (e.g. MutantDetail) belong in the
  analyzer's own ``models.py``, NOT here.
- ``AnalyzerResult.details`` is intentionally ``list[Any]`` — each analyzer
  types it internally; the aggregator and reporter treat it as opaque.

ExecutionStatus semantics
-------------------------
This enum describes the *technical* outcome of running a tool.
It is deliberately separate from quality evaluation (QualityGate),
which lives in the aggregation layer.

    SUCCESS  — the tool ran and the engine successfully interpreted its output.
    FAILED   — the tool ran but the engine could not parse or process its output
               (e.g. unexpected format, empty output, missing expected fields).
    ERROR    — the tool could not be executed at all (not installed, timeout,
               unhandled exception before any output was produced).
    SKIPPED  — the analyzer was declared but intentionally not executed
               (future: conditional runners, language gates, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class ExecutionStatus(str, Enum):
    """Technical execution outcome of an analyzer run.

    This enum captures what happened during execution only.
    It does NOT express whether the results meet quality thresholds —
    that is the responsibility of QualityGatePolicy in the aggregation layer.

    Values
    ------
    SUCCESS:
        The tool ran and the engine successfully interpreted its output.
    FAILED:
        The tool ran but the engine could not parse or process its output.
        Examples: unexpected output format, empty result, missing required fields.
    ERROR:
        The tool could not be executed at all.
        Examples: command not found, timeout exceeded, unhandled exception.
    SKIPPED:
        The analyzer was declared but not executed.
        Examples: conditional execution, language gates, disabled in config.
    """

    SUCCESS = "success"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass
class RunMetrics:
    """Generic numeric metrics produced by an analyzer.

    Field semantics
    ---------------
    score:
        Primary quality score in the range 0–100.  Interpretation is
        tool-specific (mutation score, coverage %, etc.).
        Not all analyzers produce a score — treat ``None`` as "not available".
    total:
        Total number of items evaluated (mutants, lines, checks, …).
    ok_count:
        Items that passed / are clean (killed mutants, covered lines,
        passing checks, …).
    issue_count:
        Items with problems (surviving mutants, violations, findings, …).
    extra:
        Catch-all for tool-specific metrics that do not fit the fields above.
        Examples: severity breakdown for bandit, grade distribution for radon.
        Consumers must treat this as opaque unless they know the specific analyzer.
        It is NOT a transversal field — do not build cross-analyzer logic on it.

    Note: Not all fields are meaningful for every analyzer — populate only
    what the underlying tool actually reports.  Consumers MUST treat ``None``
    as "not available", not as zero.
    """

    score: float | None = None
    total: int | None = None
    ok_count: int | None = None
    issue_count: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalyzerResult:
    """Normalized output produced by any analyzer after a complete run.

    Artifacts
    ---------
    ``artifacts`` is a mapping of logical name → absolute ``Path`` for every
    file written by the analyzer::

        {
            "raw":          Path("qa-report/mutmut/raw/mutmut-raw.txt"),
            "normalized":   Path("qa-report/mutmut/normalized/mutmut.json"),
            "summary_json": Path("qa-report/mutmut/summary/mutmut-summary.json"),
            "summary_md":   Path("qa-report/mutmut/summary/mutmut-summary.md"),
        }

    Consumers (aggregator, reporter) iterate over this dict — they never
    hardcode paths.

    Quality evaluation
    ------------------
    This model intentionally does NOT contain a quality gate verdict.
    Quality evaluation is a policy concern handled by the aggregation layer
    (QualityGatePolicy). This model only records what the tool produced.
    """

    analyzer: str                                      # e.g. "mutmut", "flake8"
    language: str                                      # e.g. "python"
    execution_status: ExecutionStatus = ExecutionStatus.SUCCESS
    metrics: RunMetrics = field(default_factory=RunMetrics)
    artifacts: dict[str, Path] = field(default_factory=dict)
    details: list[Any] = field(default_factory=list)   # typed by each analyzer
    raw_output: str = ""                               # full stdout/stderr captured
    error_message: str = ""                            # populated when status == ERROR


@dataclass
class RunnerResult:
    """Output of a full engine orchestration run.

    Produced by ``Runner.run()`` and consumed by the aggregation layer.
    Lives in ``core`` so aggregation and reporting can import it without
    depending on the orchestration module.

    Attributes
    ----------
    run_id:
        Unique identifier for this run.  Generated as a UUID by the Runner
        unless the caller injects one (e.g. ``$GITHUB_RUN_ID`` in CI).
    results:
        One ``AnalyzerResult`` per analyzer, in execution order.
    """

    run_id: str = ""
    results: list[AnalyzerResult] = field(default_factory=list)

    @property
    def all_succeeded(self) -> bool:
        """Return True if every analyzer completed without ERROR status."""
        return all(r.execution_status != ExecutionStatus.ERROR for r in self.results)
