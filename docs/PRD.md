# kaos-core: Product Requirements Document

**Module:** `kaos-core`
**Version:** 0.1.0 (initial)
**Status:** Draft (rev 2 — incorporates review feedback)
**Date:** 2026-03-23
**Author:** 273 Ventures LLC
**Python:** >= 3.13, validated on 3.13 and 3.14
**MCP Spec:** 2025-11-25

---

## 1. Purpose & Scope

`kaos-core` is the foundational library for the **Kelvin Agentic OS (KAOS)** module ecosystem. It provides the protocol primitives, registry infrastructure, execution engine, and type system that all other KAOS modules build upon.

### 1.1 Goals

- **MCP-native**: Internal data models are isomorphic to the MCP spec (2025-11-25) — tools, resources, prompts, sampling, elicitation, and roots are protocol-native shapes, not "exportable later". Convenience helpers layer on top but never replace the spec envelope.
- **Pydantic-AI interoperable**: Once exposed through the sibling `kaos-mcp` module (stdio or streamable HTTP), KAOS tools are consumable as pydantic-ai toolsets (`MCPServerStdio`, `MCPServerStreamableHTTP`) with zero custom adapter code. kaos-core itself is a pure library — it does not run a transport.
- **Async-first, sync-compatible**: All I/O operations are `async def` with thin synchronous wrappers where needed.
- **Type-safe**: Pydantic v2 models throughout; full mypy/pyright compatibility; generic `Agent[DepsT, OutputT]` patterns where applicable.
- **Python 3.13 + 3.14 compatible**: All schema extraction uses `inspect` / `typing.get_type_hints()` / `annotationlib`-safe paths to handle PEP 649 deferred annotation evaluation. CI validates both versions.
- **Successor to kelvin_core**: Carries forward proven patterns (context isolation, decorator-based tool registration, VFS) while shedding legacy baggage and adding agentic capabilities. Replaces process-global singletons with explicit runtime containers (see 5.3).

### 1.2 Non-Goals

- This module does **not** contain domain-specific tools (billing, NLP, PDF, etc.) — those belong in sibling KAOS modules.
- This module does **not** implement an MCP server or client transport layer directly — it defines the protocol-native data models and abstractions that `kaos-mcp` (a sibling module) serializes onto the wire. Pydantic-AI interop flows through that sibling server, not through kaos-core directly.
- This module does **not** bundle an LLM client — LLM interaction is provided by `kaos-llm` or via pydantic-ai's model layer.

### 1.3 Relationship to kelvin_core

| Aspect | kelvin_core | kaos-core |
|--------|-------------|-----------|
| MCP alignment | Partial (tool/resource/prompt shapes) | Protocol-native (spec 2025-11-25 envelopes, annotations, roots, tasks†) |
| Agent primitives | None | Sampling, elicitation (form + URL modes), roots, delegation |
| Pydantic-AI integration | None | Via `kaos-mcp` — zero custom adapter code |
| Transport awareness | None | Transport-agnostic abstractions; transport is `kaos-mcp`'s responsibility |
| Auth model | Credential store only | OAuth 2.1 resource-server token model |
| Python version | >= 3.13 | >= 3.13, CI-validated on 3.13 + 3.14 |
| Registry pattern | Process-global singletons | Runtime container with optional per-interpreter global access |
| Config | Custom loader + TOML/YAML/env | Pydantic Settings v2 with profiles + env + secrets |

_† Tasks are experimental in MCP 2025-11-25 and are feature-flagged in kaos-core v0.1._

### 1.4 Interop Contract with `kaos-mcp`

`kaos-core` is the contract-defining library for the sibling `kaos-mcp` FastMCP server/runtime layer.

`kaos-mcp` may rely on these surfaces as the initial stable boundary:

- `KaosRuntime` runtime-scoped registries and VFS access
- MCP-native `ToolResult` serialization and metadata-preserving result envelopes
- `ToolMetadata`, `ResourceMetadata`, and `PromptMetadata` as canonical descriptor models
- `KaosContext` for session identity, negotiated capabilities, roots, trace/session metadata, and progress callbacks
- sampling, elicitation, roots, and task data models as transport-facing protocol types

The first `kaos-mcp` slice should treat these areas as explicitly deferred or follow-up work:

- prompt and resource completions remain server-owned behavior until `kaos-core` grows a first-class completion contract
- request-scoped resource reads are not yet fully hardened through the registry helper path
- task exposure remains experimental and is not yet owned by `KaosRuntime`

This means the initial server slice should prove tools first, then widen to resources/prompts after the server boundary is validated.

---

## 2. Architecture Overview

