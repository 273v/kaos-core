# kaos-core

[![PyPI - Version](https://img.shields.io/pypi/v/kaos-core)](https://pypi.org/project/kaos-core/)
[![Python](https://img.shields.io/pypi/pyversions/kaos-core)](https://pypi.org/project/kaos-core/)
[![License](https://img.shields.io/pypi/l/kaos-core)](https://github.com/273v/kaos-core/blob/main/LICENSE)
[![CI](https://github.com/273v/kaos-core/actions/workflows/ci.yml/badge.svg)](https://github.com/273v/kaos-core/actions/workflows/ci.yml)

`kaos-core` is the foundational runtime for the **Kelvin Agentic Operating System (KAOS)** — an MCP-native type system, runtime container, registries, execution engine, agent primitives, and virtual filesystem.

It is the dependency-light base every other `kaos-*` package builds on. `kaos-core` does not run servers, talk to LLMs, or extract documents — companion packages do those things. This package is what makes them all consistent.

## Install

```bash
uv add kaos-core
# or
pip install kaos-core
```

`kaos-core` requires Python **3.13** or newer and has only five runtime
dependencies (`click`, `cryptography`, `psutil`, `pydantic`,
`pydantic-settings`). To expose `kaos-core` runtimes over the Model
Context Protocol, add the companion package
[`kaos-mcp`](https://github.com/273v/kaos-mcp) (ships separately).

## Quick start

Define a tool, register it on a runtime, and execute it:

```python
import asyncio

from kaos_core import (
    KaosRuntime,
    ToolAnnotations,
    ToolCapability,
    ToolCategory,
    kaos_tool,
)


@kaos_tool(
    name="kaos-demo-square",
    description="Square an integer",
    category=ToolCategory.DATA,
    capability=ToolCapability.TRANSFORM,
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
    auto_register=False,
)
async def square(value: int) -> int:
    return value * value


async def main() -> None:
    runtime = KaosRuntime()
    runtime.tools.register_tool(square)

    tool = runtime.tools.get_tool("kaos-demo-square")
    result = await tool.execute({"value": 7})
    print(result.text)  # "49"


asyncio.run(main())
```

Inputs are validated against the JSON Schema generated from your type
hints — `tool.execute({"value": "not-int"})` raises `ValidationError`
before reaching the function body.

## Concepts

The package is built around six small, composable primitives.

| Concept | What it is |
|---|---|
| **`KaosRuntime`** | Dependency-injection container. Tools, resources, prompts, and namespaces live here. `KaosRuntime.default()` is fine for scripts and tests; library code should accept a `KaosRuntime` parameter. |
| **`KaosTool`** | Abstract base for tools. Subclass it directly or use the `@kaos_tool` decorator. Inputs are type-validated against the JSON Schema derived from your function signature. |
| **`KaosContext`** | Per-execution context with `session_id` / `trace_id` for structured logging, plus access to runtime configuration and the artifact store. |
| **`ModuleSettings`** | Typed-settings base class with six-level resolution: explicit overrides → `KaosContext._config` → `KAOS_<MOD>_*` env vars → legacy env vars → `.env` → field defaults. API keys use `pydantic.SecretStr` so they are redacted in logs. |
| **Artifacts** | Three-tier policy for results of varying size. `INLINE_THRESHOLD = 16 KB` (inline acceptable), `SUMMARY_THRESHOLD = 256 KB` (summary inline + resource link), larger values move by handle (`kaos://artifacts/...`). Use `ArtifactManifest.to_tool_result()` to auto-select the tier. |
| **Virtual filesystem** | Flat S3-style namespace (`VirtualFileSystem`) with memory and disk backends. Range reads, pagination, lazy loading. Directories are emergent; `mkdir` is a no-op. |

For detailed guidance on writing your own `kaos-*` package on top of
this one, see the upstream [KAOS Modules](https://github.com/273v/kaos-modules)
monorepo and the published [kaos-reference](https://github.com/273v/kaos-reference)
example package.

## CLI

`kaos-core` ships a `kaos-core` administrative CLI. Every command
supports `--json` for machine-readable output:

```bash
kaos-core tools list                              # registered tools
kaos-core tools search "pdf" --category document  # search by query + facet
kaos-core artifacts list --session my-session     # stored artifacts
kaos-core config show                             # runtime settings (with secrets redacted)
kaos-core vfs ls /artifacts/                      # VFS contents
```

## Compatibility & status

| Aspect | |
|---|---|
| **Python** | 3.13, 3.14 |
| **OS** | Linux, macOS, Windows (pure Python wheel; no native code) |
| **Maturity** | Alpha. The public API is intentionally narrow and is documented in `kaos_core.__all__` (105 symbols). |
| **Stability policy** | Pre-1.0: minor bumps may change behaviour. We document every change in [`CHANGELOG.md`](CHANGELOG.md). The MCP tool surface and the `KAOS_<MOD>_*` environment variable namespace are public API and follow the same policy. |
| **Test coverage** | 218 unit tests, 90% line coverage on 2,856 statements. |
| **Type checker** | Validated with [`ty`](https://docs.astral.sh/ty/), Astral's Python type checker. |

## Companion packages

`kaos-core` is the foundation; the broader KAOS platform layers on top:

- [`kaos-mcp`](https://github.com/273v/kaos-mcp) — FastMCP server bridge, `kaos` management CLI, MCP resource templates
- [`kaos-content`](https://github.com/273v/kaos-content) — typed document AST (Block/Inline + provenance) for every extractor
- [`kaos-pdf`](https://github.com/273v/kaos-pdf) · [`kaos-web`](https://github.com/273v/kaos-web) · [`kaos-office`](https://github.com/273v/kaos-office) · [`kaos-tabular`](https://github.com/273v/kaos-tabular) · [`kaos-source`](https://github.com/273v/kaos-source) — extraction packages
- [`kaos-llm-client`](https://github.com/273v/kaos-llm-client) · [`kaos-llm-core`](https://github.com/273v/kaos-llm-core) — LLM transport and typed LLM programming
- [`kaos-agents`](https://github.com/273v/kaos-agents) · [`kaos-citations`](https://github.com/273v/kaos-citations) — agentic runtime and legal-citation pipeline

Each package has its own GitHub repository and PyPI distribution; they
share `kaos-core` as a dependency rather than a build-time link, so
mixing versions is supported within the SemVer compatibility window.

## Development

```bash
git clone https://github.com/273v/kaos-core
cd kaos-core
uv sync --group dev
```

Install pre-commit hooks (recommended — they run the same checks as CI
on every commit, scoped to staged files):

```bash
uvx pre-commit install
uvx pre-commit run --all-files     # one-time full sweep
```

Manual QA commands (the same set CI runs):

```bash
uv run ruff format --check kaos_core tests
uv run ruff check kaos_core tests
uv run ty check kaos_core tests
uv run pytest -m "not live and not network and not slow"
uv run python benchmarks/benchmark_core.py
```

## Build from source

```bash
uv build
uv pip install dist/kaos_core-*.whl
```

Or install editable from the module root:

```bash
uv pip install -e .
```

## Contributing

Issues and pull requests are welcome. By contributing you certify the
[Developer Certificate of Origin v1.1](https://developercertificate.org/);
sign every commit with `git commit -s`. Please open an issue before
starting on a non-trivial change so we can align on scope.

For security issues, see [SECURITY.md](SECURITY.md) — please report
privately via [GitHub Private Vulnerability Reporting](https://github.com/273v/kaos-core/security/advisories/new)
rather than opening a public issue.

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

Copyright 2026 273 Ventures LLC.
