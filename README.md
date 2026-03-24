# kaos-core

`kaos-core` is the foundational library for Kelvin Agentic OS modules. It provides the MCP-native type system, runtime container, registries, execution engine, agent primitives, and VFS abstractions that sibling modules build on.

## Design Summary

- MCP-native internal envelopes for tools, resources, prompts, logging, roots, sampling, elicitation, and tasks.
- Async-first runtime APIs with thin sync-friendly composition points.
- Explicit `KaosRuntime` containers instead of process-global registries.
- Pydantic v2 models and settings with Python 3.13 and 3.14 support.
- Structured logging and context-aware debugging hooks across execution paths.

## Development

```bash
uv sync --python 3.13 --group dev
uv run --python 3.13 ruff format kaos_core tests
uv run --python 3.13 ruff check --fix kaos_core tests
uv run --python 3.13 ty check kaos_core tests
uv run --python 3.13 pytest -q
uv run --python 3.13 python benchmarks/benchmark_core.py
```

## Build And Install

Build an sdist and wheel with `uv`:

```bash
uv build
```

Install the package into another environment with `pip`:

```bash
pip install dist/kaos_core-0.1.0-py3-none-any.whl
```

Or install directly from the module root with `uv`:

```bash
uv pip install .
```

## Package Layout

The package layout follows the PRD in [`docs/PRD.md`](docs/PRD.md). The current implementation includes:

- Core protocol and metadata models
- Runtime-scoped tool, resource, and prompt registries
- Execution engine and workflow executor
- Agent models including sampling, elicitation, delegation, and experimental task management
- Virtual file system with memory and disk backends
- Documentation and schema export helpers
