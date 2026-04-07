"""Configuration dataclass for MutmutAnalyzer.

Keeping config separate from the analyzer itself makes it easy to
construct, serialize and pass around without importing the full analyzer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class MutmutConfig:
    """Runtime configuration for the mutmut analyzer.

    Parameters
    ----------
    paths:
        Source paths to mutate.  Passed directly to ``mutmut run`` as
        positional arguments.  Defaults to the current directory (``["."]``),
        which lets mutmut use its own discovery logic.
    cache_dir:
        Directory where mutmut stores its ``.mutmut-cache`` file.
        Defaults to the current working directory (mutmut's own default).
        Set this explicitly to isolate runs or avoid polluting the project root.
    clean_cache:
        If ``True``, delete the mutmut cache file before running.
        Useful in CI to guarantee a fresh run.  Defaults to ``False``.
    extra_args:
        Additional arguments forwarded verbatim to ``mutmut run``
        (e.g. ``["--paths-to-mutate", "src/"]``).
    timeout:
        Maximum seconds to wait for the ``mutmut run`` subprocess.
        ``None`` means no timeout.

    Examples
    --------
    Default (mutmut decides everything):

        >>> cfg = MutmutConfig()

    Explicit cache directory + auto-clean:

        >>> cfg = MutmutConfig(cache_dir=Path("/tmp/mutmut-cache"), clean_cache=True)
    """

    paths: list[str] = field(default_factory=lambda: ["."])
    cache_dir: Path | None = None
    clean_cache: bool = False
    extra_args: list[str] = field(default_factory=list)
    timeout: int | None = 600  # 10 minutes — mutation runs can be slow
