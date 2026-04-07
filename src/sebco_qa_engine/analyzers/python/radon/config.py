"""Configuration dataclass for RadonAnalyzer.

Keeping config separate from the analyzer itself makes it easy to
construct, serialize and pass around without importing the full analyzer.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RadonConfig:
    """Runtime configuration for the radon maintainability analyzer.

    Parameters
    ----------
    paths:
        Source paths to analyze.  Passed directly to ``radon mi`` as
        positional arguments.  Defaults to the current directory (``["."]``).
    extra_args:
        Additional arguments forwarded verbatim to ``radon mi``
        (e.g. ``["--min", "B"]``).
    timeout:
        Maximum seconds to wait for the ``radon`` subprocess.
        ``None`` means no timeout.

    Examples
    --------
    Default (radon analyzes current directory):

        >>> cfg = RadonConfig()

    Analyze a specific path:

        >>> cfg = RadonConfig(paths=["src/"])
    """

    paths: list[str] = field(default_factory=lambda: ["."])
    extra_args: list[str] = field(default_factory=list)
    timeout: int | None = 120
