"""Aggregation layer — quality gate evaluation and report consolidation."""

from sebco_qa_engine.aggregation.aggregator import Aggregator
from sebco_qa_engine.aggregation.models import (
    AggregatedReport,
    AnalyzerSnapshot,
    GateVerdict,
    RunSummary,
)
from sebco_qa_engine.aggregation.policies import (
    CompositePolicy,
    GateResult,
    IssueCountPolicy,
    QualityGatePolicy,
    ScoreGatePolicy,
    ScoreThresholds,
    SeverityPolicy,
)

__all__ = [
    "Aggregator",
    "AggregatedReport",
    "AnalyzerSnapshot",
    "GateVerdict",
    "RunSummary",
    "CompositePolicy",
    "GateResult",
    "IssueCountPolicy",
    "QualityGatePolicy",
    "ScoreGatePolicy",
    "ScoreThresholds",
    "SeverityPolicy",
]
