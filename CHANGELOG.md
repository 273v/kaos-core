# Changelog

All notable changes to `kaos-core` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- **HIGH — cross-session artifact access closed.**
  ``ArtifactStore.get/resolve/read_body/read_chunk/read_text/read_uri/delete``
  now accept a ``caller_session_id`` argument and refuse to return a
  manifest whose ``session_id`` does not match, raising the same
  ``"Unknown artifact"`` error used for genuinely missing IDs (so
  cross-session probing cannot distinguish "exists but forbidden"
  from "does not exist"). The MCP tools ``ArtifactsListTool`` and
  ``ArtifactsInspectTool`` now scope to ``context.session_id`` by
  default and ignore caller-supplied ``session_id`` input that was
  previously honoured unauthenticated.
  ``KaosContext.read_resource`` propagates ``self.session_id`` into
  its artifact-store fallback to close the resource-API side-channel.
  9 regression tests added in ``tests/unit/test_artifact_session_isolation.py``.
- **HIGH — ResourceRegistry cross-context cache leak closed.**
  The cache is now keyed on ``(uri, session_id)`` by default. A
  context-aware resource (one whose ``read()`` inspects the context)
  can no longer leak the first caller's value to subsequent callers
  in different sessions. ``KaosResource.cache_scope`` opts in to
  ``"global"`` (URI-only key) or ``"none"`` (no caching) when a
  resource is provably context-independent. 4 regression tests
  added in ``tests/unit/test_resource_cache_isolation.py``.
- **MEDIUM — ProfileManager path traversal closed.** Profile names
  are now validated against ``[A-Za-z0-9_-.]+``, with ``.``, ``..``,
  ``.active``, dotfile-style names, and the empty string rejected.
  An additional ``parent == root`` check on the resolved path
  catches symlink edge cases. ``set_active_profile`` shares the
  same validator so the active-profile marker cannot be poisoned
  with a name that ``load_profile`` would later reject. 31
  regression tests added in
  ``tests/unit/test_profile_manager_security.py``.
- **MEDIUM — CredentialsCheckTool now requires an authenticated
  context.** Previously the tool accepted ``context=None`` and
  could be used by an unauthenticated MCP caller to enumerate the
  configured ``module/service/key`` triples (no values were
  returned, but the existence map was reconnaissance-grade).
- **MEDIUM — VFS admin tools now session-scope by ``context.session_id``.**
  ``VFSListTool``, ``VFSReadTool``, and ``VFSStatTool`` previously
  operated on the unscoped default VFS namespace while
  ``KaosContext.get_vfs_path()`` writes through the session scope —
  an isolation hole that hid session writes behind a permissive
  default view and made the shared default scope reachable from
  any session. 4 regression tests added in
  ``tests/unit/test_vfs_session_isolation.py``.

### Fixed

- `SchemaExporter.export_openapi` now produces a valid OpenAPI 3.1.0
  document. Previously the output was missing the required ``info``
  object and operations had no ``responses``, which is invalid per
  https://spec.openapis.org/oas/v3.1.0.html. Each generated operation
  now also carries a unique ``operationId`` (hyphens replaced with
  underscores so the value is a valid Python identifier for code
  generators) and a ``tags`` entry sourced from the tool's
  ``module_name``. The method gained ``title``, ``version``, and
  ``description`` keyword-only parameters; the version defaults to the
  installed ``kaos-core`` version.

### Documented

- `VFSPath.mkdir` is now documented as a no-op for the flat-namespace
  VFS (directories are emergent S3-style; the method is preserved for
  ``pathlib.PurePosixPath`` API parity). No behaviour change.

### Changed

- Decorated tools created with ``@kaos_tool`` now default to explicit
  registration (``auto_register=False``), synthesize default
  ``ToolAnnotations`` when none are provided, return structured dict
  outputs with a text summary, and translate wrapped-function failures
  into ``ToolResult.create_error()`` instead of raising
  ``ToolExecutionError`` from ``execute()``. This keeps decorator-created
  tools aligned with the MCP boundary contract used by concrete core
  tools. 4 regression tests added in
  ``tests/unit/test_decorator_boundary.py``.

- ``CredentialsCheckTool`` now resolves the file-backed
  ``CredentialStore`` path from ``KaosSettings.credential_store_path`` via
  ``KaosContext.get_config()``, so runtimes and per-call contexts can
  redirect the development credential store without constructor
  monkeypatching. 1 regression test added in ``tests/unit/test_tools.py``.

- Removed unused published runtime dependencies on ``cryptography`` and
  ``psutil``. Neither package is imported by ``kaos_core`` today; keeping
  them in base installs widened the dependency surface without enabling a
  shipped feature.

- `CredentialStore` now writes credential files atomically (sibling
  temp file + ``fsync`` + ``os.replace``) and sets file mode ``0o600``
  on every write. Parent directories are created if missing. The class
  docstring is updated to call out the dev/test-only contract and to
  recommend production alternatives (managed secret services, OS
  keyring planned for v0.2). No API changes.

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
