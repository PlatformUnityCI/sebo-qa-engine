"""QA Engine runner — orchestrates one or more analyzers.

The runner is intentionally thin.  It:
  1. Accepts a list of configured analyzers and an optional run_id.
  2. Calls ``analyze()`` on each one sequentially.
  3. Returns a ``RunnerResult`` for the aggregation layer to consume.

``RunnerResult`` lives in ``core.models`` — not here — so the aggregation
and reporting layers can import it without depending on this module.
"""

from __future__ import annotations

import logging
import uuid

from sebco_qa_engine.core.base_analyzer import BaseAnalyzer
from sebco_qa_engine.core.models import RunnerResult

logger = logging.getLogger(__name__)


class Runner:
    """Orchestrates execution of a collection of analyzers.

    Parameters
    ----------
    analyzers:
        List of configured ``BaseAnalyzer`` instances to run.
    run_id:
        Unique identifier for this run.  If ``None`` (default), a UUID4 is
        generated automatically.  Pass an explicit value to correlate with
        an external system (e.g. ``$GITHUB_RUN_ID`` in CI).

    Examples
    --------
    Auto-generated run_id:

        >>> from pathlib import Path
        >>> from sebco_qa_engine.orchestration import Runner
        >>> from sebco_qa_engine.analyzers.python.mutmut import MutmutAnalyzer
        >>> runner = Runner(analyzers=[MutmutAnalyzer(output_dir=Path("qa-report/mutmut"))])
        >>> result = runner.run()
        >>> print(result.run_id)   # e.g. "a3f1c2d4-8e7b-..."

    Injected run_id (CI context):

        >>> runner = Runner(analyzers=[...], run_id="12345678")
        >>> result = runner.run()
        >>> print(result.run_id)   # "12345678"
    """

    def __init__(
        self,
        analyzers: list[BaseAnalyzer],
        run_id: str | None = None,
    ) -> None:
        self.analyzers = analyzers
        self.run_id = run_id or str(uuid.uuid4())

    def run(self) -> RunnerResult:
        """Execute all registered analyzers and return the run result."""
        run_result = RunnerResult(run_id=self.run_id)

        for analyzer in self.analyzers:
            logger.info("Running analyzer: %s (%s)", analyzer.name, analyzer.language)
            result = analyzer.analyze()
            run_result.results.append(result)
            logger.info(
                "Analyzer %s finished — execution_status: %s | score: %s",
                analyzer.name,
                result.execution_status.value,
                result.metrics.score,
            )

        return run_result