```
kaos-core/
├── kaos_core/
│   ├── __init__.py              # Public API surface
│   ├── _version.py              # Version string
│   │
│   ├── base/                    # Abstract base classes
│   │   ├── __init__.py
│   │   ├── tool.py              # KaosTool ABC
│   │   ├── resource.py          # KaosResource ABC
│   │   ├── prompt.py            # KaosPrompt ABC
│   │   └── context.py           # KaosContext
│   │
│   ├── types/                   # Shared type system
│   │   ├── __init__.py
│   │   ├── aliases.py           # Type aliases (Cursor, Uri, etc.)
│   │   ├── enums.py             # Enumerations
│   │   ├── content.py           # Content types (text, image, audio, embedded)
│   │   ├── metadata.py          # ToolMetadata, ResourceMetadata, PromptMetadata
│   │   ├── parameters.py        # ParameterSchema, InputSchema
│   │   ├── results.py           # ToolResult, StreamingResult, ProgressResult
│   │   ├── messages.py          # Message, SamplingMessage
│   │   ├── annotations.py       # MCP tool/resource annotations
│   │   └── tasks.py             # Task lifecycle types (MCP Tasks)
│   │
│   ├── registry/                # Discovery & registration
│   │   ├── __init__.py
│   │   ├── container.py         # KaosRuntime container (replaces singletons)
│   │   ├── tool_registry.py     # ToolRegistry
│   │   ├── resource_registry.py # ResourceRegistry
│   │   ├── prompt_registry.py   # PromptRegistry
│   │   └── namespace.py         # NamespaceManager
│   │
│   ├── execution/               # Tool & workflow execution
│   │   ├── __init__.py
│   │   ├── engine.py            # ExecutionEngine
│   │   ├── workflow.py          # WorkflowExecutor, DAG resolution
│   │   └── models.py            # ExecutionConfig, ExecutionState, ExecutionResult
│   │
│   ├── protocol/                # MCP protocol-level models (NEW)
│   │   ├── __init__.py
│   │   ├── capabilities.py      # Client/server capability negotiation
│   │   ├── initialize.py        # Initialize request/response, spec version
│   │   ├── roots.py             # Roots list/change notification models
│   │   └── logging.py           # MCP logging level, log event models
│   │
│   ├── agent/                   # Agentic primitives (NEW)
│   │   ├── __init__.py
│   │   ├── sampling.py          # Sampling request/response models
│   │   ├── elicitation.py       # Elicitation models (form + URL modes)
│   │   ├── delegation.py        # Agent-to-agent delegation
│   │   └── task.py              # Long-running task lifecycle (EXPERIMENTAL)
│   │
│   ├── config/                  # Configuration management
│   │   ├── __init__.py
│   │   ├── settings.py          # Pydantic Settings v2 base
│   │   ├── profiles.py          # Named configuration profiles
│   │   ├── credentials.py       # Credential store (keyring / env / file)
│   │   └── auth.py              # OAuth 2.1 token models (NEW)
│   │
│   ├── decorators/              # Convenience decorators
│   │   ├── __init__.py
│   │   └── tool_decorator.py    # @kaos_tool
│   │
│   ├── prompts/                 # Prompt templating
│   │   ├── __init__.py
│   │   ├── template.py          # PromptTemplate with variable substitution
│   │   └── registry_prompts.py  # Auto-registered system prompts
│   │
│   ├── vfs/                     # Virtual File System
│   │   ├── __init__.py
│   │   ├── core.py              # VirtualFileSystem (runtime-scoped)
│   │   ├── path.py              # VFSPath (os.PathLike)
│   │   ├── file.py              # VFSFile (io.RawIOBase)
│   │   ├── backends.py          # Memory, Disk, S3 backends
│   │   └── models.py            # VFSConfig, VFSMetadata, StorageBackend, IsolationMode
│   │
│   ├── logging.py               # Structured logging, ContextFilter
│   ├── exceptions.py            # Exception hierarchy
│   │
│   └── utils/                   # Utility modules
│       ├── __init__.py
│       ├── introspection.py     # ToolInspector
│       ├── documentation.py     # DocumentationGenerator
│       ├── schema_export.py     # JSON Schema / OpenAPI export
│       └── uri.py               # KaosURI, URITemplate
│
├── tests/
│   ├── conftest.py
│   ├── unit/
│   └── integration/
│
├── docs/
│   ├── PRD.md                   # This document
│   └── TODO.md                  # Implementation tracker
│
├── pyproject.toml
├── CLAUDE.md
└── README.md
```

---

## 3. Module & Class Hierarchy

### 3.1 `kaos_core.base` — Abstract Base Classes

#### 3.1.1 `KaosTool` (ABC)

The fundamental unit of capability. Maps 1:1 to an MCP tool.

