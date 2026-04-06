"""Tests for MutmutAnalyzer.

All subprocess calls are mocked — mutmut is NOT executed.
Tests cover: run(), normalize(), write_artifacts(), and the full analyze() pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sebco_qa_engine.analyzers.python.mutmut.analyzer import MutmutAnalyzer
from sebco_qa_engine.analyzers.python.mutmut.config import MutmutConfig
from sebco_qa_engine.analyzers.python.mutmut.models import MutantDetail
from sebco_qa_engine.core.models import ExecutionStatus


# ---------------------------------------------------------------------------
# Fixtures — synthetic mutmut output
# ---------------------------------------------------------------------------

def _make_proc(stdout: str, returncode: int = 0) -> MagicMock:
    proc = MagicMock()
    proc.stdout = stdout
    proc.stderr = ""
    proc.returncode = returncode
    return proc


def _make_analyzer(tmp_path: Path, config: MutmutConfig | None = None) -> MutmutAnalyzer:
    return MutmutAnalyzer(output_dir=tmp_path / "qa-report" / "mutmut", config=config)


def _make_raw_with_survivors() -> str:
    sep = "\n" + "=" * 60 + "\n"
    return sep.join([
        "=== mutmut run ===\n🎉  40 🙁  3",
        "=== mutmut results ===\n1: survived\n2: survived\n42: survived",
        (
            "=== mutmut show ===\n"
            "----- MUTANT: 1 -----\ndiff1\n"
            "----- MUTANT: 2 -----\ndiff2\n"
            "----- MUTANT: 42 -----\ndiff42\n"
        ),
    ])


def _make_raw_no_survivors() -> str:
    sep = "\n" + "=" * 60 + "\n"
    return sep.join([
        "=== mutmut run ===\n🎉  40 🙁  0",
        "=== mutmut results ===\nAll OK.",
        "=== mutmut show ===\nNo surviving mutants.",
    ])


# ---------------------------------------------------------------------------
# Tests: MutantDetail (mutmut-specific model)
# ---------------------------------------------------------------------------

class TestMutantDetail:
    def test_defaults(self):
        d = MutantDetail(mutant_id="1")
        assert d.mutant_id == "1"
        assert d.diff == ""
        assert d.show_output == ""

    def test_full_construction(self):
        d = MutantDetail(mutant_id="abc", diff="- x\n+ y", show_output="some output")
        assert d.diff == "- x\n+ y"
        assert d.show_output == "some output"


# ---------------------------------------------------------------------------
# Tests: run()
# ---------------------------------------------------------------------------

class TestMutmutAnalyzerRun:
    def test_run_calls_mutmut_run_first(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc(stdout="🎉  0 🙁  0")
            analyzer.run()

        first_call_args = mock_run.call_args_list[0][0][0]
        assert first_call_args == ["mutmut", "run"]

    def test_run_calls_mutmut_results_second(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc(stdout="")
            analyzer.run()

        second_call_args = mock_run.call_args_list[1][0][0]
        assert second_call_args == ["mutmut", "results"]

    def test_run_calls_show_for_each_survivor(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)

        def side_effect(cmd, **kwargs):
            if cmd[1] == "run":
                return _make_proc("🎉  10 🙁  2")
            if cmd[1] == "results":
                return _make_proc("1: survived\n2: survived\n")
            if cmd[1] == "show":
                return _make_proc(f"diff for {cmd[2]}")
            return _make_proc("")

        with patch("subprocess.run", side_effect=side_effect) as mock_run:
            analyzer.run()

        show_calls = [c for c in mock_run.call_args_list if c[0][0][1] == "show"]
        assert len(show_calls) == 2
        shown_ids = [c[0][0][2] for c in show_calls]
        assert "1" in shown_ids
        assert "2" in shown_ids

    def test_run_returns_string_with_all_sections(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc("")
            raw = analyzer.run()

        assert "=== mutmut run ===" in raw
        assert "=== mutmut results ===" in raw
        assert "=== mutmut show ===" in raw

    def test_run_handles_timeout(self, tmp_path):
        import subprocess

        analyzer = _make_analyzer(tmp_path, config=MutmutConfig(timeout=1))

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="mutmut", timeout=1)):
            raw = analyzer.run()

        assert "[TIMEOUT]" in raw

    def test_run_handles_missing_mutmut(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)

        with patch("subprocess.run", side_effect=FileNotFoundError):
            raw = analyzer.run()

        assert "[ERROR]" in raw

    def test_run_includes_extra_args(self, tmp_path):
        cfg = MutmutConfig(extra_args=["--paths-to-mutate", "src/"])
        analyzer = _make_analyzer(tmp_path, config=cfg)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc("")
            analyzer.run()

        run_call = mock_run.call_args_list[0][0][0]
        assert "--paths-to-mutate" in run_call
        assert "src/" in run_call


# ---------------------------------------------------------------------------
# Tests: normalize()
# ---------------------------------------------------------------------------

class TestMutmutAnalyzerNormalize:
    def test_score_calculated_correctly(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_make_raw_with_survivors())
        assert result.metrics.score == pytest.approx(93.02, abs=0.1)

    def test_ok_count_is_killed(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_make_raw_with_survivors())
        assert result.metrics.ok_count == 40

    def test_issue_count_is_survived(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_make_raw_with_survivors())
        assert result.metrics.issue_count == 3

    def test_total_is_sum(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_make_raw_with_survivors())
        assert result.metrics.total == 43

    def test_surviving_mutant_ids_extracted(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_make_raw_with_survivors())
        ids = [d.mutant_id for d in result.details]
        assert "1" in ids
        assert "2" in ids
        assert "42" in ids

    def test_no_survivors_execution_status_success(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_make_raw_no_survivors())
        assert result.execution_status == ExecutionStatus.SUCCESS
        assert result.details == []

    def test_perfect_score_when_no_survivors(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_make_raw_no_survivors())
        assert result.metrics.score == 100.0
        assert result.metrics.issue_count == 0

    def test_analyzer_and_language_set(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(_make_raw_with_survivors())
        assert result.analyzer == "mutmut"
        assert result.language == "python"

    def test_ansi_codes_in_raw_output_are_stripped(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        raw_with_ansi = "\x1b[2K\x1b[1A" + _make_raw_with_survivors()
        result = analyzer.normalize(raw_with_ansi)
        assert result.metrics.score is not None


# ---------------------------------------------------------------------------
# Tests: write_artifacts()
# ---------------------------------------------------------------------------

class TestMutmutAnalyzerWriteArtifacts:
    def _get_result_and_analyzer(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        sep = "\n" + "=" * 60 + "\n"
        raw = sep.join([
            "=== mutmut run ===\n🎉  10 🙁  1",
            "=== mutmut results ===\n5: survived",
            "=== mutmut show ===\n----- MUTANT: 5 -----\ndiff5",
        ])
        return analyzer, analyzer.normalize(raw)

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

    def test_normalized_json_is_valid(self, tmp_path):
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        data = json.loads(result.artifacts["normalized"].read_text())
        assert data["analyzer"] == "mutmut"
        assert "metrics" in data
        assert "details" in data

    def test_normalized_json_uses_domain_names(self, tmp_path):
        """JSON output uses 'killed'/'survived', not the generic ok_count/issue_count."""
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        data = json.loads(result.artifacts["normalized"].read_text())
        assert "killed" in data["metrics"]
        assert "survived" in data["metrics"]

    def test_summary_md_contains_table(self, tmp_path):
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        md = result.artifacts["summary_md"].read_text()
        assert "## Mutation Testing Summary" in md
        assert "Mutation Score" in md

    def test_all_canonical_artifact_keys_present(self, tmp_path):
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        assert set(result.artifacts.keys()) == {"raw", "normalized", "summary_json", "summary_md"}

    def test_directories_created_automatically(self, tmp_path):
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        assert (analyzer.output_dir / "raw").is_dir()
        assert (analyzer.output_dir / "normalized").is_dir()
        assert (analyzer.output_dir / "summary").is_dir()


# ---------------------------------------------------------------------------
# Tests: cache management
# ---------------------------------------------------------------------------

class TestMutmutCacheManagement:
    def test_cache_not_deleted_by_default(self, tmp_path):
        cache_file = tmp_path / ".mutmut-cache"
        cache_file.write_text("cache")

        cfg = MutmutConfig(cache_dir=tmp_path, clean_cache=False)
        analyzer = _make_analyzer(tmp_path, config=cfg)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc("")
            analyzer.run()

        assert cache_file.exists()

    def test_cache_deleted_when_clean_cache_true(self, tmp_path):
        cache_file = tmp_path / ".mutmut-cache"
        cache_file.write_text("cache")

        cfg = MutmutConfig(cache_dir=tmp_path, clean_cache=True)
        analyzer = _make_analyzer(tmp_path, config=cfg)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc("")
            analyzer.run()

        assert not cache_file.exists()

    def test_clean_cache_no_error_if_file_missing(self, tmp_path):
        cfg = MutmutConfig(cache_dir=tmp_path, clean_cache=True)
        analyzer = _make_analyzer(tmp_path, config=cfg)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc("")
            analyzer.run()  # Should not raise


# ---------------------------------------------------------------------------
# Tests: full analyze() pipeline
# ---------------------------------------------------------------------------

class TestMutmutAnalyzerFullPipeline:
    def test_analyze_returns_analyzer_result(self, tmp_path):
        from sebco_qa_engine.core.models import AnalyzerResult

        analyzer = _make_analyzer(tmp_path)

        def side_effect(cmd, **kwargs):
            if cmd[1] == "run":
                return _make_proc("🎉  5 🙁  0")
            return _make_proc("")

        with patch("subprocess.run", side_effect=side_effect):
            result = analyzer.analyze()

        assert isinstance(result, AnalyzerResult)

    def test_analyze_writes_artifacts_to_disk(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc("🎉  5 🙁  0")
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
