"""Configuration dataclass for BanditAnalyzer.

Keeping config separate from the analyzer itself makes it easy to
construct, serialize and pass around without importing the full analyzer.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BanditConfig:
    """Runtime configuration for the bandit security analyzer.

    Parameters
    ----------
    paths:
        Source paths to scan.  Passed directly to ``bandit`` as positional
        arguments.  Defaults to the current directory (``["."]``).
    recursive:
        If ``True``, pass ``--recursive`` to bandit so it scans
        subdirectories.  Defaults to ``True``.
    extra_args:
        Additional arguments forwarded verbatim to ``bandit``
        (e.g. ``["--skip", "B101"]``).
    timeout:
        Maximum seconds to wait for the ``bandit`` subprocess.
        ``None`` means no timeout.
    high_weight:
        Penalty per HIGH-severity finding applied to the score formula.
        ``score = max(0, 100 - (high*high_weight + medium*medium_weight + low*low_weight))``.
        Defaults to ``50`` — one HIGH issue drops the score by half.
    medium_weight:
        Penalty per MEDIUM-severity finding.  Defaults to ``10``.
    low_weight:
        Penalty per LOW-severity finding.  Defaults to ``1``.

    Examples
    --------
    Default:

        >>> cfg = BanditConfig()

    Scan a specific path without recursion:

        >>> cfg = BanditConfig(paths=["src/"], recursive=False)

    Stricter medium penalty:

        >>> cfg = BanditConfig(medium_weight=20)
    """

    paths: list[str] = field(default_factory=lambda: ["."])
    recursive: bool = True
    extra_args: list[str] = field(default_factory=list)
    timeout: int | None = 120
    # Severity weights for score = max(0, 100 - (H*high + M*medium + L*low))
    high_weight: int = 50
    medium_weight: int = 10
    low_weight: int = 1
