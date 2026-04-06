# Sebco QA Engine

Reusable, multi-language quality validation engine designed to be invoked from external repositories via GitHub Actions.

> Part of the sebco-labs ecosystem.

---

## Overview

The QA engine runs a suite of quality analyzers (mutation testing, linting, coverage, security, complexity) against a target repository and produces:

- **Normalized JSON artifacts** per analyzer
- **Markdown summaries** per analyzer
- **A single PR comment** with sections per analyzer (Phase 2)

Each analyzer follows a common contract (`BaseAnalyzer`) and runs independently.  
The engine is orchestrated via GitHub Actions reusable workflows (`workflow_call`).

---

## Architecture

```
src/sebco_qa_engine/
├── core/
│   ├── base_analyzer.py      ← ABC contract (run / normalize / write_artifacts)
│   └── models.py             ← AnalyzerResult, RunMetrics, MutantDetail
├── analyzers/
│   └── python/
│       └── mutmut/
│           ├── analyzer.py   ← MutmutAnalyzer
│           └── config.py     ← MutmutConfig
├── utils/
│   └── text.py               ← strip_ansi and other pure utilities
└── runner.py                 ← Runner (orchestrates analyzers)
```

Artifact output per analyzer:

```
qa-report/
└── mutmut/
    ├── raw/mutmut-raw.txt
    ├── normalized/mutmut.json
    └── summary/
        ├── mutmut-summary.json
        └── mutmut-summary.md
```

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
  mutation:
    uses: sebco-labs/sebo-qa-engine/.github/workflows/python-mutmut.yml@main
    with:
      output-dir: qa-report
    secrets:
      token: ${{ secrets.GITHUB_TOKEN }}
```

> See `.github/workflows/` in this repository for the full reusable workflow definitions.

### Permissions required in the calling repository

```yaml
permissions:
  contents: read
  pull-requests: write
  checks: write
```

---

## Running an analyzer directly (Python API)

```python
from pathlib import Path
from sebco_qa_engine.analyzers.python.mutmut import MutmutAnalyzer, MutmutConfig
from sebco_qa_engine.runner import Runner

cfg = MutmutConfig(
    cache_dir=Path("/tmp/mutmut-cache"),
    clean_cache=True,           # wipe cache before each run
)

runner = Runner(
    analyzers=[
        MutmutAnalyzer(output_dir=Path("qa-report/mutmut"), config=cfg),
    ]
)

run_result = runner.run()

for result in run_result.results:
    print(f"{result.analyzer}: score={result.metrics.score}%")
    print(f"  artifacts: {list(result.artifacts.keys())}")
```

---

## Interpreting results

### `AnalyzerResult` fields

| Field | Type | Description |
|---|---|---|
| `analyzer` | `str` | Analyzer name (e.g. `"mutmut"`) |
| `language` | `str` | Target language (e.g. `"python"`) |
| `status` | `AnalyzerStatus` | `success`, `failed`, `skipped`, `error` |
| `metrics.score` | `float \| None` | Primary quality score (0–100) |
| `metrics.total` | `int \| None` | Total items evaluated |
| `metrics.passed` | `int \| None` | Items that passed (killed mutants, etc.) |
| `metrics.failed` | `int \| None` | Items that failed (survivors, violations, etc.) |
| `artifacts` | `dict[str, Path]` | Paths to written artifact files |
| `details` | `list` | Per-item detail records (e.g. `MutantDetail`) |

### Artifact keys

| Key | Content |
|---|---|
| `raw` | Full tool stdout+stderr |
| `normalized` | Structured JSON following the common contract |
| `summary_json` | Compact summary JSON |
| `summary_md` | Human-readable Markdown summary |

### Mutation score interpretation

| Score | Meaning |
|---|---|
| 90–100% | Excellent — test suite catches nearly all mutations |
| 70–89%  | Good — some gaps worth investigating |
| < 70%   | Needs attention — significant test gaps |

---

## Adding a new analyzer

1. Create `src/sebco_qa_engine/analyzers/<language>/<tool>/`
2. Add `config.py` (dataclass with tool-specific options)
3. Add `analyzer.py` — subclass `BaseAnalyzer`, implement `run()`, `normalize()`, `write_artifacts()`
4. Set `name` and `language` class attributes
5. Add tests under `tests/unit/analyzers/<language>/<tool>/`

The engine automatically picks it up when you add it to the `Runner`'s analyzer list.

---

## Roadmap

| Phase | Status | Content |
|---|---|---|
| 1 | ✅ In progress | Base structure, contracts, mutmut analyzer |
| 2 | Planned | flake8, coverage, bandit, radon + aggregation + PR comment |
| 3 | Planned | Public datasets, multi-language support |

---

## License

MIT — see [LICENSE](LICENSE).
