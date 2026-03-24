# kaos-core Development Notes

- Prefer explicit `KaosRuntime` injection in library code. Only use `KaosRuntime.default()` for scripts, tests, or ergonomic wrappers.
- Keep wire-facing models MCP-native. Convenience fields are allowed only when excluded from serialization.
- Use `typing.get_type_hints()` for schema extraction and function introspection to stay compatible with Python 3.14 deferred annotations.
- New hot-path code should have a targeted test and, when appropriate, a benchmark in `benchmarks/benchmark_core.py`.
- Logging should include `session_id` and `trace_id` whenever a `KaosContext` is available.

