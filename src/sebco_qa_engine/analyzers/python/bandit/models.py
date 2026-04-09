"""Bandit-specific data models.

These types are internal to the bandit analyzer and are NOT part of the
engine's common contract.  Consumers outside this analyzer should interact
only with ``AnalyzerResult`` and ``RunMetrics`` from ``sebco_qa_engine.core``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BanditFinding:
    """Detail record for a single bandit security finding.

    Attributes
    ----------
    filename:
        Source file where the issue was found.
    line_number:
        Line number of the finding.
    severity:
        Severity level — one of ``"HIGH"``, ``"MEDIUM"``, ``"LOW"``.
    confidence:
        Confidence level — one of ``"HIGH"``, ``"MEDIUM"``, ``"LOW"``.
    test_id:
        Bandit test identifier (e.g. ``"B105"``).
    test_name:
        Bandit test name (e.g. ``"hardcoded_password_string"``).
    issue_text:
        Human-readable description of the security issue.
    """

    filename: str
    line_number: int
    severity: str  # "HIGH", "MEDIUM", "LOW"
    confidence: str  # "HIGH", "MEDIUM", "LOW"
    test_id: str  # e.g. "B105"
    test_name: str  # e.g. "hardcoded_password_string"
    issue_text: str
