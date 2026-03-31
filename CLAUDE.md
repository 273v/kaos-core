# kaos-core Development Notes

- Prefer explicit `KaosRuntime` injection in library code. Only use `KaosRuntime.default()` for scripts, tests, or ergonomic wrappers.
- Keep wire-facing models MCP-native. Convenience fields are allowed only when excluded from serialization.
- Use `typing.get_type_hints()` for schema extraction and function introspection to stay compatible with Python 3.14 deferred annotations.
- New hot-path code should have a targeted test and, when appropriate, a benchmark in `benchmarks/benchmark_core.py`.
- Logging should include `session_id` and `trace_id` whenever a `KaosContext` is available.

## Tool Types and Annotations

- `ToolAnnotations` (`kaos_core.types.annotations`) must be set on every `KaosTool`. Never leave as `None` — clients assume worst-case (destructive + open-world) when unset.
- `ToolMetadata.name` must match `^[a-z0-9]+(?:-[a-z0-9]+){2,}$` — use `kaos-{module}-{action}` pattern.
- `ParameterSchema` inputs should be flat primitives (string, integer, boolean), not nested objects. Use `constraints` for enums and ranges.
- Error messages from `ToolResult.create_error()` must include recovery guidance — these are consumed by LLMs for self-correction. See `docs/TOOL_DESIGN_GUIDE.md`.
- Search results must use a wrapper with `total_matches` and `has_more` fields for pagination.

