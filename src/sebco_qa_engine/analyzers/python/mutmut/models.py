"""Mutmut-specific data models.

These types are internal to the mutmut analyzer and are NOT part of the
engine's common contract.  Consumers outside this analyzer should interact
only with ``AnalyzerResult`` and ``RunMetrics`` from ``sebco_qa_engine.core``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MutantDetail:
    """Detail record for a single surviving mutant.

    Attributes
    ----------
    mutant_id:
        The identifier assigned by mutmut (numeric string or named form
        like ``src/foo.py__mutmut_3``).
    diff:
        Git diff of the mutation, if collected.  Empty string if not available.
    show_output:
        Full output of ``mutmut show <id>`` for this mutant.
    """

    mutant_id: str
    diff: str = ""
    show_output: str = ""