```
KaosTool(ABC)
├── Properties
│   ├── metadata: ToolMetadata               # Tool identity, schema, annotations
│   └── is_initialized: bool
│
├── Abstract Methods
│   ├── async execute(inputs, context?) -> ToolResult
│   └── validate_inputs(inputs) -> bool
│
├── Concrete Methods
│   ├── async stream_execute(inputs, context?) -> AsyncIterator[StreamingChunk]
│   ├── async startup() -> None
│   ├── async shutdown() -> None
│   ├── async health_check() -> bool
│   └── get_json_schema() -> dict            # MCP-compatible input schema
│
└── Dunder Methods
    ├── __str__, __repr__
    ├── __aenter__, __aexit__                 # async context manager
    ├── _repr_json_(), _repr_markdown_()      # Jupyter/notebook rendering
    └── __dir__                               # REPL discoverability
```

#### 3.1.2 `KaosResource` (ABC)

An addressable data source. Maps 1:1 to an MCP resource.

```
KaosResource(ABC)
├── Properties
│   └── metadata: ResourceMetadata           # URI, type, access pattern, annotations
│
├── Abstract Methods
│   ├── async read(context?) -> Any
│   └── async get_metadata(context?) -> dict
│
├── Concrete Methods
│   ├── async stream_read(context?) -> AsyncIterator[Any]
│   ├── async subscribe_changes(callback) -> str
│   ├── async unsubscribe_changes(subscription_id) -> None
│   └── _notify_subscribers(event) -> None
│
└── Dunder Methods
    ├── __str__, __repr__
    ├── _repr_json_(), _repr_markdown_()
    └── __dir__
```

#### 3.1.3 `KaosPrompt` (ABC)

A reusable prompt template. Maps 1:1 to an MCP prompt.

```
KaosPrompt(ABC)
├── Properties
│   └── metadata: PromptMetadata
│
├── Abstract Methods
│   ├── async render(inputs, context?) -> list[Message]
│   └── validate_inputs(inputs) -> None
│
└── Concrete Methods
    ├── get_variables() -> list[str]
    ├── get_examples() -> list[dict]
    └── async render_batch(batch_inputs, context?) -> list[list[Message]]
```

#### 3.1.4 `KaosContext`

Execution context carrying session identity, negotiated client capabilities, roots, logging, progress, config, VFS, and resource access. In an MCP session, the context is populated from the initialize handshake; server-to-client requests (sampling, elicitation, roots) are only valid when the client declared the corresponding capability.

```
KaosContext
├── Attributes
│   ├── session_id: str
│   ├── trace_id: str | None
│   ├── metadata: dict[str, Any]
│   ├── client_capabilities: ClientCapabilities | None   # NEW — negotiated at init
│   ├── server_capabilities: ServerCapabilities | None   # NEW — what this server offers
│   ├── roots: list[Root] | None                         # NEW — client-declared roots
│   ├── protocol_version: str | None                     # NEW — negotiated spec version
│   └── vfs: VirtualFileSystem                           # lazy-loaded
│
├── Capability Checks (NEW)
│   ├── supports_sampling() -> bool
│   ├── supports_elicitation() -> bool
│   └── supports_roots() -> bool
│
├── Factory Methods
│   ├── classmethod create(session_id, **kwargs) -> KaosContext
│   ├── classmethod create_from_dict(data) -> KaosContext
│   ├── classmethod create_from_initialize(init_result) -> KaosContext   # NEW
│   └── classmethod create_test_context() -> KaosContext
│
├── Logging
│   ├── info(message, **kwargs)
│   ├── warning(message, **kwargs)
│   └── error(message, **kwargs)
│
├── Progress
│   ├── report_progress(progress, total?, message?)
│   └── set_progress_callback(callback)
│
├── Config & Resources
│   ├── get_config(key, default?) -> Any
│   ├── set_config(key, value)
│   ├── async read_resource(uri) -> Any
│   └── get_vfs_path(path) -> VFSPath
│
└── Lifecycle
    ├── create_child_context(**kwargs) -> KaosContext
    └── async cleanup()
```

---

### 3.2 `kaos_core.types` — Type System

#### 3.2.1 Enumerations

```
ToolCapability(str, Enum)
    EXTRACT, ANALYZE, TRANSFORM, QUERY, GENERATE, VALIDATE

ToolCategory(str, Enum)
    DOCUMENT, TEXT, DATA, MEDIA, INTEGRATION, UTILITY, AGENT

ResourceType(str, Enum)
    DOCUMENT, DATASET, MODEL, CONFIGURATION, TEMPLATE, PAGE, EXTRACTION

ExecutionState(str, Enum)
    PENDING, RUNNING, COMPLETED, FAILED, CANCELLED, PAUSED

TaskState(str, Enum)                         # NEW — MCP Tasks (EXPERIMENTAL)
    WORKING, INPUT_REQUIRED, COMPLETED, FAILED, CANCELLED

ElicitationMode(str, Enum)                   # NEW
    FORM, URL

StorageBackend(str, Enum)
    MEMORY, DISK, S3, HYBRID

IsolationMode(str, Enum)
    GLOBAL, NAMESPACE, CONTEXT

LogLevel(str, Enum)
    DEBUG, INFO, WARNING, ERROR, CRITICAL
```

#### 3.2.2 Type Aliases

