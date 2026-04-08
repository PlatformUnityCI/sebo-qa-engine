"""CoverageAnalyzer — test coverage analyzer for Python.

Execution flow (via BaseAnalyzer.analyze):

    1. run()              → executes ``coverage report --format=text``
    2. normalize()        → parses raw output into AnalyzerResult
    3. write_artifacts()  → writes raw / normalized / summary files

All subprocess calls happen inside ``run()``.  ``normalize()`` and
``write_artifacts()`` are pure data transformations — no I/O side effects
other than disk writes in the last step.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path

from sebco_qa_engine.analyzers.python.coverage.config import CoverageConfig
from sebco_qa_engine.core.base_analyzer import BaseAnalyzer
from sebco_qa_engine.core.models import (
    AnalyzerResult,
    ExecutionStatus,
    RunMetrics,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

# Matches the TOTAL summary line from ``coverage report``.
# Handles both formats:
#   TOTAL  <stmts> <miss> <cover%>
#   TOTAL  <stmts> <miss> <branches> <partial> <cover%>
_TOTAL_RE = re.compile(
    r"^TOTAL\s+(\d+)\s+(\d+)\s+(?:\d+\s+\d+\s+)?(\d+)%",
    re.MULTILINE,
)

# Matches individual file coverage lines:
#   src/foo.py          50     10    80%
#   src/foo.py          50     10     5     2    80%
_FILE_RE = re.compile(
    r"^(\S+)\s+(\d+)\s+(\d+)\s+(?:\d+\s+\d+\s+)?(\d+)%",
    re.MULTILINE,
)


class CoverageAnalyzer(BaseAnalyzer):
    """Runs coverage report and produces normalized artifacts.

    Parameters
    ----------
    output_dir:
        Root directory for this analyzer's artifacts.  Subdirectories
        ``raw/``, ``normalized/``, and ``summary/`` are created automatically.
    config:
        Runtime configuration.  Defaults to ``CoverageConfig()``.

    Examples
    --------
    Basic usage:

        >>> from pathlib import Path
        >>> from sebco_qa_engine.analyzers.python.coverage import CoverageAnalyzer
        >>> result = CoverageAnalyzer(output_dir=Path("qa-report/coverage")).analyze()
        >>> print(result.metrics.score)

    With extra args:

        >>> from sebco_qa_engine.analyzers.python.coverage import CoverageAnalyzer, CoverageConfig
        >>> cfg = CoverageConfig(extra_args=["--include=src/*"])
        >>> result = CoverageAnalyzer(output_dir=Path("qa-report/coverage"), config=cfg).analyze()
    """

    name = "coverage"
    language = "python"

    def __init__(self, output_dir: Path, config: CoverageConfig | None = None) -> None:
        super().__init__(output_dir)
        self.config = config or CoverageConfig()

    # ------------------------------------------------------------------
    # BaseAnalyzer implementation
    # ------------------------------------------------------------------

    def run(self) -> str:
        """Execute ``coverage report`` and return combined stdout+stderr.

        Coverage exits 0 even with low coverage — non-zero exit is not raised.

        Returns
        -------
        str
            Combined stdout + stderr from the coverage process.
        """
        cmd = [
            "coverage",
            "report",
            "--format=text",
            *self.config.extra_args,
        ]

        logger.debug("[coverage] Running: %s", " ".join(cmd))

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config.timeout,
            )
        except subprocess.TimeoutExpired:
            logger.warning("[coverage] Command timed out after %ss", self.config.timeout)
            return f"[TIMEOUT] Command timed out after {self.config.timeout}s: {' '.join(cmd)}"
        except FileNotFoundError:
            logger.error("[coverage] Command not found: coverage")
            return "[ERROR] Command not found: coverage"

        output = (proc.stdout or "") + (proc.stderr or "")

        if proc.returncode != 0:
            logger.debug("[coverage] Exit code %d for: %s", proc.returncode, " ".join(cmd))

        return output

    def normalize(self, raw_output: str) -> AnalyzerResult:
        """Parse raw coverage report output into a structured AnalyzerResult."""
        # Detect sentinel strings injected by run() on hard failures.
        # These mean the tool never ran — semantically ERROR, not FAILED.
        if raw_output.startswith("[TIMEOUT]") or raw_output.startswith("[ERROR]"):
            return AnalyzerResult(
                analyzer=self.name,
                language=self.language,
                execution_status=ExecutionStatus.ERROR,
                metrics=RunMetrics(),
                details=[],
                raw_output=raw_output,
                error_message=raw_output,
            )

        total_match = _TOTAL_RE.search(raw_output)

        if not total_match:
            return AnalyzerResult(
                analyzer=self.name,
                language=self.language,
                execution_status=ExecutionStatus.FAILED,
                metrics=RunMetrics(),
                details=[],
                raw_output=raw_output,
            )

        stmts = int(total_match.group(1))
        miss = int(total_match.group(2))
        cover_pct = int(total_match.group(3))

        metrics = RunMetrics(
            score=float(cover_pct),
            total=stmts,
            ok_count=stmts - miss,
            issue_count=miss,
        )

        # Parse per-file lines — exclude the TOTAL line
        details: list[dict] = []
        for m in _FILE_RE.finditer(raw_output):
            filename = m.group(1)
            if filename == "TOTAL":
                continue
            details.append({
                "file": filename,
                "stmts": int(m.group(2)),
                "miss": int(m.group(3)),
                "cover_pct": int(m.group(4)),
            })

        return AnalyzerResult(
            analyzer=self.name,
            language=self.language,
            execution_status=ExecutionStatus.SUCCESS,
            metrics=metrics,
            details=details,
            raw_output=raw_output,
        )

    def write_artifacts(self, result: AnalyzerResult) -> None:
        """Write raw output, normalized JSON, and markdown/JSON summaries."""
        raw_dir, norm_dir, summary_dir = self._artifact_dirs()

        raw_path = raw_dir / "coverage-raw.txt"
        raw_path.write_text(result.raw_output, encoding="utf-8")

        norm_path = norm_dir / "coverage.json"
        norm_path.write_text(self._to_normalized_json(result), encoding="utf-8")

        summary_json_path = summary_dir / "coverage-summary.json"
        summary_json_path.write_text(self._to_summary_json(result), encoding="utf-8")

        summary_md_path = summary_dir / "coverage-summary.md"
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
        m = result.metrics
        payload = {
            "analyzer": result.analyzer,
            "language": result.language,
            "execution_status": result.execution_status.value,
            "metrics": {
                "score": m.score,
                "total": m.total,
                "ok_count": m.ok_count,
                "issue_count": m.issue_count,
            },
            "details": result.details,
        }
        return json.dumps(payload, indent=2, ensure_ascii=False)

    @staticmethod
    def _to_summary_json(result: AnalyzerResult) -> str:
        m = result.metrics
        payload = {
            "analyzer": result.analyzer,
            "execution_status": result.execution_status.value,
            "score": m.score,
            # score_percent is an explicit alias for dashboards / reporters
            # that look for a named percent field rather than the raw float.
            "score_percent": round(m.score, 2) if m.score is not None else None,
            "stmts": m.total,
            "missed": m.issue_count,
            "covered": m.ok_count,
        }
        return json.dumps(payload, indent=2, ensure_ascii=False)

    @staticmethod
    def _to_summary_md(result: AnalyzerResult) -> str:
        m = result.metrics
        score_str = f"{m.score:.0f}%" if m.score is not None else "N/A"
        stmts_str = str(m.total) if m.total is not None else "N/A"
        missed_str = str(m.issue_count) if m.issue_count is not None else "N/A"
        covered_str = str(m.ok_count) if m.ok_count is not None else "N/A"

        details: list[dict] = result.details  # type: ignore[assignment]
        first_20 = details[:20]

        if first_20:
            rows = "\n".join(
                f"| `{d['file']}` | {d['stmts']} | {d['miss']} | {d['cover_pct']}% |"
                for d in first_20
            )
            table = (
                "| File | Stmts | Miss | Cover |\n"
                "|------|------:|-----:|------:|"
                f"\n{rows}"
            )
        else:
            table = "No per-file data available."

        return f"""\
## Coverage Summary

| Metric | Value |
|---|---:|
| **Coverage** | **{score_str}** |
| Statements | {stmts_str} |
| Missed | {missed_str} |
| Covered | {covered_str} |

### Per-file Coverage (first 20)

{table}

### Artifacts

- `raw/coverage-raw.txt` — full tool output
- `normalized/coverage.json` — structured normalized data
- `summary/coverage-summary.json` — summary JSON
- `summary/coverage-summary.md` — this file
"""
