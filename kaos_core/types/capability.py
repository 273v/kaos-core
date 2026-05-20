"""Capability — uniform abstraction over Tool / Source / Retriever / Judge / Persona / UI surface.

See ``kaos-modules/docs/plans/2026-05-19-lateral-redesign-capability-layer.md``
for the motivating design discussion.

The agent's planner reasons about *capabilities*; the runtime resolves a
chosen capability to one or more concrete tools at dispatch time. This
removes the agent's burden of knowing every per-domain tool name and
collapses the M1 fitness-ranker decision surface from ~200 tools to a
handful of capabilities the planner can compose.

Capability sits in :mod:`kaos_core.types` alongside
:class:`ToolMetadata`, :class:`ToolAnnotations`, and the
:class:`ToolCategory` / :class:`ToolCapability` enums. The in-process
registry (``CapabilityRegistry``) lives in :mod:`kaos_agents.registry` —
keeping the type itself in kaos-core preserves kaos-mcp's independence
from kaos-agents and matches the existing ``ToolMetadata`` placement.

Coarse-grained ``CostClass`` and ``LatencyClass`` buckets let the planner
reason about cost and latency without per-call estimates. Concrete spend
is still tracked in :class:`ActionResult.cost_usd` post-execution; these
buckets are pre-execution hints for planning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class CapabilityKind(StrEnum):
    """High-level taxonomy buckets for capabilities.

    Distinct from :class:`ToolCategory` (kaos-mcp domain enum) and
    :class:`ToolCapability` (verb-level tool classifier). ``CapabilityKind``
    is the **planner's** mental model: "what does this resource do for me?"

    The buckets are deliberately small and stable. Adding a new bucket is
    a public-API change; adding a new ``tag`` is not.
    """

    SEARCH = "search"
    """Discover pointers to information. Returns manifests / hits with
    metadata. Cheaper and more reversible than READ. Examples:
    ``kaos-web-search``, ``kaos-source-fr-search``."""

    READ = "read"
    """Fetch content given a pointer. Returns a ``ContentDocument`` or
    equivalent body. Heavier than SEARCH. Examples:
    ``kaos-web-fetch-page``, ``kaos-source-fr-get-content``,
    ``kaos-pdf-parse``."""

    EXTRACT = "extract"
    """Parse content into a structured form (typed fields, AST, table,
    citation). Composes with READ. Examples:
    ``kaos-extract-schema``, ``kaos-citations-extract``."""

    COMPUTE = "compute"
    """Arithmetic, comparison, aggregation, or other deterministic
    computation. Examples: a calculator tool, a SQL query over
    pre-loaded data, a date-arithmetic helper."""

    JUDGE = "judge"
    """Evaluate input against a rubric and emit a structured verdict.
    Replaces bespoke critic Signatures in plan §6. Examples:
    grounding check, format compliance, goal satisfaction."""

    DRAFT = "draft"
    """Produce a new document, response, or artifact. Examples:
    ``kaos-office-write-docx``, response composition."""

    MUTATE = "mutate"
    """Change external state — file write, API POST, etc. Rare for
    read-only agents. Always carries ``side_effects=True``."""

    GRAPH = "graph"
    """Walk or query a knowledge graph (SPARQL, ego subgraph, typed
    projections). Examples: ``kaos-agent-graph-walk``,
    ``kaos-graph-sparql``."""

    META = "meta"
    """Introspect agent runtime state — current cost, last error,
    plan step, memory contents. Self-reflection capabilities."""


class CostClass(StrEnum):
    """Coarse pre-execution cost buckets.

    Concrete spend is tracked in :class:`ActionResult.cost_usd` after the
    capability executes; this enum lets the planner reason about cost
    classes during planning without needing per-call estimates.
    """

    FREE = "free"
    """No LLM call, no network egress, no disk I/O beyond the runtime's
    own working set. Examples: a calculator, an in-process AST query."""

    CHEAP = "cheap"
    """One network call or a trivial LLM call (< $0.001 expected).
    Examples: a single web search, an MCP resource read."""

    MODERATE = "moderate"
    """Multi-step LLM call or a heavy network fetch
    ($0.001 to $0.01 expected). Examples: ReAct over a small tool set,
    a single-page browser render."""

    EXPENSIVE = "expensive"
    """Heavy LLM run, browser session, bulk fetch, or expensive optimisation
    (> $0.01 expected). Examples: a long-horizon plan-execute, a
    multi-page crawl, a corpus filter over hundreds of documents."""


class LatencyClass(StrEnum):
    """Coarse pre-execution latency buckets.

    Like :class:`CostClass`, these are planning-time hints. Actual
    latency is captured in event spans post-execution.
    """

    INSTANT = "instant"
    """< 100 ms — local compute only. Examples: AST query, BM25 search
    over an in-memory index."""

    FAST = "fast"
    """< 1 s — cached or simple-network result. Examples: cached web
    search, MCP resource read with warm cache."""

    MODERATE = "moderate"
    """1 to 10 s — typical fetch + parse round-trip. Examples: live web
    search, kaos-source HTTP fetch, single-doc parse."""

    SLOW = "slow"
    """> 10 s — browser session, large-document parse, multi-step
    workflow. Examples: Playwright crawl, long PDF, MiproV2 optimiser
    pass."""


@dataclass(frozen=True, slots=True)
class Capability:
    """A capability the planner can pick.

    Subsumes "tool", "source", "retriever", "judge", "persona", and
    "UI surface" under one type with a :class:`CapabilityKind`
    discriminator.

    Fields:
        name: Canonical capability name (kebab-case). E.g., ``retrieve``,
            ``discover``, ``extract-document``, ``judge-grounding``.
            Must be unique within a registry.
        kind: High-level taxonomy bucket.
        description: One-paragraph semantic description for the planner.
            Describes WHAT the capability does and WHEN to pick it, not
            which tool implements it.
        inputs: Named input slots, e.g., ``("query", "source_filter",
            "max_n")``. The planner uses these to construct call args.
        outputs: Named output kinds, e.g., ``("RetrievalHit[]",)`` or
            ``("ContentDocument",)``. Lets the planner predict what
            comes back without inspecting the implementation.
        cost_class: Pre-execution cost bucket. Defaults to ``MODERATE``.
        latency_class: Pre-execution latency bucket. Defaults to
            ``MODERATE``.
        side_effects: Whether invocation changes external state.
            Mirrors :attr:`ToolMetadata.side_effects`. Read-only
            capabilities set ``False``.
        preconditions: Named runtime requirements that must hold before
            invocation, e.g., ``("session.has_documents",
            "session.has_corpus")``. Empty tuple means "no
            precondition".
        tags: Free-form extensible labels — ``experimental``, ``beta``,
            ``legal-domain``, ``requires-api-key``, etc.
        backing_tool_names: Concrete tool names that implement this
            capability. The runtime resolves a chosen Capability to this
            set at dispatch time. Empty tuple means the capability is
            purely declarative (e.g., a Persona or a UI surface).
    """

    name: str
    kind: CapabilityKind
    description: str
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    cost_class: CostClass = CostClass.MODERATE
    latency_class: LatencyClass = LatencyClass.MODERATE
    side_effects: bool = False
    preconditions: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    backing_tool_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("Capability.name must be non-empty")
        if not self.description or not self.description.strip():
            raise ValueError(
                f"Capability {self.name!r}.description must be non-empty — "
                "the planner depends on this string to pick capabilities."
            )
        if self.kind == CapabilityKind.MUTATE and not self.side_effects:
            raise ValueError(
                f"Capability {self.name!r}: kind=MUTATE requires "
                "side_effects=True (mutation by definition has side effects)."
            )


# Sentinel ``field()`` for downstream callers that want a default empty
# Capability tuple without importing ``field`` themselves.
EMPTY_CAPABILITIES: tuple[Capability, ...] = ()
del field  # not used elsewhere in this module; keep namespace tidy
