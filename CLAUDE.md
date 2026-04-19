# kaos-core Development Notes

## Required Checklists

Apply these checklist sources to every change in this module.

Python:
- `../docs/python/checklists/index.md`
- `../docs/python/checklists/01-research.md`
- `../docs/python/checklists/02-design.md`
- `../docs/python/checklists/03-implement.md`
- `../docs/python/checklists/04-test.md`
- `../docs/python/checklists/05-quality.md`
- `../docs/python/checklists/06-review.md`
- `../docs/python/checklists/07-commit.md`
- `../docs/python/checklists/08-debug.md`
- `../docs/python/checklists/09-optimize.md`
- `../docs/python/checklists/10-document.md`
- `../docs/python/checklists/11-retrieval-and-evaluation.md`
- `../docs/python/checklists/12-benchmarking.md`
- `../docs/python/checklists/13-kaos-agent-retrieval.md`

Rust-adjacent:
- `../kaos-nlp-core/docs/FUZZY_HASHING_PLAN.md` (`QA Checklist`) for Rust, PyO3, native bindings, and performance-critical boundary work
- `../kaos-nlp-core/docs/todo/API_IMPROVEMENTS_TODO.md` for Rust-adjacent backlog and API-shape guidance

- Prefer explicit `KaosRuntime` injection in library code. Only use `KaosRuntime.default()` for scripts, tests, or ergonomic wrappers.
- Keep wire-facing models MCP-native. Convenience fields are allowed only when excluded from serialization.
- Use `typing.get_type_hints()` for schema extraction and function introspection to stay compatible with Python 3.14 deferred annotations.
- New hot-path code should have a targeted test and, when appropriate, a benchmark in `benchmarks/benchmark_core.py`.
- Logging should include `session_id` and `trace_id` whenever a `KaosContext` is available.
- Use `from kaos_core.logging import get_logger` instead of `logging.getLogger(__name__)`. The `get_logger()` auto-prefixes names into the `kaos.*` hierarchy (e.g., `kaos_web.clients.http` → `kaos.web.clients.http`), inheriting the structured formatter and context filter.

## ModuleSettings

`ModuleSettings` (`kaos_core.config.module_settings`) is the base class for per-module typed settings:

```python
from kaos_core.config.module_settings import ModuleSettings

class KaosWebSettings(ModuleSettings):
    browser_type: Literal["chromium", "firefox", "webkit"] = "chromium"
    model_config = SettingsConfigDict(env_prefix="KAOS_WEB_", ...)

# From environment
settings = KaosWebSettings()

# With context overrides (highest priority)
settings = KaosWebSettings.from_context(context, browser_type="firefox")
settings = context.get_module_settings(KaosWebSettings)
```

- Resolution order: explicit overrides → `KaosContext._config` → env vars → `.env` → defaults
- Modules register settings on `KaosRuntime.module_settings["web"] = KaosWebSettings()` during `register_*_tools()`
- API keys should use `pydantic.SecretStr` to prevent accidental logging

## Secret Resolution

`resolve_secret()` (`kaos_core.config.secrets`) resolves secrets from multiple sources:

1. `settings_value` (SecretStr from ModuleSettings)
2. `env_var` (direct `os.environ` lookup)
3. `credential_store` (file-based `CredentialStore`)

## Tool Types and Annotations

- `ToolAnnotations` (`kaos_core.types.annotations`) must be set on every `KaosTool`. Never leave as `None` — clients assume worst-case (destructive + open-world) when unset.
- `ToolMetadata.name` must match `^[a-z0-9]+(?:-[a-z0-9]+){2,}$` — use `kaos-{module}-{action}` pattern.
- `ParameterSchema` inputs should be flat primitives (string, integer, boolean), not nested objects. Use `constraints` for enums and ranges.
- Error messages from `ToolResult.create_error()` must include recovery guidance — these are consumed by LLMs for self-correction. See `docs/guides/tool-design.md`.
- Dict-returning tools must use `ToolResult.create_success(output=data_dict, summary="human-readable summary")` to provide both `TextContent` and `structuredContent`.
- Search results must use a wrapper with `total_matches` and `has_more` fields for pagination.

## AgentSettings

`AgentSettings` (`kaos_core.agent.settings`) configures task management and polling:

| Env var | Default | Description |
|---------|---------|-------------|
| `KAOS_AGENT_POLL_INTERVAL` | `0.25` | Polling interval (seconds) for task status checks |
| `KAOS_AGENT_TASK_PAGE_SIZE` | `50` | Page size for task list pagination |

`TaskManager` accepts an optional `settings: AgentSettings` parameter. If omitted, loads from environment.

## ToolResult Typed Accessors

Use typed accessors instead of unsafe `result.content[0].text` patterns:

- `result.text` — First TextContent text, or `None` (property)
- `result.require_text()` — First TextContent text, raises `ValueError` if not present
- `result.get_structured(key, default=None)` — Safe dict access on `structuredContent`
- `result.require_structured()` — Returns `structuredContent` dict, raises `ValueError` if `None`
