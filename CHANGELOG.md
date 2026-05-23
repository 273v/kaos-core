# Changelog

All notable changes to `kaos-core` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- `pyproject.toml` classifier bumped from `Development Status :: 3 - Alpha`
  to `Development Status :: 5 - Production/Stable` to reflect the
  0.1.0 GA release (WU-L #543) that froze the public API for the
  0.1.x line. Closes audit-04/kaos-core.md Family D (classifier drift).


## [0.1.1] — 2026-05-22

Launch-blocker plan §Issue 7 / #582 — idempotent default-VFS-namespace
prepend in `path_resolver._resolve`.

### Fixed

- **#582 path_resolver double-prefix.** Pre-0.1.1, calling
  `resolve_input_path("files/contract.docx")` against a context
  with `default_vfs_namespace="files/"` produced the broken lookup
  `"files/files/contract.docx"`. Idempotency check via
  `if namespace and stripped.startswith(namespace)` now skips the
  prepend when the caller already passed an already-namespaced
  path. Bare names still get the namespace prepended exactly once.

### Tests

- `tests/unit/test_path_resolver_idempotent.py` — 6 new tests:
  bare + already-namespaced both resolve to the same content;
  double-prefix never appears; empty-namespace passes through;
  partial-overlap (`filesystem-report.txt` vs `files/`) NOT
  mistaken for already-namespaced; multi-segment namespaces
  (`matters/{mid}/sessions/{sid}/files/`) work idempotently;
  slash-normalization sweep.
- 23/23 existing `test_path_resolver.py` tests still pass.

## [0.1.0] — 2026-05-20

### Changed

- 0.1.0 GA — WU-L of the 0.1.0 GA plan. First stable release of
  `kaos-core`. The public API is frozen for the 0.1.x line: no
  breaking changes will land until 0.2.0. kaos-core has no kaos-*
  dependencies, so the only delta vs. 0.1.0rc1 is the version bump
  itself; downstream Layer 1+ packages raise their pin floor to
  `>=0.1.0,<0.2` in this same WU-L release wave. WU-K rc1 verification
  green (10/10 Chrome MCP cases) per
  `kaos-modules/docs/releases/2026-05-20-0.1.0rc1-wu-k-green.md`.

## [0.1.0rc1] — 2026-05-20

### Changed

- WU-J of the 0.1.0 GA plan; release candidate for 0.1.0 GA. Freezes
  the public API for the 0.1.0 line — no breaking changes will land in
  0.1.x. kaos-core has no kaos-* dependencies, so the only delta vs.
  0.1.0a12 is the version bump itself; the pin floor raised to
  `>=0.1.0rc1,<0.2` is consumed by downstream Layer 1+ packages in
  this same release wave.

## [0.1.0a12] — 2026-05-20

### Added

- **`kaos_core.types.capability`** — `Capability`, `CapabilityKind`,
  `CostClass`, `LatencyClass`, and `EMPTY_CAPABILITIES` constant.
  Uniform abstraction over Tool / Source / Retriever / Judge /
  Persona / UI-surface, anchoring the kaos-agents Step 1 lateral
  redesign. The capability TYPE lives in kaos-core (alongside
  `ToolMetadata` / `ToolAnnotations` / `ToolCategory`) to preserve
  kaos-mcp's independence from kaos-agents; the in-process
  `CapabilityRegistry` lives in `kaos_agents.registry` and consumes
  this type. See
  `kaos-modules/docs/plans/2026-05-19-lateral-redesign-capability-layer.md`.
- Coarse-grained `CostClass` (FREE / CHEAP / MEDIUM / EXPENSIVE) and
  `LatencyClass` (INSTANT / FAST / SLOW / VERY_SLOW) buckets so the
  planner can reason about cost and latency without per-call
  estimates. Concrete spend is still tracked in
  `ActionResult.cost_usd` post-execution; these buckets are
  pre-execution planning hints.

### Tests

- New `tests/unit/test_capability.py` — unit coverage for the type
  shape, equality, hashing, and the `EMPTY_CAPABILITIES` sentinel.

## [0.1.0a11] — 2026-05-18

### Added

- `ModuleSettings.legacy_env_vars` for opt-in legacy environment-variable
  aliases resolved after canonical `KAOS_<MOD>_*` env vars and before `.env`.
- `KaosRuntime.reset_default(token)` and a reset token return from
  `KaosRuntime.set_default(...)` so tests and scripts can restore the prior
  default runtime.
- `cursor` input for the `kaos-core-vfs-list` MCP tool and `--cursor` for
  `kaos-core vfs ls`.

### Changed

- Decorated tool schemas now represent common typing shapes more accurately,
  including `Literal[...]`, `list[T]`, `dict[str, T]`, `T | None`, and
  Pydantic model annotations.
- User-facing `KaosCoreError.__str__()` now returns the public message only;
  structured details remain available on `.details`.
- OAuth device, PKCE, and refresh-token HTTP calls now validate endpoint URLs
  with the shared SSRF guard, default endpoint schemes to HTTPS-only, and cap
  JSON response bodies before parsing.
- `ArtifactManifest.to_tool_result()` now honors `summary_threshold` by
  returning a resource link only for artifacts at or above that threshold.

### Fixed

- `HardenedCredentialStore.get()` no longer deletes the source secret unless
  an upward migration actually writes a stronger tier.
- Function-tool, execution-engine, and task-manager failure results no longer
  include raw exception strings that may contain secrets or internal details.
- `KaosContext` logging now injects `session_id` and `trace_id` per log call
  instead of attaching context-specific filters to the shared logger.
- `EncryptedFileStorage.is_available()` now calls its passphrase provider once
  per availability probe.
- The pytest runtime fixture now resets the default runtime after each test.
- README, path resolver, security-settings, and pre-commit documentation were
  refreshed to match current behavior and tooling pins.

## [0.1.0a10] — 2026-05-17

### Changed — BREAKING

- **URI contract redesign for `resolve_input_path()`** (closes the user-
  outcome gap left by 0.1.0a9; see
  `kaos-modules/docs/plans/uri-contract-redesign.md`). Agent-facing
  contract is now:

  | Input shape                          | Resolution                                          |
  |--------------------------------------|-----------------------------------------------------|
  | bare name (`"contract.docx"`)        | session VFS prepended with `context.default_vfs_namespace` (no CWD fallback) |
  | `file:///abs/path`                   | absolute filesystem (CLI / trusted)                 |
  | `kaos://artifacts/<id>`              | artifact store (session-scoped) — unchanged         |
  | `kaos://<vfs>/...` / `vfs://<path>`  | explicit VFS path (default-namespace NOT prepended) |
  | raw `/abs/path` (no scheme)          | **REJECTED** with an actionable error               |

  Pre-0.1.0a10 "bare name → try VFS then CWD" fallback removed. Hosts
  that exposed bare names from agent inputs should now declare the
  session's upload prefix via `context.default_vfs_namespace` (e.g.
  the kaos-ui SPA backend sets `"files/"`). CLI users passing absolute
  paths must switch to `file:///abs/path`.

