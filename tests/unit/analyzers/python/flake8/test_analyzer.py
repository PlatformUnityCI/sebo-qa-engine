"""Tests for Flake8Analyzer.

All subprocess calls are mocked — flake8 is NOT executed.
Tests cover: run(), normalize(), write_artifacts(), and the full analyze() pipeline.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sebco_qa_engine.analyzers.python.flake8.analyzer import Flake8Analyzer
from sebco_qa_engine.analyzers.python.flake8.config import Flake8Config
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


def _make_analyzer(tmp_path: Path, config: Flake8Config | None = None) -> Flake8Analyzer:
    return Flake8Analyzer(output_dir=tmp_path / "qa-report" / "flake8", config=config)


# Realistic flake8 default-format output
_VIOLATIONS_OUTPUT = """\
src/foo.py:10:5: E302 expected 2 blank lines, found 1
src/foo.py:25:80: E501 line too long (90 > 79 characters)
src/bar.py:3:1: F401 'os' imported but unused
"""

_NO_VIOLATIONS_OUTPUT = ""


# ---------------------------------------------------------------------------
# Tests: run()
# ---------------------------------------------------------------------------


class TestFlake8AnalyzerRun:
    def test_run_calls_flake8_with_default_paths(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc("")
            analyzer.run()

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "flake8"
        assert "." in cmd

    def test_run_includes_format_default(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc("")
            analyzer.run()

        cmd = mock_run.call_args[0][0]
        assert "--format=default" in cmd

    def test_run_includes_max_line_length_when_set(self, tmp_path):
        cfg = Flake8Config(max_line_length=120)
        analyzer = _make_analyzer(tmp_path, config=cfg)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc("")
            analyzer.run()

        cmd = mock_run.call_args[0][0]
        assert "--max-line-length" in cmd
        assert "120" in cmd

    def test_run_omits_max_line_length_when_none(self, tmp_path):
        cfg = Flake8Config(max_line_length=None)
        analyzer = _make_analyzer(tmp_path, config=cfg)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc("")
            analyzer.run()

        cmd = mock_run.call_args[0][0]
        assert "--max-line-length" not in cmd

    def test_run_forwards_extra_args(self, tmp_path):
        cfg = Flake8Config(extra_args=["--extend-ignore", "E501"])
        analyzer = _make_analyzer(tmp_path, config=cfg)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc("")
            analyzer.run()

        cmd = mock_run.call_args[0][0]
        assert "--extend-ignore" in cmd
        assert "E501" in cmd

    def test_run_handles_timeout(self, tmp_path):
        analyzer = _make_analyzer(tmp_path, config=Flake8Config(timeout=5))

        with patch(
            "subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="flake8", timeout=5)
        ):
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


class TestFlake8AnalyzerNormalize:
    def test_violations_parsed_correctly(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_VIOLATIONS_OUTPUT)
        assert len(result.details) == 3

    def test_violation_fields(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_VIOLATIONS_OUTPUT)
        first = result.details[0]
        assert first["file"] == "src/foo.py"
        assert first["line"] == 10
        assert first["col"] == 5
        assert first["code"] == "E302"
        assert "blank lines" in first["message"]

    def test_issue_count_equals_total_violations(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_VIOLATIONS_OUTPUT)
        assert result.metrics.issue_count == 3
        assert result.metrics.total == 3

    def test_ok_count_zero_when_violations_exist(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_VIOLATIONS_OUTPUT)
        assert result.metrics.ok_count == 0

    def test_ok_count_none_when_no_violations(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_NO_VIOLATIONS_OUTPUT)
        assert result.metrics.ok_count is None

    def test_issue_count_zero_when_no_violations(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_NO_VIOLATIONS_OUTPUT)
        assert result.metrics.issue_count == 0

    def test_violation_codes_in_extra(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_VIOLATIONS_OUTPUT)
        codes = result.metrics.extra["violation_codes"]
        assert "E302" in codes
        assert "E501" in codes
        assert "F401" in codes

    def test_violation_codes_are_sorted(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_VIOLATIONS_OUTPUT)
        codes = result.metrics.extra["violation_codes"]
        assert codes == sorted(codes)

    def test_execution_status_success_with_violations(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_VIOLATIONS_OUTPUT)
        assert result.execution_status == ExecutionStatus.SUCCESS

    def test_execution_status_success_no_violations(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_NO_VIOLATIONS_OUTPUT)
        assert result.execution_status == ExecutionStatus.SUCCESS

    def test_execution_status_failed_on_timeout(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize("[TIMEOUT] Command timed out after 5s: flake8 .")
        assert result.execution_status == ExecutionStatus.FAILED

    def test_execution_status_failed_on_error(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize("[ERROR] Command not found: flake8")
        assert result.execution_status == ExecutionStatus.FAILED

    def test_analyzer_and_language_set(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_VIOLATIONS_OUTPUT)
        assert result.analyzer == "flake8"
        assert result.language == "python"

    def test_unique_violation_codes(self, tmp_path):
        """Duplicate violation codes should appear once in extra."""
        analyzer = _make_analyzer(tmp_path)
        output = "src/a.py:1:1: E302 msg\nsrc/b.py:2:1: E302 msg\n"
        result = analyzer.normalize(output)
        assert result.metrics.extra["violation_codes"].count("E302") == 1

    def test_empty_violation_codes_when_no_violations(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_NO_VIOLATIONS_OUTPUT)
        assert result.metrics.extra["violation_codes"] == []

    # --- score_percent ---

    def test_score_percent_in_metrics_score(self, tmp_path):
        """metrics.score must be score_percent (0–100 range)."""
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_VIOLATIONS_OUTPUT)  # 3 violations, budget=50
        assert result.metrics.score == pytest.approx(94.0)

    def test_score_percent_in_extra(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_VIOLATIONS_OUTPUT)
        assert result.metrics.extra["score_percent"] == pytest.approx(94.0)

    def test_max_issue_budget_in_extra(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_VIOLATIONS_OUTPUT)
        assert result.metrics.extra["max_issue_budget"] == 50

    def test_score_percent_perfect_when_no_violations(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_NO_VIOLATIONS_OUTPUT)
        assert result.metrics.score == pytest.approx(100.0)

    def test_score_percent_floored_at_zero_when_over_budget(self, tmp_path):
        """issue_count > max_issue_budget must clamp to 0, not go negative."""
        cfg = Flake8Config(max_issue_budget=2)
        analyzer = _make_analyzer(tmp_path, config=cfg)
        result = analyzer.normalize(_VIOLATIONS_OUTPUT)  # 3 violations > budget 2
        assert result.metrics.score == 0.0

    def test_score_percent_respects_custom_budget(self, tmp_path):
        """Budget 50, 3 violations → (1 - 3/50) * 100 = 94.0."""
        cfg = Flake8Config(max_issue_budget=50)
        analyzer = _make_analyzer(tmp_path, config=cfg)
        result = analyzer.normalize(_VIOLATIONS_OUTPUT)
        assert result.metrics.score == pytest.approx(94.0)

    def test_score_percent_issue_count_unchanged(self, tmp_path):
        """Adding score_percent must not affect issue_count semantics."""
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_VIOLATIONS_OUTPUT)
        assert result.metrics.issue_count == 3


# ---------------------------------------------------------------------------
# Tests: write_artifacts()
# ---------------------------------------------------------------------------


class TestFlake8AnalyzerWriteArtifacts:
    def _get_result_and_analyzer(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_VIOLATIONS_OUTPUT)
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
        assert data["analyzer"] == "flake8"
        assert "metrics" in data
        assert "details" in data

    def test_normalized_json_contains_details(self, tmp_path):
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        data = json.loads(result.artifacts["normalized"].read_text())
        assert len(data["details"]) == 3

    def test_summary_json_is_valid(self, tmp_path):
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        data = json.loads(result.artifacts["summary_json"].read_text())
        assert data["analyzer"] == "flake8"
        assert "issue_count" in data
        assert "violation_codes" in data

    def test_summary_json_contains_score_percent(self, tmp_path):
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        data = json.loads(result.artifacts["summary_json"].read_text())
        assert "score_percent" in data
        assert data["score_percent"] == pytest.approx(94.0)  # 3 violations, budget 50

    def test_summary_json_contains_max_issue_budget(self, tmp_path):
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        data = json.loads(result.artifacts["summary_json"].read_text())
        assert "max_issue_budget" in data
        assert data["max_issue_budget"] == 50

    def test_normalized_json_contains_score_percent(self, tmp_path):
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        data = json.loads(result.artifacts["normalized"].read_text())
        assert "score_percent" in data["metrics"]
        assert data["metrics"]["score_percent"] == pytest.approx(94.0)

    def test_summary_md_contains_score(self, tmp_path):
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        md = result.artifacts["summary_md"].read_text()
        assert "Score" in md
        assert "94.0%" in md

    def test_summary_markdown_contains_issue_count(self, tmp_path):
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        md = result.artifacts["summary_md"].read_text()
        assert "3" in md  # issue count

    def test_summary_markdown_contains_violations_table(self, tmp_path):
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        md = result.artifacts["summary_md"].read_text()
        assert "E302" in md
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


class TestFlake8AnalyzerFullPipeline:
    def test_analyze_returns_analyzer_result(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc(_VIOLATIONS_OUTPUT, returncode=1)
            result = analyzer.analyze()

        assert isinstance(result, AnalyzerResult)

    def test_analyze_writes_all_artifacts(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc(_VIOLATIONS_OUTPUT, returncode=1)
            result = analyzer.analyze()

        assert len(result.artifacts) == 4
        for path in result.artifacts.values():
            assert path.exists()

    def test_analyze_with_no_violations(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc("", returncode=0)
            result = analyzer.analyze()

        assert result.execution_status == ExecutionStatus.SUCCESS
        assert result.metrics.issue_count == 0

    def test_analyze_returns_error_on_exception(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)

        with patch.object(analyzer, "run", side_effect=RuntimeError("boom")):
            result = analyzer.analyze()

        assert result.execution_status == ExecutionStatus.ERROR
        assert "boom" in result.error_message
