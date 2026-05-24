# Contributing to eventforge

Thanks for considering a contribution. `eventforge` is alpha-stage
software; the public API may shift between minor releases. Issues,
bug reports, and small PRs are all welcome.

## Quick start

```bash
git clone https://github.com/adnanhd/eventforge
cd eventforge
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,logfire]"
pytest tests/ -q
```

If `pytest` is green, you have a working dev install.

## Reporting bugs

Open a GitHub issue with:

1. A minimal repro -- the smallest `Observable` / `RPCServer` /
   `WorkQueue` configuration that shows the problem.
2. What you expected.
3. What you got (error message + traceback).
4. Python version + installed `eventforge` version.

## Proposing changes

Small fixes (typos, docs, one-file refactors): open a PR directly.

Larger changes (new public API, transport changes, security-relevant
defaults): open an issue first. Pre-1.0 we still want a sketch
before code.

### PR checklist

- [ ] `pytest tests/` passes.
- [ ] If you touched the public API surface (`eventforge/__init__.py`
  exports, transport contract, RPC wire format), add or update a
  test.
- [ ] Docstrings on new public classes / functions.
- [ ] Commit subjects use the same shape as the existing log:
  `category: subject` (`feat`, `fix`, `chore`, `refactor`, `style`,
  `docs`, `test`, `bench`). ~72 char cap.
- [ ] No new `# TODO`, `# FIXME`, or `getattr(obj, "name", default)`
  on a declared field. If a field might be absent, fix the
  schema.
- [ ] No unicode em-dash, arrow, ellipsis, or curly quotes in
  shipped code or commit subjects.
- [ ] Update `CHANGELOG.md` under `[Unreleased]` if the change is
  user-visible.
- [ ] **Network defaults stay safe.** Do not change
  `TCPServerTransport`'s default `host` from `"127.0.0.1"` without a
  matching `SECURITY.md` update.

## Code style

Conventional Python. `black .` for formatting, `ruff check
eventforge/ tests/` for lint, `mypy eventforge/` for types. CI runs
all three; targets in the `Makefile`.

## Tests

Tests live in `tests/`. Run the full suite at logical checkpoints;
target specific modules during iteration:

```bash
pytest tests/test_rpc.py -q
pytest tests/ -k transport -q
```

## Releases

Releases are cut by the maintainer:

1. Bump `eventforge/__init__.py::__version__` and `pyproject.toml`.
2. Update `CHANGELOG.md`.
3. Tag the commit (`git tag v0.2.0 && git push --tags`).
4. The `release` workflow builds the wheel + sdist and publishes to
   PyPI via trusted publishing.

## License

By contributing you agree that your contribution will be licensed
under the project's MIT license.
