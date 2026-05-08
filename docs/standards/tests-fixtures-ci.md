# Tests, Fixtures, And CI Standards

This document defines test tiers, fixture rules, and GitHub Actions
standards for `kaos-core`.

## Test Tiers

Use explicit markers for non-unit tests:

| Tier | Marker | Network | Credentials | Purpose |
|---|---|---|---|---|
| Unit | `unit` or none | No | No | Fast deterministic behavior. |
| Integration | `integration` | No | No | Multiple local components together. |
| Benchmark | `benchmark` | No | No | Performance-sensitive checks. |
| Network | `network` | Yes | No secrets | Public HTTP or unauthenticated services if ever added. |
| Live | `live` | Yes | Yes | Real provider APIs and credentials if ever added. |
| Slow | `slow` | Maybe | Maybe | Long-running checks or corpora if ever added. |
| Security | focused unit tests | No by default | No | Abuse cases, limits, traversal, injection. |

Unit-tier CI must not require network, credentials, local services, or
large downloads.

## Test Requirements

- New behavior needs tests.
- Bug fixes need regression tests.
- Security fixes need abuse-case tests where safe.
- README quick starts and CLI examples need smoke coverage or manual
  verification before release.
- Runtime, registry, VFS, artifact, configuration, security, schema, and
  CLI behavior need tests at the appropriate tier when changed.
- Tests should assert semantics, not just non-empty output.
- Tests should avoid wall-clock sleeps unless testing timeouts.

## Marker Discipline

- Integration tests must be marked `integration`.
- Benchmark tests must be marked `benchmark`.
- If network, live, or slow tests are introduced, they must be marked
  `network`, `live`, or `slow` and registered in `pyproject.toml`.
- CI unit selection must be able to run:

```bash
uv run pytest -m "not live and not network and not slow" --no-cov
```

The command above must not collect tests that need credentials or
external services.

## Fixtures

`kaos-core` currently has no committed fixture or golden-file directory.
If fixtures are added, they must be:

- Small enough for normal repository use.
- Redistributable under compatible terms.
- Free of customer data, privileged content, secrets, and PII.
- Documented with source, license, and purpose.
- Stable enough to support deterministic tests.

Do not commit:

- Customer documents.
- Real credentials.
- Unknown-license data.
- Non-commercial or no-derivatives data for redistributed fixtures.
- Large binary corpora that should be downloaded and hash-verified.

## Fixture Provenance

Every fixture directory should include a README or manifest that records:

- File name.
- Source URL or generation method.
- License or public-domain status.
- Retrieval date when relevant.
- SHA256 for externally sourced files.
- Reason the fixture exists.
- Any transformations applied.

Generated fixtures should include the generator script or enough
description to recreate them.

## Golden Files

Golden files are allowed when output stability matters.

Rules:

- Keep golden files small and reviewable.
- Include a command for regenerating them.
- Review diffs semantically.
- Do not bless broad golden changes without explaining the behavior
  change.
- Store comments in a companion README when the file format cannot
  carry comments.

## Fuzzing

`kaos-core` does not currently define fuzz targets. Add fuzzing or
property tests for parsers, URI handling, schema export, VFS path
handling, artifact boundaries, URL safety, and size limits when those
areas gain enough input surface to justify it.

Python fuzz/property testing:

- Prefer Hypothesis for structured inputs.
- Keep failing examples as regression tests.
- Bound generated sizes so local runs stay practical.

Fuzz targets should check:

- No crashes.
- No infinite loops.
- No unbounded memory growth.
- Valid errors for invalid inputs.
- Round-trip or invariant properties where available.

## Coverage

- Coverage is a signal, not the goal.
- New important branches should be covered.
- Public API, error paths, security limits, and serialization deserve
  explicit tests.
- Do not add trivial tests only to move a percentage.

## CI Workflows

Required PR checks:

- Formatting.
- Linting.
- Type checking.
- Unit and integration tests that do not require network, credentials,
  local services, or large downloads.
- Build check.
- Dependency/security audit where configured.

Recommended scheduled or manual checks:

- Full security scan.
- Dependency audit.
- Benchmark regression check.
- Fuzz or property-test corpus run if fuzzing is added.

Release workflow checks:

- Clean checkout.
- Build pure-Python wheel and sdist.
- Strict metadata check.
- Fresh install smoke test.
- Publish through OIDC.
- Verify published install after release when practical.

## GitHub Actions Standards

- Use least-privilege `permissions`.
- Do not expose secrets to forked PRs.
- Pin third-party actions to trusted versions.
- Prefer OIDC over static credentials.
- Separate build, test, security, and publish jobs.
- Cache dependencies carefully; never cache secrets.
- Keep workflow logs free of credentials and private paths.
- Use environment protection for publishing.

## Local Verification Commands

Base development setup:

```bash
uv sync --group dev
```

Fast local quality gate:

```bash
uv run ruff format --check kaos_core tests
uv run ruff check kaos_core tests
uv run ty check kaos_core tests
uv run pytest -m "not live and not network and not slow" --no-cov
```

Packaging gate when packaging, metadata, README rendering, or release
behavior changes:

```bash
uv build
uvx --from twine twine check --strict dist/*
```

## Release Gate

Before release:

- Unit and integration CI are green.
- Security checks are green.
- Fixtures have provenance if fixtures were added.
- Fuzz/security regressions are included for parser or input-safety
  fixes where relevant.
- Build artifacts pass metadata checks.
- Fresh install smoke test passes.
