# Changelog

All notable changes to `kaos-core` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Windows portability fixes for cross-OS CI (F1).** The
  ``windows-latest`` matrix leg added in 0.1.0a4 surfaced 11 test
  failures rooted in three platform hazards. All are now fixed.

  * **`kaos_core.utils.pathlib_compat` (new)** — ``to_posix_str(path)``
    renders any path-like as forward-slash form for external API
    boundaries; ``file_uri_to_path(uri)`` parses ``file://`` URIs into
    native ``Path`` objects on every OS, correctly handling the Windows
    ``file:///C:/foo`` form. Both are re-exported from
    ``kaos_core.utils``. Used internally for VFS list output and
    artifact roots-policy checks; reusable across the kaos-* family.

  * **`kaos-core[windows-secure]` extra** — installs ``pywin32`` on
    Windows for NTFS DACL hardening of the credentials file. Optional;
    ``CredentialStore`` falls back to a logged warning when ``pywin32``
    is missing on Windows. POSIX users do not need this extra.

### Changed

- **`CredentialStore` — owner-only access via the platform's native
  primitive.** On POSIX, behavior is unchanged (``chmod 0o600``). On
  Windows, the file is now hardened via an NTFS DACL granting full
  control to the current user only (``win32security`` from the
  ``windows-secure`` extra). When ``pywin32`` is missing on Windows,
  the file is written without DACL hardening and a warning is logged.
  See the docstring for the explicit limitations; production secrets
  should use a managed secrets service regardless.

### Fixed

- **`DiskBackend.list` returned ``[]`` on Windows for any non-empty
  prefix.** ``str(child.relative_to(...))`` rendered with the native
  separator (backslash on Windows), breaking the forward-slash prefix
  comparisons. Fix: route through ``Path.as_posix()``. Cascading fix
  for ``VFS.walk``, ``list_page``, ``cleanup_context``,
  ``VFSPath.iterdir``, and ``VFSListTool``.

- **`ArtifactStore` roots-policy check silently allowed cross-root
  reads on Windows.** ``urlparse('file:///C:/foo').path`` is
  ``/C:/foo``; naive ``Path('/C:/foo')`` mis-anchors the leading slash
  on Windows, so ``relative_to`` against the actual disk path failed
  in a way that let the read through. Fix: route URI → Path through
  ``file_uri_to_path``.

## [0.1.0a4] — 2026-05-07

### Added

- **`kaos_core.security` — central outbound URL validation + response size caps.**
  New module providing the canonical implementations of "is this URL safe to
  fetch?" and "is this response body too large?" across the KAOS platform.
  Strict-by-default; everything is configurable via :class:`KaosSecuritySettings`
  (env: ``KAOS_SECURITY_*``) or per-call overrides. Stdlib-only — no new
  dependencies.

  * **`validate_outbound_url(url)`** — full SSRF guard layered on top of
    :func:`is_safe_url`. Rejects unsafe schemes (``javascript``, ``data``,
    ``vbscript``, ``file``), schemes outside the allowlist, malformed URLs,
    metadata-service hosts (AWS/Azure/GCP IMDS), loopback hosts, and
    private-network hosts (RFC1918, ULA, link-local). Per-call kwargs
    (``allow_private``, ``allow_loopback``, ``allow_metadata``,
    ``allowed_hosts``) override the corresponding settings; ``allowed_hosts``
    is a union of settings and kwarg entries with support for exact
    hostnames, ``.suffix.example.com`` wildcards, and CIDR strings.
  * **`is_safe_url(url)`** — XSS-shape scheme blocklist, byte-for-byte
    compatible with the prior :mod:`kaos_content._security.is_safe_url`
    (which delegates here as of ``kaos-content`` 0.1.0a2). Defeats
    HTML-entity, percent-decode, whitespace, and NUL-byte bypasses.
  * **`is_private_ip` / `is_loopback` / `is_metadata_service`** — predicates
    used by the SSRF guard; exposed for callers that need them directly.
  * **`read_capped_bytes` / `read_capped_json`** — async streaming response
    readers with a hard byte budget. Pre-flight ``Content-Length`` check
    plus running budget on ``aiter_bytes``. Catches both well-behaved
    oversized responses and lying-Content-Length / chunked-transfer
    bombs. Duck-typed protocol — works with httpx, aiohttp, mocks.
  * **`check_content_length` / `cap_loaded_bytes`** — sync helpers for
    pre-flight and post-hoc size enforcement.
  * **`KaosSecuritySettings`** — strict-by-default settings class with
    env prefix ``KAOS_SECURITY_``. Knobs:
    ``block_private_networks`` (default True),
    ``block_metadata_services`` (default True),
    ``block_loopback`` (default True),
    ``allowed_schemes`` (default ``("http", "https")``),
    ``allowed_hosts`` (default ``[]``),
    ``response_max_bytes`` (default 100 MB),
    ``response_size_check_via_content_length`` (default True),
    ``response_size_check_via_streaming`` (default True).
  * **`UnsafeURLError` / `ResponseSizeError`** — new exceptions inheriting
    :class:`KaosCoreError`. Carry structured ``reason``/``host`` and
    ``max_bytes``/``seen_bytes``/``content_length`` attributes for
    programmatic handling and agent-friendly error envelopes.

  Motivation: the cross-package audit of ``kaos-source`` (KSRC-02 / KSRC-04)
  identified 7 sites across ``kaos-source`` and ``kaos-web`` that performed
  ``resp.json()`` on untrusted bodies without size caps, plus 2 sites that
  ran ``follow_redirects=True`` without SSRF validation. Centralizing the
  fixes in ``kaos-core`` rather than inlining per-package keeps the policy
  single-sourced and makes ``KAOS_SECURITY_*`` env knobs the single
  configuration surface for outbound network safety. Used by
  ``kaos-content`` 0.1.0a2 (where ``_security.is_safe_url`` becomes a
  re-export) and ``kaos-source`` 0.1.0a1 (where the audit fixes consume the
  helpers).

