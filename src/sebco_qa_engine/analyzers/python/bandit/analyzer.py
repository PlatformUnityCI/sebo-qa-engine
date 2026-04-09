"""BanditAnalyzer — security linting analyzer for Python.

Execution flow (via BaseAnalyzer.analyze):

    1. run()              → executes ``bandit -f json [--recursive] <paths>``
    2. normalize()        → parses JSON output into AnalyzerResult
    3. write_artifacts()  → writes raw / normalized / summary files

All subprocess calls happen inside ``run()``.  ``normalize()`` and
``write_artifacts()`` are pure data transformations — no I/O side effects
other than disk writes in the last step.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import asdict
from pathlib import Path

from sebco_qa_engine.analyzers.python.bandit.config import BanditConfig
from sebco_qa_engine.analyzers.python.bandit.models import BanditFinding
from sebco_qa_engine.core.base_analyzer import BaseAnalyzer
from sebco_qa_engine.core.models import (
    AnalyzerResult,
    ExecutionStatus,
    RunMetrics,
)

logger = logging.getLogger(__name__)


class BanditAnalyzer(BaseAnalyzer):
    """Runs bandit security linting and produces normalized artifacts.

    Parameters
    ----------
    output_dir:
        Root directory for this analyzer's artifacts.  Subdirectories
        ``raw/``, ``normalized/``, and ``summary/`` are created automatically.
    config:
        Runtime configuration.  Defaults to ``BanditConfig()``.

    Examples
    --------
    Basic usage:

        >>> from pathlib import Path
        >>> from sebco_qa_engine.analyzers.python.bandit import BanditAnalyzer
        >>> result = BanditAnalyzer(output_dir=Path("qa-report/bandit")).analyze()
        >>> print(result.metrics.issue_count)

    With custom configuration:

        >>> from sebco_qa_engine.analyzers.python.bandit import BanditAnalyzer, BanditConfig
        >>> cfg = BanditConfig(paths=["src/"], recursive=False)
        >>> result = BanditAnalyzer(output_dir=Path("qa-report/bandit"), config=cfg).analyze()
    """

    name = "bandit"
    language = "python"

    def __init__(self, output_dir: Path, config: BanditConfig | None = None) -> None:
        super().__init__(output_dir)
        self.config = config or BanditConfig()

    # ------------------------------------------------------------------
    # BaseAnalyzer implementation
    # ------------------------------------------------------------------

    def run(self) -> str:
        """Execute bandit and return its JSON output as a string.

        Bandit exits 0 when no issues are found, 1 when issues are found —
        both are valid outcomes and do NOT raise.

        Returns
        -------
        str
            JSON string from bandit's stdout, or an ``[ERROR]``/``[TIMEOUT]``
            sentinel string on failure.
        """
        cmd = [
            "bandit",
            "-f",
            "json",
            *(["--recursive"] if self.config.recursive else []),
            *self.config.paths,
            *self.config.extra_args,
        ]
        logger.debug("[bandit] Running: %s", " ".join(cmd))

        try:
            proc = subprocess.run(  # noqa: S603
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config.timeout,
            )
        except subprocess.TimeoutExpired:
            logger.warning("[bandit] Command timed out after %ss", self.config.timeout)
            return f"[TIMEOUT] Command timed out after {self.config.timeout}s: {' '.join(cmd)}"
        except FileNotFoundError:
            logger.error("[bandit] Command not found: bandit")
            return "[ERROR] Command not found: bandit"

        if proc.returncode not in (0, 1):
            logger.warning("[bandit] Unexpected exit code %d", proc.returncode)

        # Bandit writes JSON to stdout and progress/logging text to stderr.
        # Concatenating both breaks json.loads — return only stdout.
        # If stdout is empty on an unexpected exit code, surface stderr so
        # normalize() can detect the failure and set execution_status=FAILED.
        stdout = proc.stdout or ""
        if not stdout.strip() and proc.returncode not in (0, 1):
            stderr = proc.stderr or ""
            return stderr if stderr.strip() else "[ERROR] bandit produced no output"
        return stdout

    def normalize(self, raw_output: str) -> AnalyzerResult:
        """Parse bandit JSON output into a structured AnalyzerResult.

        Parameters
        ----------
        raw_output:
            The string returned by ``run()``.
        """
        # Handle error sentinels from run().
        # Use `in` (not startswith) — stderr noise can precede the sentinel.
        if "[ERROR]" in raw_output or "[TIMEOUT]" in raw_output:
            return AnalyzerResult(
                analyzer=self.name,
                language=self.language,
                execution_status=ExecutionStatus.ERROR,
                raw_output=raw_output,
                error_message=raw_output,
            )

        try:
            data = json.loads(raw_output)
        except (json.JSONDecodeError, ValueError):
            logger.warning("[bandit] Failed to parse JSON output")
            return AnalyzerResult(
                analyzer=self.name,
                language=self.language,
                execution_status=ExecutionStatus.FAILED,
                raw_output=raw_output,
            )

        # Extract severity counts from the _totals section.
        # execution_status is SUCCESS regardless of how many issues are found —
        # bandit ran and produced parseable JSON.  Quality evaluation (FAIL/WARN/PASS)
        # is the aggregation layer's responsibility (SeverityPolicy).
        totals = data.get("metrics", {}).get("_totals", {})
        high = int(totals.get("SEVERITY.HIGH", 0))
        medium = int(totals.get("SEVERITY.MEDIUM", 0))
        low = int(totals.get("SEVERITY.LOW", 0))
        issue_count = high + medium + low

        # Severity-weighted score (0–100).
        # Each severity level carries a configurable penalty so that a single
        # HIGH finding has far more impact than many LOW ones.
        #   score = max(0, 100 - (H * high_weight + M * medium_weight + L * low_weight))
        # Example default weights (50 / 10 / 1):
        #   0 HIGH, 0 MED, 15 LOW  → score = max(0, 100 - 15)  = 85
        #   1 HIGH, 0 MED,  0 LOW  → score = max(0, 100 - 50)  = 50
        #   0 HIGH, 5 MED,  0 LOW  → score = max(0, 100 - 50)  = 50
        penalty = (
            high * self.config.high_weight
            + medium * self.config.medium_weight
            + low * self.config.low_weight
        )
        score = float(max(0, 100 - penalty))

        # ok_count = scanned lines of code (loc), if reported by bandit.
        loc = int(totals.get("loc", 0))

        metrics = RunMetrics(
            score=score,
            total=issue_count,
            ok_count=loc or None,
            issue_count=issue_count,
            extra={
                "severity": {"high": high, "medium": medium, "low": low},
                "score_percent": score,
                "weights": {
                    "high": self.config.high_weight,
                    "medium": self.config.medium_weight,
                    "low": self.config.low_weight,
                },
            },
        )

        # Parse individual findings from results array
        findings: list[BanditFinding] = []
        for item in data.get("results", []):
            findings.append(
                BanditFinding(
                    filename=item.get("filename", ""),
                    line_number=item.get("line_number", 0),
                    severity=item.get("issue_severity", ""),
                    confidence=item.get("issue_confidence", ""),
                    test_id=item.get("test_id", ""),
                    test_name=item.get("test_name", ""),
                    issue_text=item.get("issue_text", ""),
                )
            )

        return AnalyzerResult(
            analyzer=self.name,
            language=self.language,
            execution_status=ExecutionStatus.SUCCESS,
            metrics=metrics,
            details=findings,
            raw_output=raw_output,
        )

    def write_artifacts(self, result: AnalyzerResult) -> None:
        """Write raw output, normalized JSON, and markdown/JSON summaries."""
        raw_dir, norm_dir, summary_dir = self._artifact_dirs()

        raw_path = raw_dir / "bandit-raw.json"
        raw_path.write_text(result.raw_output, encoding="utf-8")

        norm_path = norm_dir / "bandit.json"
        norm_path.write_text(self._to_normalized_json(result), encoding="utf-8")

        summary_json_path = summary_dir / "bandit-summary.json"
        summary_json_path.write_text(self._to_summary_json(result), encoding="utf-8")

        summary_md_path = summary_dir / "bandit-summary.md"
        summary_md_path.write_text(self._to_summary_md(result), encoding="utf-8")

        result.artifacts = {
            "raw": raw_path,
            "normalized": norm_path,
            "summary_json": summary_json_path,
            "summary_md": summary_md_path,
        }

    # ------------------------------------------------------------------
    # Private helpers — serialization
    # ------------------------------------------------------------------

    @staticmethod
    def _to_normalized_json(result: AnalyzerResult) -> str:
        extra = result.metrics.extra or {}
        severity = extra.get("severity", {})
        payload = {
            "analyzer": result.analyzer,
            "language": result.language,
            "execution_status": result.execution_status.value,
            "metrics": {
                "score": result.metrics.score,
                "total": result.metrics.total,
                "issue_count": result.metrics.issue_count,
                "ok_count": result.metrics.ok_count,
                "severity": severity,
                "weights": extra.get("weights", {}),
            },
            "details": [asdict(d) for d in result.details],
        }
        return json.dumps(payload, indent=2, ensure_ascii=False)

    @staticmethod
    def _to_summary_json(result: AnalyzerResult) -> str:
        extra = result.metrics.extra or {}
        severity = extra.get("severity", {})
        payload = {
            "analyzer": result.analyzer,
            "execution_status": result.execution_status.value,
            "score": result.metrics.score,
            "score_percent": extra.get("score_percent"),
            "issue_count": result.metrics.issue_count,
            "severity": severity,
        }
        return json.dumps(payload, indent=2, ensure_ascii=False)

    @staticmethod
    def _to_summary_md(result: AnalyzerResult) -> str:
        extra = result.metrics.extra or {}
        severity = extra.get("severity", {})
        high = severity.get("high", 0)
        medium = severity.get("medium", 0)
        low = severity.get("low", 0)
        total = result.metrics.issue_count or 0
        score = result.metrics.score
        score_str = f"{score:.0f}%" if score is not None else "N/A"
        weights = extra.get("weights", {})
        w_h = weights.get("high", 50)
        w_m = weights.get("medium", 10)
        w_l = weights.get("low", 1)

        return f"""\
## Security Analysis Summary (bandit)

| Metric | Value |
|---|---:|
| Score | **{score_str}** |
| High severity | **{high}** (×{w_h} penalty each) |
| Medium severity | **{medium}** (×{w_m} penalty each) |
| Low severity | **{low}** (×{w_l} penalty each) |
| Total findings | **{total}** |

Execution status: `{result.execution_status.value}`

### Artifacts

- `raw/bandit-raw.json` — full bandit JSON output
- `normalized/bandit.json` — structured normalized data
- `summary/bandit-summary.json` — summary JSON
- `summary/bandit-summary.md` — this file
"""
