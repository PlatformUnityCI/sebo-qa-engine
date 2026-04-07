"""Tests for RadonAnalyzer.

All subprocess calls are mocked — radon is NOT executed.
Tests cover: run(), normalize(), write_artifacts(), and the full analyze() pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sebco_qa_engine.analyzers.python.radon.analyzer import RadonAnalyzer
from sebco_qa_engine.analyzers.python.radon.config import RadonConfig
from sebco_qa_engine.core.models import ExecutionStatus


# ---------------------------------------------------------------------------
# Fixtures — synthetic radon output
# ---------------------------------------------------------------------------

def _make_proc(stdout: str, returncode: int = 0) -> MagicMock:
    proc = MagicMock()
    proc.stdout = stdout
    proc.stderr = ""
    proc.returncode = returncode
    return proc


def _make_analyzer(tmp_path: Path, config: RadonConfig | None = None) -> RadonAnalyzer:
    return RadonAnalyzer(output_dir=tmp_path / "qa-report" / "radon", config=config)


RADON_JSON = json.dumps({
    "src/foo.py": [{"type": "Module", "rank": "A", "mi": 87.5, "name": "src/foo.py"}],
    "src/bar.py": [{"type": "Module", "rank": "B", "mi": 65.3, "name": "src/bar.py"}],
})

RADON_JSON_EMPTY = json.dumps({})


# ---------------------------------------------------------------------------
# Tests: run()
# ---------------------------------------------------------------------------

class TestRadonAnalyzerRun:
    def test_run_calls_radon_mi_with_json_flag(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc(stdout=RADON_JSON)
            analyzer.run()

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "radon"
        assert cmd[1] == "mi"
        assert "-j" in cmd

    def test_run_includes_paths(self, tmp_path):
        cfg = RadonConfig(paths=["src/", "tests/"])
        analyzer = _make_analyzer(tmp_path, config=cfg)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc(stdout=RADON_JSON)
            analyzer.run()

        cmd = mock_run.call_args[0][0]
        assert "src/" in cmd
        assert "tests/" in cmd

    def test_run_includes_extra_args(self, tmp_path):
        cfg = RadonConfig(extra_args=["--min", "B"])
        analyzer = _make_analyzer(tmp_path, config=cfg)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc(stdout=RADON_JSON)
            analyzer.run()

        cmd = mock_run.call_args[0][0]
        assert "--min" in cmd
        assert "B" in cmd

    def test_run_returns_stdout(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc(stdout=RADON_JSON)
            raw = analyzer.run()

        assert raw == RADON_JSON

    def test_run_handles_timeout(self, tmp_path):
        import subprocess

        analyzer = _make_analyzer(tmp_path, config=RadonConfig(timeout=1))

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="radon", timeout=1)):
            raw = analyzer.run()

        assert "[TIMEOUT]" in raw

    def test_run_handles_missing_radon(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)

        with patch("subprocess.run", side_effect=FileNotFoundError):
            raw = analyzer.run()

        assert "[ERROR]" in raw


# ---------------------------------------------------------------------------
# Tests: normalize()
# ---------------------------------------------------------------------------

class TestRadonAnalyzerNormalize:
    def test_execution_status_success_on_valid_json(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(RADON_JSON)
        assert result.execution_status == ExecutionStatus.SUCCESS

    def test_score_is_mean_of_mi_values(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(RADON_JSON)
        expected_mean = round((87.5 + 65.3) / 2, 2)
        assert result.metrics.score == pytest.approx(expected_mean, abs=0.01)

    def test_total_is_module_entry_count(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(RADON_JSON)
        assert result.metrics.total == 2

    def test_grades_counted_correctly(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(RADON_JSON)
        grades = result.metrics.extra["grades"]
        assert grades["A"] == 1
        assert grades["B"] == 1
        assert grades["C"] == 0

    def test_details_parsed_correctly(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(RADON_JSON)
        assert len(result.details) == 2
        files = [d["file"] for d in result.details]
        assert "src/foo.py" in files
        assert "src/bar.py" in files

    def test_detail_contains_mi_and_rank(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(RADON_JSON)
        foo_detail = next(d for d in result.details if d["file"] == "src/foo.py")
        assert foo_detail["mi"] == 87.5
        assert foo_detail["rank"] == "A"

    def test_analyzer_and_language_set(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(RADON_JSON)
        assert result.analyzer == "radon"
        assert result.language == "python"

    def test_empty_json_returns_success_with_none_score(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(RADON_JSON_EMPTY)
        assert result.execution_status == ExecutionStatus.SUCCESS
        assert result.metrics.score is None
        assert result.metrics.total == 0
        assert result.details == []

    def test_invalid_json_returns_failed(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize("not valid json {{")
        assert result.execution_status == ExecutionStatus.FAILED

    def test_error_sentinel_returns_error_status(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize("[ERROR] Command not found: radon")
        assert result.execution_status == ExecutionStatus.ERROR

    def test_timeout_sentinel_returns_error_status(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize("[TIMEOUT] Command timed out after 120s")
        assert result.execution_status == ExecutionStatus.ERROR

    def test_grades_all_present_in_extra(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(RADON_JSON)
        grades = result.metrics.extra["grades"]
        for grade in ["A", "B", "C", "D", "E", "F"]:
            assert grade in grades


# ---------------------------------------------------------------------------
# Tests: write_artifacts()
# ---------------------------------------------------------------------------

class TestRadonAnalyzerWriteArtifacts:
    def _get_result_and_analyzer(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(RADON_JSON)
        return analyzer, result

    def test_raw_file_created(self, tmp_path):
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        assert result.artifacts["raw"].exists()

    def test_normalized_json_created(self, tmp_path):
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        assert result.artifacts["normalized"].exists()

    def test_summary_json_created(self, tmp_path):
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        assert result.artifacts["summary_json"].exists()

    def test_summary_md_created(self, tmp_path):
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
        assert data["analyzer"] == "radon"
        assert "metrics" in data
        assert "details" in data

    def test_summary_json_is_valid(self, tmp_path):
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        data = json.loads(result.artifacts["summary_json"].read_text())
        assert data["analyzer"] == "radon"
        assert "score" in data
        assert "total_files" in data
        assert "grades" in data

    def test_summary_md_contains_score_and_grades(self, tmp_path):
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        md = result.artifacts["summary_md"].read_text()
        assert "Maintainability Summary" in md
        assert "Mean MI Score" in md
        assert "Grade Distribution" in md

    def test_directories_created_automatically(self, tmp_path):
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        assert (analyzer.output_dir / "raw").is_dir()
        assert (analyzer.output_dir / "normalized").is_dir()
        assert (analyzer.output_dir / "summary").is_dir()


# ---------------------------------------------------------------------------
# Tests: full analyze() pipeline
# ---------------------------------------------------------------------------

class TestRadonAnalyzerFullPipeline:
    def test_analyze_returns_analyzer_result(self, tmp_path):
        from sebco_qa_engine.core.models import AnalyzerResult

        analyzer = _make_analyzer(tmp_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc(stdout=RADON_JSON)
            result = analyzer.analyze()

        assert isinstance(result, AnalyzerResult)

    def test_analyze_writes_all_artifacts(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc(stdout=RADON_JSON)
            result = analyzer.analyze()

        assert len(result.artifacts) == 4
        for path in result.artifacts.values():
            assert path.exists()

    def test_analyze_returns_error_result_on_exception(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)

        with patch.object(analyzer, "run", side_effect=RuntimeError("boom")):
            result = analyzer.analyze()

        assert result.execution_status == ExecutionStatus.ERROR
        assert "boom" in result.error_message
