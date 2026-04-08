# Sebco QA Engine

Language-agnostic, reusable quality validation engine designed to be invoked from external repositories via GitHub Actions. The core is decoupled from any specific language or tool — analyzers are pluggable strategy components that conform to a common contract, making it straightforward to add new languages without touching the orchestration or aggregation layers.

> Part of the sebco-labs / PlatformUnityCI ecosystem.

---

## What it does

The QA engine runs a suite of quality analyzers against a target repository, applies configurable quality gates, and produces:

- **Normalized JSON artifacts** per analyzer
- **Markdown summaries** per analyzer
- **An aggregated report** (`qa-report.json`) with scores and gate verdicts
- **A PR comment** with the full summary (upserted on every push)
- **GitHub Step Summary** in the Actions run

---

## Architecture

```
src/sebco_qa_engine/
├── core/
│   ├── base_analyzer.py        ← ABC contract (run / normalize / write_artifacts)
│   └── models.py               ← AnalyzerResult, RunMetrics, RunnerResult
├── analyzers/
│   ├── python/                 ← ✅ Implemented
│   │   ├── mutmut/             ← Mutation testing
│   │   ├── flake8/             ← Linting (PEP 8)
│   │   ├── coverage/           ← Line/branch coverage
│   │   ├── bandit/             ← Security scanning
│   │   └── radon/              ← Complexity / maintainability index
│   ├── java/                   ← 🔲 Planned
│   ├── go/                     ← 🔲 Planned
│   └── javascript/             ← 🔲 Planned
│       ├── react/              ← Unit / component testing
│       ├── cypress/            ← E2E testing
│       └── playwright/         ← E2E testing
├── aggregation/
│   ├── aggregator.py           ← Consolidates RunnerResult → AggregatedReport
│   ├── policies.py             ← ScoreGatePolicy, IssueCountPolicy, SeverityPolicy, CompositePolicy
│   ├── defaults.py             ← DEFAULT_POLICIES (one place for all thresholds)
│   └── models.py               ← AggregatedReport, AnalyzerSnapshot, RunSummary
├── orchestration/
│   └── runner.py               ← Runner (executes analyzers in sequence)
└── utils/
    └── text.py                 ← strip_ansi and other pure utilities
```

Artifact output per analyzer:

```
qa-report/
├── flake8/
│   ├── raw/flake8-raw.txt
│   ├── normalized/flake8.json
│   ├── summary/flake8-summary.json
│   └── summary/flake8-summary.md
├── coverage/
│   ├── raw/coverage-raw.txt
│   ├── normalized/coverage.json
│   ├── summary/coverage-summary.json
│   └── summary/coverage-summary.md
├── bandit/
│   ├── raw/bandit-raw.json
│   ├── normalized/bandit.json
│   ├── summary/bandit-summary.json
│   └── summary/bandit-summary.md
├── radon/
│   ├── raw/radon-raw.json
│   ├── normalized/radon.json
│   ├── summary/radon-summary.json
│   └── summary/radon-summary.md
├── mutmut/
│   ├── raw/mutmut-raw.txt
│   ├── normalized/mutmut.json
│   ├── summary/mutmut-summary.json
│   └── summary/mutmut-summary.md
├── qa-report.json              ← Aggregated report with all scores and gate verdicts
└── qa-summary.md               ← Human-readable Markdown (also posted as PR comment)
```

---

## Analyzers

### Python ✅

