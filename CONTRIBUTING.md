# Contributing

Thank you for contributing. Keep changes focused, tested, signed off,
and documented. Participation in this project is governed by the
[project conduct expectations](CODE_OF_CONDUCT.md).

## Setup

```bash
uv sync --group dev
uvx pre-commit install
```

The pre-commit hook runs the same ruff/ty checks as CI. Installing it
shortens the local feedback loop; CI remains the final gate.

`kaos-core` requires Python 3.13 or newer. It is a pure-Python package
with import package `kaos_core` and CLI entry point `kaos-core`.

## Before Opening A PR

Run the local quality gate:

```bash
uv run ruff format --check kaos_core tests
uv run ruff check kaos_core tests
uv run ty check kaos_core tests
uv run pytest -m "not live and not network and not slow" --no-cov
```

When packaging, metadata, README rendering, or release behavior changes,
also run:

```bash
uv build
uvx --from twine twine check --strict dist/*
```

Type checking uses `ty`, not mypy. Inline ignores use
`# ty: ignore[...]`; `# type: ignore[...]` is mypy syntax and is not a
substitute for a `ty` ignore.

## Standards

Read the standards before making non-trivial changes:

- [Python design and architecture](docs/standards/python-design-and-architecture.md)
- [Code quality standards](docs/standards/code-quality-standards.md)
- [Engineering process](docs/standards/engineering-process.md)
- [Tests, fixtures, and CI](docs/standards/tests-fixtures-ci.md)

## Pull Requests

Pull requests should explain:

- what changed
- why it changed
- how it was tested
- whether public API, CLI behavior, package metadata, fixtures, or
  release artifacts changed
- whether `CHANGELOG.md` needs an `[Unreleased]` entry

Bug fixes need regression tests. User-visible behavior changes need docs
and a CHANGELOG entry under `[Unreleased]`.

Before requesting review, confirm:

- [ ] One logical change per PR.
- [ ] Branch rebased on `main`.
- [ ] Tests added or updated when behavior changes.
- [ ] Local quality gate run.
- [ ] Public API, CLI, package metadata, fixtures, and release impact
      considered.
- [ ] DCO sign-off on every commit (`git commit -s`).

## Testing Standards

- New public API needs a test through its real entry point.
- Mocked-only tests are not enough for security-sensitive behavior.
- URL validation, credential handling, allowlists, VFS/session
  isolation, and size-limit changes must test both accepted and rejected
  cases with realistic inputs.
- Fixtures must be redistributable and documented if this package adds
  them later.

## Issues

Bug reports should include the `kaos-core` version, Python version,
operating system, installation method, a minimal reproducer, expected
behavior, and actual behavior.

Feature requests should describe the user-facing problem and call out
any expected public API, CLI, schema, configuration, security, or
compatibility impact.

## Commits

Use conventional commit style and sign commits with `git commit -s` for
the Developer Certificate of Origin:

```text
feat: add new capability
fix: correct broken behavior
docs: update examples
ci: adjust workflow
chore: refresh tooling
```

## Changelog

Update `CHANGELOG.md` for user-visible changes, including public API,
CLI behavior, schema output, package metadata, security behavior, and
deprecations.

## Security

Do not report suspected vulnerabilities in public issues. Follow
[SECURITY.md](SECURITY.md).

## License

By contributing, you agree that your contributions are licensed under
the [Apache License 2.0](LICENSE). The DCO sign-off (`-s`) on each
commit is your attestation that you have the right to license the work
under that license.
