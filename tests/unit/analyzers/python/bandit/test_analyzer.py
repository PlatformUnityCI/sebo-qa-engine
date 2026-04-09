"""Tests for BanditAnalyzer.

All subprocess calls are mocked — bandit is NOT executed.
Tests cover: run(), normalize(), write_artifacts(), and the full analyze() pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sebco_qa_engine.analyzers.python.bandit.analyzer import BanditAnalyzer
from sebco_qa_engine.analyzers.python.bandit.config import BanditConfig
from sebco_qa_engine.analyzers.python.bandit.models import BanditFinding
from sebco_qa_engine.core.models import ExecutionStatus

# ---------------------------------------------------------------------------
# Fixtures — synthetic bandit output
# ---------------------------------------------------------------------------


def _make_proc(stdout: str, returncode: int = 0) -> MagicMock:
    proc = MagicMock()
    proc.stdout = stdout
    proc.stderr = ""
    proc.returncode = returncode
    return proc


def _make_analyzer(tmp_path: Path, config: BanditConfig | None = None) -> BanditAnalyzer:
    return BanditAnalyzer(output_dir=tmp_path / "qa-report" / "bandit", config=config)


BANDIT_JSON_WITH_FINDINGS = json.dumps(
    {
        "errors": [],
        "generated_at": "2024-01-01T00:00:00Z",
        "metrics": {
            "_totals": {
                "CONFIDENCE.HIGH": 1,
                "CONFIDENCE.LOW": 0,
                "CONFIDENCE.MEDIUM": 1,
                "CONFIDENCE.UNDEFINED": 0,
                "SEVERITY.HIGH": 1,
                "SEVERITY.LOW": 0,
                "SEVERITY.MEDIUM": 1,
                "SEVERITY.UNDEFINED": 0,
                "loc": 100,
                "nosec": 0,
            }
        },
        "results": [
            {
                "filename": "src/foo.py",
                "line_number": 10,
                "issue_severity": "HIGH",
                "issue_confidence": "HIGH",
                "test_id": "B105",
                "test_name": "hardcoded_password_string",
                "issue_text": "Possible hardcoded password: 'secret'",
            },
            {
                "filename": "src/bar.py",
                "line_number": 5,
                "issue_severity": "MEDIUM",
                "issue_confidence": "MEDIUM",
                "test_id": "B106",
                "test_name": "hardcoded_password_funcarg",
                "issue_text": "Possible hardcoded password as func arg",
            },
        ],
    }
)

# HIGH=1, MED=1, LOW=0  →  score = max(0, 100 - (1*50 + 1*10 + 0*1)) = 40
_EXPECTED_SCORE_WITH_FINDINGS = 40.0

BANDIT_JSON_NO_FINDINGS = json.dumps(
    {
        "errors": [],
        "generated_at": "2024-01-01T00:00:00Z",
        "metrics": {
            "_totals": {
                "SEVERITY.HIGH": 0,
                "SEVERITY.MEDIUM": 0,
                "SEVERITY.LOW": 0,
                "loc": 50,
                "nosec": 0,
            }
        },
        "results": [],
    }
)


# ---------------------------------------------------------------------------
# Tests: BanditFinding model
# ---------------------------------------------------------------------------


class TestBanditFinding:
    def test_construction(self):
        f = BanditFinding(
            filename="src/foo.py",
            line_number=10,
            severity="HIGH",
            confidence="HIGH",
            test_id="B105",
            test_name="hardcoded_password_string",
            issue_text="Possible hardcoded password: 'secret'",
        )
        assert f.filename == "src/foo.py"
        assert f.line_number == 10
        assert f.severity == "HIGH"
        assert f.confidence == "HIGH"
        assert f.test_id == "B105"
        assert f.test_name == "hardcoded_password_string"
        assert f.issue_text == "Possible hardcoded password: 'secret'"


# ---------------------------------------------------------------------------
# Tests: run()
# ---------------------------------------------------------------------------


class TestBanditAnalyzerRun:
    def test_run_calls_bandit_with_json_format(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc(stdout=BANDIT_JSON_NO_FINDINGS)
            analyzer.run()

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "bandit"
        assert "-f" in cmd
        assert "json" in cmd

    def test_run_includes_recursive_flag_by_default(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc(stdout=BANDIT_JSON_NO_FINDINGS)
            analyzer.run()

        cmd = mock_run.call_args[0][0]
        assert "--recursive" in cmd

    def test_run_excludes_recursive_flag_when_disabled(self, tmp_path):
        cfg = BanditConfig(recursive=False)
        analyzer = _make_analyzer(tmp_path, config=cfg)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc(stdout=BANDIT_JSON_NO_FINDINGS)
            analyzer.run()

        cmd = mock_run.call_args[0][0]
        assert "--recursive" not in cmd

    def test_run_includes_paths(self, tmp_path):
        cfg = BanditConfig(paths=["src/", "tests/"])
        analyzer = _make_analyzer(tmp_path, config=cfg)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc(stdout=BANDIT_JSON_NO_FINDINGS)
            analyzer.run()

        cmd = mock_run.call_args[0][0]
        assert "src/" in cmd
        assert "tests/" in cmd

    def test_run_includes_extra_args(self, tmp_path):
        cfg = BanditConfig(extra_args=["--skip", "B101"])
        analyzer = _make_analyzer(tmp_path, config=cfg)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc(stdout=BANDIT_JSON_NO_FINDINGS)
            analyzer.run()

        cmd = mock_run.call_args[0][0]
        assert "--skip" in cmd
        assert "B101" in cmd

    def test_run_handles_timeout(self, tmp_path):
        import subprocess

        analyzer = _make_analyzer(tmp_path, config=BanditConfig(timeout=1))

        with patch(
            "subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="bandit", timeout=1)
        ):
            raw = analyzer.run()

        assert "[TIMEOUT]" in raw

    def test_run_handles_missing_bandit(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)

        with patch("subprocess.run", side_effect=FileNotFoundError):
            raw = analyzer.run()

        assert "[ERROR]" in raw

    def test_run_accepts_exit_code_0(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc(stdout=BANDIT_JSON_NO_FINDINGS, returncode=0)
            raw = analyzer.run()

        assert raw  # Should not be empty

    def test_run_accepts_exit_code_1(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc(stdout=BANDIT_JSON_WITH_FINDINGS, returncode=1)
            raw = analyzer.run()

        assert raw

    def test_run_returns_only_stdout_not_stderr(self, tmp_path):
        """Bandit emits JSON to stdout and logging text to stderr.
        Concatenating both breaks json.loads — run() must return only stdout."""
        analyzer = _make_analyzer(tmp_path)

        proc = MagicMock()
        proc.stdout = BANDIT_JSON_WITH_FINDINGS
        proc.stderr = (
            "[main]  INFO    profile include tests: None\n[main]  INFO    running on 10 files"
        )
        proc.returncode = 1

        with patch("subprocess.run", return_value=proc):
            raw = analyzer.run()

        # Must be parseable JSON — stderr noise must not be included
        data = json.loads(raw)
        assert "results" in data

    def test_run_surfaces_stderr_when_stdout_empty_on_error(self, tmp_path):
        """If bandit exits unexpectedly with no stdout, return stderr so
        normalize() can produce a FAILED result instead of silently succeeding."""
        analyzer = _make_analyzer(tmp_path)

        proc = MagicMock()
        proc.stdout = ""
        proc.stderr = "bandit: error: something went wrong"
        proc.returncode = 2

        with patch("subprocess.run", return_value=proc):
            raw = analyzer.run()

        assert "something went wrong" in raw


# ---------------------------------------------------------------------------
# Tests: normalize()
# ---------------------------------------------------------------------------


class TestBanditAnalyzerNormalize:
    def test_execution_status_success_on_valid_json(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(BANDIT_JSON_WITH_FINDINGS)
        assert result.execution_status == ExecutionStatus.SUCCESS

    def test_findings_count_correct(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(BANDIT_JSON_WITH_FINDINGS)
        assert result.metrics.issue_count == 2

    def test_severity_high_count(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(BANDIT_JSON_WITH_FINDINGS)
        assert result.metrics.extra["severity"]["high"] == 1

    def test_severity_medium_count(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(BANDIT_JSON_WITH_FINDINGS)
        assert result.metrics.extra["severity"]["medium"] == 1

    def test_severity_low_count(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(BANDIT_JSON_WITH_FINDINGS)
        assert result.metrics.extra["severity"]["low"] == 0

    def test_details_parsed_correctly(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(BANDIT_JSON_WITH_FINDINGS)
        assert len(result.details) == 2
        first: BanditFinding = result.details[0]
        assert first.filename == "src/foo.py"
        assert first.line_number == 10
        assert first.severity == "HIGH"
        assert first.confidence == "HIGH"
        assert first.test_id == "B105"
        assert first.test_name == "hardcoded_password_string"

    def test_analyzer_and_language_set(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(BANDIT_JSON_WITH_FINDINGS)
        assert result.analyzer == "bandit"
        assert result.language == "python"

    def test_no_findings_zero_counts(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(BANDIT_JSON_NO_FINDINGS)
        assert result.metrics.issue_count == 0
        assert result.metrics.extra["severity"]["high"] == 0
        assert result.metrics.extra["severity"]["medium"] == 0
        assert result.metrics.extra["severity"]["low"] == 0
        assert result.details == []

    def test_no_findings_execution_status_success(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(BANDIT_JSON_NO_FINDINGS)
        assert result.execution_status == ExecutionStatus.SUCCESS

    def test_invalid_json_returns_failed(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize("not valid json {{ garbage")
        assert result.execution_status == ExecutionStatus.FAILED

    def test_error_sentinel_returns_error_status(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize("[ERROR] Command not found: bandit")
        assert result.execution_status == ExecutionStatus.ERROR

    def test_timeout_sentinel_returns_error_status(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize("[TIMEOUT] Command timed out after 120s")
        assert result.execution_status == ExecutionStatus.ERROR

    def test_empty_json_object_handled_gracefully(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize("{}")
        assert result.execution_status == ExecutionStatus.SUCCESS
        assert result.metrics.issue_count == 0
        assert result.details == []

    def test_total_equals_issue_count(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(BANDIT_JSON_WITH_FINDINGS)
        assert result.metrics.total == result.metrics.issue_count


# ---------------------------------------------------------------------------
# Tests: write_artifacts()
# ---------------------------------------------------------------------------


class TestBanditAnalyzerWriteArtifacts:
    def _get_result_and_analyzer(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(BANDIT_JSON_WITH_FINDINGS)
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
        assert data["analyzer"] == "bandit"
        assert "metrics" in data
        assert "details" in data

    def test_summary_json_is_valid(self, tmp_path):
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        data = json.loads(result.artifacts["summary_json"].read_text())
        assert data["analyzer"] == "bandit"
        assert "issue_count" in data
        assert "severity" in data

    def test_summary_md_contains_severity_rows(self, tmp_path):
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        md = result.artifacts["summary_md"].read_text()
        assert "Security Analysis Summary" in md
        assert "High severity" in md
        assert "Medium severity" in md
        assert "Low severity" in md

    def test_summary_md_shows_score(self, tmp_path):
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        md = result.artifacts["summary_md"].read_text()
        # HIGH=1, MED=1 → score=40 → displayed as "40%"
        assert "40%" in md

    def test_directories_created_automatically(self, tmp_path):
        analyzer, result = self._get_result_and_analyzer(tmp_path)
        analyzer.write_artifacts(result)
        assert (analyzer.output_dir / "raw").is_dir()
        assert (analyzer.output_dir / "normalized").is_dir()
        assert (analyzer.output_dir / "summary").is_dir()


# ---------------------------------------------------------------------------
# Tests: full analyze() pipeline
# ---------------------------------------------------------------------------


class TestBanditAnalyzerFullPipeline:
    def test_analyze_returns_analyzer_result(self, tmp_path):
        from sebco_qa_engine.core.models import AnalyzerResult

        analyzer = _make_analyzer(tmp_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc(stdout=BANDIT_JSON_WITH_FINDINGS, returncode=1)
            result = analyzer.analyze()

        assert isinstance(result, AnalyzerResult)

    def test_analyze_writes_all_artifacts(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc(stdout=BANDIT_JSON_NO_FINDINGS, returncode=0)
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


# ---------------------------------------------------------------------------
# Tests: severity-weighted score
# ---------------------------------------------------------------------------


class TestBanditAnalyzerScore:
    def test_score_uses_severity_weights(self, tmp_path):
        # HIGH=1, MED=1, LOW=0 → 100 - (1×50 + 1×10 + 0×1) = 40
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(BANDIT_JSON_WITH_FINDINGS)
        assert result.metrics.score == pytest.approx(_EXPECTED_SCORE_WITH_FINDINGS)

    def test_score_is_100_when_no_findings(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(BANDIT_JSON_NO_FINDINGS)
        assert result.metrics.score == pytest.approx(100.0)

    def test_score_only_low_findings(self, tmp_path):
        # 15 LOW findings → 100 - (0×50 + 0×10 + 15×1) = 85
        data = json.dumps(
            {
                "errors": [],
                "metrics": {
                    "_totals": {
                        "SEVERITY.HIGH": 0,
                        "SEVERITY.MEDIUM": 0,
                        "SEVERITY.LOW": 15,
                        "loc": 200,
                    }
                },
                "results": [],
            }
        )
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(data)
        assert result.metrics.score == pytest.approx(85.0)

    def test_score_clamped_to_zero_on_severe_findings(self, tmp_path):
        # 3 HIGH findings → 100 - 150 = clamped to 0
        data = json.dumps(
            {
                "errors": [],
                "metrics": {
                    "_totals": {
                        "SEVERITY.HIGH": 3,
                        "SEVERITY.MEDIUM": 0,
                        "SEVERITY.LOW": 0,
                        "loc": 500,
                    }
                },
                "results": [],
            }
        )
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(data)
        assert result.metrics.score == pytest.approx(0.0)

    def test_custom_weights_applied(self, tmp_path):
        cfg = BanditConfig(high_weight=10, medium_weight=5, low_weight=0)
        analyzer = BanditAnalyzer(output_dir=tmp_path / "qa-report" / "bandit", config=cfg)
        # HIGH=1, MED=2 → 100 - (1×10 + 2×5) = 80
        data = json.dumps(
            {
                "errors": [],
                "metrics": {
                    "_totals": {
                        "SEVERITY.HIGH": 1,
                        "SEVERITY.MEDIUM": 2,
                        "SEVERITY.LOW": 0,
                        "loc": 100,
                    }
                },
                "results": [],
            }
        )
        result = analyzer.normalize(data)
        assert result.metrics.score == pytest.approx(80.0)

    def test_weights_stored_in_extra(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(BANDIT_JSON_WITH_FINDINGS)
        weights = result.metrics.extra["weights"]
        assert weights["high"] == 50
        assert weights["medium"] == 10
        assert weights["low"] == 1

    def test_score_percent_in_extra_matches_score(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(BANDIT_JSON_WITH_FINDINGS)
        assert result.metrics.extra["score_percent"] == pytest.approx(result.metrics.score)

    def test_ok_count_is_loc_when_present(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(BANDIT_JSON_WITH_FINDINGS)
        assert result.metrics.ok_count == 100  # loc=100 in fixture

    def test_ok_count_from_loc_no_findings(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(BANDIT_JSON_NO_FINDINGS)
        assert result.metrics.ok_count == 50  # loc=50 in fixture


# ---------------------------------------------------------------------------
# Tests: error_message populated on ERROR status
# ---------------------------------------------------------------------------


class TestBanditAnalyzerErrorMessage:
    def test_error_sentinel_populates_error_message(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        raw = "[ERROR] Command not found: bandit"
        result = analyzer.normalize(raw)
        assert result.error_message == raw

    def test_timeout_sentinel_populates_error_message(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        raw = "[TIMEOUT] Command timed out after 120s: bandit -f json ."
        result = analyzer.normalize(raw)
        assert result.error_message == raw

    def test_error_message_empty_on_success(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(BANDIT_JSON_WITH_FINDINGS)
        assert result.error_message == ""


# ---------------------------------------------------------------------------
# Tests: summary JSON / normalized JSON have score fields
# ---------------------------------------------------------------------------


class TestBanditAnalyzerSummaryJson:
    def _get_summary_data(self, tmp_path) -> dict:
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(BANDIT_JSON_WITH_FINDINGS)
        analyzer.write_artifacts(result)
        return json.loads(result.artifacts["summary_json"].read_text())

    def test_summary_json_has_score(self, tmp_path):
        data = self._get_summary_data(tmp_path)
        assert "score" in data
        assert data["score"] == pytest.approx(_EXPECTED_SCORE_WITH_FINDINGS)

    def test_summary_json_has_score_percent(self, tmp_path):
        data = self._get_summary_data(tmp_path)
        assert "score_percent" in data
        assert data["score_percent"] == pytest.approx(_EXPECTED_SCORE_WITH_FINDINGS)

    def test_summary_json_no_max_issue_budget(self, tmp_path):
        # max_issue_budget was removed — must not appear in serialized output
        data = self._get_summary_data(tmp_path)
        assert "max_issue_budget" not in data

    def test_normalized_json_has_score(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(BANDIT_JSON_WITH_FINDINGS)
        analyzer.write_artifacts(result)
        data = json.loads(result.artifacts["normalized"].read_text())
        assert data["metrics"]["score"] == pytest.approx(_EXPECTED_SCORE_WITH_FINDINGS)

    def test_normalized_json_has_weights(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        result = analyzer.normalize(BANDIT_JSON_WITH_FINDINGS)
        analyzer.write_artifacts(result)
        data = json.loads(result.artifacts["normalized"].read_text())
        assert data["metrics"]["weights"] == {"high": 50, "medium": 10, "low": 1}
