"""Base contract for all QA engine analyzers.

Every analyzer MUST subclass ``BaseAnalyzer`` and implement the three
abstract methods that form the strategy contract:

    run()             → execute the tool via subprocess and capture raw output
    normalize()       → transform raw output into an AnalyzerResult
    write_artifacts() → persist normalized data + summary files to disk

The template method ``analyze()`` orchestrates those three steps in order
and is the single public entry point callers use.

Protected path helpers
----------------------
Subclasses call ``self._artifact_dirs()`` to get the canonical subdirectory
paths (raw / normalized / summary) already created, and
``self._artifact_path(subdir, filename)`` to build individual file paths.
This avoids duplicating directory-creation logic across every analyzer.

Example
-------
    result = MutmutAnalyzer(output_dir=Path("qa-report/mutmut")).analyze()
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path

from sebco_qa_engine.core.models import AnalyzerResult, ExecutionStatus

logger = logging.getLogger(__name__)

# Canonical subdirectory names — consistent across all analyzers.
_SUBDIR_RAW = "raw"
_SUBDIR_NORMALIZED = "normalized"
_SUBDIR_SUMMARY = "summary"


class BaseAnalyzer(ABC):
    """Abstract base for all analyzers.

    Parameters
    ----------
    output_dir:
        Root directory where *this analyzer's* artifacts will be written.
        Canonical subdirectories (``raw/``, ``normalized/``, ``summary/``)
        are created automatically when ``_artifact_dirs()`` is called.
    """

    #: Must be overridden by every subclass — used in logging and artifact naming.
    name: str = ""
    language: str = ""

    def __init__(self, output_dir: Path) -> None:
        if not self.name:
            raise NotImplementedError(
                f"{type(self).__name__} must define a `name` class attribute."
            )
        if not self.language:
            raise NotImplementedError(
                f"{type(self).__name__} must define a `language` class attribute."
            )
        self.output_dir = output_dir

    # ------------------------------------------------------------------
    # Template method — public API
    # ------------------------------------------------------------------

    def analyze(self) -> AnalyzerResult:
        """Run the full analysis pipeline for this analyzer.

        Orchestrates: run → normalize → write_artifacts.

        Returns the normalized ``AnalyzerResult`` with all artifact paths
        populated.  On unhandled exceptions the result is returned with
        ``status = ERROR`` so the orchestrator can continue with other
        analyzers.
        """
        logger.info("[%s] Starting analysis", self.name)

        try:
            raw_output = self.run()
            logger.debug("[%s] Raw output captured (%d chars)", self.name, len(raw_output))

            result = self.normalize(raw_output)
            logger.debug("[%s] Normalization complete — status: %s", self.name, result.execution_status)

            self.write_artifacts(result)
            logger.info("[%s] Artifacts written to %s", self.name, self.output_dir)

        except Exception as exc:  # noqa: BLE001
            logger.exception("[%s] Unexpected error during analysis", self.name)
            result = AnalyzerResult(
                analyzer=self.name,
                language=self.language,
                execution_status=ExecutionStatus.ERROR,
                error_message=str(exc),
            )

        return result

    # ------------------------------------------------------------------
    # Abstract interface — every subclass implements these
    # ------------------------------------------------------------------

    @abstractmethod
    def run(self) -> str:
        """Execute the underlying tool and return its full raw output.

        Implementations MUST use ``subprocess`` to invoke the tool.
        They MUST NOT raise on non-zero exit codes — capture and return
        the output so ``normalize()`` can make sense of it.

        Returns
        -------
        str
            Combined stdout + stderr from the tool execution.
        """

    @abstractmethod
    def normalize(self, raw_output: str) -> AnalyzerResult:
        """Parse ``raw_output`` and return a populated ``AnalyzerResult``.

        The returned result MUST have ``artifacts`` empty — artifact paths
        are assigned by ``write_artifacts()``.

        Parameters
        ----------
        raw_output:
            The string returned by ``run()``.
        """

    @abstractmethod
    def write_artifacts(self, result: AnalyzerResult) -> None:
        """Persist normalized data and summaries to ``self.output_dir``.

        MUST populate ``result.artifacts`` with the paths of every file
        written, using the canonical keys:
        - ``"raw"``          → raw tool output
        - ``"normalized"``   → normalized JSON
        - ``"summary_json"`` → summary JSON
        - ``"summary_md"``   → summary Markdown

        Use ``self._artifact_dirs()`` to obtain pre-created subdirectories
        and ``self._artifact_path()`` to build individual file paths.

        Parameters
        ----------
        result:
            The ``AnalyzerResult`` produced by ``normalize()``.
            Mutate it in-place to add artifact paths.
        """

    # ------------------------------------------------------------------
    # Protected path helpers — used by concrete write_artifacts() impls
    # ------------------------------------------------------------------

    def _artifact_dirs(self) -> tuple[Path, Path, Path]:
        """Create and return the three canonical artifact subdirectories.

        Returns
        -------
        tuple[Path, Path, Path]
            ``(raw_dir, normalized_dir, summary_dir)`` — all guaranteed to exist.
        """
        raw_dir = self.output_dir / _SUBDIR_RAW
        norm_dir = self.output_dir / _SUBDIR_NORMALIZED
        summary_dir = self.output_dir / _SUBDIR_SUMMARY

        for d in (raw_dir, norm_dir, summary_dir):
            d.mkdir(parents=True, exist_ok=True)

        return raw_dir, norm_dir, summary_dir

    def _artifact_path(self, subdir: str, filename: str) -> Path:
        """Return ``output_dir / subdir / filename`` without creating anything.

        Convenience method for building paths consistently.  Use
        ``_artifact_dirs()`` first to ensure the directories exist.
        """
        return self.output_dir / subdir / filename
