"""Aggregation-layer data models.

These models are produced by the Aggregator and consumed by the reporting
layer.  They are intentionally separate from ``core.models`` because:

- They carry quality gate verdicts, which are policy evaluations —
  not technical facts about tool execution.
- They are output-only: nothing upstream produces them, only the Aggregator.
- ``core.models`` must stay minimal so analyzers don't need to know about
  aggregation concerns.

Model hierarchy
---------------
    RunnerResult  ──[Aggregator]──►  AggregatedReport
                                          │
                                          ├── RunSummary       (global counts + %)
                                          └── list[AnalyzerSnapshot]  (one per analyzer)

``AnalyzerSnapshot`` is a flat projection of ``AnalyzerResult`` enriched with
the quality gate verdict.  It intentionally omits ``raw_output`` and ``details``
(too heavy / opaque for the aggregate view).  Consumers needing per-analyzer
detail read the artifact files directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class GateVerdict(str, Enum):
    """Quality gate evaluation result for a single analyzer.

    Produced by a ``QualityGatePolicy`` — not by the analyzer itself.

    Values
    ------
    PASS:
        All evaluated signals are within configured thresholds.
    WARN:
        At least one signal is outside the warning threshold but within
        the failure threshold.  Informational — does not block the pipeline
        by default.
    FAIL:
        At least one signal is below the minimum acceptable threshold.
        Should block the pipeline or trigger a notification.
    SKIP:
        Evaluation was not possible.  Reasons include:
        - no policy configured for this analyzer
        - execution_status was not SUCCESS (nothing to evaluate)
        - required signal (e.g. score) was None
    """

    PASS = "pass"  # noqa: S105  # nosec B105
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"


@dataclass
class AnalyzerSnapshot:
    """Flat projection of an AnalyzerResult enriched with a quality gate verdict.

    Produced by ``Aggregator._snapshot()``.  This is the unit the reporting
    layer (PR comment, dashboard) consumes per analyzer.

    Fields
    ------
    analyzer:
        Analyzer name, e.g. ``"mutmut"``.
    language:
        Target language, e.g. ``"python"``.
    execution_status:
        String value of ``ExecutionStatus`` — what happened technically.
    quality_gate:
        String value of ``GateVerdict`` — policy evaluation result.
    gate_reason:
        Human-readable explanation of the verdict.
        Example: ``"score 93.02% is above warn threshold (80.0%)"``.
    score:
        ``metrics.score`` — primary quality score, or ``None``.
    total:
        ``metrics.total`` — total items evaluated, or ``None``.
    ok_count:
        ``metrics.ok_count`` — passing items, or ``None``.
    issue_count:
        ``metrics.issue_count`` — items with problems, or ``None``.
    extra:
        ``metrics.extra`` — tool-specific data (severity, grades, …).
        Treat as opaque unless you know the specific analyzer.
    artifact_paths:
        Artifact file paths as strings (relative to the engine working dir).
        Keys: ``"raw"``, ``"normalized"``, ``"summary_json"``, ``"summary_md"``.
    error_message:
        Populated when ``execution_status`` is ``"error"`` or ``"failed"``.
    """

    analyzer: str
    language: str
    execution_status: str
    quality_gate: str
    gate_reason: str
    score: float | None = None
    total: int | None = None
    ok_count: int | None = None
    issue_count: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    artifact_paths: dict[str, str] = field(default_factory=dict)
    error_message: str = ""


@dataclass
class RunSummary:
    """Global execution and quality counts for one engine run.

    Counts
    ------
    declared:
        Total analyzers registered in the runner.
    executed:
        Analyzers that ran (execution_status != skipped).
    passed:
        Analyzers whose quality_gate == pass.
    warned:
        Analyzers whose quality_gate == warn.
    failed:
        Analyzers whose quality_gate == fail.
    errored:
        Analyzers with execution_status == error.
    skipped:
        Analyzers with execution_status == skipped.

    Percentages
    -----------
    executed_pct:
        ``executed / declared * 100``
        How many of the declared analyzers actually ran.
    success_pct:
        ``passed / executed * 100``  (0.0 if executed == 0)
        Of the analyzers that ran, how many passed the quality gate.
    pending_pct:
        ``(warned + failed + errored) / declared * 100``
        Fraction of declared analyzers that need attention.
        Skipped analyzers are intentional — they are NOT counted as pending.
    """

    declared: int = 0
    executed: int = 0
    passed: int = 0
    warned: int = 0
    failed: int = 0
    errored: int = 0
    skipped: int = 0
    executed_pct: float = 0.0
    success_pct: float = 0.0
    pending_pct: float = 0.0


@dataclass
class AggregatedReport:
    """Complete output of one Aggregator.aggregate() call.

    This is the contract between the aggregation layer and the reporting layer.
    The reporter reads only this model — it never reads ``AnalyzerResult`` directly.

    Fields
    ------
    run_id:
        Inherited from ``RunnerResult.run_id``.
    language:
        The language all analyzers in this run target.
        Assumes a single-language run for now; multi-language runs in Phase 3.
    generated_at:
        ISO 8601 UTC timestamp of when the report was generated.
    summary:
        Global execution and quality counts.
    scores:
        Convenience mapping ``{analyzer_name: score_or_None}``.
        Derived field — useful for the reporter's global table.
        Not part of the essential contract; do not build logic that depends
        on it being complete or non-None.
    results:
        One ``AnalyzerSnapshot`` per analyzer, in execution order.
    """

    run_id: str
    language: str
    generated_at: str
    summary: RunSummary = field(default_factory=RunSummary)
    scores: dict[str, float | None] = field(default_factory=dict)
    results: list[AnalyzerSnapshot] = field(default_factory=list)
