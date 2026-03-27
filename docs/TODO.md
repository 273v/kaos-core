# kaos-core: Implementation Tracker

**Last updated:** 2026-03-27 (rev 4 — artifact helpers, threshold constants, content resource support)

---

## Current Status

- [x] Core v0.1 package scaffolding, runtime layers, execution engine, agent primitives, VFS, docs, CI, and benchmark harness are implemented.
- [x] Validation passes with `ruff check`, `ty check`, and `pytest` on Python 3.13. **`ty` is the required type checker, not mypy.**
- [x] Coverage: 56 tests, 90% coverage.
- [x] The sibling MCP server/runtime module is `kaos-mcp`; references to `kaos-mcp-server` should be treated as stale wording.
- [x] `kaos-core` now has an explicit interop contract for `kaos-mcp`: runtime registries, metadata models, MCP-native tool results, and context capability/roots/progress hooks are the stable boundary.
- [x] **Artifact helpers added (2026-03-27)**: `INLINE_THRESHOLD` (16 KB), `SUMMARY_THRESHOLD` (256 KB), `ArtifactManifest.to_resource_link()`, `ArtifactManifest.to_tool_result()` — auto-selects inline vs summary+link vs handle-only based on artifact size.
- [ ] Remaining hardening: prompt registry/template edges, metadata/parameter edge cases, negative elicitation/VFS branches.
- [ ] Prompt/resource completions remain server-owned behavior; `kaos-core` does not define completion providers.
- [ ] Experimental tasks remain deferred at server boundary.

---

## Phase 0 — Project Scaffolding

- [ ] Create `pyproject.toml` with metadata, dependencies, and build config
- [ ] Create `kaos_core/__init__.py` with public API exports
- [ ] Create `kaos_core/_version.py`
- [ ] Create `CLAUDE.md` with development guidelines
- [ ] Create `README.md`
- [ ] Set up `tests/conftest.py` with shared fixtures
- [ ] Configure ruff, mypy, pytest in `pyproject.toml`
- [ ] Add CI matrix for Python 3.13 + 3.14 validation

---

## Phase 1 — Types & Exceptions

### 1.1 Enumerations
- [ ] `kaos_core/types/enums.py` — `ToolCapability`, `ToolCategory`, `ResourceType`, `ExecutionState`, `TaskState`, `ElicitationMode`, `StorageBackend`, `IsolationMode`, `LogLevel`
- [ ] Unit tests for enums

### 1.2 Type Aliases
- [ ] `kaos_core/types/aliases.py` — `Cursor`, `ProgressToken`, `RequestId`, `Timestamp`, `Uri`, `MimeType`

### 1.3 Content Types
- [ ] `kaos_core/types/content.py` — `TextContent`, `ImageContent`, `AudioContent`, `EmbeddedResource`, `ContentType` union
- [ ] Unit tests for content models

### 1.4 Parameter & Result Models
- [ ] `kaos_core/types/parameters.py` — `ParameterSchema` with `to_json_schema()`
- [ ] `kaos_core/types/results.py` — MCP-native `ToolResult` (content, structuredContent, isError, _meta), `ErrorInfo`, `StreamingChunk`, `StreamingResult`, `ProgressUpdate`, `ProgressResult`, `WorkflowResult`
- [ ] Verify `ToolResult.to_mcp_dict()` produces spec-compliant wire format
- [ ] Unit tests for result models, factory methods, and MCP serialization

### 1.5 Metadata Models
- [ ] `kaos_core/types/metadata.py` — `ToolMetadata` (with icon, supports_tasks, output_schema), `ResourceMetadata` (with icon), `PromptMetadata` (with icon)
- [ ] `kaos_core/types/annotations.py` — `ToolAnnotations`, `ResourceAnnotations`
- [ ] Unit tests for metadata validation and `to_mcp_dict()` round-trip

### 1.6 Message Models
- [ ] `kaos_core/types/messages.py` — `Message`, `UserMessage`, `AssistantMessage`, `SamplingMessage`
- [ ] Unit tests for messages

### 1.7 Task Models (EXPERIMENTAL)
- [ ] `kaos_core/types/tasks.py` — `TaskDefinition` (with ttl), `CreateTaskResult` (with _meta), `TaskStatus` (with poll_interval), `TaskListRequest`, `TaskListResponse`
- [ ] Unit tests for task lifecycle models and cursor pagination

### 1.8 Exceptions
- [ ] `kaos_core/exceptions.py` — full hierarchy: `KaosCoreError`, `RegistryError`, `ToolError`, `ToolExecutionError`, `ResourceError`, `ValidationError`, `ExecutionError`, `WorkflowError`, `SamplingError`, `ElicitationError`, `URLElicitationRequiredError`, `TaskError`
- [ ] Unit tests for exception construction and details

### 1.9 Types Package Init
- [ ] `kaos_core/types/__init__.py` — re-export all public types

---

## Phase 2 — Logging

