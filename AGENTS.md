# Sebco QA Engine — Agent Rules

## Principles
- Keep architecture modular and layered
- Analyzers must follow BaseAnalyzer contract
- Do not mix aggregation logic with reporting
- Avoid tool-specific logic in core

## Python
- Use type hints
- Prefer dataclasses for models
- Keep analyzers isolated and testable

## Testing
- Do not execute real tools in unit tests
- Mock subprocess calls
- Keep tests deterministic

## CI / Workflow
- Keep logic in Python, not YAML
- Ensure artifacts are always generated