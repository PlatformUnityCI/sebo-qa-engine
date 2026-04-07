"""MutmutAnalyzer — mutation testing analyzer for Python.

Execution flow (via BaseAnalyzer.analyze):

    1. run()              → executes ``mutmut run`` + ``mutmut results``
                            + ``mutmut show <id>`` for each survivor
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
from dataclasses import asdict
from pathlib import Path

from sebco_qa_engine.analyzers.python.mutmut.config import MutmutConfig
from sebco_qa_engine.analyzers.python.mutmut.models import MutantDetail
from sebco_qa_engine.core.base_analyzer import BaseAnalyzer
from sebco_qa_engine.core.models import (
    AnalyzerResult,
    ExecutionStatus,
    RunMetrics,
)
from sebco_qa_engine.utils.text import strip_ansi

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_SECTION_SEP = "\n" + "=" * 60 + "\n"

# Extract killed / survived counts from mutmut's emoji progress line
_KILLED_RE = re.compile(r"🎉\s*(\d+)")
_SURVIVED_RE = re.compile(r"🙁\s*(\d+)")

# Surviving mutant line patterns from ``mutmut results``
_NAMED_MUTANT_RE = re.compile(r"^([A-Za-z0-9_./-]+(?:__mutmut_\d+)):\s+survived$")
_NUM_MUTANT_RE = re.compile(r"^(\d+)\b")


class MutmutAnalyzer(BaseAnalyzer):
    """Runs mutmut mutation testing and produces normalized artifacts.

    Parameters
    ----------
    output_dir:
        Root directory for this analyzer's artifacts.  Subdirectories
        ``raw/``, ``normalized/``, and ``summary/`` are created automatically.
    config:
        Runtime configuration.  Defaults to ``MutmutConfig()`` (mutmut
        handles all defaults itself).

    Examples
    --------
    Basic usage:

        >>> from pathlib import Path
        >>> from sebco_qa_engine.analyzers.python.mutmut import MutmutAnalyzer
        >>> result = MutmutAnalyzer(output_dir=Path("qa-report/mutmut")).analyze()
        >>> print(result.metrics.score)

    With explicit cache management:

        >>> from sebco_qa_engine.analyzers.python.mutmut import MutmutAnalyzer, MutmutConfig
        >>> cfg = MutmutConfig(cache_dir=Path("/tmp/mutmut"), clean_cache=True)
        >>> result = MutmutAnalyzer(output_dir=Path("qa-report/mutmut"), config=cfg).analyze()
    """

    name = "mutmut"
    language = "python"

    def __init__(self, output_dir: Path, config: MutmutConfig | None = None) -> None:
        super().__init__(output_dir)
        self.config = config or MutmutConfig()

    # ------------------------------------------------------------------
    # BaseAnalyzer implementation
    # ------------------------------------------------------------------

    def run(self) -> str:
        """Execute mutmut and collect all output into a single raw string.

        Steps:
          1. Optionally clean the cache file.
          2. Run ``mutmut run`` (tolerates non-zero exits — mutation runs
             always exit non-zero when there are survivors).
          3. Run ``mutmut results`` to get the survivors list.
          4. For each surviving mutant, run ``mutmut show <id>``.

        Returns
        -------
        str
            All captured output sections joined with a separator.
        """
        self._maybe_clean_cache()

        sections: list[str] = []

        # Step 1 — mutmut run
        run_out = self._run_subprocess(["mutmut", "run", *self.config.extra_args])
        sections.append("=== mutmut run ===\n" + run_out)

        # Step 2 — mutmut results
        results_out = self._run_subprocess(["mutmut", "results"])
        sections.append("=== mutmut results ===\n" + results_out)

        # Step 3 — show each survivor
        surviving_ids = self._parse_surviving_ids(strip_ansi(results_out))
        if surviving_ids:
            show_parts: list[str] = []
            for mutant_id in surviving_ids:
                show_out = self._run_subprocess(["mutmut", "show", mutant_id])
                show_parts.append(f"----- MUTANT: {mutant_id} -----\n{show_out}")
            sections.append("=== mutmut show ===\n" + "\n".join(show_parts))
        else:
            sections.append("=== mutmut show ===\nNo surviving mutants.")

        return _SECTION_SEP.join(sections)

    def normalize(self, raw_output: str) -> AnalyzerResult:
        """Parse raw output into a structured AnalyzerResult."""
        clean = strip_ansi(raw_output)

        run_section = self._extract_section(clean, "=== mutmut run ===")
        results_section = self._extract_section(clean, "=== mutmut results ===")
        show_section = self._extract_section(clean, "=== mutmut show ===")

        killed = self._parse_int(_KILLED_RE, run_section)
        survived_count = self._parse_int(_SURVIVED_RE, run_section)

        # Fallback: count from results section if emoji parsing failed
        surviving_ids = self._parse_surviving_ids(results_section)
        if survived_count is None:
            survived_count = len(surviving_ids)

        total = (killed or 0) + (survived_count or 0) if killed is not None else None
        score = round((killed / total) * 100, 2) if killed is not None and total else None

        metrics = RunMetrics(
            score=score,
            total=total,
            ok_count=killed,       # killed mutants = tests that caught the mutation
            issue_count=survived_count,  # surviving mutants = test gaps
        )

        details = self._parse_mutant_details(surviving_ids, show_section)
        execution_status = (
            ExecutionStatus.SUCCESS if killed is not None else ExecutionStatus.FAILED
        )

        return AnalyzerResult(
            analyzer=self.name,
            language=self.language,
            execution_status=execution_status,
            metrics=metrics,
            details=details,
            raw_output=raw_output,
        )

    def write_artifacts(self, result: AnalyzerResult) -> None:
        """Write raw output, normalized JSON, and markdown/JSON summaries."""
        raw_dir, norm_dir, summary_dir = self._artifact_dirs()

        raw_path = raw_dir / "mutmut-raw.txt"
        raw_path.write_text(result.raw_output, encoding="utf-8")

        norm_path = norm_dir / "mutmut.json"
        norm_path.write_text(self._to_normalized_json(result), encoding="utf-8")

        summary_json_path = summary_dir / "mutmut-summary.json"
        summary_json_path.write_text(self._to_summary_json(result), encoding="utf-8")

        summary_md_path = summary_dir / "mutmut-summary.md"
        summary_md_path.write_text(self._to_summary_md(result), encoding="utf-8")

        result.artifacts = {
            "raw": raw_path,
            "normalized": norm_path,
            "summary_json": summary_json_path,
            "summary_md": summary_md_path,
        }

    # ------------------------------------------------------------------
    # Private helpers — subprocess
    # ------------------------------------------------------------------

    def _maybe_clean_cache(self) -> None:
        """Delete the mutmut cache file if ``config.clean_cache`` is True."""
        if not self.config.clean_cache:
            return

        cache_dir = self.config.cache_dir or Path(".")
        cache_file = cache_dir / ".mutmut-cache"
        if cache_file.exists():
            cache_file.unlink()
            logger.info("[mutmut] Cache file removed: %s", cache_file)

    def _run_subprocess(self, cmd: list[str]) -> str:
        """Run *cmd* and return combined stdout+stderr as a string.

        Non-zero exit codes are logged but do NOT raise — mutmut exits
        non-zero when there are surviving mutants, which is a valid outcome.
        """
        env = self._build_env()
        logger.debug("[mutmut] Running: %s", " ".join(cmd))

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config.timeout,
                env=env,
            )
        except subprocess.TimeoutExpired:
            logger.warning("[mutmut] Command timed out: %s", " ".join(cmd))
            return f"[TIMEOUT] Command timed out after {self.config.timeout}s: {' '.join(cmd)}"
        except FileNotFoundError:
            logger.error("[mutmut] Command not found: %s", cmd[0])
            return f"[ERROR] Command not found: {cmd[0]}"

        output = (proc.stdout or "") + (proc.stderr or "")

        if proc.returncode not in (0, 1):
            # returncode 1 is normal for mutmut (survivors exist)
            logger.debug("[mutmut] Exit code %d for: %s", proc.returncode, " ".join(cmd))

        return output

    def _build_env(self) -> dict[str, str] | None:
        """Build environment variables for subprocess calls.

        If ``config.cache_dir`` is set, injects ``MUTMUT_CACHE_DIR`` so
        mutmut writes its cache to the configured location.
        """
        import os

        if self.config.cache_dir is None:
            return None

        env = os.environ.copy()
        env["MUTMUT_CACHE_DIR"] = str(self.config.cache_dir)
        return env

    # ------------------------------------------------------------------
    # Private helpers — parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_section(text: str, header: str) -> str:
        """Return the content that follows *header* up to the next separator."""
        sep = "=" * 60
        start = text.find(header)
        if start == -1:
            return ""
        start += len(header)
        end = text.find(sep, start)
        return text[start:end].strip() if end != -1 else text[start:].strip()

    @staticmethod
    def _parse_int(pattern: re.Pattern[str], text: str) -> int | None:
        """Return the first integer captured by *pattern* in *text*, or None."""
        m = pattern.search(text)
        return int(m.group(1)) if m else None

    @staticmethod
    def _parse_surviving_ids(results_text: str) -> list[str]:
        """Extract unique mutant IDs from ``mutmut results`` output."""
        ids: list[str] = []
        seen: set[str] = set()

        for line in results_text.splitlines():
            line = line.strip()
            if not line:
                continue

            m = _NAMED_MUTANT_RE.match(line)
            if m:
                mid = m.group(1)
            else:
                m = _NUM_MUTANT_RE.match(line)
                mid = m.group(1) if m else None

            if mid and mid not in seen:
                ids.append(mid)
                seen.add(mid)

        return ids

    @staticmethod
    def _parse_mutant_details(surviving_ids: list[str], show_section: str) -> list[MutantDetail]:
        """Build MutantDetail objects from the show section."""
        details: list[MutantDetail] = []
        if not surviving_ids:
            return details

        for mutant_id in surviving_ids:
            marker = f"----- MUTANT: {mutant_id} -----"
            start = show_section.find(marker)
            if start == -1:
                details.append(MutantDetail(mutant_id=mutant_id))
                continue

            start += len(marker)
            next_marker = show_section.find("----- MUTANT:", start)
            block = (
                show_section[start:next_marker].strip()
                if next_marker != -1
                else show_section[start:].strip()
            )
            details.append(MutantDetail(mutant_id=mutant_id, show_output=block))

        return details

    # ------------------------------------------------------------------
    # Private helpers — serialization
    # ------------------------------------------------------------------

    @staticmethod
    def _to_normalized_json(result: AnalyzerResult) -> str:
        payload = {
            "analyzer": result.analyzer,
            "language": result.language,
            "execution_status": result.execution_status.value,
            "metrics": {
                "score": result.metrics.score,
                "total": result.metrics.total,
                "killed": result.metrics.ok_count,
                "survived": result.metrics.issue_count,
            },
            "details": [asdict(d) for d in result.details],
        }
        return json.dumps(payload, indent=2, ensure_ascii=False)

    @staticmethod
    def _to_summary_json(result: AnalyzerResult) -> str:
        m = result.metrics
        payload = {
            "analyzer": result.analyzer,
            "execution_status": result.execution_status.value,
            "score": m.score,
            "killed": m.ok_count,
            "survived": m.issue_count,
            "total": m.total,
            "surviving_mutant_ids": [d.mutant_id for d in result.details],  # type: ignore[attr-defined]
        }
        return json.dumps(payload, indent=2, ensure_ascii=False)

    @staticmethod
    def _to_summary_md(result: AnalyzerResult) -> str:
        m = result.metrics
        score_str = f"{m.score}%" if m.score is not None else "N/A"
        killed_str = str(m.ok_count) if m.ok_count is not None else "N/A"
        survived_str = str(m.issue_count) if m.issue_count is not None else "N/A"
        total_str = str(m.total) if m.total is not None else "N/A"

        details: list[MutantDetail] = result.details  # type: ignore[assignment]
        mutant_lines = (
            "\n".join(f"- `{d.mutant_id}`" for d in details)
            if details
            else "No surviving mutants detected."
        )

        return f"""\
## Mutation Testing Summary

| Metric | Value |
|---|---:|
| Mutation Score | **{score_str}** |
| Killed | **{killed_str}** |
| Survived | **{survived_str}** |
| Total evaluated | **{total_str}** |

### Surviving mutants

{mutant_lines}

### Artifacts

- `raw/mutmut-raw.txt` — full tool output
- `normalized/mutmut.json` — structured normalized data
- `summary/mutmut-summary.json` — summary JSON
- `summary/mutmut-summary.md` — this file
"""
