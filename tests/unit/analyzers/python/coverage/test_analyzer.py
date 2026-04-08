"""Tests for CoverageAnalyzer.

All subprocess calls are mocked — coverage is NOT executed.
Tests cover: run(), normalize(), write_artifacts(), and the full analyze() pipeline.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sebco_qa_engine.analyzers.python.coverage.analyzer import CoverageAnalyzer
from sebco_qa_engine.analyzers.python.coverage.config import CoverageConfig
from sebco_qa_engine.core.models import AnalyzerResult, ExecutionStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_proc(stdout: str, returncode: int = 0) -> MagicMock:
    proc = MagicMock()
    proc.stdout = stdout
    proc.stderr = ""
    proc.returncode = returncode
    return proc


def _make_analyzer(tmp_path: Path, config: CoverageConfig | None = None) -> CoverageAnalyzer:
    return CoverageAnalyzer(output_dir=tmp_path / "qa-report" / "coverage", config=config)


# Realistic ``coverage report`` output (simple format: stmts miss cover%)
_COVERAGE_OUTPUT_SIMPLE = """\
Name                      Stmts   Miss  Cover
---------------------------------------------
src/foo.py                   50     10    80%
src/bar.py                  100      5    95%
src/baz.py                   30     30     0%
---------------------------------------------
TOTAL                       180     45    75%
"""

# Branch coverage format: stmts miss branch partial cover%
_COVERAGE_OUTPUT_BRANCH = """\
Name                      Stmts   Miss Branch BrPart  Cover
-----------------------------------------------------------
src/foo.py                   50     10     20      5    80%
src/bar.py                  100      5     40      2    95%
-----------------------------------------------------------
TOTAL                       150     15     60      7    88%
"""

_COVERAGE_OUTPUT_NO_TOTAL = """\
Name                      Stmts   Miss  Cover
---------------------------------------------
src/foo.py                   50     10    80%
---------------------------------------------
"""


# ---------------------------------------------------------------------------
# Tests: run()
# ---------------------------------------------------------------------------

class TestCoverageAnalyzerRun:
    def test_run_calls_coverage_report(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc("")
            analyzer.run()

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "coverage"
        assert cmd[1] == "report"

    def test_run_includes_format_text(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc("")
            analyzer.run()

        cmd = mock_run.call_args[0][0]
        assert "--format=text" in cmd

    def test_run_forwards_extra_args(self, tmp_path):
        cfg = CoverageConfig(extra_args=["--include=src/*"])
        analyzer = _make_analyzer(tmp_path, config=cfg)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc("")
            analyzer.run()

        cmd = mock_run.call_args[0][0]
        assert "--include=src/*" in cmd

    def test_run_handles_timeout(self, tmp_path):
        analyzer = _make_analyzer(tmp_path, config=CoverageConfig(timeout=5))

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="coverage", timeout=5)):
            raw = analyzer.run()

        assert "[TIMEOUT]" in raw

    def test_run_handles_file_not_found(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)

        with patch("subprocess.run", side_effect=FileNotFoundError):
            raw = analyzer.run()

        assert "[ERROR]" in raw

    def test_run_returns_combined_stdout_stderr(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)

        proc = MagicMock()
        proc.stdout = "stdout content"
        proc.stderr = "stderr content"
        proc.returncode = 0

        with patch("subprocess.run", return_value=proc):
            raw = analyzer.run()

        assert "stdout content" in raw
        assert "stderr content" in raw


# ---------------------------------------------------------------------------
# Tests: normalize()
# ---------------------------------------------------------------------------

class TestCoverageAnalyzerNormalize:
    def test_score_parsed_from_total_line(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_COVERAGE_OUTPUT_SIMPLE)
        assert result.metrics.score == pytest.approx(75.0)

    def test_total_stmts_parsed(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_COVERAGE_OUTPUT_SIMPLE)
        assert result.metrics.total == 180

    def test_issue_count_is_missed(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_COVERAGE_OUTPUT_SIMPLE)
        assert result.metrics.issue_count == 45

    def test_ok_count_is_covered_stmts(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_COVERAGE_OUTPUT_SIMPLE)
        assert result.metrics.ok_count == 180 - 45

    def test_execution_status_success_when_total_found(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_COVERAGE_OUTPUT_SIMPLE)
        assert result.execution_status == ExecutionStatus.SUCCESS

    def test_execution_status_failed_when_no_total(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_COVERAGE_OUTPUT_NO_TOTAL)
        assert result.execution_status == ExecutionStatus.FAILED

    def test_failed_result_has_empty_details(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_COVERAGE_OUTPUT_NO_TOTAL)
        assert result.details == []

    def test_per_file_details_parsed(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_COVERAGE_OUTPUT_SIMPLE)
        # 3 files (not TOTAL)
        assert len(result.details) == 3

    def test_per_file_detail_fields(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_COVERAGE_OUTPUT_SIMPLE)
        first = result.details[0]
        assert first["file"] == "src/foo.py"
        assert first["stmts"] == 50
        assert first["miss"] == 10
        assert first["cover_pct"] == 80

    def test_total_line_excluded_from_details(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_COVERAGE_OUTPUT_SIMPLE)
        files = [d["file"] for d in result.details]
        assert "TOTAL" not in files

    def test_branch_coverage_format_parsed(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_COVERAGE_OUTPUT_BRANCH)
        assert result.metrics.score == pytest.approx(88.0)
        assert result.metrics.total == 150

    def test_analyzer_and_language_set(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_COVERAGE_OUTPUT_SIMPLE)
        assert result.analyzer == "coverage"
        assert result.language == "python"

    def test_metrics_none_when_failed(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_COVERAGE_OUTPUT_NO_TOTAL)
        assert result.metrics.score is None
        assert result.metrics.total is None

    def test_raw_output_preserved(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_COVERAGE_OUTPUT_SIMPLE)
        assert result.raw_output == _COVERAGE_OUTPUT_SIMPLE


# ---------------------------------------------------------------------------
# Tests: write_artifacts()
# ---------------------------------------------------------------------------

class TestCoverageAnalyzerWriteArtifacts:
    def _get_result_and_analyzer(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_COVERAGE_OUTPUT_SIMPLE)
        return analyzer, result

    def test_raw_artifact_created(self, tmp_path):
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        assert result.artifacts["raw"].exists()

    def test_normalized_artifact_created(self, tmp_path):
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        assert result.artifacts["normalized"].exists()

    def test_summary_json_artifact_created(self, tmp_path):
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        assert result.artifacts["summary_json"].exists()

    def test_summary_md_artifact_created(self, tmp_path):
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        assert result.artifacts["summary_md"].exists()

    def test_all_canonical_artifact_keys_present(self, tmp_path):
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        assert set(result.artifacts.keys()) == {"raw", "normalized", "summary_json", "summary_md"}

    def test_normalized_json_is_valid(self, tmp_path):
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        data = json.loads(result.artifacts["normalized"].read_text())
        assert data["analyzer"] == "coverage"
        assert "metrics" in data
        assert "details" in data

    def test_normalized_json_has_score(self, tmp_path):
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        data = json.loads(result.artifacts["normalized"].read_text())
        assert data["metrics"]["score"] == pytest.approx(75.0)

    def test_summary_json_is_valid(self, tmp_path):
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        data = json.loads(result.artifacts["summary_json"].read_text())
        assert data["analyzer"] == "coverage"
        assert "score" in data
        assert "stmts" in data
        assert "missed" in data
        assert "covered" in data

    def test_summary_markdown_contains_coverage_percent(self, tmp_path):
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        md = result.artifacts["summary_md"].read_text()
        # Score is formatted without decimal — "75%" not "75.0%"
        assert "75%" in md

    def test_summary_markdown_contains_file_table(self, tmp_path):
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        md = result.artifacts["summary_md"].read_text()
        assert "src/foo.py" in md

    def test_directories_created_automatically(self, tmp_path):
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        assert (analyzer.output_dir / "raw").is_dir()
        assert (analyzer.output_dir / "normalized").is_dir()
        assert (analyzer.output_dir / "summary").is_dir()

    def test_raw_file_content_matches_raw_output(self, tmp_path):
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        raw_content = result.artifacts["raw"].read_text()
        assert raw_content == result.raw_output


# ---------------------------------------------------------------------------
# Tests: full analyze() pipeline
# ---------------------------------------------------------------------------

class TestCoverageAnalyzerFullPipeline:
    def test_analyze_returns_analyzer_result(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc(_COVERAGE_OUTPUT_SIMPLE)
            result = analyzer.analyze()

        assert isinstance(result, AnalyzerResult)

    def test_analyze_writes_all_artifacts(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc(_COVERAGE_OUTPUT_SIMPLE)
            result = analyzer.analyze()

        assert len(result.artifacts) == 4
        for path in result.artifacts.values():
            assert path.exists()

    def test_analyze_success_with_valid_output(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc(_COVERAGE_OUTPUT_SIMPLE)
            result = analyzer.analyze()

        assert result.execution_status == ExecutionStatus.SUCCESS
        assert result.metrics.score == pytest.approx(75.0)

    def test_analyze_returns_error_on_exception(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)

        with patch.object(analyzer, "run", side_effect=RuntimeError("boom")):
            result = analyzer.analyze()

        assert result.execution_status == ExecutionStatus.ERROR
        assert "boom" in result.error_message


# ---------------------------------------------------------------------------
# Tests: normalize() — sentinel strings from run() map to ERROR status
# ---------------------------------------------------------------------------

class TestCoverageAnalyzerNormalizeSentinels:
    """Verify that [TIMEOUT] and [ERROR] sentinels injected by run() produce
    ExecutionStatus.ERROR — not FAILED — in normalize()."""

    def test_timeout_sentinel_yields_error_status(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        raw = "[TIMEOUT] Command timed out after 120s: coverage report --format=text"
        result = analyzer.normalize(raw)
        assert result.execution_status == ExecutionStatus.ERROR

    def test_error_sentinel_yields_error_status(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        raw = "[ERROR] Command not found: coverage"
        result = analyzer.normalize(raw)
        assert result.execution_status == ExecutionStatus.ERROR

    def test_timeout_sentinel_preserves_raw_output(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        raw = "[TIMEOUT] Command timed out after 120s: coverage report --format=text"
        result = analyzer.normalize(raw)
        assert result.raw_output == raw

    def test_error_sentinel_populates_error_message(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        raw = "[ERROR] Command not found: coverage"
        result = analyzer.normalize(raw)
        assert result.error_message == raw

    def test_timeout_sentinel_has_no_score(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        raw = "[TIMEOUT] Command timed out after 120s: coverage report --format=text"
        result = analyzer.normalize(raw)
        assert result.metrics.score is None

    def test_error_sentinel_has_empty_details(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        raw = "[ERROR] Command not found: coverage"
        result = analyzer.normalize(raw)
        assert result.details == []


# ---------------------------------------------------------------------------
# Tests: _to_summary_json — score_percent field and score formatting
# ---------------------------------------------------------------------------

class TestCoverageAnalyzerSummaryJson:
    def _get_summary_data(self, tmp_path) -> dict:
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_COVERAGE_OUTPUT_SIMPLE)
        analyzer.write_artifacts(result)
        return json.loads(result.artifacts["summary_json"].read_text())

    def test_summary_json_has_score_percent_field(self, tmp_path):
        data = self._get_summary_data(tmp_path)
        assert "score_percent" in data

    def test_summary_json_score_percent_equals_score(self, tmp_path):
        data = self._get_summary_data(tmp_path)
        assert data["score_percent"] == pytest.approx(75.0)

    def test_summary_json_score_percent_none_when_failed(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_COVERAGE_OUTPUT_NO_TOTAL)
        analyzer.write_artifacts(result)
        data = json.loads(result.artifacts["summary_json"].read_text())
        assert data["score_percent"] is None

    def test_summary_markdown_score_no_decimal(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_COVERAGE_OUTPUT_SIMPLE)
        analyzer.write_artifacts(result)
        md = result.artifacts["summary_md"].read_text()
        # Should show "75%" not "75.0%"
        assert "75%" in md
        assert "75.0%" not in md