```python
Cursor       = str              # Pagination cursor
ProgressToken = str | int       # Progress tracking token
RequestId     = str | int       # JSON-RPC request ID
Timestamp     = str             # ISO 8601
Uri           = str             # Resource URI (kaos:// scheme)
MimeType      = str             # MIME type
```

#### 3.2.3 Content Models (Pydantic BaseModel)

```
TextContent         { type: "text", text: str }
ImageContent        { type: "image", data: str, mimeType: str }
AudioContent        { type: "audio", data: str, mimeType: str }
EmbeddedResource    { type: "resource", resource: Any }
ContentType = TextContent | ImageContent | AudioContent | EmbeddedResource
```

#### 3.2.4 Metadata Models

```
ToolMetadata(BaseModel)
├── Identity:       name, display_name, description, icon (str | None)  # icon: NEW per MCP 2025-11-25
├── Classification: category (ToolCategory), capability (ToolCapability), tags
├── Schema:         input_schema (list[ParameterSchema]), output_schema (dict | None)
├── Operational:    estimated_duration, resource_requirements, side_effects, idempotent
├── Task:           supports_tasks: bool = False                  # NEW — declares task support
├── Integration:    module_name, version, dependencies
├── MCP:            annotations (ToolAnnotations | None)
├── Validators:     validate_hierarchical_name, validate_duration
└── Methods:        get_input_json_schema() -> dict, to_mcp_dict() -> dict

ToolAnnotations(BaseModel)
├── title: str | None
├── readOnlyHint: bool = False
├── destructiveHint: bool = False
├── idempotentHint: bool = False
├── openWorldHint: bool = True
└── humanConfirmationRequired: bool = False

ResourceMetadata(BaseModel)
├── Identity:       uri, name, description, icon (str | None)     # icon: NEW per MCP 2025-11-25
├── Classification: resource_type (ResourceType), tags
├── Content:        size, created_at, modified_at, checksum, mime_type
├── Access:         access_pattern, requires_authentication, supports_subscription
├── MCP:            annotations (ResourceAnnotations | None)
└── Integration:    provider_module, version, template_uri, template_parameters

ResourceAnnotations(BaseModel)
├── audience: list[str]         # ["user", "assistant"]
├── priority: float = 0.0       # 0.0 – 1.0

PromptMetadata(BaseModel)
├── name, description, version, author, icon (str | None)         # icon: NEW per MCP 2025-11-25
├── tags, category
├── input_schema, output_schema, examples
└── provider_module, documentation_url
```

#### 3.2.5 Parameter & Result Models

The result types are **isomorphic to MCP's tool result contract** — the internal envelope matches the protocol shape, with convenience helpers layered on top.

```
ParameterSchema(BaseModel)
├── name, type, description, required, default, constraints, examples
└── Methods: to_json_schema() -> dict

ErrorInfo(BaseModel)
├── code, message, details?, traceback?

ToolResult(BaseModel)                        # MCP-native envelope
├── content: list[ContentType]               # text, image, audio, embedded resource
├── structuredContent: dict | None           # NEW — MCP outputSchema-validated content
├── isError: bool = False                    # NEW — MCP error flag
├── _meta: dict | None                       # NEW — MCP metadata (task refs, etc.)
│
├── Convenience (non-MCP, excluded from serialization)
│   ├── execution_time: float | None
│   ├── warnings: list[str]
│   ├── progress: float | None
│   └── next_cursor: Cursor | None
│
├── Factory Methods
│   ├── create_success(output, **kw) -> ToolResult
│   ├── create_error(error, **kw) -> ToolResult
│   ├── create_text(text) -> ToolResult      # NEW — shorthand
│   └── create_resource_link(uri, name?, mime_type?) -> ToolResult  # NEW
│
└── Methods
    └── to_mcp_dict() -> dict                # Serialize to MCP wire format

StreamingChunk(BaseModel)
├── data, index, is_final, metadata, cursor?

StreamingResult
├── async chunks() -> AsyncIterator[StreamingChunk]
├── async collect() -> list[Any]

ProgressUpdate(BaseModel)
├── current, total?, percentage?, message, metadata

ProgressResult
├── async progress() -> AsyncIterator[ProgressUpdate]
├── async wait_for_completion() -> ToolResult?

WorkflowResult(BaseModel)
├── success, steps (list[ToolResult]), execution_time, failed_step, metadata
├── Properties: total_steps, successful_steps, failed_steps
```

#### 3.2.6 Message Models

```
Message(BaseModel)
├── role: Literal["user", "assistant"], content: ContentType

SamplingMessage(BaseModel)                                        # NEW
├── role: Literal["user", "assistant"], content: ContentType

UserMessage(Message)   # role = "user"
AssistantMessage(Message)  # role = "assistant"
```

#### 3.2.7 Task Models (NEW — MCP Tasks primitive, EXPERIMENTAL)