- [ ] `kaos_core/logging.py` — `ContextFilter`, `StructuredFormatter`, `setup_kaos_logging()`, `get_logger()`
- [ ] Unit tests for logging setup and context filter

---

## Phase 3 — Protocol Models (NEW)

- [ ] `kaos_core/protocol/__init__.py`
- [ ] `kaos_core/protocol/capabilities.py` — `ClientCapabilities`, `ServerCapabilities`, `RootsCapability`, `ResourcesCapability`
- [ ] `kaos_core/protocol/initialize.py` — `InitializeRequest`, `InitializeResult`, `Implementation`
- [ ] `kaos_core/protocol/roots.py` — `Root`, roots list/change notification models
- [ ] `kaos_core/protocol/logging.py` — `McpLogLevel`, `LogEvent`
- [ ] Unit tests for capability models, initialize round-trip, roots

---

## Phase 4 — Base Classes

### 4.1 Context
- [ ] `kaos_core/base/context.py` — `KaosContext` with client/server capabilities, roots, protocol_version, capability checks (supports_sampling, supports_elicitation, supports_roots), factory methods (including create_from_initialize), logging, progress, config, VFS, child contexts, cleanup
- [ ] Unit tests for context creation, capability checks, child contexts, config get/set

### 4.2 Tool
- [ ] `kaos_core/base/tool.py` — `KaosTool` ABC with execute, stream_execute, validate_inputs, startup/shutdown, health_check, dunder methods
- [ ] Ensure schema extraction uses `typing.get_type_hints()` (PEP 649 safe)
- [ ] Unit tests with concrete test tool implementation

### 4.3 Resource
- [ ] `kaos_core/base/resource.py` — `KaosResource` ABC with read, stream_read, get_metadata, subscribe/unsubscribe
- [ ] Unit tests with concrete test resource implementation

### 4.4 Prompt
- [ ] `kaos_core/base/prompt.py` — `KaosPrompt` ABC with render, validate_inputs, get_variables, render_batch
- [ ] Unit tests with concrete test prompt implementation

### 4.5 Base Package Init
- [ ] `kaos_core/base/__init__.py` — re-export `KaosTool`, `KaosResource`, `KaosPrompt`, `KaosContext`

---

## Phase 5 — Registry & Runtime Container

### 5.1 Runtime Container
- [ ] `kaos_core/registry/container.py` — `KaosRuntime` with per-runtime registries, `default()` via contextvars, `set_default()`, async shutdown
- [ ] Unit tests for runtime creation, default access, contextvars isolation, multi-runtime coexistence

### 5.2 Namespace Manager
- [ ] `kaos_core/registry/namespace.py` — `NamespaceManager`, `NamespaceInfo`
- [ ] Unit tests for namespace claiming, alias resolution, validation

### 5.3 Tool Registry
- [ ] `kaos_core/registry/tool_registry.py` — `ToolRegistry` (runtime-scoped, not singleton) with register, get, search, schema, hierarchy
- [ ] Unit tests for registration, search, aliases

### 5.4 Resource Registry
- [ ] `kaos_core/registry/resource_registry.py` — `ResourceRegistry` (runtime-scoped) with register, get, search, templates, cache
- [ ] Unit tests for registration, URI resolution, caching

### 5.5 Prompt Registry
- [ ] `kaos_core/registry/prompt_registry.py` — `PromptRegistry` (runtime-scoped) with register, get, list, search
- [ ] Unit tests for prompt registration and lookup

### 5.6 Registry Package Init
- [ ] `kaos_core/registry/__init__.py` — re-export all registries and `KaosRuntime`

---

## Phase 6 — Configuration

### 6.1 Settings
- [ ] `kaos_core/config/settings.py` — `KaosSettings(BaseSettings)` with env prefix, .env, secrets
- [ ] Unit tests for settings loading from env, file, defaults

### 6.2 Profiles
- [ ] `kaos_core/config/profiles.py` — `ProfileManager` with load/save/list/active
- [ ] Unit tests for profile management

### 6.3 Credentials
- [ ] `kaos_core/config/credentials.py` — `CredentialStore` with get/set/delete/list
- [ ] Unit tests for credential storage

### 6.4 Auth
- [ ] `kaos_core/config/auth.py` — `OAuthToken` model with expiry check
- [ ] Unit tests for token model

### 6.5 Config Package Init
- [ ] `kaos_core/config/__init__.py` — re-export convenience functions

---

## Phase 7 — Decorators

- [ ] `kaos_core/decorators/tool_decorator.py` — `@kaos_tool` decorator, `FunctionTool` wrapper
- [ ] `kaos_core/decorators/__init__.py`
- [ ] Ensure all annotation introspection uses `typing.get_type_hints()` / `annotationlib`-safe paths
- [ ] Unit tests for decorator with various signatures, auto-registration, annotations
- [ ] Unit tests on Python 3.14 with deferred annotations

---

## Phase 8 — Prompts

