"""RadonAnalyzer — code maintainability analyzer for Python.

Execution flow (via BaseAnalyzer.analyze):

    1. run()              → executes ``radon mi -j <paths>``
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
from pathlib import Path

from sebco_qa_engine.analyzers.python.radon.config import RadonConfig
from sebco_qa_engine.core.base_analyzer import BaseAnalyzer
from sebco_qa_engine.core.models import (
    AnalyzerResult,
    ExecutionStatus,
    RunMetrics,
)

logger = logging.getLogger(__name__)


class RadonAnalyzer(BaseAnalyzer):
    """Runs radon maintainability index analysis and produces normalized artifacts.

    Parameters
    ----------
    output_dir:
        Root directory for this analyzer's artifacts.  Subdirectories
        ``raw/``, ``normalized/``, and ``summary/`` are created automatically.
    config:
        Runtime configuration.  Defaults to ``RadonConfig()``.

    Examples
    --------
    Basic usage:

        >>> from pathlib import Path
        >>> from sebco_qa_engine.analyzers.python.radon import RadonAnalyzer
        >>> result = RadonAnalyzer(output_dir=Path("qa-report/radon")).analyze()
        >>> print(result.metrics.score)

    With custom configuration:

        >>> from sebco_qa_engine.analyzers.python.radon import RadonAnalyzer, RadonConfig
        >>> cfg = RadonConfig(paths=["src/"])
        >>> result = RadonAnalyzer(output_dir=Path("qa-report/radon"), config=cfg).analyze()
    """

    name = "radon"
    language = "python"

    def __init__(self, output_dir: Path, config: RadonConfig | None = None) -> None:
        super().__init__(output_dir)
        self.config = config or RadonConfig()

    # ------------------------------------------------------------------
    # BaseAnalyzer implementation
    # ------------------------------------------------------------------

    def run(self) -> str:
        """Execute ``radon mi -j`` and return its JSON output as a string.

        ``radon mi`` exits 0 always.

        Returns
        -------
        str
            JSON string from radon's stdout, or an ``[ERROR]``/``[TIMEOUT]``
            sentinel string on failure.
        """
        cmd = [
            "radon",
            "mi",
            "-j",
            *(["--min", self.config.min_rank] if self.config.min_rank else []),
            *self.config.paths,
            *self.config.extra_args,
        ]
        logger.debug("[radon] Running: %s", " ".join(cmd))

        try:
            proc = subprocess.run(  # noqa: S603
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config.timeout,
            )
        except subprocess.TimeoutExpired:
            logger.warning("[radon] Command timed out after %ss", self.config.timeout)
            return f"[TIMEOUT] Command timed out after {self.config.timeout}s: {' '.join(cmd)}"
        except FileNotFoundError:
            logger.error("[radon] Command not found: radon")
            return "[ERROR] Command not found: radon"

        return (proc.stdout or "") + (proc.stderr or "")

    def normalize(self, raw_output: str) -> AnalyzerResult:
        """Parse ``radon mi -j`` JSON output into a structured AnalyzerResult.

        Supports both radon output formats:

        **radon ≥ 5.x** (current) — flat dict per file::

            {"src/foo.py": {"mi": 87.5, "rank": "A"}, ...}

        **radon < 5.x** (legacy) — list of module entries per file::

            {"src/foo.py": [{"type": "Module", "mi": 87.5, "rank": "A", ...}], ...}

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
            logger.warning("[radon] Failed to parse JSON output")
            return AnalyzerResult(
                analyzer=self.name,
                language=self.language,
                execution_status=ExecutionStatus.FAILED,
                raw_output=raw_output,
            )

        # Parse per-file entries — handle both current (dict) and legacy (list) formats.
        all_mi_values: list[float] = []
        grade_counts: dict[str, int] = {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0, "F": 0}
        details: list[dict] = []

        for filename, entry in data.items():
            # Current format (radon ≥ 5.x): entry is a plain dict {mi, rank}
            # Legacy format (radon < 5.x): entry is a list of module dicts
            entries: list[dict] = entry if isinstance(entry, list) else [entry]

            for mod in entries:
                mi_value = mod.get("mi")
                rank = mod.get("rank", "")
                if mi_value is not None:
                    all_mi_values.append(float(mi_value))
                if rank in grade_counts:
                    grade_counts[rank] += 1
                details.append(
                    {
                        "file": filename,
                        "mi": mi_value,
                        "rank": rank,
                    }
                )

        total = len(all_mi_values)

        # radon MI values are already in the 0-100 range — the mean is the score.
        raw_score = round(sum(all_mi_values) / total, 2) if total > 0 else None

        # Clamp to [0, 100] defensively (radon can theoretically exceed 100).
        score = round(max(0.0, min(100.0, raw_score)), 2) if raw_score is not None else None

        # low_count = files ranked C, D, E, or F (signal for issue_count).
        low_count = sum(grade_counts.get(g, 0) for g in ("C", "D", "E", "F"))

        metrics = RunMetrics(
            score=score,
            total=total,
            ok_count=grade_counts.get("A", 0) + grade_counts.get("B", 0),
            issue_count=low_count,
            extra={"grades": grade_counts},
        )

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

        raw_path = raw_dir / "radon-raw.json"
        raw_path.write_text(result.raw_output, encoding="utf-8")

        norm_path = norm_dir / "radon.json"
        norm_path.write_text(self._to_normalized_json(result), encoding="utf-8")

        summary_json_path = summary_dir / "radon-summary.json"
        summary_json_path.write_text(self._to_summary_json(result), encoding="utf-8")

        summary_md_path = summary_dir / "radon-summary.md"
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
        grades = result.metrics.extra.get("grades", {}) if result.metrics.extra else {}
        payload = {
            "analyzer": result.analyzer,
            "language": result.language,
            "execution_status": result.execution_status.value,
            "metrics": {
                "score": result.metrics.score,
                "total": result.metrics.total,
                "grades": grades,
            },
            "details": result.details,
        }
        return json.dumps(payload, indent=2, ensure_ascii=False)

    @staticmethod
    def _to_summary_json(result: AnalyzerResult) -> str:
        grades = result.metrics.extra.get("grades", {}) if result.metrics.extra else {}
        payload = {
            "analyzer": result.analyzer,
            "execution_status": result.execution_status.value,
            "score": result.metrics.score,
            "total_files": result.metrics.total,
            "grades": grades,
        }
        return json.dumps(payload, indent=2, ensure_ascii=False)

    @staticmethod
    def _to_summary_md(result: AnalyzerResult) -> str:
        m = result.metrics
        grades = m.extra.get("grades", {}) if m.extra else {}
        score_str = f"{m.score}" if m.score is not None else "N/A"
        total_str = str(m.total) if m.total is not None else "N/A"
        ok_str = str(m.ok_count) if m.ok_count is not None else "N/A"
        issue_str = str(m.issue_count) if m.issue_count is not None else "N/A"

        grade_rows = "\n".join(
            f"| {grade} | **{count}** |" for grade, count in sorted(grades.items())
        )

        return f"""\
## Maintainability Summary (radon)

| Metric | Value |
|---|---:|
| Mean MI Score | **{score_str}** |
| Total modules | **{total_str}** |
| A/B (healthy) | **{ok_str}** |
| C-F (at risk) | **{issue_str}** |

### Grade Distribution

| Grade | Count |
|---|---:|
{grade_rows}

Execution status: `{result.execution_status.value}`

### Artifacts

- `raw/radon-raw.json` — full radon JSON output
- `normalized/radon.json` — structured normalized data
- `summary/radon-summary.json` — summary JSON
- `summary/radon-summary.md` — this file
"""