## [0.1.0a3] — 2026-05-07

### Changed

- **`kaos_core.agent` subpackage renamed to `kaos_core.mcp_types`.** The
  prior name collided with `kaos-agents` (the agent runtime) and
  obscured what the contents actually are: every type in this
  subpackage is an MCP wire-protocol shape — direct counterpart to
  the MCP specification's client-initiated subaction messages
  (`sampling/createMessage`, `elicitation/create`, MCP async tasks).
  Top-level `kaos_core` re-exports are unchanged
  (`from kaos_core import SamplingRequest, TaskManager` still works);
  only callers importing from a subpackage path need to update:
  - `from kaos_core.agent import …`
    → `from kaos_core.mcp_types import …`
  - `from kaos_core.agent.{sampling,elicitation,task,settings} import …`
    → `from kaos_core.mcp_types.{sampling,elicitation,task,settings} import …`
  No back-compat shim ships at v0.1.0a3 — alpha status permits direct
  breaking changes.

- **`DelegationRequest` / `DelegationResult` / `UsageStats` moved to
  `kaos_core.types.delegation`.** They describe an A2A delegation
  pattern that is not part of the MCP specification, so they no longer
  fit alongside the MCP protocol shapes. Top-level `kaos_core` exports
  unchanged.

- **`SamplingRequest.max_tokens` default raised from `256` to `32_768`.**
  The 256 floor was a 2023-era safeguard from when MCP clients
  delegated to expensive third-party APIs and wanted a hard cap. By
  2026, frontier models routinely accept 64K-200K output budgets and
  the typical sub-call needs more than 256 tokens to produce a useful
  answer. Aligned with the same bump in `kaos-llm-client` and
  `kaos-agents`.

### Added

- **`maintainers` field in `pyproject.toml`** (cross-package metadata
  consistency). The next published wheel + sdist carry
  `Maintainer-email: Michael Bommarito <mike@273ventures.com>`
  alongside the existing `Author-email: 273 Ventures LLC`.

## [0.1.0a2] — 2026-05-07

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

- Core MCP tools no longer tell callers to start the removed
  ``kaos-core-serve`` entry point when no runtime context is attached.
  The error guidance now points to the companion ``kaos-mcp`` package or
  explicit ``KaosRuntime`` registration.

- The end-to-end integration test now carries the registered
  ``integration`` marker explicitly, keeping marker-based selection in
  sync with the test directory layout.

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

[Unreleased]: https://github.com/273v/kaos-core/compare/v0.1.0a3...HEAD
[0.1.0a3]: https://github.com/273v/kaos-core/compare/v0.1.0a2...v0.1.0a3
[0.1.0a2]: https://github.com/273v/kaos-core/compare/v0.1.0a1...v0.1.0a2
[0.1.0a1]: https://github.com/273v/kaos-core/releases/tag/v0.1.0a1
