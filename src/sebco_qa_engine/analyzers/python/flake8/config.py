"""Configuration dataclass for Flake8Analyzer.

Keeping config separate from the analyzer itself makes it easy to
construct, serialize and pass around without importing the full analyzer.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Flake8Config:
    """Runtime configuration for the flake8 analyzer.

    Parameters
    ----------
    paths:
        Source paths to lint.  Passed directly to ``flake8`` as positional
        arguments.  Defaults to the current directory (``["."]``).
    max_line_length:
        Override flake8's default max line length.  ``None`` means use
        flake8's own default (79).
    extra_args:
        Additional arguments forwarded verbatim to ``flake8``
        (e.g. ``["--extend-ignore", "E501"]``).
    timeout:
        Maximum seconds to wait for the ``flake8`` subprocess.
        ``None`` means no timeout.

    Examples
    --------
    Default:

        >>> cfg = Flake8Config()

    Custom line length:

        >>> cfg = Flake8Config(max_line_length=120, paths=["src/"])
    """

    paths: list[str] = field(default_factory=lambda: ["."])
    max_line_length: int | None = None  # None = use flake8 default
    extra_args: list[str] = field(default_factory=list)
    timeout: int | None = 120
    # Budget used to derive score_percent for reporting/dashboard.
    # score_percent = max(0, round((1 - issue_count / max_issue_budget) * 100, 2))
    # Does NOT affect the quality gate — that still uses max_issues (aggregation layer).
    max_issue_budget: int = 50