- **`kaos-core-vfs-list`** now lists inside `context.default_vfs_namespace`
  when no explicit `path` is supplied so bare-name agents can discover
  what their lookups will hit.

### Added

- **`KaosContext.default_vfs_namespace`** field (default `""`).
- **`KaosContext.with_default_namespace(ns)`** child-context helper.
- **`vfs://<path>`** URI scheme and **`file:///abs/path`** URI scheme.
- 9 new unit tests covering the redesigned contract.

### Migration

- **CLI callers** passing absolute paths: prefix with `file://`.
- **Host backends** (e.g. kaos-ui SPA): set
  `context.default_vfs_namespace = "files/"` per session.
- Pass-through tools (those that hand the raw `path` to
  `resolve_input_path()`) need no change.

## [0.1.0a9] — 2026-05-17

### Added

- **`kaos_core.path_resolver`** — `resolve_input_path()` async context
  manager + `ResolvedInput` / `ResolvedOrigin` value types +
  `InputPathResolutionError` exception. Canonical resolver for
  agent-supplied file/path inputs across every kaos-* MCP tool that
  accepts a `path` parameter. Resolves four input shapes:
  `kaos://artifacts/<uuid>` (artifact-store lookup with session
  isolation), `kaos://<other>/...` (VFS read), relative path found in
  the session VFS (extracted to temp), and absolute filesystem path
  (passthrough). Reads from `KaosContext.runtime.vfs` /
  `runtime.artifacts` with the caller's `session_id` so cross-session
  artifact reads cannot succeed. Emits agent-friendly
  what/how-to-fix/alternative-tool error triples on every failure path,
  including mime-type and size-cap mismatches. Upstream fix for the
  hallucination incident documented in
  `kaos-modules/docs/plans/vfs-blind-tools-audit-and-fix-plan.md`:
  every file-input tool in kaos-office / kaos-pdf / kaos-tabular /
  kaos-source can now drop its raw `Path(p).exists()` calls and route
  through this helper so SPA-uploaded files become visible.

