from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from kaos_core import (
    CredentialStore,
    DocumentationGenerator,
    KaosResource,
    OAuthToken,
    ProfileManager,
    PromptMetadata,
    PromptTemplate,
    ResourceMetadata,
    ResourceType,
    ToolAnnotations,
    ToolCapability,
    ToolCategory,
    kaos_tool,
)
from kaos_core.logging import ContextFilter, StructuredFormatter


@kaos_tool(
    name="kaos-core-registry-echo",
    description="Echo text",
    category=ToolCategory.TEXT,
    capability=ToolCapability.TRANSFORM,
    module_name="kaos-core",
    version="0.1.0",
    auto_register=False,
    annotations=ToolAnnotations(readOnlyHint=True),
)
async def registry_echo(text: str) -> str:
    return text


class SampleResource(KaosResource):
    @property
    def metadata(self) -> ResourceMetadata:
        return ResourceMetadata(
            uri="kaos://core/document/sample",
            name="sample",
            description="sample resource",
            resource_type=ResourceType.DOCUMENT,
            provider_module="kaos-core",
            version="0.1.0",
        )

    async def read(self, context: Any = None) -> str:
        del context
        return "sample"

    async def get_metadata(self, context: Any = None) -> dict[str, str]:
        del context
        return {"kind": "sample"}


async def test_registries_and_documentation(runtime: Any) -> None:
    runtime.tools.register_tool(registry_echo, aliases=["echo"])
    runtime.resources.register_resource(SampleResource(), templates=["kaos://core/document/{name}"])
    runtime.prompts.register_prompt(
        PromptTemplate(
            "Describe {topic}",
            metadata=PromptMetadata(
                name="describe-topic", description="Describe topic", version="0.1.0"
            ),
        )
    )

    assert runtime.tools.get_tool("echo") is registry_echo
    assert runtime.tools.find_compatible_tools(input_type="string") == ["kaos-core-registry-echo"]
    assert runtime.tools.get_tool_hierarchy()["kaos-core"] == ["kaos-core-registry-echo"]
    assert runtime.tools.list_namespaces() == ["kaos-core"]
    assert await runtime.resources.get_resource("kaos://core/document/sample") == "sample"
    assert (
        runtime.resources.resolve_template("kaos://core/document/{name}", name="sample")
        == "kaos://core/document/sample"
    )
    assert runtime.prompts.search_prompts()[-1].name == "describe-topic"

    docs = DocumentationGenerator().generate_tool_card(registry_echo)
    assert "kaos-core-registry-echo" in docs


def test_profile_credentials_oauth_and_logging(tmp_path: Path) -> None:
    profiles = ProfileManager(tmp_path / "profiles")
    settings = profiles.load_profile("dev")
    profiles.save_profile("dev", settings)
    profiles.set_active_profile("dev")
    assert profiles.get_active_profile() == "dev"
    assert profiles.list_profiles() == ["dev"]

    credentials = CredentialStore(tmp_path / "creds.json")
    credentials.set("core", "api", "default", "secret")
    assert credentials.get("core", "api") == "secret"
    credentials.delete("core", "api")
    assert credentials.get("core", "api") is None

    token = OAuthToken(
        access_token=SecretStr("token"),
        token_type="Bearer",
        expires_at="2999-01-01T00:00:00+00:00",
    )
    assert token.is_expired() is False

    record = ContextFilter(session_id="s1", trace_id="t1")
    logger_record = logging.LogRecord(
        name="kaos.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    record.filter(logger_record)
    formatted = StructuredFormatter(json_output=True).format(logger_record)
    payload = json.loads(formatted)
    assert payload["session_id"] == "s1"
    assert payload["trace_id"] == "t1"
