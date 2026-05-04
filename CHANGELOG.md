# Changelog

All notable changes to `kaos-core` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- `KaosTool.validate_inputs` now performs primitive JSON Schema type
  checks (string, integer, number, boolean, array, object, null) on
  every provided input — previously only the presence of required
  fields was validated. Type mismatches raise
  :class:`~kaos_core.exceptions.ValidationError` with a list of all
  failing fields. This closes a contract gap where tools advertised
  typed schemas but accepted any value at runtime.

  Booleans are rejected for `integer` / `number` fields (Python's
  ``bool`` is a subclass of ``int`` but a distinct JSON type), and
  integers are rejected for `boolean` fields, matching the behaviour
  of the ``jsonschema`` library.

  Full JSON Schema validation (`enum`, `minimum`/`maximum`, `pattern`,
  nested `properties`, `oneOf`/`anyOf`, `$ref`) is on the v0.2 roadmap
  via the `jsonschema` library.

## [0.1.0a1] — 2026-05-04

First public alpha release.

### Added

- Foundational runtime, MCP-native types, registries, and execution engine
  for the KAOS (Kelvin Agentic Operating System) platform.
- `KaosRuntime` container with explicit dependency injection (`KaosRuntime.default()`
  for scripts and tests; explicit construction for library code).
- Tool, resource, prompt, and namespace registries with provenance tracking.
- `KaosContext` execution context with session/trace correlation.
- `ModuleSettings` typed-settings base class with six-level resolution
  (overrides → context → environment → `.env` → field defaults).
- `SecretStr`-aware `resolve_secret()` for credential resolution from
  settings, environment variables, or the `CredentialStore` file backend.
- Three-tier artifact policy (inline / summary / handle) with thresholds
  `INLINE_THRESHOLD = 16 KB` and `SUMMARY_THRESHOLD = 256 KB`.
- Disk-first virtual filesystem (`VirtualFileSystem`) with memory and disk
  backends, range reads, pagination, and lazy loading.
- Agent primitives: `SamplingRequest`, `ElicitationRequest`,
  `DelegationRequest`, `TaskManager`.
- `WorkflowExecutor` and `ExecutionEngine` for composable execution.
- Structured logging via `kaos_core.logging.get_logger()` with auto-prefix
  to the `kaos.*` hierarchy.
- 10 built-in MCP tools registered via `register_core_tools()`.
- CLI entrypoint `kaos-core` (administrative).
- Python 3.13 and 3.14 support.

### Removed

- `kaos-core-serve` script entry point and `kaos_core.serve` module —
  exposing tools over the Model Context Protocol is the responsibility
  of the companion package
  [`kaos-mcp`](https://github.com/273v/kaos-mcp), which ships separately.
  Bundling a stub server in `kaos-core` whose only resolution path went
  through `kaos-mcp` was a misleading dependency contract.
- `[mcp]` and `[pydantic-ai]` optional dependencies. Neither was
  imported anywhere in `kaos_core/`; the extras advertised integrations
  that belong to higher-level packages.
- `docs/PRD.md` and `docs/TODO.md`. These were monorepo design notes
  whose claims had drifted from shipped behavior. Design history will
  be reintroduced via the documentation site.

### License

This release is the first to ship under the Apache License 2.0. Earlier
internal versions were proprietary.

[Unreleased]: https://github.com/273v/kaos-core/compare/v0.1.0a1...HEAD
[0.1.0a1]: https://github.com/273v/kaos-core/releases/tag/v0.1.0a1