## [0.1.0a8] — 2026-05-17

### Added

- **`ArtifactStore.create_from_bytes(data, ...)`** — canonical path
  for tools that produce content in memory (HTTP fetches, document
  conversions, LLM-generated payloads) and need to expose it via the
  artifact tiering (summary inline / summary + link / link-only) rather
  than inlining a truncated string into the `ToolResult`. Until now,
  tools had to choose between `create_from_path` (forces a pre-existing
  VFS file) or inlining a Python string and hardcoding a `max_chars`
  cap. The latter is the anti-pattern the broader artifact-first plan
  is removing across `kaos-source`, `kaos-web`, and `kaos-agents`.
  Sanitises `name` before joining with `subdir` so caller-supplied
  names cannot escape the artifacts directory. Optional `source_uri`
  parameter to populate the new first-class field below.

- **`ArtifactManifest.source_uri: str | None`** as a first-class
  field on the manifest (was previously buried in the free-form
  `provenance` / `metadata` dicts). Lets agents and the SPA render
  provenance — "where did this come from?" — directly from the
  manifest without dict spelunking. `create_from_path` and
  `create_from_bytes` both accept the parameter. `None` for purely
  derived or user-uploaded artifacts.

- **`KaosCoreArtifactSettings`** (`kaos_core.artifacts.settings`,
  `kaos_core.KaosCoreArtifactSettings`) — typed `ModuleSettings` with
  `inline_threshold` and `summary_threshold` fields, env prefix
  `KAOS_CORE_ARTIFACT_`. Authoritative source for the inline / summary
  / handle-only tier thresholds. `ArtifactManifest.to_tool_result`
  accepts an optional `settings` parameter; the module-level
  `INLINE_THRESHOLD` / `SUMMARY_THRESHOLD` constants are now derived
  from the default settings instance so existing imports keep working
  unchanged. Per-deployment overrides:

  ```bash
  export KAOS_CORE_ARTIFACT_INLINE_THRESHOLD=32768
  export KAOS_CORE_ARTIFACT_SUMMARY_THRESHOLD=524288
  ```

### Why

This is Stage A of the cross-package
`no-hardcoded-caps-and-artifact-first-tool-results` plan (lives in the
kaos-modules monorepo at
`docs/plans/no-hardcoded-caps-and-artifact-first-tool-results.md`).
Stage A is the critical-path foundation; downstream stages (kaos-mcp
serving `kaos://artifacts/{id}/{body,manifest,range}` resources,
`kaos-source` and `kaos-web` migrating fetch tools off `max_chars`
truncation, kaos-agents `ArtifactToCorpusHook`, kaos-ui `ArtifactCard`)
all depend on these primitives being available.

### Backward compatibility

- `INLINE_THRESHOLD` and `SUMMARY_THRESHOLD` module-level constants
  remain exported from `kaos_core.artifacts` and `kaos_core` with the
  same default values (16 KiB / 256 KiB). Downstream consumers
  (`kaos-agents`, `kaos-content`, `kaos-llm-core`) import them by name
  and continue to resolve to the same values.
- `to_tool_result(...)` keyword-arg signature is purely additive
  (`settings` is optional).
- `create_from_path(...)` keyword-arg signature is purely additive
  (`source_uri` is optional and defaults to `None`).
- New `ArtifactManifest.source_uri` field has a `None` default, so
  manifests persisted under earlier versions deserialize cleanly.

## [0.1.0a7] — 2026-05-15

### Fixed

- **`ParameterSchema.to_json_schema()` now emits a defensive
  `items: {}` for `type=array` declarations that don't otherwise
  set `items`.** OpenAI's strict JSON Schema validator rejects
  bare-array function parameters with `400 invalid_function_parameters`,
  which previously took down the ENTIRE tool catalog for
  openai-provider sessions in kaos-agents — the agent could see no
  tools and hallucinated answers instead of using
  `kaos-source-fr-search` / `kaos-content-search-document` /
  `kaos-pdf-extract-parse` etc. Anthropic providers accepted the
  loose shape silently, masking the bug. The defensive floor keeps
  the catalog valid even when an individual tool forgets to declare
  its element type; per-call-site cleanup to declare proper item
  types (better LLM guidance) is downstream in the tool repos.

