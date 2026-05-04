# kaos-core

[![PyPI - Version](https://img.shields.io/pypi/v/kaos-core)](https://pypi.org/project/kaos-core/)
[![Python](https://img.shields.io/pypi/pyversions/kaos-core)](https://pypi.org/project/kaos-core/)
[![License](https://img.shields.io/pypi/l/kaos-core)](https://github.com/273v/kaos-core/blob/main/LICENSE)

`kaos-core` is the foundational library for KAOS (Kelvin Agentic Operating System) modules. It provides the MCP-native type system, runtime container, registries, execution engine, agent primitives, and VFS abstractions that sibling modules build on.

## Install

```bash
uv add kaos-core
# or
pip install kaos-core
```

Optional extras:

```bash
uv add 'kaos-core[mcp]'           # MCP server runtime
uv add 'kaos-core[pydantic-ai]'   # pydantic-ai integration
```

## Design Summary

- MCP-native internal envelopes for tools, resources, prompts, logging, roots, sampling, elicitation, and tasks.
- Async-first runtime APIs with thin sync-friendly composition points.
- Explicit `KaosRuntime` containers instead of process-global registries.
- Pydantic v2 models and settings with Python 3.13 and 3.14 support.
- Structured logging and context-aware debugging hooks across execution paths.

## CLI

```bash
kaos-core tools list --json                     # registered tools
kaos-core tools search "pdf" --category document  # search tools
kaos-core artifacts list --session my-session   # stored artifacts
kaos-core config show --json                    # runtime settings
kaos-core vfs ls /artifacts/                    # VFS contents
```

All commands support `--json` for structured output.

## Development

```bash
uv sync --python 3.13 --group dev
```

Install pre-commit hooks (recommended — they run the same checks as CI on
every commit, scoped to staged files):

```bash
uvx pre-commit install
uvx pre-commit run --all-files     # one-time full sweep
```

Manual QA commands (the same set CI runs):

```bash
uv run ruff format --check kaos_core tests
uv run ruff check kaos_core tests
uv run ty check kaos_core tests
uv run pytest -m "not live and not network and not slow" --no-cov
uv run python benchmarks/benchmark_core.py
```

## Build From Source

```bash
uv build
uv pip install dist/kaos_core-*.whl
```

Or install editable from the module root:

```bash
uv pip install -e .
```

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

## Package Layout

The package layout follows the PRD in [`docs/PRD.md`](docs/PRD.md). The current implementation includes:

- Core protocol and metadata models
- Runtime-scoped tool, resource, and prompt registries
- Execution engine and workflow executor
- Agent models including sampling, elicitation, delegation, and experimental task management
- Virtual file system with memory and disk backends
- Documentation and schema export helpers
