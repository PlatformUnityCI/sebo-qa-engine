"""Aggregator — consolidates RunnerResult into AggregatedReport.

The Aggregator is a pure transformation layer:
  - Input:  RunnerResult  (from orchestration)
  - Output: AggregatedReport  (for reporting)

It does NOT write files, does NOT know about analyzers, and does NOT
execute any tools.  It only reads AnalyzerResult objects and applies
quality gate policies.

Usage
-----
    from sebco_qa_engine.aggregation import Aggregator
    from sebco_qa_engine.aggregation.defaults import DEFAULT_POLICIES

    aggregator = Aggregator(policies=DEFAULT_POLICIES, base_dir=Path("qa-report"))
    report = aggregator.aggregate(runner_result)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sebco_qa_engine.aggregation.models import (
    AggregatedReport,
    AnalyzerSnapshot,
    GateVerdict,
    RunSummary,
)
from sebco_qa_engine.aggregation.policies import (
    GateResult,
    QualityGatePolicy,
)
from sebco_qa_engine.core.models import AnalyzerResult, ExecutionStatus, RunnerResult

logger = logging.getLogger(__name__)

_NO_POLICY_RESULT = GateResult(
    verdict=GateVerdict.SKIP,
    reason="no policy configured for this analyzer",
    evaluated_on="none",
)


class Aggregator:
    """Consolidates a RunnerResult into an AggregatedReport.

    Parameters
    ----------
    policies:
        Mapping of analyzer name → QualityGatePolicy.
        Analyzers with no entry receive GateVerdict.SKIP automatically.
    base_dir:
        Root directory used to convert artifact Paths to relative strings.
        Typically the same ``output_dir`` passed to the Runner.
        If a path cannot be made relative, its string representation is used.
    language:
        Target language label for the report (default: ``"python"``).
    """

    def __init__(
        self,
        policies: dict[str, QualityGatePolicy],
        base_dir: Path,
        language: str = "python",
    ) -> None:
        self.policies = policies
        self.base_dir = base_dir
        self.language = language

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def aggregate(self, runner_result: RunnerResult) -> AggregatedReport:
        """Transform *runner_result* into a consolidated AggregatedReport."""
        generated_at = datetime.now(timezone.utc).isoformat()

        snapshots: list[AnalyzerSnapshot] = []
        for result in runner_result.results:
            gate = self._evaluate_gate(result)
            snapshot = self._snapshot(result, gate)
            snapshots.append(snapshot)
            logger.info(
                "Gate evaluated — analyzer: %s | execution: %s | gate: %s | reason: %s",
                result.analyzer,
                result.execution_status.value,
                gate.verdict.value,
                gate.reason,
            )

        summary = self._build_summary(snapshots, declared=len(runner_result.results))
        scores = {s.analyzer: s.score for s in snapshots}

        return AggregatedReport(
            run_id=runner_result.run_id,
            language=self.language,
            generated_at=generated_at,
            summary=summary,
            scores=scores,
            results=snapshots,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _evaluate_gate(self, result: AnalyzerResult) -> GateResult:
        """Apply the registered policy for *result.analyzer*, or return SKIP."""
        policy: QualityGatePolicy | None = self.policies.get(result.analyzer)
        if policy is None:
            return _NO_POLICY_RESULT
        return policy.evaluate(result)

    def _snapshot(self, result: AnalyzerResult, gate: GateResult) -> AnalyzerSnapshot:
        """Project an AnalyzerResult + GateResult into a flat AnalyzerSnapshot."""
        return AnalyzerSnapshot(
            analyzer=result.analyzer,
            language=result.language,
            execution_status=result.execution_status.value,
            quality_gate=gate.verdict.value,
            gate_reason=gate.reason,
            score=result.metrics.score,
            total=result.metrics.total,
            ok_count=result.metrics.ok_count,
            issue_count=result.metrics.issue_count,
            extra=dict(result.metrics.extra),
            artifact_paths=self._relativize_paths(result.artifacts),
            error_message=result.error_message,
        )

    def _relativize_paths(self, artifacts: dict[str, Path]) -> dict[str, str]:
        """Convert artifact Paths to strings relative to base_dir.

        Falls back to the absolute path string if relativization fails
        (e.g. path is on a different drive, or is already relative).
        """
        result: dict[str, str] = {}
        for key, path in artifacts.items():
            try:
                result[key] = str(path.relative_to(self.base_dir))
            except ValueError:
                result[key] = str(path)
        return result

    @staticmethod
    def _build_summary(snapshots: list[AnalyzerSnapshot], declared: int) -> RunSummary:
        """Compute RunSummary from the list of AnalyzerSnapshot objects."""
        executed = sum(
            1 for s in snapshots
            if s.execution_status != ExecutionStatus.SKIPPED.value
        )
        passed  = sum(1 for s in snapshots if s.quality_gate == GateVerdict.PASS.value)
        warned  = sum(1 for s in snapshots if s.quality_gate == GateVerdict.WARN.value)
        failed  = sum(1 for s in snapshots if s.quality_gate == GateVerdict.FAIL.value)
        errored = sum(
            1 for s in snapshots
            if s.execution_status == ExecutionStatus.ERROR.value
        )
        skipped = sum(
            1 for s in snapshots
            if s.execution_status == ExecutionStatus.SKIPPED.value
        )

        executed_pct = round(executed / declared * 100, 2) if declared else 0.0
        success_pct  = round(passed / executed * 100, 2) if executed else 0.0
        # pending = warned + failed + errored (skipped is intentional, not pending)
        pending_pct  = round((warned + failed + errored) / declared * 100, 2) if declared else 0.0

        return RunSummary(
            declared=declared,
            executed=executed,
            passed=passed,
            warned=warned,
            failed=failed,
            errored=errored,
            skipped=skipped,
            executed_pct=executed_pct,
            success_pct=success_pct,
            pending_pct=pending_pct,
        )