> **Note:** Tasks are marked experimental in MCP spec 2025-11-25. These models track the spec closely but are feature-flagged in kaos-core v0.1. Breaking changes are expected as the spec matures.

```
TaskDefinition(BaseModel)
├── task_id, name, description
├── tool_name, inputs
├── timeout?, ttl?                           # TTL per MCP task semantics
├── metadata

CreateTaskResult(BaseModel)                  # NEW — MCP CreateTaskResult
├── task_id: str
├── _meta: dict | None                       # io.modelcontextprotocol/related-task

TaskStatus(BaseModel)
├── task_id, state (TaskState)
├── progress?, message?
├── poll_interval: float | None              # NEW — server-suggested poll interval
├── result (ToolResult | None)
├── created_at, updated_at

TaskListRequest(BaseModel)                   # NEW — cursor pagination
├── cursor: Cursor | None
├── state_filter: TaskState | None

TaskListResponse(BaseModel)                  # NEW
├── tasks: list[TaskStatus]
├── next_cursor: Cursor | None
```

#### 3.2.8 Annotation Models (NEW)

```
ToolAnnotations(BaseModel)       # see 3.2.4
ResourceAnnotations(BaseModel)   # see 3.2.4
```

---

### 3.3 `kaos_core.registry` — Discovery & Registration

Registries are owned by a `KaosRuntime` container (see 5.3). For convenience, a per-interpreter default runtime is available via `KaosRuntime.default()`, but explicit container passing is the primary API.

```
KaosRuntime                                                       # NEW — replaces singletons
├── __init__(config?: KaosSettings)
├── tools: ToolRegistry                      # per-runtime instance
├── resources: ResourceRegistry              # per-runtime instance
├── prompts: PromptRegistry                  # per-runtime instance
├── namespaces: NamespaceManager             # per-runtime instance
├── settings: KaosSettings
├── classmethod default() -> KaosRuntime     # per-interpreter default (contextvars)
├── classmethod set_default(runtime) -> None
└── async shutdown() -> None

ToolRegistry
├── register_tool(tool, aliases?) -> None
├── get_tool(name) -> KaosTool | None
├── search_tools(category?, capability?, tags?, query?, namespace?) -> list[ToolMetadata]
├── get_tool_schema(name) -> dict | None
├── find_compatible_tools(input_type?, output_type?) -> list[str]
├── get_tool_hierarchy() -> dict
├── list_namespaces() -> list[str]
├── list_tools() -> list[str]
├── list_tool_objects() -> list[KaosTool]
├── get_tools(names?) -> dict[str, KaosTool]
└── get_stats() -> dict

ResourceRegistry
├── register_resource(resource, uri, templates?) -> None
├── async get_resource(uri, use_cache?) -> Any
├── search_resources(resource_type?, module?, tags?, query?) -> list[ResourceMetadata]
├── list_templates() -> list[str]
├── resolve_template(template, **kwargs) -> str
├── clear_cache(uri?) -> None
└── get_stats() -> dict

PromptRegistry                                                    # NEW
├── register_prompt(prompt) -> None
├── get_prompt(name) -> KaosPrompt | None
├── list_prompts() -> list[str]
├── search_prompts(category?, tags?) -> list[PromptMetadata]
└── get_stats() -> dict

NamespaceManager
├── claim_namespace(namespace, module_name, version, force?) -> bool
├── register_alias(alias, full_name) -> bool
├── resolve_name(name) -> str
├── validate_tool_name(name) -> bool
├── get_namespace_info(namespace) -> NamespaceInfo | None
├── list_namespaces() -> list[str]
└── increment_tool_count(namespace) -> None
```

---

### 3.4 `kaos_core.execution` — Execution Engine

```
ExecutionConfig(BaseModel)
├── max_retries, retry_delay, timeout
├── parallel_limit, enable_caching, enable_logging, enable_metrics

ExecutionEngine
├── __init__(config?)
├── async execute(tool_name, inputs, context?, execution_id?) -> ExecutionResult
├── async execute_batch(requests) -> list[ExecutionResult]       # NEW
├── get_metrics(tool_name?) -> dict
└── clear_cache(tool_name?) -> None

WorkflowDefinition(BaseModel)
├── workflow_id, name, description
├── steps (list[WorkflowStep]), inputs, outputs
├── config (ExecutionConfig), metadata

WorkflowExecutor
├── __init__(engine?)
├── register_workflow(workflow) -> None
├── async execute_workflow(workflow_id, inputs?, context?) -> dict
└── get_registered_workflows() -> list[str]

ExecutionResult(BaseModel)
├── execution_id, state (ExecutionState), output, error?
├── duration, retries, metadata
```

---

### 3.5 `kaos_core.protocol` — MCP Protocol Models (NEW)

Models for MCP protocol-level concerns: initialization, capability negotiation, roots, and structured logging. These are data models only — actual protocol handling is in `kaos-mcp`.

