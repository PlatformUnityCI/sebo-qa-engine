"""Flake8Analyzer — style and lint analyzer for Python.

Execution flow (via BaseAnalyzer.analyze):

    1. run()              → executes ``flake8`` on the configured paths
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

from sebco_qa_engine.analyzers.python.flake8.config import Flake8Config
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

# Matches: filename:line:col: CODE message
# e.g.  src/foo.py:10:5: E302 expected 2 blank lines, found 1
_VIOLATION_RE = re.compile(r"^(.+):(\d+):(\d+):\s+([A-Z]\d+)\s+(.+)$")


class Flake8Analyzer(BaseAnalyzer):
    """Runs flake8 linting and produces normalized artifacts.

    Parameters
    ----------
    output_dir:
        Root directory for this analyzer's artifacts.  Subdirectories
        ``raw/``, ``normalized/``, and ``summary/`` are created automatically.
    config:
        Runtime configuration.  Defaults to ``Flake8Config()``.

    Examples
    --------
    Basic usage:

        >>> from pathlib import Path
        >>> from sebco_qa_engine.analyzers.python.flake8 import Flake8Analyzer
        >>> result = Flake8Analyzer(output_dir=Path("qa-report/flake8")).analyze()
        >>> print(result.metrics.issue_count)

    With custom config:

        >>> from sebco_qa_engine.analyzers.python.flake8 import Flake8Analyzer, Flake8Config
        >>> cfg = Flake8Config(paths=["src/"], max_line_length=120)
        >>> result = Flake8Analyzer(output_dir=Path("qa-report/flake8"), config=cfg).analyze()
    """

    name = "flake8"
    language = "python"

    def __init__(self, output_dir: Path, config: Flake8Config | None = None) -> None:
        super().__init__(output_dir)
        self.config = config or Flake8Config()

    # ------------------------------------------------------------------
    # BaseAnalyzer implementation
    # ------------------------------------------------------------------

    def run(self) -> str:
        """Execute flake8 and return combined stdout+stderr.

        Exit code 0 means no violations; exit code 1 means violations found.
        Both are valid outcomes — no exception is raised on non-zero exit.

        Returns
        -------
        str
            Combined stdout + stderr from the flake8 process.
        """
        cmd = [
            "flake8",
            *self.config.paths,
            "--format=default",
            *(
                ["--max-line-length", str(self.config.max_line_length)]
                if self.config.max_line_length is not None
                else []
            ),
            *self.config.extra_args,
        ]

        logger.debug("[flake8] Running: %s", " ".join(cmd))

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config.timeout,
            )
        except subprocess.TimeoutExpired:
            logger.warning("[flake8] Command timed out after %ss", self.config.timeout)
            return f"[TIMEOUT] Command timed out after {self.config.timeout}s: {' '.join(cmd)}"
        except FileNotFoundError:
            logger.error("[flake8] Command not found: flake8")
            return "[ERROR] Command not found: flake8"

        output = (proc.stdout or "") + (proc.stderr or "")

        if proc.returncode not in (0, 1):
            logger.debug("[flake8] Exit code %d for: %s", proc.returncode, " ".join(cmd))

        return output

    def normalize(self, raw_output: str) -> AnalyzerResult:
        """Parse raw flake8 output into a structured AnalyzerResult."""
        violations: list[dict] = []
        parse_error = False

        for line in raw_output.splitlines():
            line = line.strip()
            if not line:
                continue
            # Skip timeout/error sentinel lines
            if line.startswith("[TIMEOUT]") or line.startswith("[ERROR]"):
                continue

            m = _VIOLATION_RE.match(line)
            if m:
                violations.append({
                    "file": m.group(1),
                    "line": int(m.group(2)),
                    "col": int(m.group(3)),
                    "code": m.group(4),
                    "message": m.group(5),
                })
            else:
                # Unexpected non-empty line that doesn't match the violation pattern
                parse_error = True

        total = len(violations)
        unique_codes = sorted({v["code"] for v in violations})

        # Determine execution status:
        # - If output is completely empty or all lines parsed OK → SUCCESS
        # - If there's unparseable content → FAILED
        # Special case: timeout/error output → treat as FAILED
        has_sentinel = any(
            line.startswith("[TIMEOUT]") or line.startswith("[ERROR]")
            for line in raw_output.splitlines()
        )
        if has_sentinel:
            execution_status = ExecutionStatus.FAILED
        elif parse_error and total == 0:
            # Only unparseable lines, no violations found → FAILED
            execution_status = ExecutionStatus.FAILED
        else:
            execution_status = ExecutionStatus.SUCCESS

        budget = self.config.max_issue_budget
        score_percent = max(0.0, round((1 - total / budget) * 100, 2))

        metrics = RunMetrics(
            score=score_percent,
            total=total,
            ok_count=0 if total > 0 else None,
            issue_count=total,
            extra={
                "violation_codes": unique_codes,
                "score_percent": score_percent,
                "max_issue_budget": budget,
            },
        )

        return AnalyzerResult(
            analyzer=self.name,
            language=self.language,
            execution_status=execution_status,
            metrics=metrics,
            details=violations,
            raw_output=raw_output,
        )

    def write_artifacts(self, result: AnalyzerResult) -> None:
        """Write raw output, normalized JSON, and markdown/JSON summaries."""
        raw_dir, norm_dir, summary_dir = self._artifact_dirs()

        raw_path = raw_dir / "flake8-raw.txt"
        raw_path.write_text(result.raw_output, encoding="utf-8")

        norm_path = norm_dir / "flake8.json"
        norm_path.write_text(self._to_normalized_json(result), encoding="utf-8")

        summary_json_path = summary_dir / "flake8-summary.json"
        summary_json_path.write_text(self._to_summary_json(result), encoding="utf-8")

        summary_md_path = summary_dir / "flake8-summary.md"
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
                "score_percent": m.extra.get("score_percent"),
                "max_issue_budget": m.extra.get("max_issue_budget"),
                "issue_count": m.issue_count,
                "total": m.total,
                "ok_count": m.ok_count,
                "violation_codes": m.extra.get("violation_codes", []),
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
            "score_percent": m.extra.get("score_percent"),
            "max_issue_budget": m.extra.get("max_issue_budget"),
            "issue_count": m.issue_count,
            "violation_codes": m.extra.get("violation_codes", []),
        }
        return json.dumps(payload, indent=2, ensure_ascii=False)

    @staticmethod
    def _to_summary_md(result: AnalyzerResult) -> str:
        m = result.metrics
        issue_str = str(m.issue_count) if m.issue_count is not None else "N/A"
        score_str = (
            f"{m.extra['score_percent']}%"
            if m.extra.get("score_percent") is not None
            else "N/A"
        )
        budget_str = str(m.extra.get("max_issue_budget", "N/A"))
        codes = m.extra.get("violation_codes", [])
        codes_str = ", ".join(f"`{c}`" for c in codes) if codes else "None"

        details: list[dict] = result.details  # type: ignore[assignment]
        first_20 = details[:20]

        if first_20:
            rows = "\n".join(
                f"| `{v['file']}` | {v['line']} | {v['col']} | `{v['code']}` | {v['message']} |"
                for v in first_20
            )
            table = (
                "| File | Line | Col | Code | Message |\n"
                "|------|-----:|----:|------|---------|"
                f"\n{rows}"
            )
        else:
            table = "No violations detected."

        return f"""\
## Flake8 Lint Summary

| Metric | Value |
|---|---:|
| Score | **{score_str}** |
| Total Violations | **{issue_str}** / {budget_str} budget |
| Violation Codes | {codes_str} |

### Violations (first 20)

{table}

### Artifacts

- `raw/flake8-raw.txt` — full tool output
- `normalized/flake8.json` — structured normalized data
- `summary/flake8-summary.json` — summary JSON
- `summary/flake8-summary.md` — this file
"""
