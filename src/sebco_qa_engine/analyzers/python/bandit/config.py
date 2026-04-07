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

    Examples
    --------
    Default (bandit scans current directory recursively):

        >>> cfg = BanditConfig()

    Scan a specific path without recursion:

        >>> cfg = BanditConfig(paths=["src/"], recursive=False)
    """

    paths: list[str] = field(default_factory=lambda: ["."])
    recursive: bool = True
    extra_args: list[str] = field(default_factory=list)
    timeout: int | None = 120