```
ClientCapabilities(BaseModel)
├── sampling: dict | None                    # Non-None = client supports sampling
├── elicitation: dict | None                 # Non-None = client supports elicitation
├── roots: RootsCapability | None            # Non-None = client supports roots
├── experimental: dict | None

ServerCapabilities(BaseModel)
├── tools: dict | None                       # Non-None = server offers tools
├── resources: ResourcesCapability | None
├── prompts: dict | None
├── logging: dict | None
├── experimental: dict | None

RootsCapability(BaseModel)
├── listChanged: bool = False                # Server wants roots/list_changed notifications

ResourcesCapability(BaseModel)
├── subscribe: bool = False
├── listChanged: bool = False

Root(BaseModel)
├── uri: str                                 # File URI or other root
├── name: str | None

InitializeRequest(BaseModel)
├── protocol_version: str
├── capabilities: ClientCapabilities
├── client_info: Implementation

InitializeResult(BaseModel)
├── protocol_version: str
├── capabilities: ServerCapabilities
├── server_info: Implementation
├── instructions: str | None

Implementation(BaseModel)
├── name: str
├── version: str

McpLogLevel(str, Enum)
├── DEBUG, INFO, NOTICE, WARNING, ERROR, CRITICAL, ALERT, EMERGENCY

LogEvent(BaseModel)
├── level: McpLogLevel
├── logger: str | None
├── data: Any
```

---

### 3.6 `kaos_core.agent` — Agentic Primitives (NEW)


This is the primary new subsystem distinguishing KAOS from Kelvin.

#### 3.5.1 Sampling

Models for servers requesting LLM completions through the client (MCP sampling).

```
SamplingRequest(BaseModel)
├── messages: list[SamplingMessage]
├── model_preferences: ModelPreferences | None
├── system_prompt: str | None
├── max_tokens: int
├── temperature: float | None
├── stop_sequences: list[str] | None
├── metadata: dict

SamplingResponse(BaseModel)
├── role: Literal["assistant"]
├── content: ContentType
├── model: str
├── stop_reason: str | None

ModelPreferences(BaseModel)
├── hints: list[ModelHint]
├── cost_priority: float = 0.0           # 0.0 – 1.0
├── speed_priority: float = 0.0
├── intelligence_priority: float = 0.0

ModelHint(BaseModel)
├── name: str | None
```

#### 3.5.2 Elicitation

Models for servers requesting structured input from the user. Supports both **form mode** (structured schema-validated input) and **URL mode** (browser-based out-of-band authentication). Per MCP 2025-11-25, sensitive data (credentials, tokens) **must** use URL mode, not form mode.

```
ElicitationMode(str, Enum)                   # NEW
├── FORM                                     # Structured schema input
├── URL                                      # Out-of-band browser flow

ElicitationRequest(BaseModel)
├── elicitation_id: str                      # NEW — unique ID per request
├── message: str
├── mode: ElicitationMode = ElicitationMode.FORM
├── requested_schema: dict | None            # JSON Schema (form mode only)
├── url: str | None                          # Target URL (URL mode only)
├── timeout: float | None

ElicitationResponse(BaseModel)
├── elicitation_id: str                      # NEW — matches request
├── action: Literal["accept", "decline", "cancel"]
├── content: dict | None                     # Validated against requested_schema (form mode)

ElicitationCompletionNotification(BaseModel) # NEW — URL mode completion
├── elicitation_id: str
├── success: bool
├── error: str | None

URLElicitationRequiredError(KaosCoreError)   # NEW — raised when form mode used for sensitive data
```

#### 3.5.3 Delegation

Agent-to-agent delegation patterns.

```
DelegationRequest(BaseModel)
├── target_agent: str
├── prompt: str
├── inputs: dict
├── context_forward: bool = True          # Forward parent context
├── usage_tracking: bool = True           # Unified token tracking

DelegationResult(BaseModel)
├── agent: str
├── result: ToolResult
├── usage: UsageStats
```

#### 3.5.4 Task Lifecycle (EXPERIMENTAL)

Long-running async task tracking aligned with MCP Tasks primitive. Feature-flagged in v0.1; expect breaking changes as the MCP spec evolves.

```
TaskManager
├── async create_task(definition: TaskDefinition) -> CreateTaskResult
├── async get_task(task_id) -> TaskStatus
├── async get_task_result(task_id, blocking?: bool) -> ToolResult   # NEW — blocking mode
├── async cancel_task(task_id) -> bool
├── async list_tasks(request: TaskListRequest) -> TaskListResponse  # NEW — cursor pagination
├── async wait_for_task(task_id, timeout?) -> TaskStatus
├── async cleanup_expired() -> int                                  # NEW — TTL-based cleanup
└── is_enabled() -> bool                                            # NEW — feature flag check
```

---

### 3.7 `kaos_core.config` — Configuration