- [ ] `kaos_core/prompts/template.py` — `PromptTemplate`, `TemplateVariable`
- [ ] `kaos_core/prompts/registry_prompts.py` — auto-registered system prompts
- [ ] `kaos_core/prompts/__init__.py`
- [ ] Unit tests for template rendering, variable extraction, partial formatting

---

## Phase 9 — Execution Engine

### 9.1 Models
- [ ] `kaos_core/execution/models.py` — `ExecutionConfig`, `ExecutionContext`, `ExecutionResult`, `WorkflowStep`, `WorkflowDefinition`
- [ ] Unit tests for execution models

### 9.2 Engine
- [ ] `kaos_core/execution/engine.py` — `ExecutionEngine` with execute, execute_batch, metrics, caching, retry, semaphore
- [ ] Unit tests for engine execution, retry, timeout, caching

### 9.3 Workflow
- [ ] `kaos_core/execution/workflow.py` — `WorkflowExecutor` with DAG resolution, step execution
- [ ] Unit tests for workflow registration, execution, dependency ordering

### 9.4 Execution Package Init
- [ ] `kaos_core/execution/__init__.py`

---

## Phase 10 — Agent Primitives (NEW)

### 10.1 Sampling
- [ ] `kaos_core/agent/sampling.py` — `SamplingRequest`, `SamplingResponse`, `ModelPreferences`, `ModelHint`
- [ ] Unit tests for sampling models

### 10.2 Elicitation
- [ ] `kaos_core/agent/elicitation.py` — `ElicitationMode`, `ElicitationRequest` (with elicitation_id, form + URL modes), `ElicitationResponse`, `ElicitationCompletionNotification`, `URLElicitationRequiredError`
- [ ] Verify sensitive-data paths raise `URLElicitationRequiredError` when form mode is used
- [ ] Unit tests for both elicitation modes and completion notifications

### 10.3 Delegation
- [ ] `kaos_core/agent/delegation.py` — `DelegationRequest`, `DelegationResult`, `UsageStats`
- [ ] Unit tests for delegation models

### 10.4 Task Manager (EXPERIMENTAL)
- [ ] `kaos_core/agent/task.py` — `TaskManager` with create (returns `CreateTaskResult`), get, get_task_result (blocking mode), cancel, list (cursor pagination), wait, cleanup_expired (TTL), is_enabled (feature flag)
- [ ] Unit tests for task lifecycle (create -> working -> completed/failed/cancelled)
- [ ] Unit tests for cursor pagination and TTL expiry

### 10.5 Agent Package Init
- [ ] `kaos_core/agent/__init__.py`

---

## Phase 11 — VFS

### 11.1 Models
- [ ] `kaos_core/vfs/models.py` — `VFSConfig`, `VFSMetadata`, `StorageBackend`, `IsolationMode`
- [ ] Unit tests for VFS models

### 11.2 Path & File
- [ ] `kaos_core/vfs/path.py` — `VFSPath(os.PathLike)` with full path protocol
- [ ] `kaos_core/vfs/file.py` — `VFSFile(io.RawIOBase)` with IO protocol
- [ ] Unit tests for path operations and file IO

### 11.3 Backends
- [ ] `kaos_core/vfs/backends.py` — Memory, Disk, (S3 stub) backends
- [ ] Unit tests for each backend

### 11.4 Core
- [ ] `kaos_core/vfs/core.py` — `VirtualFileSystem` (runtime-scoped, not singleton) with read/write/cleanup
- [ ] Unit tests for VFS with context isolation

### 11.5 VFS Package Init
- [ ] `kaos_core/vfs/__init__.py`

---

## Phase 12 — Utils

- [ ] `kaos_core/utils/introspection.py` — `ToolInspector` (uses `typing.get_type_hints()` for PEP 649 safety)
- [ ] `kaos_core/utils/documentation.py` — `DocumentationGenerator`
- [ ] `kaos_core/utils/schema_export.py` — `SchemaExporter` with MCP manifest export
- [ ] `kaos_core/utils/uri.py` — `KaosURI`, `URITemplate`
- [ ] `kaos_core/utils/__init__.py`
- [ ] Unit tests for all utils

---

## Phase 13 — Integration & Polish

- [ ] Integration tests: tool registration via `KaosRuntime` -> execution -> MCP-native result
- [ ] Integration tests: workflow with multi-step DAG
- [ ] Integration tests: agent sampling/elicitation round-trip (mocked, both form + URL modes)
- [ ] Integration tests: VFS context isolation end-to-end
- [ ] Integration tests: multi-runtime coexistence (simulated subinterpreters)
- [x] Verify mypy strict mode passes on Python 3.13 and 3.14
- [x] Verify ruff lint/format passes
- [x] Ensure 90%+ test coverage on core paths
- [ ] Final `__init__.py` public API audit — all `__all__` exports correct
- [ ] Verify `ToolResult`, `ToolMetadata`, `ResourceMetadata` serialize to MCP-compliant dicts
- [ ] Write `README.md` with quickstart examples
