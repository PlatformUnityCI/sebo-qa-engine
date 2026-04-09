## Running via Python API

```python
from pathlib import Path
from sebco_qa_engine.orchestration.runner import Runner
from sebco_qa_engine.aggregation.aggregator import Aggregator
from sebco_qa_engine.aggregation.defaults import DEFAULT_POLICIES
from sebco_qa_engine.analyzers.python.flake8 import Flake8Analyzer
from sebco_qa_engine.analyzers.python.coverage import CoverageAnalyzer
from sebco_qa_engine.analyzers.python.bandit import BanditAnalyzer

output_dir = Path("qa-report")

runner = Runner(
    analyzers=[
        Flake8Analyzer(output_dir=output_dir / "flake8"),
        CoverageAnalyzer(output_dir=output_dir / "coverage"),
        BanditAnalyzer(output_dir=output_dir / "bandit"),
    ]
)

runner_result = runner.run()

aggregator = Aggregator(policies=DEFAULT_POLICIES, base_dir=output_dir)
report = aggregator.aggregate(runner_result)

for snapshot in report.results:
    print(f"{snapshot.analyzer}: gate={snapshot.quality_gate} score={snapshot.score}")
```

---

## Quality gate policies

The aggregation layer exposes four composable policies:

| Policy | Use when |
|---|---|
| `ScoreGatePolicy(ScoreThresholds(warn_below, fail_below))` | Tool produces a percentage score (mutmut, coverage, radon) |
| `IssueCountPolicy(max_issues, warn_above)` | Tool counts violations (flake8) |
| `SeverityPolicy(max_high, max_medium)` | Tool reports severity tiers (bandit) |
| `CompositePolicy([...policies])` | Combine multiple signals; worst verdict wins |

### Gate verdicts

| Verdict | Meaning |
|---|---|
| `PASS` | All thresholds met |
| `WARN` | Warning threshold breached — CI continues |
| `FAIL` | Fail threshold breached — CI exits non-zero |
| `SKIP` | Signal unavailable or analyzer did not execute |

### Overriding defaults

```python
from sebco_qa_engine.aggregation.policies import ScoreGatePolicy, ScoreThresholds
from sebco_qa_engine.aggregation.defaults import DEFAULT_POLICIES

custom_policies = {
    **DEFAULT_POLICIES,
    "coverage": ScoreGatePolicy(ScoreThresholds(warn_below=90.0, fail_below=80.0)),
}

aggregator = Aggregator(policies=custom_policies, base_dir=output_dir)
```

---

## Adding a new analyzer

1. Create `src/sebco_qa_engine/analyzers/<language>/<tool>/`
2. Add `config.py` — dataclass with tool-specific options
3. Add `analyzer.py` — subclass `BaseAnalyzer`, implement `run()`, `normalize()`, `write_artifacts()`
4. Set `name` and `language` class attributes
5. Add an entry to `aggregation/defaults.py` with sensible thresholds
6. Add tests under `tests/unit/analyzers/<language>/<tool>/`

The engine picks it up automatically when you add it to the `Runner`'s analyzer list.

---

## Interpreting the aggregated report

### `AnalyzerSnapshot` fields

| Field | Type | Description |
|---|---|---|
| `analyzer` | `str` | Analyzer name (`"mutmut"`, `"flake8"`, …) |
| `language` | `str` | Target language (`"python"`) |
| `execution_status` | `str` | `success`, `failed`, `skipped`, `error` |
| `quality_gate` | `str` | `pass`, `warn`, `fail`, `skip` |
| `gate_reason` | `str` | Human-readable explanation of the gate verdict |
| `score` | `float \| None` | Primary quality score (0–100) |
| `total` | `int \| None` | Total items evaluated |
| `ok_count` | `int \| None` | Items that passed |
| `issue_count` | `int \| None` | Items that failed |
| `artifact_paths` | `dict[str, str]` | Relative paths to written artifact files |
| `error_message` | `str \| None` | Set when `execution_status` is `error` |

### `RunSummary` fields

| Field | Description |
|---|---|
| `declared` | Total analyzers registered |
| `executed` | Analyzers that ran (not skipped) |
| `passed` / `warned` / `failed` / `errored` / `skipped` | Count per gate verdict |
| `executed_pct` | `executed / declared * 100` |
| `success_pct` | `passed / executed * 100` |
| `pending_pct` | `(warned + failed + errored) / declared * 100` |

---

## CI / Governance workflows

This repository ships three workflows of its own:

| Workflow | File | Trigger | Purpose |
|---|---|---|---|
| **Python QA Engine** | `python-qa.yml` | `workflow_call` (from consumer repos) | Reusable QA pipeline — runs analyzers, aggregates, comments on PRs |
| **PR Governance** | `pr-governance.yml` | `pull_request_target` → `main` | Enforces PR conventions via `PlatformUnityCI/cross-platform-guard` |
| **Release** | `release.yml` | push → `main` | Semantic versioning and GitHub releases via `PlatformUnityCI/cross-platform-guard` |

Releases follow [Conventional Commits](https://www.conventionalcommits.org/) and are published automatically with semantic-release (configured in `.releaserc.json`).

Dependency updates are managed by **Dependabot** (weekly, for both `pip` and `github-actions`).

---