```
KaosSettings(BaseSettings)                   # Pydantic Settings v2
├── log_level, log_file, log_format
├── cache_enabled, cache_directory
├── timeout, retry_limit, max_concurrent_requests
├── model_config = SettingsConfigDict(
│       env_prefix="KAOS_",
│       env_file=".env",
│       secrets_dir="/run/secrets"
│   )

ProviderConfig(BaseModel)
├── name, enabled, timeout, retry_limit, metadata

APIProviderConfig(ProviderConfig)
├── api_key (SecretStr), base_url, headers

ProfileManager
├── load_profile(name) -> KaosSettings
├── save_profile(name, settings) -> None
├── list_profiles() -> list[str]
├── get_active_profile() -> str

CredentialStore
├── get(module, service, key?) -> str | None
├── set(module, service, key, value) -> None
├── delete(module, service, key?) -> None
├── list_services(module) -> list[str]

OAuthToken(BaseModel)                        # NEW
├── access_token: SecretStr
├── token_type: str
├── expires_at: Timestamp | None
├── refresh_token: SecretStr | None
├── scope: str | None
├── Methods: is_expired() -> bool
```

---

### 3.8 `kaos_core.decorators`

```
@kaos_tool(
    name?, display_name?, description?,
    category=ToolCategory.DATA,
    capability=ToolCapability.TRANSFORM,
    module_name="decorated",
    version="1.0.0",
    tags?,
    auto_register=True,
    include_context=False,
    annotations?                              # NEW — ToolAnnotations
) -> Callable

FunctionTool(KaosTool)                        # Internal wrapper
├── execute(inputs, context?) -> ToolResult
├── validate_inputs(inputs) -> None
└── validate_output(output) -> None
```

---

### 3.9 `kaos_core.prompts`

```
PromptTemplate(KaosPrompt)
├── __init__(template, variables?, metadata?, delimiter="{}")
├── async render(inputs, context?) -> list[Message]
├── validate_inputs(inputs) -> None
├── get_variables() -> list[str]
├── add_variable(variable) -> None
└── format_partial(**kwargs) -> PromptTemplate

TemplateVariable(BaseModel)
├── name, description, required, default, var_type
└── validate(value) -> None
```

---

### 3.10 `kaos_core.vfs` — Virtual File System

```
VFSConfig(BaseModel)
├── default_backend, max_memory_size, disk_base_path
├── enable_compression, lazy_compression
├── isolation_mode, auto_cleanup, cache_ttl

VirtualFileSystem                            # runtime-scoped, not singleton
├── __init__(config?) -> VirtualFileSystem
├── get_path(path, context_id?) -> VFSPath
├── async read(path, context_id?) -> bytes
├── async write(path, data, context_id?) -> int
├── async cleanup_context(context_id) -> None

VFSPath(os.PathLike)
├── __truediv__(other) -> VFSPath
├── exists(), is_file(), is_dir()
├── async read_bytes(), read_text()
├── async write_bytes(data), write_text(text)
├── iterdir(), mkdir(), unlink(), rmdir()
├── Properties: name, parent, parts

VFSFile(io.RawIOBase)
├── Standard IO protocol (read, write, seek, close)
```

---

### 3.11 `kaos_core.exceptions`

```
KaosCoreError (Exception)
├── RegistryError
├── ToolError
├── ToolExecutionError          (tool_name, step_name?)
├── ResourceError               (resource_uri?)
├── ValidationError             (field?, value?)
├── ExecutionError
├── WorkflowError               (workflow_id?, step_id?)
├── SamplingError               # NEW
├── ElicitationError            # NEW
│   └── URLElicitationRequiredError    # NEW — form mode used for sensitive data
└── TaskError                   # NEW (task_id?, EXPERIMENTAL)
```

---

### 3.12 `kaos_core.logging`

```
ContextFilter(logging.Filter)
├── Adds session_id, trace_id to records

StructuredFormatter(logging.Formatter)
├── JSON or structured text output

setup_kaos_logging(log_level?, log_format?, log_file?, ...) -> None
get_logger(name) -> logging.Logger
```

---

### 3.13 `kaos_core.utils`

```
ToolInspector
├── get_source_info(tool) -> dict
├── get_dependencies(tool) -> dict
├── get_call_graph(tool) -> dict
├── get_complexity_metrics(tool) -> dict
└── generate_report(tool) -> str

DocumentationGenerator
├── generate_tool_card(tool) -> str
├── generate_resource_card(resource) -> str
├── generate_api_reference(tools, resources, title?) -> str
└── generate_module_summary(module_name, tools, resources) -> str

KaosURI (dataclass)
├── scheme, module, resource_type, resource_id, version?, parameters?
├── classmethod parse(uri) -> KaosURI
├── to_string() -> str
└── validate() -> bool

URITemplate
├── __init__(template)
├── format(**kwargs) -> str
├── extract_placeholders() -> list[str]
└── matches(uri) -> dict | None

SchemaExporter
├── export_tool_schema(tool) -> dict          # JSON Schema
├── export_openapi(tools) -> dict             # OpenAPI fragment
└── export_mcp_manifest(tools, resources, prompts) -> dict   # NEW
```

