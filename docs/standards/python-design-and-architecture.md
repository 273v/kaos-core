# Python Design And Architecture Standards

These standards apply to Python code in `kaos-core`.

`kaos-core` is a pure-Python package. It publishes the `kaos_core`
import package and the `kaos-core` administrative CLI.

## Package Shape

- Keep the import package name aligned with the distribution name:
  `kaos-core` publishes import package `kaos_core`.
- Declare the public API in `kaos_core.__all__`.
- Keep `kaos_core/py.typed` in the wheel.
- Keep import-time work minimal: no network calls, filesystem scans,
  runtime initialization, logging setup, or expensive model loads at
  import time.
- Use absolute imports for package code.
- Keep base dependencies small. `kaos-core` is the dependency-light
  runtime base for other `kaos-*` packages.
- Prefer a small top-level package surface that re-exports stable,
  documented names only.

## Public API

Treat all of these as public API once released:

- Names exported from `kaos_core.__all__`.
- Documented modules, classes, functions, dataclasses, Pydantic models,
  protocols, and type aliases.
- `kaos-core` CLI commands, flags, `--json` output, and exit behavior.
- Runtime, registry, tool, prompt, resource, execution, VFS, artifact,
  configuration, security, and MCP type contracts.
- JSON Schema, OpenAPI-style schema export, MCP-compatible shapes, and
  `ToolResult` content contracts.
- Environment-variable conventions exposed through `ModuleSettings`,
  including the `KAOS_<MOD>_*` namespace.

Changing or removing public API requires a changelog entry and a version
bump consistent with the package's pre-1.0 stability policy.

## Dependency Boundaries

- Keep runtime dependencies minimal and justified.
- Do not make `kaos-core` depend on provider clients, LLM clients,
  document extractors, web frameworks, or server packages. Companion
  packages provide those integrations.
- Do not make tests pass by relying on undeclared transitive
  dependencies.
- Do not use private APIs from dependencies unless the risk is recorded
  and covered by tests.
- Keep adapters and compatibility code localized so dependency changes
  do not leak through public runtime contracts.

## Data Modeling

- Use Pydantic for external boundaries: configuration, JSON-like inputs,
  MCP-compatible payloads, CLI `--json` output, schema export, and
  serialized results.
- Use dataclasses or small typed objects for simple internal value
  records when Pydantic validation is not needed.
- Keep parsing and validation at boundaries. Internal functions should
  receive typed, normalized values.
- Prefer explicit result types over loosely shaped dictionaries.
- Avoid returning ambiguous tuples from public APIs.

## Functions And Classes

- Prefer functions for stateless transformations.
- Use classes when there is persistent state, lifecycle management,
  shared configuration, registries, stores, backends, runtimes, or an
  explicit protocol.
- Keep constructors cheap. Use explicit factory methods or runtime
  setup calls for expensive initialization.
- Avoid inheritance unless the abstraction is stable and tested through
  multiple implementations.
- Prefer protocols or small composition points over deep class
  hierarchies.

## Configuration

- Define typed settings for package configuration.
- Read environment variables and config files at the edge, not deep in
  algorithmic code.
- Keep `ModuleSettings` resolution order documented and covered by
  tests when it changes.
- Represent secrets with secret-aware types where available.
- Do not print, log, serialize, or include secrets in exception strings.
- Preserve redaction behavior in CLI and structured logging output.

## Error Handling

- Use package-specific exception types for user-facing failure modes.
- Error messages should explain what failed, why it likely failed, and
  what the caller can do next.
- Do not expose stack traces, credentials, internal paths, or provider
  payloads in user-facing errors.
- Preserve original exceptions with exception chaining when debugging
  context matters.
- Validate untrusted inputs early and fail with bounded, predictable
  errors.

## Async And Concurrency

- Use async APIs where existing runtime, execution, VFS, tool, prompt,
  or resource contracts are async.
- Use synchronous APIs for simple CPU-bound transformations unless the
  package already exposes an async surface.
- Bound concurrency with semaphores or worker limits when concurrent
  execution is introduced.
- Apply timeouts to external calls if a future feature adds external
  I/O.
- Offload blocking or CPU-heavy work from event loops.
- Make cancellation safe: clean up files, subprocesses, stores, and
  runtime state.

## Files, Paths, And Inputs

- Accept `str` and `PathLike` inputs where file paths are part of the
  public API.
- Normalize paths at boundaries.
- Preserve VFS session isolation and flat namespace semantics.
- Do not follow symlinks, traverse directories, or read arbitrary files
  unless the API explicitly permits it.
- Put size, row, token, page, recursion, and time limits on untrusted
  inputs.
- Prefer streaming for large artifacts and VFS content.

## CLI Design

- Every `kaos-core` CLI command must support `--help`.
- Commands that produce machine-consumable output must support `--json`.
- JSON output must remain stable once released.
- CLI errors should be concise and actionable.
- CLI examples in README and docs must be tested or manually verified
  before release.

## Documentation Expectations

- README quick starts must be runnable from a fresh environment.
- Examples should use public APIs only.
- Advanced docs belong under `docs/`.
- Any advertised runtime behavior, CLI command, schema export,
  configuration convention, security control, or VFS/artifact behavior
  must have at least one test at the appropriate tier.
