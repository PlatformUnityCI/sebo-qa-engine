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
> [!NOTE]
> For technical details, architecture, and advanced usage, see the documentation in `docs/`.

## Artifact output per analyzer:

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

## Setup

### Requirements

- Python ≥ 3.11
- The consumer repository must provide the analyzer dependencies required by `sebco-qa-engine`
- These dependencies are typically installed through the consumer repository's `requirements.txt`

## Analyzer tools expected by `sebco-qa-engine`
## Python ✅

| Analyzer | Tool | Signal | Gate type |
|---|---|---|---|
| `mutmut` | [mutmut](https://mutmut.readthedocs.io/) | Mutation score (%) | `ScoreGatePolicy` |
| `flake8` | [flake8](https://flake8.pycqa.org/) | Violation count | `IssueCountPolicy` |
| `coverage` | [coverage.py](https://coverage.readthedocs.io/) | Line/branch coverage (%) | `ScoreGatePolicy` |
| `bandit` | [bandit](https://bandit.readthedocs.io/) | Severity breakdown (HIGH/MEDIUM/LOW) | `SeverityPolicy` |
| `radon` | [radon](https://radon.readthedocs.io/) | Maintainability index (%) | `ScoreGatePolicy` |


> [!IMPORTANT]
> The consumer repository must install the analyzer dependencies required by the selected `analyzers` set.
> In most cases, this is done through the consumer repository's `requirements.txt`.

---

## Using from another repository

### Via `workflow_call` (recommended)

In your repository, create example: `.github/workflows/qa.yml`. And add next step:

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

> [!TIP]
> `engine-ref` is optional and defaults to `main`.
> You only need to set it when testing a feature branch of `sebco-qa-engine`.

### Required permissions in the calling repository

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

> [!WARNING]
> Since the consumer repository uses `mutmut`, it must include a root-level `pyproject.toml`.

#### Example

```toml
[tool.mutmut]
paths_to_mutate = [
  "lib_core/time_utils"
]
tests_dir = [
  "tests"
]
runner = "python -m pytest -m regression -q"
do_not_mutate = [
  "__init__.py"
]
```

### 🧠 What this means
| Keys | Description |
|---|---|
|`paths_to_mutate` | defines the source code path that mutmut will mutate |
|`tests_dir` | defines where the test suite lives |
|`runner` | defines how tests should be executed during mutation analysis |
|`do_not_mutate` | excludes files that should never be mutated, such as __init__.py |

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

> [!NOTE]
> Testing a feature branch of `sebco-qa-engine`.
>
> By default, `sebco-qa-engine` installs the engine package from `main`. This is the expected behavior for normal consumer usage.
>
> If you want to test a feature branch, the workflow reference and `engine-ref` must point to the same branch.
>
> If these references do not match, the workflow may run one branch while installing the engine package from another.
>
> Example:
>
> ```yaml
> qa-engine:
>   uses: PlatformUnityCI/sebco-qa-engine/.github/workflows/python-qa.yml@feature/my-branch
>   with:
>     python-version: "3.12"
>     analyzers: "mutmut,flake8,coverage,bandit,radon"
>     output-dir: "qa-report"
>     engine-ref: "feature/my-branch"
>   secrets:
>     token: ${{ secrets.GITHUB_TOKEN }}
> ```
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