### Added

- **Strict-schema unit test suite for `ParameterSchema`.** New
  `tests/unit/test_parameter_schema_openai.py` pins six cases:
  defensive `items` floor, caller override preservation,
  non-array immunity, nested object-array round-trip, optional
  + default behaviour, and (skipped when `jsonschema` isn't
  installed) full Draft 2020-12 validation. The strict gate
  catches future regressions on OpenAI compatibility.
- **`jsonschema>=4.21` added to the dev dependency group** so CI
  runs the optional Draft 2020-12 validator step instead of
  silently skipping it. No runtime impact (test-only).

## [0.1.0a6] — 2026-05-11

### Added

- `KaosRuntime.__init__(vfs=...)` kwarg for explicit VFS injection.
- `KaosRuntime.test_mode(in_memory: bool = True)` classmethod —
  canonical pytest constructor with in-memory VFS + cleanup baked in.
  Closes the disk-VFS cross-pytest-leakage footgun observed in
  kaos-agents live composition tests (Excel test went from ~25-40%
  flake to 8/8 stable after switching to test_mode).

### Changed

- `KaosRuntime.vfs` is now a property; setting it invalidates the
  cached `artifacts` ArtifactStore. Eliminates the cross-attribute
  coupling footgun where replacing `runtime.vfs` post-init left
  `runtime.artifacts` still pointing at the old VFS.
- `KaosRuntime.artifacts` is now a `@cached_property` over
  `self.vfs` instead of being captured at construction time.

### Mirrored from monorepo

