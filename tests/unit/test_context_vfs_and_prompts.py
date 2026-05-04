from __future__ import annotations

from typing import Any

from kaos_core import (
    ClientCapabilities,
    Implementation,
    InitializeRequest,
    InitializeResult,
    KaosContext,
    PromptTemplate,
    Root,
    RootsCapability,
    ServerCapabilities,
    TextContent,
)


async def test_context_vfs_isolation_and_prompt_rendering(runtime: Any) -> None:
    first = KaosContext.create(session_id="session-a", runtime=runtime)
    second = KaosContext.create(session_id="session-b", runtime=runtime)

    await first.get_vfs_path("note.txt").write_text("alpha")
    await second.get_vfs_path("note.txt").write_text("beta")

    assert await first.get_vfs_path("note.txt").read_text() == "alpha"
    assert await second.get_vfs_path("note.txt").read_text() == "beta"

    prompt = PromptTemplate("Hello {name}")
    rendered = await prompt.render({"name": "KAOS"})

    assert isinstance(rendered[0].content, TextContent)
    assert rendered[0].content.text == "Hello KAOS"


def test_context_create_from_initialize_preserves_client_state(runtime: Any) -> None:
    init_request = InitializeRequest(
        protocol_version="2025-11-25",
        capabilities=ClientCapabilities(sampling={}, roots=RootsCapability()),
        client_info=Implementation(name="client", version="1.0.0"),
    )
    init_result = InitializeResult(
        protocol_version="2025-11-25",
        capabilities=ServerCapabilities(tools={}),
        server_info=Implementation(name="server", version="1.0.0"),
    )
    roots = [Root(uri="file:///tmp/project", name="project")]

    context = KaosContext.create_from_initialize(
        init_result,
        runtime=runtime,
        init_request=init_request,
        roots=roots,
    )

    assert context.supports_sampling() is True
    assert context.supports_roots() is True
    assert context.client_capabilities == init_request.capabilities
    assert context.roots == roots
