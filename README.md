# kaos-core

> **Part of [Kelvin Agentic OS](https://kelvin.legal) (KAOS)** — open agentic
> infrastructure for legal work, built by
> [273 Ventures](https://273ventures.com).
> See the [full KAOS package map](https://github.com/273v) for the rest of the stack.

[![PyPI - Version](https://img.shields.io/pypi/v/kaos-core)](https://pypi.org/project/kaos-core/)
[![Python](https://img.shields.io/pypi/pyversions/kaos-core)](https://pypi.org/project/kaos-core/)
[![License](https://img.shields.io/pypi/l/kaos-core)](https://github.com/273v/kaos-core/blob/main/LICENSE)
[![quality](https://github.com/273v/kaos-core/actions/workflows/quality.yml/badge.svg)](https://github.com/273v/kaos-core/actions/workflows/quality.yml)

`kaos-core` is the foundational runtime for KAOS modules — an MCP-native type
system, runtime container, registries, execution engine, agent primitives, and
virtual filesystem.

It is the dependency-light base every other `kaos-*` package builds on.
`kaos-core` does not run servers, talk to LLMs, or extract documents —
companion packages do those things. This package is what makes them all
consistent.

To expose `kaos-core` runtimes over the Model Context Protocol, add the
companion package [`kaos-mcp`](https://github.com/273v/kaos-mcp) (ships
separately).

## Install

```bash
uv add kaos-core
# or
pip install kaos-core
```

`kaos-core` requires Python **3.13** or newer and has only three runtime
dependencies (`click`, `pydantic`, `pydantic-settings`).

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

Inputs are checked against the JSON Schema generated from your type hints for
required fields, unexpected fields, primitive types, literal enum values, and
list item types — `tool.execute({"value": "not-int"})` raises
`ValidationError` before reaching the function body.

## Concepts

The package is built around six small, composable primitives.

| Concept | What it is |
|---|---|
| **`KaosRuntime`** | Dependency-injection container. Tools, resources, prompts, and namespaces live here. `KaosRuntime.default()` is fine for scripts and tests; library code should accept a `KaosRuntime` parameter. Tests that set a default should reset it with the token returned by `KaosRuntime.set_default()`. |
| **`KaosTool`** | Abstract base for tools. Subclass it directly or use the `@kaos_tool` decorator. Inputs are checked against the JSON Schema derived from your function signature. |
| **`KaosContext`** | Per-execution context with `session_id` / `trace_id` for structured logging, plus access to runtime configuration and the artifact store. |
| **`ModuleSettings`** | Typed-settings base class with six-level resolution: explicit overrides → `KaosContext._config` → `KAOS_<MOD>_*` env vars → legacy env aliases declared by `legacy_env_vars` → `.env` → field defaults. API keys use `pydantic.SecretStr` so they are redacted in logs. |
| **Artifacts** | Three-tier policy for results of varying size. Values below `INLINE_THRESHOLD = 16 KB` can inline the body, values below `SUMMARY_THRESHOLD = 256 KB` return summary + resource link, and values at or above `SUMMARY_THRESHOLD` return a handle only (`kaos://artifacts/...`). Use `ArtifactManifest.to_tool_result()` to auto-select the tier. |
| **Virtual filesystem** | Flat S3-style namespace (`VirtualFileSystem`) with memory and disk backends. Range reads, pagination, lazy loading. Directories are emergent; `mkdir` is a no-op. |

## CLI

`kaos-core` ships a `kaos-core` administrative CLI. Every command supports
`--json` for machine-readable output:

```bash
kaos-core tools list                              # registered tools
kaos-core tools search "pdf" --category document  # search by query + facet
kaos-core artifacts list --session my-session     # stored artifacts
kaos-core config show                             # runtime settings (with secrets redacted)
kaos-core vfs ls /artifacts/ --cursor 100         # paginated VFS contents
```

## Compatibility & status

| Aspect | |
|---|---|
| **Python** | 3.13, 3.14 (informational matrix entries for 3.14t free-threaded and 3.15-dev) |
| **OS** | Linux, macOS, Windows (pure-Python wheel; no native code) |
| **Maturity** | Alpha. The public API is documented in `kaos_core.__all__`. |
| **Stability policy** | Pre-1.0: minor bumps may change behaviour. Every change is documented in [`CHANGELOG.md`](CHANGELOG.md). The MCP tool surface and the `KAOS_<MOD>_*` environment-variable namespace are public API and follow the same policy. |
| **Test coverage** | Tracked by CI with `pytest` and `pytest-cov`; run the local gate below before opening a PR. |
| **Type checker** | Validated with [`ty`](https://docs.astral.sh/ty/), Astral's Python type checker. |

## Companion packages

`kaos-core` is one of the packages in the
[Kelvin Agentic OS](https://kelvin.legal). The broader stack:

| Package | Layer | What it does |
|---|---|---|
| [`kaos-core`](https://github.com/273v/kaos-core) | Core | Foundational runtime, MCP-native types, registries, execution engine, VFS |
| [`kaos-content`](https://github.com/273v/kaos-content) | Core | Typed document AST: Block/Inline, provenance, views |
| [`kaos-mcp`](https://github.com/273v/kaos-mcp) | Bridge | FastMCP server, `kaos` management CLI, MCP resource templates |
| [`kaos-pdf`](https://github.com/273v/kaos-pdf) | Extraction | PDF → AST with provenance |
| [`kaos-web`](https://github.com/273v/kaos-web) | Extraction | Web extraction, browser automation, search, domain intelligence |
| [`kaos-office`](https://github.com/273v/kaos-office) | Extraction | DOCX / PPTX / XLSX readers + writers to AST |
| [`kaos-tabular`](https://github.com/273v/kaos-tabular) | Extraction | DuckDB-powered SQL analytics |
| [`kaos-source`](https://github.com/273v/kaos-source) | Data | Government + financial data connectors (Federal Register, eCFR, EDGAR, GovInfo, PACER, GLEIF) |
| [`kaos-llm-client`](https://github.com/273v/kaos-llm-client) | LLM | Multi-provider LLM transport |
| [`kaos-llm-core`](https://github.com/273v/kaos-llm-core) | LLM | Typed LLM programming (Signatures, Programs, Optimizers) |
| [`kaos-nlp-core`](https://github.com/273v/kaos-nlp-core) | Primitives (Rust) | High-performance NLP primitives |
| [`kaos-nlp-transformers`](https://github.com/273v/kaos-nlp-transformers) | ML | Dense embeddings + retrieval |
| [`kaos-graph`](https://github.com/273v/kaos-graph) | Primitives (Rust) | Graph algorithms + RDF/SPARQL |
| [`kaos-ml-core`](https://github.com/273v/kaos-ml-core) | Primitives (Rust) | Classical ML on the document AST |
| [`kaos-citations`](https://github.com/273v/kaos-citations) | Legal | Legal citation extraction, resolution, verification |
| [`kaos-agents`](https://github.com/273v/kaos-agents) | Agentic | Agent runtime, memory, recipes |
| [`kaos-reference`](https://github.com/273v/kaos-reference) | Sample | Reference module for module authors |

Packages depend on `kaos-core`; everything else is opt-in. Mix and match the
ones you need.

## Development

```bash
git clone https://github.com/273v/kaos-core
cd kaos-core
uv sync --group dev
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
```

## Build from source

```bash
uv build
uv pip install dist/*.whl
```

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md)
for setup, quality gates, pull request expectations, and engineering
standards. By contributing you certify the
[Developer Certificate of Origin v1.1](https://developercertificate.org/) —
sign every commit with `git commit -s`. Please open an issue before starting
on a non-trivial change so we can align on scope.

## Security

For security issues, **please do not file a public issue**. Report privately
via [GitHub Private Vulnerability Reporting](https://github.com/273v/kaos-core/security/advisories/new)
or email **security@273ventures.com**. See [SECURITY.md](SECURITY.md) for the
full disclosure policy.

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

Copyright 2026 [273 Ventures LLC](https://273ventures.com).
Built for [kelvin.legal](https://kelvin.legal).