---

## 4. Dependencies

```toml
[project]
requires-python = ">=3.13"

[project.dependencies]
pydantic = ">=2.11.0"
pydantic-settings = ">=2.8.0"
psutil = ">=6.0.0"
cryptography = ">=44.0.0"
click = ">=8.1.0"

[project.optional-dependencies]
mcp = ["mcp>=1.26.0"]
pydantic-ai = ["pydantic-ai-slim[mcp]>=1.70.0"]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "ruff>=0.9.0",
    "mypy>=1.14",
]
```

---

## 5. Key Design Decisions

### 5.1 URI Scheme: `kaos://`

Resources use `kaos://module/type/id?version=X` — a clean break from `kelvin://` to avoid ambiguity during migration.

### 5.2 Naming Convention

Tool names follow MCP hierarchical format: `kaos-module-domain-operation` (hyphen-separated).

### 5.3 Runtime Container, Not Process-Global Singletons

kelvin_core used process-global singletons (`ToolRegistry.get_instance()`). Python 3.14 introduced standard-library subinterpreters and officially supported free-threaded builds, making process-global mutable state a worse fit.

kaos-core replaces this with `KaosRuntime` — an explicit container that owns tool, resource, prompt, and namespace registries along with settings and VFS. Multiple runtimes can coexist (e.g., in tests, subinterpreters, or multi-tenant servers).

For ergonomics, a **per-interpreter default** is available via `KaosRuntime.default()`, backed by `contextvars.ContextVar` for request-local override:

```python
# Explicit (preferred in libraries and servers):
runtime = KaosRuntime(config=my_settings)
runtime.tools.register_tool(my_tool)

# Convenient (acceptable in scripts and CLIs):
KaosRuntime.default().tools.register_tool(my_tool)
```

### 5.4 Pydantic Settings v2 over Custom Loader

Replace kelvin_core's hand-rolled config loader with `pydantic-settings` `BaseSettings`. This gives us env var binding, `.env` files, secrets directory support, and profile layering for free.

### 5.5 Agent Primitives as Models, Not Transports

`kaos_core.agent` defines the *data models* for sampling, elicitation, delegation, and tasks. `kaos_core.protocol` defines the *capability negotiation and initialization* models. The actual transport (stdio, streamable HTTP) is handled by `kaos-mcp`. This keeps kaos-core transport-agnostic.

Pydantic-AI interop is achieved by running `kaos-mcp` as a stdio subprocess or HTTP service, which pydantic-ai then connects to via `MCPServerStdio` or `MCPServerStreamableHTTP`. kaos-core itself never speaks a wire protocol.

### 5.6 MCP-Native Result Envelopes

Internal result models (`ToolResult`, metadata types) are isomorphic to MCP's wire format — `content`, `structuredContent`, `isError`, `_meta`. Convenience helpers (`.create_success()`, `.execution_time`) are layered on top but excluded from MCP serialization. This avoids a lossy translation step at the `kaos-mcp` boundary.

### 5.7 Python 3.14 Compatibility

Python 3.14 (PEP 649) switched to deferred annotation evaluation. All schema extraction in decorators, introspection, and documentation generation uses `typing.get_type_hints()` or `annotationlib` rather than raw `__annotations__` access. CI runs the full test suite on both 3.13 and 3.14.

### 5.8 Experimental Features

Features tracking parts of the MCP spec that are themselves marked experimental are feature-flagged:

| Feature | MCP Status | kaos-core Status |
|---------|-----------|-----------------|
| Tasks | Experimental | Feature-flagged, `TaskManager.is_enabled()` |
| URL-mode elicitation | Stable (2025-11-25) | Implemented, but URL handling delegated to transport |
| Sampling tool-calling (SEP-1577) | Stable | Modeled in `SamplingRequest` |

Breaking changes to experimental features do **not** require a major version bump in kaos-core v0.x.

---

## 6. Support Matrix

| Dimension | Supported |
|-----------|-----------|
| Python | 3.13, 3.14 (CI-validated) |
| MCP spec | 2025-11-25 |
| Pydantic | >= 2.11.0 |
| pydantic-settings | >= 2.8.0 |
| mcp SDK | >= 1.26.0 (optional) |
| pydantic-ai | >= 1.70.0 (optional, via `kaos-mcp`) |
| OS | Linux, macOS, Windows |

---

## 7. Assumptions

- kaos-core is a **pure library layer**. `kaos-mcp` is the actual MCP boundary that serializes protocol messages onto stdio or streamable HTTP.
- "MCP-native" means protocol-native shapes internally — not "exportable later".
- The `protocol/` package models capability negotiation but does not perform it — that is `kaos-mcp`'s responsibility.
