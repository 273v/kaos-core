# Repository Agent Guidance

## Scope

These instructions apply to this repository. They are the canonical
cross-tool guidance for coding agents working on `kaos-core`; other
agent-specific files should defer here instead of duplicating policy.

For contributor workflow and detailed standards, read:

- [CONTRIBUTING.md](CONTRIBUTING.md)
- [Python design and architecture](docs/standards/python-design-and-architecture.md)
- [Code quality standards](docs/standards/code-quality-standards.md)
- [Engineering process](docs/standards/engineering-process.md)
- [Tests, fixtures, and CI](docs/standards/tests-fixtures-ci.md)

## Project Identity

- Distribution package: `kaos-core`.
- Import package: `kaos_core`.
- CLI entry point: `kaos-core`.
- Runtime baseline: Python 3.13+.
- Tooling: `uv`, `ruff`, `ty` (not mypy), and `pytest`.
- This is a pure-Python, dependency-light runtime base. Do not add
  provider clients, LLM clients, document extractors, web frameworks, or
  server packages here.

## Setup

```bash
uv sync --group dev
uvx pre-commit install
```

Use `uv` for environment, test, build, and packaging commands. Avoid
manual dependency edits unless the task explicitly changes packaging.

## Local Checks

Run the relevant smallest check first while iterating. Before a PR, run
the documented quality gate:

```bash
uv run ruff format --check kaos_core tests
uv run ruff check kaos_core tests
uv run ty check kaos_core tests
uv run pytest -m "not live and not network and not slow" --no-cov
```

When packaging, release behavior, or distribution metadata changes, also
run:

```bash
uv build
uvx --from twine twine check --strict dist/*
```

## Architecture Rules

- Keep the public API explicit and stable. `kaos_core.__all__`,
  documented modules, CLI behavior, JSON/schema output, MCP-compatible
  shapes, and environment-variable conventions are public surface.
- Preserve the MCP-native runtime and type model. External boundaries
  should use typed, schema-friendly Pydantic models where appropriate.
- Prefer explicit `KaosRuntime` injection in library code. Use
  `KaosRuntime.default()` only for scripts, examples, and tests where a
  process-level default is intentional.
- Preserve `ModuleSettings` resolution behavior and secret redaction.
  Settings should resolve through explicit overrides, context config,
  `KAOS_<MOD>_*` environment variables, legacy env vars, `.env`, and
  defaults without exposing secrets in logs, CLI output, JSON, or errors.
- Keep artifact handling size-aware. Inline small results, summarize and
  link medium results, and use manifest/resource handles for large
  artifacts.
- Preserve disk-first VFS behavior and session isolation. Do not bypass
  path normalization, size limits, or namespace rules.
- Use structured `kaos.*` logging through
  `kaos_core.logging.get_logger`; avoid ad hoc logging setup at import
  time.
- Keep errors agent-friendly: actionable, bounded, and free of secrets,
  internal paths, stack traces, or raw provider payloads.
- Maintain CLI, environment-variable, schema, and `ToolResult`
  compatibility unless the change intentionally updates public behavior
  and includes docs, tests, and changelog coverage.

## Testing

- New public API or behavior needs tests through the real entry point.
- Bug fixes need regression tests.
- Security-sensitive behavior needs accepted and rejected cases with
  realistic inputs.
- For VFS/session isolation, URL validation, credentials, allowlists,
  size caps, artifact tiering, schema output, and CLI JSON behavior,
  test the contract rather than only internals.
- Do not use live network services or live credentials in normal tests.

## Security

- Never commit secrets, tokens, private keys, credentials, or `.env`
  files.
- Use secret-aware types for credentials and preserve redaction in logs,
  CLI output, JSON output, and exceptions.
- Bound untrusted input by size, path, URL, recursion, time, or other
  appropriate limits.
- Do not add GPL, AGPL, unknown-license, non-commercial, or
  no-derivatives dependencies.
- Report suspected vulnerabilities through [SECURITY.md](SECURITY.md),
  not public issues.

## Commits, PRs, And Releases

- Keep one logical change per PR.
- Use conventional commit style and sign commits with `git commit -s`.
- Before committing, inspect `git status` and stage only intended files.
  Preserve unrelated user changes.
- Public API, CLI behavior, schema output, package metadata, security
  behavior, and deprecations require a `CHANGELOG.md` entry.
- Do not edit release metadata, generated files, `uv.lock`, or
  packaging files unless the task explicitly requires it.
- Do not force-push unless a maintainer explicitly requests it.
