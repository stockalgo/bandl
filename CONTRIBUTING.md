# Contributing to Bandl

Thank you for helping improve Bandl. This document describes how to set up your environment, run checks, and open changes.

## Development setup

```bash
git clone https://github.com/stockalgo/bandl.git
cd bandl
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Running tests

Unit tests (default; no network):

```bash
pytest tests/v2/
```

Integration tests (public market APIs; optional):

```bash
pytest tests/v2/ -m integration --override-ini="addopts="
```

## Linting and formatting

[Ruff](https://docs.astral.sh/ruff/) enforces style on `lib/bandl/v2` and `tests/v2`:

```bash
ruff check lib/bandl/v2 tests/v2
ruff format lib/bandl/v2 tests/v2
```

CI runs `ruff check` and `ruff format --check` on pull requests.

## Packaging sanity check

```bash
pip install build twine
python -m build
twine check dist/*
```

## Pull requests

- Open PRs against the default branch (`master` unless the maintainers rename it).
- Keep commits focused and describe *why* the change matters in the PR body when it is not obvious.
- Ensure CI is green (tests, Ruff, wheel build).
- Avoid committing secrets (API keys, `.env`). Use `examples/.env.example` for documented variables only.

## Code of conduct

Contributors are expected to follow the [Contributor Covenant](CODE_OF_CONDUCT.md) for this repository.

## Security

See [SECURITY.md](SECURITY.md) for reporting vulnerabilities.
