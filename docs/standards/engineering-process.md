# Engineering Process

This document defines how `kaos-core` handles features, bugs,
enhancements, fixes, releases, branches, pull requests, and tags.

## Work Types

| Type | Meaning | Expected output |
|---|---|---|
| Feature | New user-visible capability | Design note if needed, implementation, tests, docs, changelog. |
| Enhancement | Improvement to existing behavior | Focused implementation, tests, docs when public behavior changes. |
| Bug fix | Correction of broken behavior | Regression test, fix, changelog if user-visible. |
| Security fix | Fix for vulnerability or unsafe behavior | Private handling when needed, regression test, advisory if applicable. |
| Maintenance | Tooling, dependencies, CI, docs, cleanup | Focused PR, verification evidence. |
| Release | Publish package artifacts | Clean tag, GitHub release, PyPI artifacts, changelog. |

## Issue Triage

Every issue should answer:

- What behavior is expected?
- What behavior happened?
- What `kaos-core` version, platform, Python version, and installation
  method are involved?
- Is there a minimal reproducer?
- Is this runtime, registry, tool, prompt, resource, execution, VFS,
  artifact, configuration, security, CLI, packaging, or docs behavior?
- Is this unit, integration, benchmark, packaging, or docs behavior?
- Is there security sensitivity?

Labels should distinguish type, priority, package area, and test tier.

## Feature Process

1. Write the user-facing goal.
2. Identify the public API surface affected.
3. Decide whether a short design note is needed.
4. Implement behind stable boundaries.
5. Add tests at the correct tier.
6. Update README, docs, and examples.
7. Add a CHANGELOG entry.
8. Verify package build and install behavior when public API changes.

Do not use feature flags to hide unfinished public APIs. Keep provider,
server, extractor, LLM, and document-format integrations in companion
packages unless the feature is truly core runtime infrastructure.

## Bug Fix Process

1. Reproduce the bug.
2. Add a failing regression test.
3. Fix the smallest responsible code path.
4. Confirm the regression test fails before and passes after.
5. Check adjacent behavior for the same failure mode.
6. Add a CHANGELOG entry if released users are affected.

Do not mark a bug fixed because a broad refactor appears to cover it.
The regression test is the proof.

## Enhancement Process

Enhancements should preserve existing contracts unless the versioning
policy allows a breaking change.

Before implementation, decide:

- Is this observable behavior or internal cleanup?
- Does it affect performance, memory, errors, output ordering,
  serialization, CLI output, schema output, or environment-variable
  behavior?
- Does it need migration guidance?
- Does it require benchmark evidence?

## Branches

- `main` is the protected release branch.
- Use short-lived topic branches.
- Branch names should describe intent:
  - `feat/<short-name>`
  - `fix/<short-name>`
  - `docs/<short-name>`
  - `ci/<short-name>`
  - `chore/<short-name>`
  - `security/<short-name>`
- Delete branches after merge.
- Do not reuse release tags as branch names.

## Pull Requests

Pull requests are the review unit.

A PR should include:

- Problem statement.
- Summary of the change.
- Tests and commands run.
- User-visible impact.
- Public API, CLI, schema, environment-variable, or package metadata
  impact.
- Release impact.
- Screenshots or sample output when CLI/docs output changes.
- Risk notes for security, performance, dependencies, or compatibility.

Keep PRs focused. Split mixed work into separate PRs when review would
otherwise be ambiguous.

## Commits

- Use conventional commit style.
- Sign commits with `git commit -s`; this repository requires the
  Developer Certificate of Origin.
- Keep commits buildable when practical.
- Do not include secrets, local paths, generated caches, virtual
  environments, or build artifacts.
- Use package scopes when they help release notes.

Examples:

```text
feat: add runtime namespace export
fix: preserve VFS session isolation
docs: clarify CLI JSON output
ci: add weekly dependency audit
chore: refresh ruff and ty pins
```

## Tags

- Release tags are immutable.
- Use `v<version>` tag format, for example `v0.1.0a2`.
- A tag represents the exact commit used to build and publish release
  artifacts.
- Do not move a public tag. If a published artifact is wrong, yank when
  appropriate and release a new version.

Branch, PR, and tag roles:

| Object | Purpose |
|---|---|
| Branch | Temporary workspace for a change. |
| Pull request | Review, discussion, checks, and merge decision. |
| Tag | Immutable release pointer. |

## Releases

A release requires:

- CHANGELOG entry.
- Version bump from `kaos_core/_version.py`.
- Clean formatting, linting, typing, tests, and security checks.
- Built pure-Python wheel and sdist.
- Strict metadata check.
- Fresh install smoke test.
- OIDC Trusted Publishing.
- GitHub release notes matching the tag and changelog.

Do not use static PyPI API tokens.

## Hotfixes

Use a hotfix only for urgent breakage or security issues.

Hotfix requirements:

- Narrow scope.
- Regression test.
- Fast maintainer review.
- Patch or prerelease version bump.
- Clear changelog entry.
- Follow-up issue if deeper cleanup remains.

## Security Handling

- Do not discuss suspected vulnerabilities in public issues until they
  are triaged.
- Use the repository's vulnerability reporting process in
  `SECURITY.md`.
- Rotate exposed credentials before cleanup.
- Add regression tests for security fixes where safe.
- Publish advisories when users need action.
