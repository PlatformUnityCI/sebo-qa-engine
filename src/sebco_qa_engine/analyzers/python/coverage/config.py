"""Configuration dataclass for CoverageAnalyzer.

Keeping config separate from the analyzer itself makes it easy to
construct, serialize and pass around without importing the full analyzer.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CoverageConfig:
    """Runtime configuration for the coverage analyzer.

    Parameters
    ----------
    report_format:
        Report format to use.  ``"report"`` uses the ``coverage report``
        command which produces human-readable text output.
    extra_args:
        Additional arguments forwarded verbatim to ``coverage report``
        (e.g. ``["--include=src/*"]``).
    timeout:
        Maximum seconds to wait for the ``coverage`` subprocess.
        ``None`` means no timeout.

    Examples
    --------
    Default:

        >>> cfg = CoverageConfig()

    With source filter:

        >>> cfg = CoverageConfig(extra_args=["--include=src/*"])
    """

    report_format: str = "report"  # "report" uses coverage report command
    extra_args: list[str] = field(default_factory=list)
    timeout: int | None = 120