| Analyzer | Tool | Signal | Gate type |
|---|---|---|---|
| `mutmut` | [mutmut](https://mutmut.readthedocs.io/) | Mutation score (%) | `ScoreGatePolicy` |
| `flake8` | [flake8](https://flake8.pycqa.org/) | Violation count | `IssueCountPolicy` |
| `coverage` | [coverage.py](https://coverage.readthedocs.io/) | Line/branch coverage (%) | `ScoreGatePolicy` |
| `bandit` | [bandit](https://bandit.readthedocs.io/) | Severity breakdown (HIGH/MEDIUM/LOW) | `SeverityPolicy` |
| `radon` | [radon](https://radon.readthedocs.io/) | Maintainability index (%) | `ScoreGatePolicy` |

### Java 🔲 Planned

<!-- Add Java analyzers here (e.g. PITest for mutation, Checkstyle for linting, JaCoCo for coverage, SpotBugs for security) -->

### Go 🔲 Planned

<!-- Add Go analyzers here (e.g. go test -cover for coverage, staticcheck/golangci-lint for linting, govulncheck for security) -->

### JavaScript 🔲 Planned

<!-- Add JavaScript/TypeScript analyzers here -->

#### React

<!-- Add React-specific analyzers here (e.g. jest/vitest for unit tests, react-testing-library coverage, eslint-plugin-react for linting) -->

#### Cypress

<!-- Add Cypress E2E test result analyzer here -->

#### Playwright

<!-- Add Playwright E2E test result analyzer here -->

---

### Default quality gate thresholds (Python)

| Analyzer | WARN | FAIL | Approach |
|---|---|---|---|
| `mutmut` | score < 80% | score < 60% | Score = killed / total × 100. Surviving mutants are test gaps. |
| `flake8` | — | issue_count > 0 | Zero-tolerance: any PEP 8 / style violation fails the gate. Score is relative to a configurable `max_issue_budget`. |
| `coverage` | score < 80% | score < 70% | Score = line coverage % reported by `coverage report`. |
| `bandit` | — | any HIGH finding or medium > 5 | Severity-weighted score: HIGH × 50 + MEDIUM × 10 + LOW × 1 penalty subtracted from 100. Gate is hard on HIGH, tolerant on LOW. |
| `radon` | score < 70% | score < 50% | Score = mean Maintainability Index across all modules (0–100). Files ranked C–F count as `issue_count`. |

---

## Setup

### Requirements

- Python ≥ 3.11
- The analyzer tools installed in the **target repo** (not the engine itself)

### Install the engine (development)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Dev dependencies

The `[dev]` extra installs:

| Tool | Purpose |
|---|---|
| `pytest` | Test runner |
| `pytest-cov` | Coverage reporting for the engine's own tests |
| `mutmut` | Mutation testing of the engine itself |
| `ruff` | Planned — see Roadmap Phase 3 |

### Run the test suite

```bash
pytest
```

With coverage:

```bash
pytest --cov=sebco_qa_engine --cov-report=term-missing
```

---

## Using from another repository

### Via `workflow_call` (recommended)

In your repository, create `.github/workflows/qa.yml`:

```yaml
name: QA Engine

on:
  pull_request:
    branches: [main]

jobs:
  qa:
    uses: PlatformUnityCI/sebco-qa-engine/.github/workflows/python-qa.yml@main
    with:
      python-version: "3.12"
      analyzers: "flake8,coverage,bandit,radon,mutmut"
      output-dir: qa-report
    secrets:
      token: ${{ secrets.GITHUB_TOKEN }}
```

#### Available inputs

| Input | Default | Description |
|---|---|---|
| `python-version` | `"3.12"` | Python version to use |
| `analyzers` | `"flake8,coverage,bandit,radon, mutmut"` | Comma-separated list of analyzers to run. Valid values: `flake8`, `coverage`, `bandit`, `radon`, `mutmut` |
| `output-dir` | `"qa-report"` | Directory where QA artifacts are written |
| `engine-ref` | `"main"` | Branch/tag of this engine to install |
| `install-command` | `"pip install -e .[dev] --quiet"` | Command to install consumer repo dependencies |

#### Required permissions in the calling repository

```yaml
permissions:
  contents: read
  pull-requests: write
```

### What the workflow does

1. Checks out the consumer repo and sets up Python
2. Installs consumer dependencies + this engine from GitHub
3. Runs the requested analyzers and writes artifacts to `output-dir`
4. Aggregates results into `qa-report.json` and `qa-summary.md`
5. Writes the summary to the GitHub Step Summary
6. Upserts a PR comment with the full report (on pull_request events)
7. Uploads all artifacts to the Actions run
8. Fails the job if any quality gate returned `FAIL`

---

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

## Roadmap

| Phase | Status | Content |
|---|---|---|
| 1 | ✅ Done | Base structure, contracts, mutmut analyzer |
| 2 | ✅ Done | flake8, coverage, bandit, radon + aggregation layer + PR comment |
| 3 | Planned | Threshold overrides via config file, multi-language support (Go, Java, JavaScript), ruff integration for engine linting, public datasets |

---

## License

MIT — see [LICENSE](LICENSE).