This release mirrors monorepo commit `d0ba060` (Sprint-1 #1, "close
KaosRuntime VFS leakage footgun") from `kaos-modules` plus
associated regression tests at `tests/unit/test_runtime_isolation.py`.
Per `memory/feedback_per_module_split_mirror.md`, monorepo source
edits to published packages must be mirrored back to the per-module
repo before they ship.

### Security

- **bandit + vulture now run in both pre-commit and CI.** The
  ``.pre-commit-config.yaml`` gains two new hooks (bandit static
  security scan + vulture dead-code scan), mirrored by two new jobs
  in ``security.yml`` (``bandit (static security)`` +
  ``vulture (dead-code scan)``). Pre-commit gives contributors fast
  feedback before push; CI makes the scan publicly visible on every
  PR. Bandit skip list is justified inline per audit
  (``B101,B404,B603,B607``); vulture runs at ``--min-confidence 100``
  with a hand-curated ``--ignore-names`` list for framework callbacks
  / signal handlers / OAuth field names that vulture can't infer
  from the import graph alone. Both hooks currently pass clean.

## [0.1.0a5] — 2026-05-10

### Added

- **CLI verbs for credential management (F2.5).** Six new
  ``kaos-core`` subcommands cover the day-to-day operator surface:

  * ``kaos-core creds tiers [--json]`` — report which storage
    tiers are available on this host. Useful when debugging "why
    is my secret in plaintext on this box?".
  * ``kaos-core creds list [--module M] [--json]`` — list stored
    credential names per module. Values are never printed.
  * ``kaos-core creds set MODULE SERVICE [KEY] [--json]`` — store a
    credential. The value is read from stdin (uses
    :func:`getpass.getpass` when stdin is a TTY, plain ``read``
    otherwise) so it never appears in shell history. Lands in
    the strongest available tier.
  * ``kaos-core creds delete MODULE SERVICE [KEY] [--json]`` —
    remove a credential from every tier that holds it.
  * ``kaos-core creds migrate [--dry-run] [--json]`` — promote
    stored credentials to the strongest available tier. Walks the
    well-known KAOS module namespaces; ``--dry-run`` reports what
    would move without writing.
  * ``kaos-core auth status [--json]`` — list stored OAuth tokens
    (metadata only — never secret values). Read-only; the full
    ``auth login`` workflow is deferred to F2.6 once provider
    metadata storage is designed.

  Each verb honors the same ``--json`` contract as the rest of the
  ``kaos-core`` CLI for pipe-friendly scripting. The dispatcher is
  built fresh per invocation so ``KAOS_*_DIR`` and other env
  overrides are respected even when the CLI runs inside a sandbox.

### Fixed

- **`CredentialStore.delete` left empty service / module entries
  behind**, causing ``list_services`` to keep reporting a service
  long after its last key was deleted. The fix prunes empty
  containers on delete so the API stays consistent. Surfaced by
  the F2.5 ``creds delete`` → ``creds list`` round-trip test.

- **OAuth flow runners (F2.4).** New ``kaos_core.auth`` subpackage
  with provider-agnostic OAuth 2.0 / 2.1 plumbing that produces
  :class:`OAuthToken` objects. Opt-in via ``kaos-core[oauth]``
  (httpx). The base install does not import the subpackage; the
  ``kaos_core.auth`` import probes for ``httpx`` and raises
  :class:`ImportError` with an actionable install hint when the
  extra is missing.

  * :class:`PKCELoopbackFlow` — RFC 7636 + RFC 8252 §7.3 PKCE
    with a 127.0.0.1 loopback redirect. Generates a 128-character
    URL-safe ``code_verifier``, a SHA-256 ``code_challenge``, binds
    a port in the IANA dynamic range, opens the browser via
    :func:`webbrowser.open`, waits for the callback on a stdlib
    asyncio TCP server, validates the ``state`` parameter, and
    exchanges the code at the token endpoint. Injection points
    (``open_browser``, ``http_client``, ``port_range``,
    ``timeout_seconds``) keep the runner testable and tunable.
  * :class:`DeviceCodeFlow` — RFC 8628 device authorization grant
    for headless / SSH / WSL. Polls the token endpoint with the
    correct grant_type URN, handles ``authorization_pending``,
    ``slow_down`` (with the recommended 5-second increment),
    ``access_denied``, ``expired_token``. Injection points
    (``http_client``, ``display``, ``poll_sleep``,
    ``slow_down_increment``, ``timeout_seconds``) make polling-loop
    tests instant and let callers customize the user prompt.
  * :class:`AuthFlow` runtime-checkable Protocol (``run()``
    coroutine) and :class:`FlowSelector` heuristic — pick loopback
    when a graphical session is available and 127.0.0.1 is
    bindable, device flow otherwise. ``force_loopback`` /
    ``force_device`` overrides for CLI flags.
  * :func:`refresh_token` — async ``grant_type=refresh_token`` POST
    against the token's recorded ``issuer``. Returns a fresh
    :class:`OAuthToken` (per OAuth 2.1, the previous refresh
    token is invalidated server-side after rotation; callers must
    persist the returned token). Optional pre-configured
    :class:`httpx.AsyncClient` for connection reuse.
  * :class:`OAuthFlowError` — raised for protocol-level failures
    (IdP error responses, callback state mismatch, missing
    ``device_authorization_endpoint``). Transport-level
    :class:`httpx.HTTPError` propagates as-is.

  ``OAuthToken`` extended with ``issuer``, ``client_id``, and
  ``obtained_at`` fields (all optional, all defaulted to ``None``
  so existing serialized tokens still load) plus a new
  :meth:`is_expired_within` helper for proactive refresh.

- **Encrypted-file backend (F2.3).** New ``EncryptedFileStorage``
  (Tier 4) ships a Fernet ciphertext under an Argon2id-derived KEK
  in a versioned JSON envelope. Sits between the keyring tier and
  the plaintext tier in the F2 hierarchy. Opt-in via
  ``kaos-core[encrypted-store]``; the umbrella ``kaos-core[hardened]``
  extra now pulls keyring + encrypted-store together.

  * **Envelope format (`version: 1`)** — JSON wrapper carrying
    ``kdf`` parameters (algorithm, salt, memory_cost_kib,
    iterations, lanes), ``cipher: "fernet"``, the ciphertext, and
    timestamps. Versioned so future KDF / cipher rotation can
    coexist with old files.
  * **KDF defaults** — Argon2id with 64 MiB memory, 3 iterations,
    4 lanes (OWASP 2026 desktop-interactive guidance). The
    envelope records what was actually used, so files always
    decrypt regardless of how the defaults change.
  * **Atomic writes + hardening** — sibling temp file +
    ``fsync`` + ``os.replace``, with the F1.5
    ``_harden_owner_only`` helper applied before the replace so
    the new file gets owner-only access (``0o600`` on POSIX, NTFS
    DACL on Windows) the moment it appears.
  * **Passphrase chain** — ``KAOS_PASSPHRASE`` env var by default
    via ``env_passphrase_provider``; library users can pass any
    callable. Interactive prompting belongs to the F2.5 CLI
    surface.
  * **Threat model gain** — strictly better than plaintext-0o600
    against backup / sync leakage (Dropbox, Time Machine, dotfile
    repo): the file is ciphertext under a passphrase the backup
    process never sees.

- **OS keyring backend (F2.2).** New ``KeyringStorage`` (Tier 3 in
  the F2 hierarchy) wraps the third-party ``keyring`` package
  behind the :class:`SecretStorage` Protocol. Lights up macOS
  Keychain, Windows Credential Manager / WinVault, Linux libsecret
  / Secret Service, and KDE Wallet behind a single uniform
  interface. Opt-in via the new ``kaos-core[keyring]`` extra.

  The probe disables the tier in three real-world hazard scenarios
  to avoid silent foot-guns:

  * Backend ``priority < 1`` (the inert ``Fail`` keyring) — rejected.
  * Backend module is ``keyrings.alt.*`` — rejected. Those backends
    silently store plaintext under ``~/.local/share/python_keyring/``,
    which would make "keyring success" a lie.
  * Headless Linux (no ``DISPLAY`` / ``WAYLAND_DISPLAY`` / TTY) —
    skipped by default; override with ``KAOS_FORCE_KEYRING=1``.
  * WSL — skipped by default (libsecret D-Bus session is unreliable);
    override with ``KAOS_WSL_USE_KEYRING=1``.
  * Hard opt-out via ``KAOS_DISABLE_KEYRING=1`` — applies on every
    platform including macOS / Windows where the platform-specific
    heuristics never fire. Useful for CI sandboxes and operators
    who explicitly don't want the OS keyring touched.

  ``list_services`` is backed by a small JSON *index* in
  ``$XDG_STATE_HOME/kaos/credentials.keyring.index.json`` because
  the keyring API has no cross-backend enumeration primitive. The
  index holds **no secret values** — only ``(module, service, key)``
  names. Profile names scope the keyring service identifier so
  multiple kaos-core profiles can coexist without colliding on
  Keychain / Credential Manager service names.

- **Tier-aware credential dispatcher (F2.1).** New
  ``kaos_core.config.storage`` subpackage introduces an optional
  hardened-storage layer that sits between
  :func:`resolve_secret` and the on-disk credential store.
  Foundation for F2.2 (keyring) and F2.3 (encrypted-file); the
  base install ships only the existing plaintext tier (now
  formally identified as :attr:`StorageTier.PLAINTEXT`) and the
  dispatcher gracefully degrades to it when no extras are
  installed.

  * **`SecretStorage` Protocol** — ``runtime_checkable``; the
    common shape every backend implements.
  * **`StorageTier` IntEnum** — ``NONE`` < ``PLAINTEXT`` <
    ``ENCRYPTED_FILE`` < ``KEYRING`` < ``SYSTEM_BROKER``,
    spaced by 10 so future tiers can slot in without
    renumbering.
  * **`HardenedCredentialStore`** — reads from the strongest
    tier that has the secret, auto-migrates upward on hit,
    writes to the strongest available tier and clears weaker
    tiers, supports a ``prefer_tier=`` cap for testing /
    forced-downgrade scenarios.
  * **`PlaintextStorage`** — Tier-5 adapter that wraps the
    existing :class:`CredentialStore` to fit the Protocol.
  * **`kaos_config_dir() / kaos_state_dir() / kaos_cache_dir()`** —
    XDG basedir resolver (POSIX/macOS) + ``%LOCALAPPDATA%`` Known-
    Folder resolver (Windows). Tokens go in ``$XDG_STATE_HOME``,
    not ``$XDG_CONFIG_HOME``; on Windows always
    ``%LOCALAPPDATA%`` (DPAPI breaks under roaming
    ``%APPDATA%``). Each helper honors a ``KAOS_*_DIR`` override.

  ``resolve_secret`` now accepts either a ``CredentialStore``
  (legacy callers) or a ``HardenedCredentialStore`` for the
  ``credential_store=`` argument; both share the same ``get``
  shape so existing callers are unaffected.

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
